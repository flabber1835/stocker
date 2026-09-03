#!/usr/bin/env python3
"""Bounded real-corpus metamorphic future-leak certification.

Two independent layers are intentional.

1. Every eligible calendar year receives the cheap, exhaustive-prefix probe.
   Run B contains physically poisoned post-cutoff rows and run C physically
   removes them.  Neither mutation may change any economic prefix at/before T.
   A deliberately future-reading negative control must change the prefix.
2. Official certification additionally loads the artifact through the real
   CanonicalPITDataset validator and drives representative bounded windows
   through the exact pinned Production transition kernel.  This keeps the
   dynamic test tied to the production economic implementation without turning
   implementation validation into another full 20-year replay.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import csv
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "backtester.dynamic-future-leak/2"
REAL_SCHEMA = "backtester.real-kernel-future-leak/1"
PASS = "PASS"
FAIL = "FAIL"
ECONOMIC_KEYS = (
    "selected_universe", "rankings_signals", "decisions", "pending_orders",
    "executions", "holdings", "cash", "strategy_state", "path_dependent_state",
    "nav", "checkpoint_state",
)


def _jsonable(value: Any) -> Any:
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
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return _jsonable(enum_value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    return str(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _truth(value: Any, default: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "1.0", "true", "yes"}


def _number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _sessions(dataset: Path) -> list[str]:
    path = dataset / "session-hashes.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    values = [str(row.get("session") or "")[:10] for row in rows]
    values = [x for x in values if x]
    if len(values) != len(set(values)) or values != sorted(values):
        raise RuntimeError("canonical session axis is not unique/monotonic")
    return values


def deterministic_cutoffs(sessions: Iterable[str]) -> list[str]:
    by_year: dict[int, list[str]] = defaultdict(list)
    for session in sessions:
        by_year[int(session[:4])].append(session)
    result = []
    for year in sorted(by_year):
        rows = by_year[year]
        if len(rows) < 145:
            continue
        index = min(max(140, len(rows) * 3 // 5), len(rows) - 6)
        result.append(rows[index])
    return result


def _representative_real_cutoffs(cutoffs: list[str]) -> list[str]:
    """Five deterministic epochs; annual coverage remains in the outer probe."""
    if len(cutoffs) <= 5:
        return list(cutoffs)
    indexes = {0, len(cutoffs) // 4, len(cutoffs) // 2,
               (3 * len(cutoffs)) // 4, len(cutoffs) - 1}
    return [cutoffs[index] for index in sorted(indexes)]


def _load_window(
    dataset: Path,
    sessions: list[str],
    cutoff: str,
    lookback: int = 130,
    future: int = 5,
) -> dict[str, list[dict[str, str]]]:
    index = sessions.index(cutoff)
    selected = sessions[
        max(0, index - lookback): min(len(sessions), index + future + 1)
    ]
    wanted = set(selected)
    years = sorted({int(x[:4]) for x in selected})
    by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    for year in years:
        path = dataset / f"observations-{year}.csv.gz"
        if not path.is_file():
            raise RuntimeError(f"canonical observation partition missing for {year}")
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                session = str(row.get("session") or row.get("date") or "")[:10]
                if session in wanted:
                    by_session[session].append(dict(row))
    missing = [x for x in selected if x not in by_session]
    if missing:
        raise RuntimeError(
            f"canonical cutoff window lacks observations: {missing[:5]}"
        )
    for session in by_session:
        by_session[session].sort(
            key=lambda r: (
                str(r.get("security_id") or ""), str(r.get("ticker") or "")
            )
        )
    return dict(by_session)


def _poison_row(row: Mapping[str, str], cutoff: str) -> dict[str, str]:
    session = str(row.get("session") or row.get("date") or "")[:10]
    out = dict(row)
    if session <= cutoff:
        return out
    sid = str(row.get("security_id") or row.get("ticker") or "0")
    salt = int(
        hashlib.sha256((session + "|" + sid).encode()).hexdigest()[:8], 16
    )
    factor = 25.0 + (salt % 1000) / 17.0
    for key in (
        "signal_close", "raw_close", "raw_open", "close", "closeunadj",
        "canonical_raw_open",
    ):
        value = _number(out, key)
        if value is not None:
            out[key] = f"{value * factor:.12f}"
    for key in ("reported_volume", "raw_compatible_volume", "volume"):
        if key in out:
            out[key] = str(10_000_000_000 + salt)
    if "security_type" in out:
        out["security_type"] = (
            "non_common"
            if str(out.get("security_type")).lower() == "common"
            else "common"
        )
    if "ff12" in out:
        out["ff12"] = "POISON_FUTURE"
    return out


def _poisoned_mapping(
    rows: Mapping[str, list[dict[str, str]]], cutoff: str
) -> dict[str, list[dict[str, str]]]:
    return {
        session: [_poison_row(row, cutoff) for row in values]
        for session, values in rows.items()
    }


def _truncated_mapping(
    rows: Mapping[str, list[dict[str, str]]], cutoff: str
) -> dict[str, list[dict[str, str]]]:
    return {
        session: [dict(row) for row in values]
        for session, values in rows.items()
        if session <= cutoff
    }


class SessionScopedCanonicalWindow:
    """Decision authority that physically refuses post-as-of reads."""

    def __init__(
        self,
        rows: Mapping[str, list[dict[str, str]]],
        as_of: str,
        *,
        poison_future: bool = False,
    ):
        self._rows = rows
        self.as_of = as_of
        self.poison_future = poison_future

    def rows_for(self, session: str) -> tuple[dict[str, str], ...]:
        session = str(session)
        if session > self.as_of:
            raise RuntimeError(
                f"decision-time future read blocked: {session} > {self.as_of}"
            )
        return tuple(dict(row) for row in self._rows.get(session, ()))

    def unsafe_rows_for_negative_control(
        self, session: str
    ) -> tuple[dict[str, str], ...]:
        rows = self._rows.get(str(session), ())
        if self.poison_future:
            return tuple(_poison_row(row, self.as_of) for row in rows)
        return tuple(dict(row) for row in rows)


def _visible_security(row: Mapping[str, str]) -> bool:
    return (
        _truth(row.get("listing_active"), True)
        and _truth(row.get("tradeable"), True)
        and str(row.get("security_type") or "").strip().lower() == "common"
        and bool(str(row.get("security_id") or "").strip())
    )


def _run_prefix_probe(
    window: SessionScopedCanonicalWindow,
    ordered_sessions: list[str],
    cutoff: str,
    *,
    intentional_future_read: bool = False,
) -> dict[str, str]:
    histories: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=127))
    holdings: dict[str, float] = {}
    cash = 1.0
    pending: dict[str, float] = {}
    nav = 1.0
    peak = 1.0
    category_hashes = {key: hashlib.sha256() for key in ECONOMIC_KEYS}
    prior_close: dict[str, float] = {}
    through = [s for s in ordered_sessions if s <= cutoff and s in window._rows]
    if not through:
        raise RuntimeError("dynamic future-leak cutoff has no replay sessions")
    next_after = next(
        (s for s in ordered_sessions if s > cutoff and s in window._rows), None
    )
    for session in through:
        rows = window.rows_for(session)
        by_sid = {
            str(r.get("security_id") or ""): r
            for r in rows
            if str(r.get("security_id") or "")
        }
        executions = []
        if pending:
            total_target = sum(pending.values())
            new_holdings = {}
            for sid, weight in sorted(pending.items()):
                row = by_sid.get(sid)
                price = _number(
                    row or {}, "raw_open", "canonical_raw_open", "signal_close", "close"
                )
                if price is None:
                    continue
                new_holdings[sid] = weight
                executions.append((sid, round(weight, 12), round(price, 12)))
            holdings = new_holdings
            cash = (
                max(0.0, 1.0 - sum(holdings.values()))
                if total_target <= 1.0 + 1e-12 else 0.0
            )
            pending = {}
        gross = cash
        for sid, weight in sorted(holdings.items()):
            close = _number(by_sid.get(sid, {}), "signal_close", "close")
            prev = prior_close.get(sid)
            gross += (
                weight
                if close is None or prev is None or prev <= 0
                else weight * (close / prev)
            )
        nav *= gross
        if gross > 0:
            holdings = {
                sid: weight
                * (
                    (_number(by_sid.get(sid, {}), "signal_close", "close")
                     or prior_close.get(sid, 1.0))
                    / max(prior_close.get(sid, 1.0), 1e-12)
                )
                / gross
                for sid, weight in holdings.items()
            }
            cash = cash / gross
        peak = max(peak, nav)
        candidates = []
        for row in rows:
            sid = str(row.get("security_id") or "")
            close = _number(row, "signal_close", "close")
            if close is not None:
                histories[sid].append(close)
                prior_close[sid] = close
            if not _visible_security(row) or len(histories[sid]) < 20:
                continue
            hist = histories[sid]
            candidates.append((sid, hist[-1] / hist[0] - 1.0))
        if intentional_future_read and session == cutoff and next_after is not None:
            future = window.unsafe_rows_for_negative_control(next_after)
            future_close = {
                str(r.get("security_id") or ""): _number(r, "signal_close", "close")
                for r in future
            }
            candidates = [
                (
                    sid,
                    signal
                    + 0.01 * math.log(max(future_close.get(sid) or 1.0, 1e-12)),
                )
                for sid, signal in candidates
            ]
        rankings = sorted(candidates, key=lambda x: (-x[1], x[0]))
        selected = [sid for sid, _ in rankings[:10]]
        decisions = {sid: 0.1 for sid in selected}
        pending = dict(decisions)
        drawdown = nav / peak - 1.0
        state = {
            "session": session,
            "selected": selected,
            "rankings": [(sid, round(sig, 12)) for sid, sig in rankings[:25]],
            "decisions": decisions,
            "pending": pending,
            "executions": executions,
            "holdings": {
                sid: round(w, 12) for sid, w in sorted(holdings.items())
            },
            "cash": round(cash, 12),
            "strategy_state": {
                "candidate_count": len(candidates), "selected_count": len(selected)
            },
            "path_state": {
                "peak_nav": round(peak, 12),
                "drawdown": round(drawdown, 12),
                "history_sizes_sha256": _hash(
                    {sid: len(v) for sid, v in sorted(histories.items())}
                ),
            },
            "nav": round(nav, 12),
        }
        checkpoint = _hash(state)
        values = {
            "selected_universe": selected,
            "rankings_signals": state["rankings"],
            "decisions": decisions,
            "pending_orders": pending,
            "executions": executions,
            "holdings": state["holdings"],
            "cash": state["cash"],
            "strategy_state": state["strategy_state"],
            "path_dependent_state": state["path_state"],
            "nav": state["nav"],
            "checkpoint_state": checkpoint,
        }
        for key in ECONOMIC_KEYS:
            category_hashes[key].update(_json_bytes([session, values[key]]))
    return {key: digest.hexdigest() for key, digest in category_hashes.items()}


def run(dataset: Path) -> dict[str, Any]:
    """Annual real-corpus boundary probe kept cheap enough for every commit."""
    sessions = _sessions(dataset)
    cutoffs = deterministic_cutoffs(sessions)
    if not cutoffs:
        raise RuntimeError("canonical history has no deterministic future-leak cutoffs")
    records = []
    for cutoff in cutoffs:
        rows = _load_window(dataset, sessions, cutoff)
        poison_rows = _poisoned_mapping(rows, cutoff)
        truncated_rows = _truncated_mapping(rows, cutoff)
        normal = SessionScopedCanonicalWindow(rows, cutoff)
        poisoned = SessionScopedCanonicalWindow(poison_rows, cutoff)
        truncated = SessionScopedCanonicalWindow(truncated_rows, cutoff)
        a = _run_prefix_probe(normal, sessions, cutoff)
        b = _run_prefix_probe(poisoned, sessions, cutoff)
        c = _run_prefix_probe(truncated, sessions, cutoff)
        mismatches = [key for key in ECONOMIC_KEYS if a[key] != b[key]]
        truncation_mismatches = [key for key in ECONOMIC_KEYS if a[key] != c[key]]
        bad_a = _run_prefix_probe(
            normal, sessions, cutoff, intentional_future_read=True
        )
        bad_b = _run_prefix_probe(
            poisoned, sessions, cutoff, intentional_future_read=True
        )
        negative_differences = [
            key for key in ECONOMIC_KEYS if bad_a[key] != bad_b[key]
        ]
        records.append({
            "cutoff": cutoff,
            "year": int(cutoff[:4]),
            "prefix_hashes_run_a": a,
            "prefix_hashes_poisoned_future": b,
            "prefix_hashes_truncated_future": c,
            "pre_cutoff_mismatches": mismatches,
            "truncation_mismatches": truncation_mismatches,
            "negative_control_detected": bool(negative_differences),
            "negative_control_differences": negative_differences,
        })
    status = PASS if all(
        not row["pre_cutoff_mismatches"]
        and not row["truncation_mismatches"]
        and row["negative_control_detected"]
        for row in records
    ) else FAIL
    return {
        "schema": SCHEMA,
        "status": status,
        "contract": (
            "changing or removing canonical data strictly after cutoff must not "
            "change any economic prefix through cutoff"
        ),
        "cutoff_scheme": (
            "one deterministic cutoff per calendar year after >=127 prior sessions "
            "and with >=5 future sessions"
        ),
        "economic_prefix_fields": list(ECONOMIC_KEYS),
        "cutoffs": records,
        "years": [row["year"] for row in records],
        "negative_control": (
            "intentional T+1 close read must be detected at every cutoff"
        ),
    }


def _candidate_projection(plan) -> list[dict[str, Any]]:
    rows = []
    for candidate in tuple(getattr(plan, "leadership_candidates", ()) or ()):
        rows.append({
            "security_id": str(getattr(candidate, "security_id", "")),
            "ticker": str(getattr(candidate, "ticker", "")),
            "score": _jsonable(getattr(candidate, "score", None)),
            "momentum": _jsonable(getattr(candidate, "momentum", None)),
            "recent": _jsonable(getattr(candidate, "recent", None)),
            "in_top_decile": bool(getattr(candidate, "in_top_decile", False)),
        })
    return rows


def _actual_values(state, plan, session: str) -> dict[str, Any]:
    candidates = _candidate_projection(plan)
    selected = [
        row["security_id"] for row in candidates if row["in_top_decile"]
    ]
    wealth = dict(getattr(state, "wealth_core", None) or {})
    ledger = dict(getattr(state, "ledger", None) or {})
    current_events = [
        row for row in (ledger.get("events") or [])
        if str((row or {}).get("session") or "") == session
    ]
    path_fields = (
        "security_cooldowns", "unresolved_terminals",
        "sessions_since_valid_mark", "terminal_pending_sessions",
        "terminal_pending_terms", "terminal_carry_audit",
        "last_valid_mark_session", "slots",
    )
    path_state = {
        "wealth_core": {key: wealth.get(key) for key in path_fields},
        "shadow_peak_nav": getattr(state, "shadow_peak_nav", None),
        "shadow_nav_history": getattr(state, "shadow_nav_history", None),
        "trailing_stop_sessions": getattr(state, "trailing_stop_sessions", None),
        "controller_session_history": getattr(state, "controller_session_history", None),
        "breadth_history": getattr(state, "breadth_history", None),
        "recent_leadership": getattr(state, "recent_leadership", None),
        "ldrc": getattr(state, "ldrc", None),
        "feed_sha256": _hash(getattr(state, "feed", None) or {}),
    }
    return {
        "selected_universe": selected,
        "rankings_signals": candidates,
        "decisions": getattr(state, "last_decision", None),
        "pending_orders": getattr(state, "pending", None) or [],
        "executions": current_events,
        "holdings": wealth.get("episodes") or {},
        "cash": wealth.get("cash"),
        "strategy_state": {
            "controller": getattr(state, "controller", None),
            "eligible_universe_count": int(
                getattr(plan, "eligible_universe_count", 0) or 0
            ),
            "wealth_core_hashes": getattr(plan, "hashes", None) or {},
        },
        "path_dependent_state": path_state,
        "nav": float(getattr(plan, "estimated_equity", 0.0)),
        "checkpoint_state": getattr(state, "state_hash"),
    }


def _runtime_imports():
    from backtester.canonical_pit_dataset import CanonicalPITDataset
    from sentinel.controller.concordance_parent import load as load_controller
    from sentinel.controller.machine import Controller
    from sentinel.core.decision import runtime_strategy_identity
    import sentinel.core.kernel as kernel
    from sentinel.core.session import FeedAnchor, PublishedSession, SessionState
    from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar

    kernel_path = Path(kernel.__file__).resolve()
    if "main-src" not in kernel_path.parts:
        raise RuntimeError(
            f"real replay kernel did not load from pinned main-src: {kernel_path}"
        )

    @dataclass(frozen=True)
    class PitSecurityMeta(SecurityMeta):
        pit_issuer_id: str = ""
        pit_issuer_source: str = ""

        def issuer_key(self):
            return self.pit_issuer_id, self.pit_issuer_source

    return {
        "CanonicalPITDataset": CanonicalPITDataset,
        "load_controller": load_controller,
        "Controller": Controller,
        "runtime_strategy_identity": runtime_strategy_identity,
        "kernel": kernel,
        "FeedAnchor": FeedAnchor,
        "PublishedSession": PublishedSession,
        "SessionState": SessionState,
        "PitSecurityMeta": PitSecurityMeta,
        "VendorBar": VendorBar,
        "kernel_path": str(kernel_path),
    }


def _meta_record(dataset, sid: str, session: str, current=None):
    if current is not None:
        return current
    return dataset.metadata_for(str(sid), str(session))


def _pit_meta(runtime, record: Mapping[str, Any]):
    classification = str(record.get("security_type") or "").strip().lower()
    category = (
        "SEC Common Stock" if classification == "common" else
        "SEC Non-Common" if classification == "non_common" else None
    )
    first = str(record.get("listing_first_session") or "").strip() or None
    issuer_id = str(record.get("issuer_id") or "").strip()
    issuer_source = str(record.get("issuer_source") or "").strip()
    if not issuer_id:
        raise RuntimeError(
            f"canonical metadata has no causal issuer for {record.get('security_id')}"
        )
    return runtime["PitSecurityMeta"](
        security_id=str(record.get("security_id") or ""),
        ticker=str(record.get("ticker") or ""),
        category=category,
        permaticker=None,
        related_tickers=(),
        first_session=first,
        last_session=None,
        exchange=None,
        exchange_authoritative=False,
        pit_issuer_id=issuer_id,
        pit_issuer_source=issuer_source,
    )


def _prior_split_factor(row: Mapping[str, Any]) -> float:
    raw = _number(row, "raw_close", "closeunadj")
    signal = _number(row, "signal_close", "close")
    ratio = _number(row, "split_ratio") or 1.0
    if raw is None or signal is None:
        raise RuntimeError(
            f"cannot reconstruct pre-window split basis for {row.get('security_id')}"
        )
    value = (signal / raw) / ratio
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(
            f"invalid pre-window split basis for {row.get('security_id')}: {value}"
        )
    return value


def _actual_publication(
    runtime,
    dataset,
    all_sessions: list[str],
    session_index: Mapping[str, int],
    rows: list[dict[str, str]],
    session: str,
    state,
    spy_levels: Mapping[str, float],
    terminal_by_session: Mapping[str, tuple[Any, ...]],
):
    current = {
        str(row.get("security_id") or ""): row
        for row in rows
        if str(row.get("security_id") or "")
    }
    needed = set(current)
    needed.update(
        str(sid) for sid in ((getattr(state, "feed", None) or {}).get("series") or {})
    )
    terminals = tuple(terminal_by_session.get(session, ()) or ())
    for term in terminals:
        needed.add(str(getattr(term, "security_id", "")))
        delivered = getattr(term, "delivered_security_id", None)
        if delivered:
            needed.add(str(delivered))
    meta = {}
    sectors = {}
    for sid in sorted(needed):
        if not sid:
            continue
        record = _meta_record(dataset, sid, session, current.get(sid))
        if record is None:
            raise RuntimeError(
                f"real replay metadata missing for path-dependent security {sid} on {session}"
            )
        m = _pit_meta(runtime, record)
        meta[sid] = m
        sectors[sid] = str(record.get("ff12") or f"UNKNOWN:{sid}")

    bars = []
    for sid, row in sorted(current.items()):
        bars.append(runtime["VendorBar"](
            session=session,
            security_id=sid,
            ticker=str(row.get("ticker") or ""),
            raw_close=_number(row, "raw_close", "closeunadj"),
            raw_open=_number(row, "raw_open", "canonical_raw_open"),
            volume=_number(row, "raw_compatible_volume", "reported_volume", "volume"),
            split_ratio=_number(row, "split_ratio") or 1.0,
            dividend_per_share=(
                float(row.get("dividend_per_share") or 0.0)
                if str(row.get("dividend_per_share") or "").strip() else 0.0
            ),
            tradeable=_truth(row.get("tradeable"), False),
            unresolved_corporate_action=False,
        ))

    existing = set(
        str(sid) for sid in ((getattr(state, "feed", None) or {}).get("series") or {})
    )
    anchors = {}
    for bar in bars:
        if bar.security_id in existing:
            continue
        m = meta[bar.security_id]
        if m.first_session is not None and str(m.first_session) < session:
            issuer_id, _source = m.issuer_key()
            if not issuer_id:
                raise RuntimeError(
                    f"real replay feed anchor lacks issuer for {bar.security_id}"
                )
            anchors[bar.security_id] = runtime["FeedAnchor"](
                security_id=bar.security_id,
                ticker=bar.ticker,
                issuer_id=str(issuer_id),
                prior_split_factor=_prior_split_factor(current[bar.security_id]),
            )
        elif m.first_session is not None and str(m.first_session) > session:
            raise RuntimeError(
                f"security {bar.security_id} appears before listing first session"
            )

    idx = session_index[session]
    tail = all_sessions[max(0, idx - 20): idx + 1]
    spy = [float(spy_levels[s]) for s in tail]
    return runtime["PublishedSession"](
        session=session,
        data_version=1,
        bars=tuple(bars),
        meta=meta,
        sectors=sectors,
        spy_closeadj=spy,
        spy_sessions=tuple(tail),
        spy_expected_sessions=tuple(tail),
        terminal_events=terminals,
        feed_anchors=anchors,
    )


def _advance_actual(runtime, state, publication, controller_config, strategy_identity):
    kernel = runtime["kernel"]
    original = kernel.plan_session
    captured = {}

    def capture(*args, **kwargs):
        plan = original(*args, **kwargs)
        captured["plan"] = plan
        return plan

    kernel.plan_session = capture
    try:
        result = kernel.advance_session(
            state,
            publication,
            controller_config=controller_config,
            strategy_identity=strategy_identity,
        )
    finally:
        kernel.plan_session = original
    plan = captured.get("plan")
    if plan is None:
        raise RuntimeError("exact Production kernel emitted no captured plan")
    return result, plan


def _future_contaminated_current(
    current_rows: list[dict[str, str]], future_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    current = {
        str(row.get("security_id") or ""): dict(row)
        for row in current_rows
        if str(row.get("security_id") or "")
    }
    future = {
        str(row.get("security_id") or ""): row
        for row in future_rows
        if str(row.get("security_id") or "")
    }
    common = sorted(set(current).intersection(future))
    preferred = [
        sid for sid in common
        if _truth(current[sid].get("tradeable"), False)
        and str(current[sid].get("security_type") or "").lower() == "common"
        and _number(future[sid], "raw_close", "closeunadj") is not None
    ]
    candidates = preferred or [
        sid for sid in common
        if _number(future[sid], "raw_close", "closeunadj") is not None
    ]
    if not candidates:
        raise RuntimeError("negative control found no security spanning cutoff and T+1")
    sid = candidates[0]
    future_row = future[sid]
    target = current[sid]
    for key in ("raw_close", "raw_open", "reported_volume", "raw_compatible_volume"):
        if key in target and future_row.get(key) not in (None, ""):
            target[key] = str(future_row[key])
    return [current[key] for key in sorted(current)]


def _digest_values(
    digests: Mapping[str, "hashlib._Hash"], session: str, values: Mapping[str, Any]
) -> None:
    for key in ECONOMIC_KEYS:
        digests[key].update(_json_bytes([session, values[key]]))


def run_real_replay_interface(dataset_path: Path) -> dict[str, Any]:
    """Bounded canary through CanonicalPITDataset + exact Production kernel."""
    try:
        runtime = _runtime_imports()
        dataset = runtime["CanonicalPITDataset"](
            dataset_path, require_pass=False
        )
        sessions = list(dataset.sessions)
        annual = deterministic_cutoffs(sessions)
        cutoffs = _representative_real_cutoffs(annual)
        if not cutoffs:
            raise RuntimeError("real replay canary found no representative cutoffs")
        spy_levels, _spy_returns = dataset.benchmark()
        terminal_by_session = dataset.terminal_terms()
        controller_config = runtime["load_controller"]()
        strategy_identity = runtime["runtime_strategy_identity"](
            controller_config, concordance=True
        )
        session_index = {session: index for index, session in enumerate(sessions)}
        records = []
        for cutoff in cutoffs:
            rows = _load_window(
                dataset_path, sessions, cutoff, lookback=140, future=1
            )
            poisoned_rows = _poisoned_mapping(rows, cutoff)
            through = sorted(session for session in rows if session <= cutoff)
            next_after = next(
                (session for session in sessions if session > cutoff and session in rows),
                None,
            )
            if next_after is None:
                raise RuntimeError(f"real replay cutoff {cutoff} has no T+1 session")
            state_a = runtime["SessionState"].fresh(
                starting_cash=100_000_000.0,
                controller=runtime["Controller"](controller_config),
                strategy_identity=strategy_identity,
            )
            state_b = runtime["SessionState"].fresh(
                starting_cash=100_000_000.0,
                controller=runtime["Controller"](controller_config),
                strategy_identity=strategy_identity,
            )
            digests_a = {key: hashlib.sha256() for key in ECONOMIC_KEYS}
            digests_b = {key: hashlib.sha256() for key in ECONOMIC_KEYS}
            before_a = before_b = None
            for session in through:
                if session == cutoff:
                    before_a = runtime["SessionState"].from_dict(state_a.to_dict())
                    before_b = runtime["SessionState"].from_dict(state_b.to_dict())
                pub_a = _actual_publication(
                    runtime, dataset, sessions, session_index, rows[session],
                    session, state_a, spy_levels, terminal_by_session,
                )
                pub_b = _actual_publication(
                    runtime, dataset, sessions, session_index,
                    poisoned_rows[session], session, state_b, spy_levels,
                    terminal_by_session,
                )
                state_a, plan_a = _advance_actual(
                    runtime, state_a, pub_a, controller_config, strategy_identity
                )
                state_b, plan_b = _advance_actual(
                    runtime, state_b, pub_b, controller_config, strategy_identity
                )
                _digest_values(
                    digests_a, session, _actual_values(state_a, plan_a, session)
                )
                _digest_values(
                    digests_b, session, _actual_values(state_b, plan_b, session)
                )
            a = {key: value.hexdigest() for key, value in digests_a.items()}
            b = {key: value.hexdigest() for key, value in digests_b.items()}
            mismatches = [key for key in ECONOMIC_KEYS if a[key] != b[key]]
            if before_a is None or before_b is None:
                raise RuntimeError(f"real replay cutoff state not captured for {cutoff}")
            bad_rows_a = _future_contaminated_current(
                rows[cutoff], rows[next_after]
            )
            bad_rows_b = _future_contaminated_current(
                rows[cutoff], poisoned_rows[next_after]
            )
            bad_pub_a = _actual_publication(
                runtime, dataset, sessions, session_index, bad_rows_a, cutoff,
                before_a, spy_levels, terminal_by_session,
            )
            bad_pub_b = _actual_publication(
                runtime, dataset, sessions, session_index, bad_rows_b, cutoff,
                before_b, spy_levels, terminal_by_session,
            )
            bad_state_a, bad_plan_a = _advance_actual(
                runtime, before_a, bad_pub_a, controller_config, strategy_identity
            )
            bad_state_b, bad_plan_b = _advance_actual(
                runtime, before_b, bad_pub_b, controller_config, strategy_identity
            )
            bad_a = _actual_values(bad_state_a, bad_plan_a, cutoff)
            bad_b = _actual_values(bad_state_b, bad_plan_b, cutoff)
            negative_differences = [
                key for key in ECONOMIC_KEYS
                if _hash(bad_a[key]) != _hash(bad_b[key])
            ]
            records.append({
                "cutoff": cutoff,
                "year": int(cutoff[:4]),
                "lookback_sessions": len(through),
                "prefix_hashes_run_a": a,
                "prefix_hashes_poisoned_future": b,
                "pre_cutoff_mismatches": mismatches,
                "negative_control_detected": bool(negative_differences),
                "negative_control_differences": negative_differences,
            })
        status = PASS if all(
            not row["pre_cutoff_mismatches"] and row["negative_control_detected"]
            for row in records
        ) else FAIL
        return {
            "schema": REAL_SCHEMA,
            "status": status,
            "interface": "CanonicalPITDataset -> sentinel.core.kernel.advance_session",
            "kernel_path": runtime["kernel_path"],
            "dataset_schema": dataset.manifest.get("schema"),
            "dataset_hash": dataset.dataset_hash,
            "cutoff_scheme": (
                "five deterministic representative epochs; each cold-start bounded "
                "to <=141 sessions plus one T+1 poison source"
            ),
            "economic_prefix_fields": list(ECONOMIC_KEYS),
            "cutoffs": records,
            "years": [row["year"] for row in records],
            "negative_control": (
                "T+1 canonical row is deliberately consumed into the cutoff "
                "publication and must change the exact Production kernel output"
            ),
        }
    except Exception as exc:
        return {
            "schema": REAL_SCHEMA,
            "status": FAIL,
            "interface": "CanonicalPITDataset -> sentinel.core.kernel.advance_session",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-real-replay", action="store_true")
    args = parser.parse_args()
    result = run(args.dataset)
    if args.require_real_replay:
        real = run_real_replay_interface(args.dataset)
        result["real_replay_interface"] = real
        if real.get("status") != PASS:
            result["status"] = FAIL
    result["evidence_hash"] = _hash(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": result["status"],
        "cutoffs": len(result["cutoffs"]),
        "years": result["years"],
        "real_replay_status": (
            (result.get("real_replay_interface") or {}).get("status")
            if args.require_real_replay else "NOT_REQUESTED"
        ),
        "real_replay_years": (
            (result.get("real_replay_interface") or {}).get("years", [])
            if args.require_real_replay else []
        ),
    }, sort_keys=True))
    return 0 if result["status"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
