#!/usr/bin/env python3
"""Verify primary-source split adjudications against exact frozen-main normalization."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import pandas as pd


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_SPLIT_OVERRIDE_VERIFY_OUTPUT",
        "backtester-results/causal-split-overrides-verify.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    base_path = lab / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
    spec = importlib.util.spec_from_file_location("split_override_verify_base", base_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import base runner {base_path}")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    import sentinel.feed.domains as domains
    import stock_strategy_shared.split_reconciliation as split_module
    from sentinel.feed.actions_map import dividends_from_actions, split_ratios_from_actions
    from sentinel.feed.universe import parse_related_tickers
    from stock_strategy_shared.wealth_core.feed import SecurityMeta

    from backtester.causal_split_overrides import (
        ADJUDICATED_DISPOSITION,
        install_primary_split_adjudication,
        load_frozen_split_overrides,
    )

    expected_main = "c502d077cae9c494f8b74a41ee8be7f40b25837d"
    if os.environ.get("BACKTESTER_MAIN_SHA") != expected_main:
        raise RuntimeError("exact main identity is not pinned")

    main_api = {
        "SecurityMeta": SecurityMeta,
        "parse_related_tickers": parse_related_tickers,
        "split_ratios_from_actions": split_ratios_from_actions,
        "dividends_from_actions": dividends_from_actions,
        "TERMINAL_ACTION_SIDES": {},
    }

    sfp = lab / "PIT input data" / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"
    sessions, _spy_level, _spy_return, _bil = runner.build_sfp_levels(sfp)
    actions = lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz"
    _rows, authority, _maps = runner.load_actions(actions, sessions, main_api)
    tickers = lab / "sharadar" / "SHARADAR_TICKERS.zip"
    _meta, _sectors, resolver, _canonical = runner.load_current_metadata(tickers, main_api)

    data_path = lab / "backtester" / "data" / "causal-split-overrides-v1.json"
    checksum_path = lab / "backtester" / "data" / "causal-split-overrides-v1.SHA256"
    override_sha, overrides = load_frozen_split_overrides(
        data_path, checksum_path,
        authority=authority,
        sessions=sessions,
        resolve_identity=resolver.resolve,
    )
    if len(overrides) != 12:
        raise RuntimeError(f"expected twelve frozen split overrides, got {len(overrides)}")
    real_decide = install_primary_split_adjudication(split_module, overrides)

    by_year: dict[int, pd.DataFrame] = {}
    results = []
    try:
        for key, frozen in sorted(overrides.items(), key=lambda item: item[0][1]):
            ticker, session = key
            year = int(session[:4])
            frame = by_year.get(year)
            if frame is None:
                sep_path = lab / "sharadar" / f"SHARADAR_SEP_{year}.csv.gz"
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
                by_year[year] = frame

            rows = frame[(frame["ticker"] == ticker) & (frame["date"] <= session)].copy()
            rows.sort_values("date", inplace=True, kind="mergesort")
            if len(rows) < 2 or str(rows.iloc[-1]["date"]) != session:
                raise RuntimeError(f"missing immediate SEP predecessor/event rows for {ticker} {session}")
            pair = rows.tail(2)
            raw_rows = []
            for row in pair.itertuples(index=False):
                raw_rows.append({
                    "ticker": str(row.ticker), "date": str(row.date),
                    "open": row.open, "close": row.close,
                    "closeunadj": row.closeunadj, "volume": row.volume,
                })

            report = domains.NormalisationReport()
            bars = list(domains.normalise_sep_rows(
                raw_rows,
                resolve_identity=resolver.resolve,
                dividends={},
                authoritative_splits=authority,
                report=report,
            ))
            disposition = report.split_dispositions.get(key)
            if disposition is None:
                raise RuntimeError(f"no split disposition for adjudicated event {key}")
            if disposition.get("disposition") != ADJUDICATED_DISPOSITION:
                raise RuntimeError(f"wrong split disposition for {key}: {disposition}")
            if not math.isclose(float(disposition.get("stated")), float(frozen["expected_vendor_stated"]), rel_tol=0, abs_tol=1e-12):
                raise RuntimeError(f"vendor witness drift for {key}: {disposition}")
            if not math.isclose(float(disposition.get("derived")), float(frozen["expected_sep_derived"]), rel_tol=1e-9, abs_tol=1e-12):
                raise RuntimeError(f"SEP witness drift for {key}: {disposition}")
            if not math.isclose(float(disposition.get("applied_ratio")), float(frozen["multiplier"]), rel_tol=0, abs_tol=1e-12):
                raise RuntimeError(f"legal multiplier not applied for {key}: {disposition}")

            event_bars = [bar.vendor for bar in bars if bar.vendor.session == session]
            if len(event_bars) != 1:
                raise RuntimeError(f"expected exactly one normalized event bar for {key}")
            event_bar = event_bars[0]
            if not math.isclose(float(event_bar.split_ratio), float(frozen["multiplier"]), rel_tol=0, abs_tol=1e-12):
                raise RuntimeError(f"VendorBar split ratio wrong for {key}: {event_bar.split_ratio}")

            results.append({**frozen, "previous_session": str(pair.iloc[-2]["date"]), "runtime_disposition": disposition, "vendor_bar_split_ratio": float(event_bar.split_ratio)})
    finally:
        split_module.SplitStreamReconciler.decide = real_decide

    payload = {
        "schema": "backtester.causal-split-overrides-verify/1",
        "status": "PASS",
        "strategy_main_sha": expected_main,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "split_override_sha256": override_sha,
        "override_count": len(results),
        "results": results,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "split_override_sha256": override_sha,
        "results": [{
            "ticker": row["ticker"],
            "effective_session": row["effective_session"],
            "security_id": row["security_id"],
            "vendor_stated": row["expected_vendor_stated"],
            "sep_derived": row["expected_sep_derived"],
            "legal_multiplier": row["multiplier"],
            "disposition": row["runtime_disposition"]["disposition"],
        } for row in results],
    }, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
