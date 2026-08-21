"""No-oracle deterministic integration differential for Simplified LD-RC v3.

Both sides receive the same pinned Sharadar/Wealth-Core/native-parent inputs.
The production side is :func:`sentinel.core.production.advance_state`. The
reference side below is deliberately handwritten from the retained strategy
formula and imports neither ``recent_leadership`` nor ``ldrc`` nor the
production Concordance integration module. No historical expected-allocation
CSV or session tape is read.

A fresh certification seed has one *current* TICKERS observation, not historical
point-in-time TICKERS snapshots back to 1998. Therefore this tool uses the
current published metadata projection on BOTH sides to prove historical
integration parity and explicitly reports ``historical_metadata_causality`` as
``NOT_CLAIMED``. Live and outage/catch-up production does the opposite: it keeps
``load_published_session``'s session-effective metadata default and refuses a
missed decision when no causal TICKERS observation exists. Keeping those claims
separate prevents a deterministic integration test from laundering current
metadata into a historical causality certification.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence
from unittest.mock import patch

from sentinel.controller.concordance_parent import load as load_concordance_parent
from sentinel.controller.machine import Controller
from sentinel.core.decision import runtime_strategy_identity
from sentinel.core.loader import (
    load_meta as load_current_meta, load_sectors as load_current_sectors,
    load_window,
)
from sentinel.core.production import (
    SessionState, advance_state, load_published_session, warm_session_state,
)
from sentinel.feed import calendar, publication, store as feed_store
from sentinel.feed.readiness import REQUIRED_SPY_SESSIONS
from sentinel.feed.store import connect

CHAIN_START = "1998-01-02"
STARTING_CASH = 100_000_000.0
STRATEGY = "sentinel-concordance-simplified-ldrc"
STRATEGY_VERSION = 3
MIN_LEADERS = 25
LEADERSHIP_FRACTION = 0.10
DIVERGENCE_CEILING = 0.55
WC_DRAWDOWN_TRIGGER = -0.10
RECENT_R20_TRIGGER = -0.08
SPY_R20_FLOOR = 0.00
RECOVERY_SESSIONS = 7
SPY_V_REBOUND = 0.11


class DifferentialRefused(RuntimeError):
    pass


class DifferentialMismatch(RuntimeError):
    def __init__(self, detail: Mapping):
        super().__init__(json.dumps(detail, sort_keys=True, default=str))
        self.detail = dict(detail)


def _finite(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _normal(value):
    if isinstance(value, tuple):
        return [_normal(v) for v in value]
    if isinstance(value, list):
        return [_normal(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _normal(v) for k, v in value.items()}
    return value


def _compare(session: str, family: str, expected: Mapping,
             actual: Mapping) -> int:
    expected_n = _normal(expected)
    actual_n = _normal(actual)
    fields = sorted(set(expected_n) | set(actual_n))
    for field in fields:
        if expected_n.get(field) != actual_n.get(field):
            raise DifferentialMismatch({
                "session": session, "family": family, "field": field,
                "expected": expected_n.get(field),
                "actual": actual_n.get(field),
            })
    return len(fields)


class ReferenceConcordance:
    """Independent formula/state implementation used only by certification."""

    def __init__(self):
        self.selected_recent: tuple[str, ...] = ()
        self.selected_close: tuple[tuple[str, float], ...] = ()
        self.nav_history: tuple[float, ...] = ()
        self.session_history: tuple[str, ...] = ()
        self.witness_last_session: str | None = None
        self.recovery_episode = False
        self.divergence_latched = False
        self.recovery_streak = 0
        self.previous_native_allocation = 1.0
        self.previous_desired_allocation = 1.0
        self.ldrc_last_session: str | None = None
        self.sessions_compared = 0
        self.field_comparisons = 0

    @staticmethod
    def _period_return(values: Sequence[float], horizon: int):
        if len(values) <= horizon or values[-1 - horizon] <= 0:
            return None
        return values[-1] / values[-1 - horizon] - 1.0

    def _witness(self, *, session: str, candidate_rows,
                 eligible_universe_count: int, signal_closes: Mapping):
        if self.witness_last_session is not None and session <= self.witness_last_session:
            raise DifferentialRefused("reference witness session did not advance")
        candidates = []
        for row in candidate_rows:
            sid = getattr(row, "security_id", None)
            momentum = getattr(row, "momentum", None)
            recent = getattr(row, "recent", None)
            if (isinstance(sid, str) and sid and _finite(momentum)
                    and _finite(recent)):
                candidates.append((sid, float(momentum), float(recent)))
        if len(candidates) != eligible_universe_count:
            raise DifferentialRefused(
                "reference candidate count differs from Wealth Core eligibility")
        ids = [row[0] for row in candidates]
        if len(ids) != len(set(ids)):
            raise DifferentialRefused("reference candidates contain duplicate identity")
        if eligible_universe_count == 0:
            population = 0
        elif eligible_universe_count < MIN_LEADERS:
            raise DifferentialRefused("leadership population is below 25-name floor")
        else:
            population = max(
                MIN_LEADERS,
                int(math.ceil(eligible_universe_count * LEADERSHIP_FRACTION)),
            )
        established = tuple(
            row[0] for row in sorted(candidates, key=lambda row: (-row[1], row[0]))[:population]
        )
        recent_members = tuple(
            row[0] for row in sorted(candidates, key=lambda row: (-row[2], row[0]))[:population]
        )
        current_close = {
            str(sid): float(close) for sid, close in signal_closes.items()
            if _finite(close) and float(close) > 0.0
        }
        previous_close = dict(self.selected_close)
        if self.selected_recent:
            total = 0.0
            for sid in self.selected_recent:
                p0 = previous_close.get(sid)
                p1 = current_close.get(sid)
                if (_finite(p0) and _finite(p1)
                        and float(p0) > 0.0 and float(p1) > 0.0):
                    total += float(p1) / float(p0) - 1.0
            one_return = total / len(self.selected_recent)
        else:
            one_return = 0.0
        prior_nav = self.nav_history[-1] if self.nav_history else 1.0
        nav = prior_nav * (1.0 + one_return)
        nav_history = (*self.nav_history, nav)[-41:]
        sessions = (*self.session_history, session)[-41:]
        recent_r20 = self._period_return(nav_history, 20)
        recent_r40 = self._period_return(nav_history, 40)
        missing = [sid for sid in recent_members if sid not in current_close]
        if missing:
            raise DifferentialRefused(
                "reference current leadership membership lacks signal close: "
                + ", ".join(missing))
        selected_close = tuple((sid, current_close[sid]) for sid in recent_members)
        decision = {
            "session": session,
            "eligible_count": eligible_universe_count,
            "population_size": population,
            "overlap_count": len(set(established).intersection(recent_members)),
            "one_session_return": one_return,
            "nav": nav,
            "recent_r20": recent_r20,
            "recent_r40": recent_r40,
            "recent_members": recent_members,
            "established_members": established,
        }
        state = {
            "version": 1,
            "selected_recent": list(recent_members),
            "selected_close": [[sid, close] for sid, close in selected_close],
            "nav_history": list(nav_history),
            "session_history": list(sessions),
            "last_session": session,
        }
        self.selected_recent = recent_members
        self.selected_close = selected_close
        self.nav_history = tuple(nav_history)
        self.session_history = tuple(sessions)
        self.witness_last_session = session
        return decision, state

    def _ldrc(self, *, session: str, native_allocation,
              effective_native_allocation, wc_drawdown,
              recent_r20, recent_r40, spy_r20):
        if self.ldrc_last_session is not None and session <= self.ldrc_last_session:
            raise DifferentialRefused("reference LD-RC session did not advance")
        if not _finite(native_allocation):
            raise DifferentialRefused("reference native allocation is not finite")
        native = float(native_allocation)
        expected_effective_native = self.previous_native_allocation
        if (effective_native_allocation is None
                or float(effective_native_allocation) != expected_effective_native):
            raise DifferentialMismatch({
                "session": session, "family": "ldrc_input",
                "field": "effective_native_allocation",
                "expected": expected_effective_native,
                "actual": effective_native_allocation,
            })
        recovery_available = _finite(recent_r20) and _finite(recent_r40)
        healthy = bool(
            recovery_available and float(recent_r20) > 0.0
            and float(recent_r40) > 0.0)
        streak = self.recovery_streak + 1 if healthy else 0
        v_rebound = bool(_finite(spy_r20) and float(spy_r20) > SPY_V_REBOUND)
        episode = self.recovery_episode
        latched = self.divergence_latched
        reasons = []
        if self.previous_native_allocation >= 1.0 - 1e-12 and native < 1.0 - 1e-12:
            episode = True
            reasons.append("RECOVERY_EPISODE_START")
        if latched and (streak >= RECOVERY_SESSIONS or v_rebound):
            latched = False
            reasons.append(
                "DIVERGENCE_CLEAR_PERSISTENCE" if streak >= RECOVERY_SESSIONS
                else "DIVERGENCE_CLEAR_SPY_V_REBOUND")
        desired = native
        if episode and native >= 1.0 - 1e-12:
            if streak >= RECOVERY_SESSIONS or v_rebound:
                episode = False
                desired = 1.0
                reasons.append(
                    "FULL_RISK_CERTIFIED_PERSISTENCE" if streak >= RECOVERY_SESSIONS
                    else "FULL_RISK_CERTIFIED_SPY_V_REBOUND")
            else:
                desired = self.previous_desired_allocation
                reasons.append("FULL_RISK_HELD_FOR_CONCORDANCE")
        entry_available = (
            _finite(wc_drawdown) and _finite(recent_r20) and _finite(spy_r20)
            and effective_native_allocation is not None
            and _finite(effective_native_allocation)
        )
        if not latched:
            effective_full = bool(
                effective_native_allocation is not None
                and float(effective_native_allocation) >= 1.0 - 1e-12)
            divergence = bool(
                native >= 1.0 - 1e-12 and effective_full and entry_available
                and float(wc_drawdown) <= WC_DRAWDOWN_TRIGGER
                and float(recent_r20) <= RECENT_R20_TRIGGER
                and float(spy_r20) >= SPY_R20_FLOOR)
            if divergence:
                latched = True
                reasons.append("LD_ENTER_DIVERGENCE")
            elif native >= 1.0 - 1e-12 and not entry_available:
                reasons.append("LD_ENTRY_EVIDENCE_UNAVAILABLE")
        if latched:
            desired = min(desired, DIVERGENCE_CEILING)
        desired = min(native, desired)
        decision = {
            "session": session,
            "native_allocation": native,
            "desired_allocation": desired,
            "recovery_episode": episode,
            "divergence_latched": latched,
            "recovery_streak": streak,
            "healthy": healthy,
            "v_rebound": v_rebound,
            "reason": "|".join(reasons) if reasons else "NORMAL",
            "entry_evidence_available": entry_available,
            "recovery_evidence_available": recovery_available,
        }
        state = {
            "version": 3,
            "recovery_episode": episode,
            "divergence_latched": latched,
            "recovery_streak": streak,
            "previous_native_allocation": native,
            "previous_desired_allocation": desired,
            "last_session": session,
        }
        self.recovery_episode = episode
        self.divergence_latched = latched
        self.recovery_streak = streak
        self.previous_native_allocation = native
        self.previous_desired_allocation = desired
        self.ldrc_last_session = session
        return decision, state

    def audit(self, **facts):
        session = facts["session"]
        witness_decision, witness_state = self._witness(
            session=session, candidate_rows=facts["candidate_rows"],
            eligible_universe_count=facts["eligible_universe_count"],
            signal_closes=facts["signal_closes"])
        ldrc_decision, ldrc_state = self._ldrc(
            session=session,
            native_allocation=facts["native_allocation"],
            effective_native_allocation=facts["effective_native_allocation"],
            wc_drawdown=facts["wc_drawdown"],
            recent_r20=witness_decision["recent_r20"],
            recent_r40=witness_decision["recent_r40"],
            spy_r20=facts["spy_r20"])
        compared = 0
        compared += _compare(
            session, "recent_leadership_decision", witness_decision,
            facts["production_witness_decision"])
        compared += _compare(
            session, "recent_leadership_state", witness_state,
            facts["production_witness_state"])
        compared += _compare(
            session, "ldrc_decision", ldrc_decision,
            facts["production_ldrc_decision"])
        compared += _compare(
            session, "ldrc_state", ldrc_state,
            facts["production_ldrc_state"])
        if float(facts["production_final_allocation"]) != float(
                ldrc_decision["desired_allocation"]):
            raise DifferentialMismatch({
                "session": session, "family": "production_composition",
                "field": "target_core_exposure",
                "expected": ldrc_decision["desired_allocation"],
                "actual": facts["production_final_allocation"],
            })
        compared += 1
        self.sessions_compared += 1
        self.field_comparisons += compared


def _known_ids(state: SessionState) -> tuple[str, ...]:
    return tuple(sorted((state.feed.get("series") or {}).keys()))


def run(conn, *, end: str) -> dict:
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        sessions = calendar.sessions_in_range(CHAIN_START, end)
        if len(sessions) <= REQUIRED_SPY_SESSIONS:
            raise DifferentialRefused("certification interval is too short")
        if sessions[-1] != end:
            raise DifferentialRefused(f"end {end} is not an XNYS session")
        controller_config = load_concordance_parent()
        strategy = runtime_strategy_identity(controller_config, concordance=True)
        if (strategy.get("allocation_overlay") != STRATEGY
                or strategy.get("allocation_overlay_version") != str(STRATEGY_VERSION)):
            raise DifferentialRefused(
                "runtime identity is not Simplified Concordance LD-RC v3")
        reference = ReferenceConcordance()
        state = SessionState.fresh(
            starting_cash=STARTING_CASH, controller=Controller(controller_config),
            strategy_identity=strategy)
        warm_count = REQUIRED_SPY_SESSIONS - 1
        warm_sessions = sessions[:warm_count]
        with publication.pinned(conn, commit=False) as held:
            frontier = feed_store.latest_visible_session(conn)
            if frontier is None or str(frontier) < end:
                raise DifferentialRefused(
                    f"published frontier {frontier} is before requested end {end}")
            window = load_window(
                conn, start=warm_sessions[0], end=warm_sessions[-1])
            if list(window.sessions) != list(warm_sessions):
                raise DifferentialRefused("feature-only warm-up is incomplete")
            state = warm_session_state(
                state, window, publication_version=held.version)
            for session in sessions[warm_count:]:
                # The final target decided at D-1 is the strategy exposure that
                # becomes effective on D.  This explicit comparison catches a
                # same-session application even if both close-time machines
                # otherwise agree.
                if state.last_decision is not None:
                    actual_effective = float(
                        state.last_decision["target_core_exposure"])
                    expected_effective = float(reference.previous_desired_allocation)
                    if actual_effective != expected_effective:
                        raise DifferentialMismatch({
                            "session": session, "family": "execution_timing",
                            "field": "prior_close_target_effective_today",
                            "expected": expected_effective,
                            "actual": actual_effective,
                        })
                    reference.field_comparisons += 1
                # A fresh historical seed has only one current TICKERS
                # observation. Override metadata strictly inside this audit
                # process so we can test overlay/integration parity without
                # creating a production causality bypass. Both sides receive
                # the same current projection and the report says explicitly
                # that historical metadata causality is NOT claimed.
                def current_meta(_conn, *, as_of=None):
                    return load_current_meta(_conn)

                def current_sectors(_conn, *, as_of=None):
                    return load_current_sectors(_conn)

                with patch("sentinel.core.loader.load_meta", current_meta), \
                     patch("sentinel.core.loader.load_sectors", current_sectors):
                    published = load_published_session(
                        conn, session, spy_sessions=REQUIRED_SPY_SESSIONS,
                        known_feed_security_ids=_known_ids(state))
                if int(published.data_version) != int(held.version):
                    raise DifferentialRefused(
                        "published session escaped the held corpus generation")
                state = advance_state(
                    state, published, controller_config=controller_config,
                    strategy_identity=strategy,
                    concordance_audit=reference.audit)
        return {
            "schema": "sentinel.concordance-differential/1",
            "verdict": "PASS",
            "oracle_used": False,
            "reference_kind": "INDEPENDENT_DETERMINISTIC_CODE",
            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",
            "historical_metadata_causality": "NOT_CLAIMED",
            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",
            "strategy": STRATEGY,
            "strategy_version": STRATEGY_VERSION,
            "parent_strategy": controller_config.strategy_id,
            "parent_fast_damaged_breadth_delta5":
                controller_config.fast_entry["min_damaged_breadth_delta5"],
            "chain_start": CHAIN_START,
            "end": end,
            "sessions_advanced": len(sessions) - warm_count,
            "sessions_compared": reference.sessions_compared,
            "field_comparisons": reference.field_comparisons,
            "first_divergence": None,
            "final_production_state_sha256": state.state_hash,
        }
    except DifferentialMismatch as exc:
        return {
            "schema": "sentinel.concordance-differential/1",
            "verdict": "FAIL", "oracle_used": False,
            "reference_kind": "INDEPENDENT_DETERMINISTIC_CODE",
            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",
            "historical_metadata_causality": "NOT_CLAIMED",
            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",
            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,
            "end": end, "first_divergence": exc.detail,
        }
    finally:
        conn.rollback()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    database_url = os.environ.get("SENTINEL_DATABASE_URL")
    if not database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    conn = None
    try:
        conn = connect(database_url)
        report = run(conn, end=args.end)
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0 if report["verdict"] == "PASS" else 1
    except DifferentialRefused as exc:
        print(json.dumps({
            "schema": "sentinel.concordance-differential/1",
            "verdict": "REFUSED", "oracle_used": False,
            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",
            "historical_metadata_causality": "NOT_CLAIMED",
            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",
            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,
            "reason": str(exc),
        }, indent=2, sort_keys=True))
        return 2
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({
            "schema": "sentinel.concordance-differential/1",
            "verdict": "REFUSED", "oracle_used": False,
            "metadata_mode": "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY",
            "historical_metadata_causality": "NOT_CLAIMED",
            "prospective_metadata_causality": "SESSION_EFFECTIVE_RUNTIME_GATE",
            "strategy": STRATEGY, "strategy_version": STRATEGY_VERSION,
            "reason": f"{type(exc).__name__}: {exc}",
        }, indent=2, sort_keys=True))
        return 2
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
