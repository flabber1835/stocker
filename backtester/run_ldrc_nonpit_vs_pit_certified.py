#!/usr/bin/env python3
"""Certified LD-RC comparison with a full-stack causal PIT D track.

A keeps the existing current/non-PIT Sharadar metadata baseline. D sends the
available causal PIT authorities through Wealth Core and Sentinel/LD-RC, allows
the two books to diverge naturally, and measures each account from its own Wealth
Core equity path. The exact requested current-main strategy implementation stays
frozen for both tracks.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
import importlib.util
import json
import math
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd

EXPECTED_MAIN_SHA = "887f479b15ad861313da666ad698034d3847121c"
LAB_ROOT = Path(__file__).resolve().parents[1]
BASE_LAUNCHER = LAB_ROOT / "backtester" / "run_sector_ad_causal_terminal_terms_v2.py"

spec = importlib.util.spec_from_file_location("ldrc_ad_base", BASE_LAUNCHER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base launcher from {BASE_LAUNCHER}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

# Bind both tracks to the exact current-main strategy implementation.
base.runner.EXPECTED_MAIN_SHA = EXPECTED_MAIN_SHA
base.runner.EXPERIMENT_ID = "2026-08-29-ldrc-nonpit-vs-fullstack-pit-certified"

# The old A/D harness was an isolation experiment and explicitly required Wealth
# Core parity. This certified experiment permits causal divergence.
base.runner.state_wc_parity = lambda *_args, **_kwargs: None

from stock_strategy_shared.wealth_core.feed import SecurityMeta  # noqa: E402
import sentinel.core.kernel as production_kernel  # noqa: E402
import sentinel.core.production as production  # noqa: E402

# Current Production exposes persistence/loading seams from core.production and
# owns the pure economic transition in core.kernel. The retained replay runner
# historically looked those pure symbols up through core.production. Bind that
# compatibility surface to the exact current-main kernel objects so the replay
# executes the current ownership boundary without copying economic logic.
production.advance_state = production_kernel.advance_session
production.session_breadth = production_kernel.session_breadth


def _production_runner_print(*args, **kwargs):
    """Keep legacy internal account names out of Production run logs."""
    if args and isinstance(args[0], str):
        text = args[0]
        if "window_years" in text and "variant" in text and "\n" in text:
            # The runner prints its pre-finalization internal table. The public
            # Production/SPY table is printed after names and hashes are final.
            return None
        if text == "[RUN] fresh chronological A/B/C replay; no prerecorded decisions":
            text = "[RUN] fresh chronological Production replay; no prerecorded decisions"
        elif text == "[PASS] fresh A/B replay completed":
            text = "[PASS] fresh Production replay completed"
        else:
            checkpoint = re.fullmatch(
                r"(\[RUN\] .+ sessions=[^ ]+) A=[^ ]+ B=([^ ]+)", text
            )
            if checkpoint is not None:
                text = f"{checkpoint.group(1)} Production={checkpoint.group(2)}"
        args = (text, *args[1:])
    print(*args, **kwargs)


base.runner.print = _production_runner_print


def _production_layer_print(*args, **kwargs):
    """Translate messages emitted by the inherited comparison layer."""
    if args and isinstance(args[0], str):
        text = args[0]
        if text.startswith("[RUN] A/D cumulative CAGR checkpoint interval="):
            text = text.replace(
                "[RUN] A/D cumulative CAGR",
                "[RUN] Production cumulative CAGR",
                1,
            )
        elif text == "[PASS] A/D PIT-equivalent replay and causal terminal provenance recorded":
            text = "[PASS] Production replay and causal terminal provenance recorded"
        elif text.startswith("[PROGRESS]") and " D_multiple=" in text:
            match = re.match(
                r"(\[PROGRESS\] session=[^ ]+ sessions=[^ ]+ from=[^ ]+).*"
                r" D_multiple=([^ ]+) D_cagr=([^ ]+)",
                text,
            )
            if match is not None:
                text = (
                    f"{match.group(1)} role=Production "
                    f"multiple={match.group(2)} cumulative_cagr={match.group(3)}"
                )
        args = (text, *args[1:])
    print(*args, **kwargs)


base.print = _production_layer_print


@dataclass(frozen=True)
class _PitSecurityMeta(SecurityMeta):
    """SecurityMeta with strict-prior SEC issuer authority."""

    pit_issuer_id: str = ""
    pit_issuer_source: str = ""

    def issuer_key(self) -> tuple[str | None, str | None]:
        return self.pit_issuer_id, self.pit_issuer_source


_pit_metadata_observations = 0
_pit_sec_cik_observations = 0
_latest_pit_state = None
_pit_prior_core_close: float | None = None
_pit_core_by_session: dict[str, tuple[float | None, float]] = {}
_production_dataset_hash: str | None = None
_production_measurement_start: str | None = None
_real_advance_state = production_kernel.advance_session
_real_raw_overlay_step = base._real_overlay_step

UNRESOLVED_OPEN_TRANSITION_MARKER = (
    "allocation transition coincides with unresolved Wealth Core open"
)
PRODUCTION_FAILURE_SCHEMA = "backtester.production-failure-context/1"


def _jsonable(value):
    """Return a deterministic, strict-JSON representation of runtime evidence."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        sequence = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [_jsonable(item) for item in sequence]
    item = getattr(value, "item", None)
    if callable(item):
        return _jsonable(item())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    return str(value)


