#!/usr/bin/env python3
"""Inspect the four remaining split conflicts whose legal date differs from vendor adjustment evidence."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import pandas as pd


CASES = {
    "DAYR": {
        "year": 1998,
        "start": "1998-03-12",
        "end": "1998-04-03",
        "legal_reference_date": "1998-03-30",
    },
    "PRTK": {
        "year": 2009,
        "start": "2009-01-26",
        "end": "2009-02-11",
        "legal_reference_date": "2009-01-30",
    },
    "NEOM": {
        "year": 2014,
        "start": "2014-05-01",
        "end": "2014-06-03",
        "legal_reference_date": "2014-05-11",
    },
    "PRPO": {
        "year": 2017,
        "start": "2017-05-30",
        "end": "2017-07-05",
        "legal_reference_date": "2017-06-13",
    },
}


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def ratio(prev, row):
    vals = (prev.get("close"), prev.get("closeunadj"), row.get("close"), row.get("closeunadj"))
    if not all(finite(v) and float(v) > 0 for v in vals):
        return None
    pc, pr, cc, cr = map(float, vals)
    return (pr * cc) / (pc * cr)


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_SPLIT_DATE_DOMAIN_OUTPUT",
        "backtester-results/split-date-domain-anomalies.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))
    base = lab / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
    spec = importlib.util.spec_from_file_location("date_domain_base", base)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {base}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    from sentinel.feed.universe import parse_related_tickers
    from stock_strategy_shared.wealth_core.feed import SecurityMeta

    main_api = {"SecurityMeta": SecurityMeta, "parse_related_tickers": parse_related_tickers}
    tickers_path = lab / "sharadar" / "SHARADAR_TICKERS.zip"
    _meta, _sectors, resolver, _canonical = runner.load_current_metadata(tickers_path, main_api)

    actions = pd.read_csv(lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz", compression="gzip", low_memory=False)
    actions["ticker"] = actions["ticker"].fillna("").astype(str)
    actions["date"] = actions["date"].astype(str).str[:10]

    cases = {}
    for ticker, cfg in CASES.items():
        sep_path = lab / "sharadar" / f"SHARADAR_SEP_{cfg['year']}.csv.gz"
        frame = pd.read_csv(
            sep_path, compression="gzip",
            usecols=["ticker", "date", "open", "close", "closeunadj", "volume"],
            low_memory=False,
        )
        frame["ticker"] = frame["ticker"].astype(str)
        frame["date"] = frame["date"].astype(str).str[:10]
        frame["_seq"] = range(len(frame))
        frame.sort_values(["date", "ticker", "_seq"], inplace=True, kind="mergesort")
        frame.drop_duplicates(["date", "ticker"], keep="last", inplace=True)
        x = frame[
            (frame["ticker"] == ticker)
            & (frame["date"] >= cfg["start"])
            & (frame["date"] <= cfg["end"])
        ].copy()
        x.sort_values("date", inplace=True, kind="mergesort")
        rows = []
        prev = None
        for r in x.itertuples(index=False):
            row = {
                "date": str(r.date),
                "security_id": resolver.resolve(ticker, str(r.date)),
                "open": None if pd.isna(r.open) else float(r.open),
                "close": None if pd.isna(r.close) else float(r.close),
                "closeunadj": None if pd.isna(r.closeunadj) else float(r.closeunadj),
                "volume": None if pd.isna(r.volume) else float(r.volume),
            }
            row["adjustment_factor_raw_over_signal"] = (
                None if not (finite(row["close"]) and finite(row["closeunadj"]) and float(row["close"]) > 0)
                else float(row["closeunadj"]) / float(row["close"])
            )
            row["derived_share_multiplier_from_previous"] = None if prev is None else ratio(prev, row)
            if prev is not None and finite(prev.get("closeunadj")) and finite(row.get("closeunadj")) and float(prev["closeunadj"]) > 0:
                row["raw_close_move"] = float(row["closeunadj"]) / float(prev["closeunadj"])
            else:
                row["raw_close_move"] = None
            rows.append(row)
            prev = row

        act = actions[
            (actions["ticker"] == ticker)
            & (actions["date"] >= cfg["start"])
            & (actions["date"] <= cfg["end"])
        ][["date", "action", "ticker", "value"]]
        cases[ticker] = {
            **cfg,
            "rows": rows,
            "actions": act.to_dict(orient="records"),
            "security_ids_in_window": sorted({str(r["security_id"]) for r in rows if r["security_id"] is not None}),
        }

    payload = {
        "schema": "backtester.split-date-domain-anomaly-inspection/1",
        "status": "PASS",
        "main_sha": os.environ.get("BACKTESTER_MAIN_SHA"),
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "cases": cases,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for ticker, case in cases.items():
        print(f"[{ticker}] security_ids={case['security_ids_in_window']} actions={case['actions']}")
        for row in case["rows"]:
            d = row["derived_share_multiplier_from_previous"]
            m = row["raw_close_move"]
            if (d is not None and abs(float(d)-1.0) > 0.02) or (m is not None and (m < 0.75 or m > 1.35)):
                print(json.dumps({"ticker":ticker, **row}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
