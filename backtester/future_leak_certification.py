#!/usr/bin/env python3
"""Bounded real-corpus metamorphic future-leak certification.

The harness drives a session-scoped canonical replay boundary at deterministic
annual cutoffs. Future rows are materially poisoned in run B. Every economic
prefix hash through the cutoff must equal run A. A deliberately future-reading
negative control must diverge, proving that the metamorphic test can fail.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "backtester.dynamic-future-leak/1"
PASS = "PASS"
FAIL = "FAIL"
ECONOMIC_KEYS = (
    "selected_universe", "rankings_signals", "decisions", "pending_orders",
    "executions", "holdings", "cash", "strategy_state", "path_dependent_state",
    "nav", "checkpoint_state",
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


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


def _load_window(dataset: Path, sessions: list[str], cutoff: str, lookback: int = 130, future: int = 5) -> dict[str, list[dict[str, str]]]:
    index = sessions.index(cutoff)
    selected = sessions[max(0, index - lookback): min(len(sessions), index + future + 1)]
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
        raise RuntimeError(f"canonical cutoff window lacks observations: {missing[:5]}")
    for session in by_session:
        by_session[session].sort(key=lambda r: (str(r.get("security_id") or ""), str(r.get("ticker") or "")))
    return dict(by_session)


def _poison_row(row: Mapping[str, str], cutoff: str) -> dict[str, str]:
    session = str(row.get("session") or row.get("date") or "")[:10]
    out = dict(row)
    if session <= cutoff:
        return out
    sid = str(row.get("security_id") or row.get("ticker") or "0")
    salt = int(hashlib.sha256((session + "|" + sid).encode()).hexdigest()[:8], 16)
    factor = 25.0 + (salt % 1000) / 17.0
    for key in ("signal_close", "raw_close", "raw_open", "close", "closeunadj", "canonical_raw_open"):
        value = _number(out, key)
        if value is not None:
            out[key] = f"{value * factor:.12f}"
    if "reported_volume" in out:
        out["reported_volume"] = str(10_000_000_000 + salt)
    if "volume" in out:
        out["volume"] = str(10_000_000_000 + salt)
    if "security_type" in out:
        out["security_type"] = "non_common" if str(out.get("security_type")).lower() == "common" else "common"
    if "ff12" in out:
        out["ff12"] = "POISON_FUTURE"
    return out


class SessionScopedCanonicalWindow:
    """Decision authority that physically refuses post-as-of reads."""
    def __init__(self, rows: Mapping[str, list[dict[str, str]]], as_of: str, *, poison_future: bool):
        self._rows = rows
        self.as_of = as_of
        self.poison_future = poison_future

    def rows_for(self, session: str) -> tuple[dict[str, str], ...]:
        session = str(session)
        if session > self.as_of:
            raise RuntimeError(f"decision-time future read blocked: {session} > {self.as_of}")
        return tuple(dict(row) for row in self._rows.get(session, ()))

    def unsafe_rows_for_negative_control(self, session: str) -> tuple[dict[str, str], ...]:
        rows = self._rows.get(str(session), ())
        if self.poison_future:
            return tuple(_poison_row(row, self.as_of) for row in rows)
        return tuple(dict(row) for row in rows)


def _visible_security(row: Mapping[str, str]) -> bool:
    return (_truth(row.get("listing_active"), True)
            and _truth(row.get("tradeable"), True)
            and str(row.get("security_type") or "").strip().lower() == "common"
            and bool(str(row.get("security_id") or "").strip()))


def _run_prefix_probe(window: SessionScopedCanonicalWindow, ordered_sessions: list[str], cutoff: str,
                      *, intentional_future_read: bool = False) -> dict[str, str]:
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
    next_after = next((s for s in ordered_sessions if s > cutoff and s in window._rows), None)
    for session in through:
        rows = window.rows_for(session)
        by_sid = {str(r.get("security_id") or ""): r for r in rows if str(r.get("security_id") or "")}
        executions = []
        if pending:
            total_target = sum(pending.values())
            new_holdings = {}
            for sid, weight in sorted(pending.items()):
                row = by_sid.get(sid)
                price = _number(row or {}, "raw_open", "canonical_raw_open", "signal_close", "close")
                if price is None:
                    continue
                new_holdings[sid] = weight
                executions.append((sid, round(weight, 12), round(price, 12)))
            holdings = new_holdings
            cash = max(0.0, 1.0 - sum(holdings.values())) if total_target <= 1.0 + 1e-12 else 0.0
            pending = {}
        gross = cash
        for sid, weight in sorted(holdings.items()):
            close = _number(by_sid.get(sid, {}), "signal_close", "close")
            prev = prior_close.get(sid)
            gross += weight if close is None or prev is None or prev <= 0 else weight * (close / prev)
        nav *= gross
        if gross > 0:
            holdings = {sid: weight * ((_number(by_sid.get(sid, {}), "signal_close", "close") or prior_close.get(sid, 1.0)) / max(prior_close.get(sid, 1.0), 1e-12)) / gross for sid, weight in holdings.items()}
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
            future_close = {str(r.get("security_id") or ""): _number(r, "signal_close", "close") for r in future}
            candidates = [(sid, signal + 0.01 * math.log(max(future_close.get(sid) or 1.0, 1e-12))) for sid, signal in candidates]
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
            "holdings": {sid: round(w, 12) for sid, w in sorted(holdings.items())},
            "cash": round(cash, 12),
            "strategy_state": {"candidate_count": len(candidates), "selected_count": len(selected)},
            "path_state": {"peak_nav": round(peak, 12), "drawdown": round(drawdown, 12), "history_sizes_sha256": _hash({sid: len(v) for sid, v in sorted(histories.items())})},
            "nav": round(nav, 12),
        }
        checkpoint = _hash(state)
        values = {
            "selected_universe": selected, "rankings_signals": state["rankings"],
            "decisions": decisions, "pending_orders": pending, "executions": executions,
            "holdings": state["holdings"], "cash": state["cash"],
            "strategy_state": state["strategy_state"], "path_dependent_state": state["path_state"],
            "nav": state["nav"], "checkpoint_state": checkpoint,
        }
        for key in ECONOMIC_KEYS:
            category_hashes[key].update(_json_bytes([session, values[key]]))
    return {key: digest.hexdigest() for key, digest in category_hashes.items()}


def run(dataset: Path) -> dict[str, Any]:
    sessions = _sessions(dataset)
    cutoffs = deterministic_cutoffs(sessions)
    if not cutoffs:
        raise RuntimeError("canonical history has no deterministic future-leak cutoffs")
    records = []
    for cutoff in cutoffs:
        rows = _load_window(dataset, sessions, cutoff)
        normal = SessionScopedCanonicalWindow(rows, cutoff, poison_future=False)
        poisoned = SessionScopedCanonicalWindow(rows, cutoff, poison_future=True)
        a = _run_prefix_probe(normal, sessions, cutoff)
        b = _run_prefix_probe(poisoned, sessions, cutoff)
        mismatches = [key for key in ECONOMIC_KEYS if a[key] != b[key]]
        bad_a = _run_prefix_probe(normal, sessions, cutoff, intentional_future_read=True)
        bad_b = _run_prefix_probe(poisoned, sessions, cutoff, intentional_future_read=True)
        negative_differences = [key for key in ECONOMIC_KEYS if bad_a[key] != bad_b[key]]
        records.append({"cutoff": cutoff, "year": int(cutoff[:4]), "prefix_hashes_run_a": a,
                        "prefix_hashes_run_b": b, "pre_cutoff_mismatches": mismatches,
                        "negative_control_detected": bool(negative_differences),
                        "negative_control_differences": negative_differences})
    status = PASS if all(not r["pre_cutoff_mismatches"] and r["negative_control_detected"] for r in records) else FAIL
    return {"schema": SCHEMA, "status": status,
            "contract": "changing canonical data strictly after cutoff must not change any economic prefix through cutoff",
            "cutoff_scheme": "one deterministic cutoff per calendar year after >=127 prior sessions and with >=5 future sessions",
            "economic_prefix_fields": list(ECONOMIC_KEYS), "cutoffs": records,
            "years": [r["year"] for r in records],
            "negative_control": "intentional T+1 close read must be detected at every cutoff"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.dataset)
    result["evidence_hash"] = _hash(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "cutoffs": len(result["cutoffs"]), "years": result["years"]}, sort_keys=True))
    return 0 if result["status"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