def _matching_held_episodes(state, unresolved: list[str]) -> list[dict]:
    """Bind every unresolved security to its held episode and source lots."""
    unresolved_set = set(unresolved)
    wealth_state = dict(getattr(state, "wealth_core", None) or {})
    feed = dict(getattr(state, "feed", None) or {})
    series_by_sid = dict(feed.get("series") or {})
    last_known = dict(getattr(state, "last_known", None) or {})
    rows: list[dict] = []
    episodes = dict(wealth_state.get("episodes") or {})
    for slot_id, raw_episode in sorted(episodes.items(), key=lambda pair: str(pair[0])):
        episode = dict(raw_episode or {})
        security_id = str(episode.get("security_id") or "")
        if security_id not in unresolved_set:
            continue
        source = dict(series_by_sid.get(security_id) or {})
        rows.append({
            "slot_id": str(slot_id),
            "security_id": security_id,
            "ticker": str(episode.get("ticker") or source.get("ticker") or ""),
            "episode": _jsonable(episode),
            "source_lots": _jsonable(episode.get("source_lots") or []),
            "feed_source_identity": _jsonable({
                key: source.get(key)
                for key in ("security_id", "ticker", "issuer_id", "split_factor")
            }),
            "last_known_mark": _jsonable(last_known.get(security_id)),
        })
    return rows


def _production_failure_payload(
    state,
    account,
    *,
    core_open,
    core_close,
    prior_core_close,
    bil_gap,
    bil_intraday,
    next_target,
) -> dict:
    """Build the stable evidence record for the fail-closed accounting guard."""
    session = str(getattr(state, "last_processed_session", None) or "")
    evidence = dict(getattr(state, "last_evidence", None) or {})
    wealth_evidence = dict(evidence.get("wealth_core") or {})
    unresolved = sorted({
        str(value)
        for value in (wealth_evidence.get("open_unresolved_security_ids") or [])
    })
    wealth_state = dict(getattr(state, "wealth_core", None) or {})
    pending_orders = [
        row for row in (getattr(state, "pending", None) or [])
        if str((row or {}).get("security_id") or "") in set(unresolved)
    ]
    return _jsonable({
        "schema": PRODUCTION_FAILURE_SCHEMA,
        "status": "FAIL_CLOSED",
        "failure": {
            "code": "UNRESOLVED_OPEN_ALLOCATION_TRANSITION",
            "message": (
                "Production allocation transition requires an exact Wealth Core open, "
                "but at least one held security has no causally resolved open"
            ),
        },
        "session": session,
        "account": {
            "role": "Production",
            "initialized": bool(getattr(account, "initialized", False)),
            "nav_before_session": float(getattr(account, "nav")),
            "effective_exposure_before_open": float(getattr(account, "effective")),
            "pending_exposure_for_this_open": float(getattr(account, "pending")),
            "next_target_exposure": float(next_target),
            "transition_required": (
                abs(float(getattr(account, "pending")) - float(getattr(account, "effective")))
                > 1e-15
            ),
            "transitions_before_session": int(getattr(account, "transitions", 0)),
            "transition_cost_before_session": float(
                getattr(account, "transition_cost", 0.0)
            ),
        },
        "core_values": {
            "prior_close_equity": prior_core_close,
            "resolved_open_equity": core_open,
            "estimated_close_equity": core_close,
            "defensive_gap_factor": bil_gap,
            "defensive_intraday_factor": bil_intraday,
        },
        "open_unresolved_security_ids": unresolved,
        "held_episodes": _matching_held_episodes(state, unresolved),
        "pending_orders_for_unresolved_securities": pending_orders,
        "terminal_state": {
            key: wealth_state.get(key) or {}
            for key in (
                "unresolved_terminals",
                "terminal_pending_sessions",
                "terminal_pending_terms",
                "terminal_carry_audit",
                "sessions_since_valid_mark",
                "last_valid_mark_session",
            )
        },
        "wealth_core_evidence": wealth_evidence,
        "decision": getattr(state, "last_decision", None),
        "source_identities": {
            "production_main_sha": EXPECTED_MAIN_SHA,
            "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
            "experiment": str(base.runner.EXPERIMENT_ID),
            "canonical_pit_dataset_hash": _production_dataset_hash,
            "strategy_identity": getattr(state, "strategy_identity", None),
            "wealth_core_hashes": wealth_evidence.get("hashes") or {},
        },
    })


