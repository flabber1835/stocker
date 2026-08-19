#!/usr/bin/env python3
"""Compare authoritative Wealth Core chain rehearsals across the #185 fix.

This tool is deliberately a READER. It does not run Wealth Core, alter expected
hashes, or decide that a new baseline is acceptable. Its inputs are two exported
``sentinel.rehearsal_envelope/1`` records produced from authoritative
``bt_wealth_core_runs`` rows by ``scripts/sentinel_rehearsal.py export``.

The old and corrected runs must cover the same window with the same canonical
strategy economics. The report then separates:

* parity/data identity changes;
* exact session intent differences (the strategy's trade instructions);
* final-book differences;
* the shared authoritative performance block (CAGR/drawdown/turnover); and
* a report-only zero-risk-free annualised Sharpe computed from the retained full
  session equity series.

Sharpe convention is explicit rather than implied: simple per-session returns,
sample standard deviation, zero risk-free rate, sqrt(252) annualisation. A run
with any missing resolved-equity session is refused for Sharpe; carrying or
interpolating an unseen valuation would manufacture evidence.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Mapping

ENVELOPE_SCHEMA = "sentinel.rehearsal_envelope/1"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: envelope root is not an object")
    if value.get("schema") != ENVELOPE_SCHEMA:
        raise ValueError(
            f"{path}: schema {value.get('schema')!r} is not {ENVELOPE_SCHEMA!r}")
    if value.get("status") != "success" or value.get("mode") != "chain_rehearsal":
        raise ValueError(
            f"{path}: requires successful chain_rehearsal, got "
            f"status={value.get('status')!r} mode={value.get('mode')!r}")
    if not isinstance(value.get("spec"), Mapping):
        raise ValueError(f"{path}: spec is not an object")
    if not isinstance(value.get("summary"), Mapping):
        raise ValueError(f"{path}: summary is not an object")
    return value


def _economic_spec(env: Mapping) -> dict:
    spec = env["spec"]
    # Engine/image identities are expected to differ across the correction.
    # Retention is evidence shape, not strategy economics. Everything else here
    # names the requested strategy/capital/window and must remain identical.
    return {
        "start_date": str(spec.get("start_date")),
        "end_date": str(spec.get("end_date")),
        "starting_cash": float(spec.get("starting_cash")),
        "config": spec.get("config") or {},
        "eligibility": spec.get("eligibility") or {},
        "change": spec.get("change") or {},
    }


def _canonical_sha(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _performance(env: Mapping) -> dict:
    perf = env["summary"].get("performance")
    if not isinstance(perf, Mapping):
        raise ValueError(f"run {env.get('run_id')} carries no performance object")
    return dict(perf)


def _sharpe(env: Mapping) -> dict:
    spec = _economic_spec(env)
    sessions = env["summary"].get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(
            f"run {env.get('run_id')} has no full session evidence; rerun with "
            "retention_mode='full' for #185 Sharpe/trade recertification")
    previous = float(spec["starting_cash"])
    returns: list[float] = []
    for index, row in enumerate(sessions):
        if not isinstance(row, Mapping):
            raise ValueError(f"session row {index} is not an object")
        equity = row.get("resolved_equity")
        if equity is None:
            raise ValueError(
                f"run {env.get('run_id')} session {row.get('session')} has no "
                "resolved_equity; refusing to invent a Sharpe across an "
                "unobserved valuation")
        equity = float(equity)
        if not math.isfinite(equity) or equity <= 0 or previous <= 0:
            raise ValueError(
                f"run {env.get('run_id')} has invalid equity {equity!r} at "
                f"session {row.get('session')}")
        returns.append(equity / previous - 1.0)
        previous = equity
    if len(returns) < 2:
        return {"value": None, "reason": "fewer than two session returns"}
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return {"value": None, "reason": "zero return standard deviation"}
    value = math.sqrt(252.0) * statistics.mean(returns) / stdev
    return {
        "value": round(value, 6),
        "reason": None,
        "convention": "simple-session-returns/sample-stdev/rf=0/sqrt252",
        "observations": len(returns),
    }


def _intent_counter(env: Mapping) -> collections.Counter:
    out: collections.Counter = collections.Counter()
    sessions = env["summary"].get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("summary.sessions is not a list")
    for row in sessions:
        session = str(row.get("session"))
        intents = row.get("intents")
        if not isinstance(intents, list):
            raise ValueError(f"{session}: intents is not a list")
        for intent in intents:
            if not isinstance(intent, Mapping):
                raise ValueError(f"{session}: intent is not an object")
            # Preserve every field. A quantity/reason/identity change is a trade
            # difference, even when operation/security happen to be unchanged.
            key = json.dumps(
                {"session": session, "intent": dict(intent)},
                sort_keys=True, separators=(",", ":"), default=str)
            out[key] += 1
    return out


def _decode_counter(counter: collections.Counter, limit: int = 100) -> list[dict]:
    rows: list[dict] = []
    for key in sorted(counter):
        rows.append({"count": int(counter[key]), **json.loads(key)})
        if len(rows) >= limit:
            break
    return rows


def _book(env: Mapping) -> dict:
    book = env["summary"].get("book_artifact")
    if not isinstance(book, Mapping):
        raise ValueError(f"run {env.get('run_id')} carries no book_artifact")
    return dict(book)


def compare(old: Mapping, new: Mapping) -> dict:
    old_spec, new_spec = _economic_spec(old), _economic_spec(new)
    if old_spec != new_spec:
        raise ValueError(
            "pre/post runs do not have identical economic specs; refusing to "
            "attribute the result to the liquidity correction")

    old_intents, new_intents = _intent_counter(old), _intent_counter(new)
    removed = old_intents - new_intents
    added = new_intents - old_intents
    old_book, new_book = _book(old), _book(new)
    old_perf, new_perf = _performance(old), _performance(new)
    metric_names = (
        "ending_equity", "ending_wealth_multiple", "total_return", "cagr",
        "maximum_drawdown", "trade_count", "gross_traded_notional",
        "gross_turnover", "annualized_turnover", "benchmark_cagr",
        "excess_cagr",
    )
    perf_delta = {}
    for name in metric_names:
        left, right = old_perf.get(name), new_perf.get(name)
        delta = None
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta = round(float(right) - float(left), 6)
        perf_delta[name] = {"before": left, "after": right, "delta": delta}

    old_sharpe, new_sharpe = _sharpe(old), _sharpe(new)
    sharpe_delta = None
    if old_sharpe["value"] is not None and new_sharpe["value"] is not None:
        sharpe_delta = round(new_sharpe["value"] - old_sharpe["value"], 6)

    old_hashes = old.get("parity_hashes") or {}
    new_hashes = new.get("parity_hashes") or {}
    changed_hashes = sorted(
        key for key in set(old_hashes) | set(new_hashes)
        if old_hashes.get(key) != new_hashes.get(key))

    return {
        "schema": "wealth_core.liquidity_recertification/1",
        "change": "Sharadar split-compatible liquidity domain (#185)",
        "economic_spec_sha256": _canonical_sha(old_spec),
        "economic_spec": old_spec,
        "before": {"run_id": old.get("run_id")},
        "after": {"run_id": new.get("run_id")},
        "parity": {
            "changed_layers": changed_hashes,
            "before": old_hashes,
            "after": new_hashes,
        },
        "trade_intents": {
            "before_count": sum(old_intents.values()),
            "after_count": sum(new_intents.values()),
            "removed_count": sum(removed.values()),
            "added_count": sum(added.values()),
            "identical": not removed and not added,
            "removed_sample": _decode_counter(removed),
            "added_sample": _decode_counter(added),
            "samples_truncated": len(removed) > 100 or len(added) > 100,
        },
        "final_book": {
            "before_sha256": _canonical_sha(old_book),
            "after_sha256": _canonical_sha(new_book),
            "identical": old_book == new_book,
            "before_held": len(old_book.get("held") or []),
            "after_held": len(new_book.get("held") or []),
        },
        "performance": perf_delta,
        "sharpe": {
            "before": old_sharpe,
            "after": new_sharpe,
            "delta": sharpe_delta,
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = compare(_load(Path(args.before)), _load(Path(args.after)))
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({
        "status": "PASS",
        "out": args.out,
        "trade_intents_identical": report["trade_intents"]["identical"],
        "final_book_identical": report["final_book"]["identical"],
        "changed_parity_layers": report["parity"]["changed_layers"],
        "cagr_delta": report["performance"]["cagr"]["delta"],
        "max_drawdown_delta": report["performance"]["maximum_drawdown"]["delta"],
        "sharpe_delta": report["sharpe"]["delta"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
