#!/usr/bin/env python3
"""Classify every unresolved split against nearby frozen SEP domain transitions.

Input is the output of scan_full_corpus_unresolved_splits.py.  This diagnostic
never runs strategy code.  It checks whether an ACTIONS ratio (or its reciprocal)
appears on the action session or a nearby trading session, which distinguishes
shifted effective dates from true ACTIONS-vs-SEP contradictions.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from stock_strategy_shared.split_reconciliation import split_ratio_from_prices

WINDOW_DAYS = 25
MATCH_TOL = 0.01
NO_EVENT_TOL = 0.02


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def relerr(a: float, b: float) -> float:
    return abs(float(a) - float(b)) / max(abs(float(a)), abs(float(b)), 1e-15)


def main() -> int:
    root = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    source = Path(os.environ.get(
        "BACKTESTER_SPLIT_SCAN_OUTPUT",
        "backtester-results/full-corpus-unresolved-splits.json",
    )).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_SPLIT_WINDOW_OUTPUT",
        "backtester-results/all-unresolved-split-window-triage.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    scan = json.loads(source.read_text(encoding="utf-8"))
    events = list(scan.get("unresolved_splits") or [])
    if scan.get("status") != "PASS" or len(events) != 128:
        raise RuntimeError(f"unexpected split-scan input: status={scan.get('status')} count={len(events)}")

    with (root / "PIT input data" / "MANIFEST.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        manifest = {row["file"]: row for row in csv.DictReader(f)}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by_ticker[str(event["ticker"])].append(event)
    target_tickers = set(by_ticker)

    collected: dict[str, list[dict]] = defaultdict(list)
    observed_hashes = {}
    for year in range(1998, 2027):
        path = root / "sharadar" / f"SHARADAR_SEP_{year}.csv.gz"
        expected = manifest[f"SEP_{year}_PIT_ONLY.csv.gz"]["source_sha256"]
        got = sha256(path)
        if got != expected:
            raise RuntimeError(f"SEP {year} hash mismatch")
        observed_hashes[str(path.relative_to(root))] = got

        frame = pd.read_csv(
            path,
            compression="gzip",
            usecols=["ticker", "date", "close", "closeunadj"],
            low_memory=False,
        )
        frame["ticker"] = frame["ticker"].astype(str)
        frame = frame[frame["ticker"].isin(target_tickers)].copy()
        if frame.empty:
            continue
        frame["date"] = frame["date"].astype(str).str[:10]
        frame.sort_values(["ticker", "date"], inplace=True, kind="mergesort")
        frame.drop_duplicates(["ticker", "date"], keep="last", inplace=True)
        for row in frame.itertuples(index=False):
            collected[str(row.ticker)].append({
                "date": str(row.date),
                "close": None if pd.isna(row.close) else float(row.close),
                "closeunadj": None if pd.isna(row.closeunadj) else float(row.closeunadj),
            })
        del frame
        print(f"[WINDOW-SCAN] loaded year={year} target_rows={sum(len(v) for v in collected.values()):,}", flush=True)

    transitions: dict[str, list[dict]] = defaultdict(list)
    for ticker, rows in collected.items():
        rows.sort(key=lambda row: row["date"])
        for prev, cur in zip(rows, rows[1:]):
            derived = split_ratio_from_prices(
                prev["close"], prev["closeunadj"], cur["close"], cur["closeunadj"])
            if derived is None or not math.isfinite(float(derived)) or float(derived) <= 0:
                continue
            transitions[ticker].append({
                "previous_session": prev["date"],
                "session": cur["date"],
                "derived_ratio": float(derived),
                "previous_close": prev["close"],
                "previous_closeunadj": prev["closeunadj"],
                "close": cur["close"],
                "closeunadj": cur["closeunadj"],
            })

    results = []
    counts: dict[str, int] = defaultdict(int)
    for event in sorted(events, key=lambda row: (str(row["session"]), str(row["ticker"]))):
        ticker = str(event["ticker"])
        session = str(event["session"])
        stated = float(event["stated"])
        target_day = date.fromisoformat(session)
        near = []
        for row in transitions.get(ticker, ()): 
            distance = (date.fromisoformat(row["session"]) - target_day).days
            if abs(distance) > WINDOW_DAYS:
                continue
            item = dict(row)
            item["calendar_offset_days"] = distance
            item["direct_relative_error"] = relerr(row["derived_ratio"], stated)
            item["inverse_relative_error"] = relerr(row["derived_ratio"], 1.0 / stated)
            near.append(item)

        exact = next((row for row in near if row["session"] == session), None)
        best_direct = min(near, key=lambda row: row["direct_relative_error"]) if near else None
        best_inverse = min(near, key=lambda row: row["inverse_relative_error"]) if near else None

        if exact is not None and exact["direct_relative_error"] <= MATCH_TOL:
            classification = "exact_direct_match"
        elif exact is not None and exact["inverse_relative_error"] <= MATCH_TOL:
            classification = "exact_inverse_match"
        elif (best_direct is not None and best_direct["session"] != session
              and best_direct["direct_relative_error"] <= MATCH_TOL):
            classification = "shifted_direct_match"
        elif (best_inverse is not None and best_inverse["session"] != session
              and best_inverse["inverse_relative_error"] <= MATCH_TOL):
            classification = "shifted_inverse_match"
        elif exact is not None and abs(float(exact["derived_ratio"]) - 1.0) <= NO_EVENT_TOL:
            classification = "exact_no_transition_no_nearby_match"
        else:
            classification = "unresolved_price_domain_conflict"
        counts[classification] += 1

        results.append({
            "ticker": ticker,
            "action_session": session,
            "stated_ratio": stated,
            "original_derived_ratio": event.get("derived"),
            "classification": classification,
            "exact_transition": exact,
            "best_direct_nearby": best_direct,
            "best_inverse_nearby": best_inverse,
            "material_nearby_transitions": [
                row for row in near if abs(float(row["derived_ratio"]) - 1.0) > NO_EVENT_TOL
            ],
        })

    payload = {
        "schema": "backtester.all-unresolved-split-window-triage/1",
        "status": "PASS",
        "diagnostic_only": True,
        "strategy_execution": False,
        "strategy_main_sha": os.environ.get("BACKTESTER_MAIN_SHA"),
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "source_split_scan_sha256": sha256(source),
        "window_calendar_days": WINDOW_DAYS,
        "match_relative_tolerance": MATCH_TOL,
        "event_count": len(results),
        "classification_counts": dict(sorted(counts.items())),
        "source_hashes": observed_hashes,
        "results": results,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "event_count": len(results),
        "classification_counts": dict(sorted(counts.items())),
        "non_no_transition": [
            {"ticker": row["ticker"], "action_session": row["action_session"],
             "classification": row["classification"]}
            for row in results if row["classification"] != "exact_no_transition_no_nearby_match"
        ],
    }, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