def _write_production_failure_context(payload: dict) -> Path:
    raw = os.environ.get("PRODUCTION_FAILURE_CONTEXT_PATH", "").strip()
    path = Path(raw).resolve() if raw else base.OUTPUT / "production_failure_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _strict_prior_cik(sectors, sid: str, meta: SecurityMeta, session: str) -> tuple[str, str]:
    ticker = str(sectors.sid_to_ticker.get(str(sid), meta.ticker) or meta.ticker)
    model = sectors.model
    cik = model._strict_prior(
        model.cik_dates.get(ticker, ()), model.cik_values.get(ticker, ()), session)
    if cik is None:
        return f"SEC_UNKNOWN:{sid}", "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON"
    return f"SEC_CIK:{cik}", "SEC_CIK_STRICT_PRIOR"


def _pit_meta_map(pub) -> dict[str, _PitSecurityMeta]:
    global _pit_metadata_observations, _pit_sec_cik_observations
    result: dict[str, _PitSecurityMeta] = {}
    for sid, meta in pub.meta.items():
        issuer_id, source = _strict_prior_cik(pub.sectors, str(sid), meta, str(pub.session))
        _pit_metadata_observations += 1
        if source == "SEC_CIK_STRICT_PRIOR":
            _pit_sec_cik_observations += 1
        result[str(sid)] = _PitSecurityMeta(
            security_id=meta.security_id,
            ticker=meta.ticker,
            category=meta.category,
            permaticker=meta.permaticker,
            related_tickers=(),
            first_session=meta.first_session,
            last_session=meta.last_session,
            exchange=meta.exchange,
            exchange_authoritative=meta.exchange_authoritative,
            pit_issuer_id=issuer_id,
            pit_issuer_source=source,
        )
    return result


def _pit_pub(pub):
    if not isinstance(pub.sectors, base.runner.FF12SectorMap):
        return pub
    pit_meta = _pit_meta_map(pub)
    pit_anchors = {}
    for sid, anchor in pub.feed_anchors.items():
        meta = pit_meta.get(str(sid))
        if meta is None:
            raise RuntimeError(f"PIT feed anchor {sid} has no session metadata")
        issuer_id, _source = meta.issuer_key()
        pit_anchors[sid] = replace(anchor, issuer_id=issuer_id)
    return replace(pub, meta=pit_meta, feed_anchors=pit_anchors)


def _advance_state_fullstack(state, pub, *args, **kwargs):
    global _latest_pit_state
    is_pit = isinstance(pub.sectors, base.runner.FF12SectorMap)
    effective_pub = _pit_pub(pub) if is_pit else pub
    result = _real_advance_state(state, effective_pub, *args, **kwargs)
    if is_pit:
        _latest_pit_state = result
    return result


production.advance_state = _advance_state_fullstack


def _raw_overlay_step_fullstack(self, *args, **kwargs):
    global _pit_prior_core_close
    if str(self.name) != "B":
        return _real_raw_overlay_step(self, *args, **kwargs)
    if _latest_pit_state is None:
        raise RuntimeError("D PIT Wealth Core state missing before account step")
    core_open, core_close = base.runner.wealth_equities(_latest_pit_state)
    session = str(_latest_pit_state.last_processed_session)
    _pit_core_by_session[session] = (core_open, core_close)
    values = list(args)
    if len(values) < 6:
        raise RuntimeError("unexpected OverlayAccount.step call shape")
    values[0] = core_open
    values[1] = core_close
    values[2] = _pit_prior_core_close
    try:
        nav = _real_raw_overlay_step(self, *values, **kwargs)
    except RuntimeError as exc:
        if UNRESOLVED_OPEN_TRANSITION_MARKER not in str(exc):
            raise
        payload = _production_failure_payload(
            _latest_pit_state,
            self,
            core_open=core_open,
            core_close=core_close,
            prior_core_close=_pit_prior_core_close,
            bil_gap=values[3],
            bil_intraday=values[4],
            next_target=values[5],
        )
        path = _write_production_failure_context(payload)
        unresolved = payload["open_unresolved_security_ids"]
        raise RuntimeError(
            "Production allocation transition coincides with unresolved Wealth Core open; "
            f"session={session} unresolved={','.join(unresolved)} "
            f"evidence={path}"
        ) from None
    _pit_prior_core_close = core_close
    return nav


base.runner.OverlayAccount.step = _raw_overlay_step_fullstack


def _calendar_checkpoint_sessions(sessions: list[str], start: str, end: str) -> set[str]:
    selected: set[str] = set()
    quarter_end_months = {3, 6, 9, 12}
    previous = None
    for session in sessions:
        if session < start or session > end:
            continue
        current = date.fromisoformat(session)
        if previous is not None:
            prior = date.fromisoformat(previous)
            if prior.month in quarter_end_months and current.month != prior.month:
                selected.add(previous)
        previous = session
    if previous is not None:
        selected.add(previous)
    return selected


def _measurement_cagr(multiple: float, start: str, session: str) -> float:
    if session <= start:
        return 0.0
    elapsed_years = (date.fromisoformat(session) - date.fromisoformat(start)).days / 365.2425
    if elapsed_years <= 0:
        return 0.0
    return float(multiple ** (1.0 / elapsed_years) - 1.0)


def _increment_production_progress(owner) -> int:
    owner._progress_sessions = int(getattr(owner, "_progress_sessions", 0)) + 1
    return owner._progress_sessions


def _emit_progress(self, *args, **kwargs):
    result = _raw_overlay_step_fullstack(self, *args, **kwargs)
    if str(self.name) == "B" and _latest_pit_state is not None:
        sessions = _increment_production_progress(base)
        if sessions % base.PROGRESS_INTERVAL == 0:
            session = str(_latest_pit_state.last_processed_session)
            start = str(_production_measurement_start or base.runner.CHAIN_START)
            if session >= start:
                print(
                    f"[PROGRESS] session={session} sessions={sessions} from={start} "
                    f"role=Production multiple={float(self.nav):.6f} "
                    f"cumulative_cagr={_measurement_cagr(float(self.nav), start, session):.6%}",
                    flush=True,
                )
    return result


base.runner.OverlayAccount.step = _emit_progress


def _max_metric_block(frame: pd.DataFrame, column: str, measurement_start: str) -> dict:
    x = frame[frame["date"] >= measurement_start][["date", column]].dropna().copy()
    if x.empty:
        raise RuntimeError(f"{column} has no values on or after {measurement_start}")
    end = str(base.runner.END_SESSION)
    if str(x.iloc[-1]["date"]) != end:
        raise RuntimeError(f"{column} has incomplete measurement window through {end}")
    values = x[column].astype(float).to_numpy()
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        raise RuntimeError(f"{column} has invalid measurement values")
    normalized = values / values[0]
    rets = normalized[1:] / normalized[:-1] - 1.0
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else float("nan")
    sharpe = float(np.mean(rets) / std * math.sqrt(252.0)) if std > 0 else float("nan")
    peak = np.maximum.accumulate(normalized)
    max_dd = float(np.min(normalized / peak - 1.0))
    elapsed_years = (
        date.fromisoformat(str(x.iloc[-1]["date"]))
        - date.fromisoformat(str(x.iloc[0]["date"]))
    ).days / 365.2425
    cagr = float(normalized[-1] ** (1.0 / elapsed_years) - 1.0)
    return {
        "start": str(x.iloc[0]["date"]),
        "end": str(x.iloc[-1]["date"]),
        "sessions": int(len(x)),
        "elapsed_years": elapsed_years,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "ending_multiple": float(normalized[-1]),
    }


def _finalize_production_result(result: int) -> int:
    global _production_dataset_hash, _production_measurement_start
    output = Path(base.OUTPUT)
    summary_path = output / "summary.json"
    if not summary_path.exists():
        raise RuntimeError("production replay did not emit summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    daily_path = output / "daily.csv"
    if not daily_path.exists():
        raise RuntimeError("production replay did not emit daily.csv")
    frame = pd.read_csv(daily_path, low_memory=False)
    if "B_nav" not in frame.columns:
        raise RuntimeError("production replay daily output lacks retained B_nav source column")
    measurement_start = str(os.environ.get("CERTIFICATION_MEASUREMENT_START", "2006-07-31"))
    _production_measurement_start = measurement_start
    production_metrics = _max_metric_block(frame, "B_nav", measurement_start)
    spy_metrics = _max_metric_block(frame, "SPY_level", measurement_start)
    summary["metrics"] = {
        "Production": production_metrics,
        "SPY": spy_metrics,
    }
    summary["roles"] = {
        "Production": {
            "source_column": "B_nav",
            "source_mode": "full-stack-causal-pit",
            "production_main_sha": EXPECTED_MAIN_SHA,
        },
        "SPY": {
            "source_column": "SPY_level",
            "source_mode": "canonical-pit-benchmark",
        },
    }
    summary.pop("A", None)
    summary.pop("B", None)
    summary.pop("D", None)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return int(result)


def main() -> int:
    result = int(base.main())
    return _finalize_production_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
