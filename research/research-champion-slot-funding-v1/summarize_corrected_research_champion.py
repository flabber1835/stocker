#!/usr/bin/env python3
"""Structural-first diagnostics for corrected Research Champion slot funding."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MEASUREMENT_START = pd.Timestamp("2006-07-31")
END = pd.Timestamp("2026-07-31")


def _daily(root: Path) -> pd.DataFrame:
    path = root / "daily.csv.gz"
    if not path.is_file():
        raise RuntimeError(f"missing replay daily evidence: {path}")
    d = pd.read_csv(path, compression="gzip", parse_dates=["date"])
    d = d[(d.date >= MEASUREMENT_START) & (d.date <= END)].copy()
    if d.empty:
        raise RuntimeError("measurement window is empty")
    return d.reset_index(drop=True)


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def structural(root: Path, output: Path) -> int:
    d = _daily(root)
    required = {
        "research_wealth_core_equity",
        "slot_funding_cash",
        "slot_funding_receivables",
        "slot_funding_reserved_cash",
        "slot_funding_uncommitted_cash",
        "slot_funding_held_count",
        "slot_funding_pending_count",
        "slot_funding_ready_count",
        "slot_funding_rejections",
        "slot_funding_fill_count",
        "slot_funding_gap_clipped_count",
        "slot_funding_open_budget_cancels",
        "slot_funding_min_fill_fraction",
    }
    missing = sorted(required.difference(d.columns))
    if missing:
        raise RuntimeError(f"slot-funding structural columns missing: {missing}")

    numeric = {c: pd.to_numeric(d[c], errors="raise") for c in required}
    cash = numeric["slot_funding_cash"].astype(float)
    reserved = numeric["slot_funding_reserved_cash"].astype(float)
    uncommitted = numeric["slot_funding_uncommitted_cash"].astype(float)
    equity = numeric["research_wealth_core_equity"].astype(float)
    if not np.isfinite(equity).all() or (equity <= 0).any():
        raise RuntimeError("non-positive/non-finite Wealth Core equity in measurement window")
    if (reserved - cash > 1e-6).any():
        bad = d.loc[(reserved - cash > 1e-6), "date"].iloc[0]
        raise RuntimeError(f"reserved entry cash exceeds account cash on {bad.date()}")
    if (uncommitted < -1e-6).any():
        bad = d.loc[(uncommitted < -1e-6), "date"].iloc[0]
        raise RuntimeError(f"negative uncommitted cash on {bad.date()}")
    if ((numeric["slot_funding_held_count"] + numeric["slot_funding_pending_count"]) > 25).any():
        raise RuntimeError("held + pending exceeds 25-slot capacity")

    rejections = numeric["slot_funding_rejections"].astype(int)
    reject_delta = rejections.diff().fillna(rejections.iloc[0]).clip(lower=0)
    held = numeric["slot_funding_held_count"].astype(int)
    pending = numeric["slot_funding_pending_count"].astype(int)
    ready = numeric["slot_funding_ready_count"].astype(int)
    cash_frac = cash / equity
    reserved_frac = reserved / equity
    uncommitted_frac = uncommitted / equity

    result = {
        "schema": "research.corrected-champion-slot-funding-structural/1",
        "status": "PASS",
        "performance_examined": False,
        "measurement": {
            "start": str(d.date.iloc[0].date()),
            "end": str(d.date.iloc[-1].date()),
            "sessions": int(len(d)),
        },
        "capacity": {
            "physical_slots": 25,
            "entry_weight": 0.04,
            "held_mean": float(held.mean()),
            "held_median": float(held.median()),
            "held_min": int(held.min()),
            "held_max": int(held.max()),
            "sessions_25_held": int((held == 25).sum()),
            "sessions_with_any_vacancy": int((held < 25).sum()),
            "sessions_with_pending_entry": int((pending > 0).sum()),
            "sessions_with_ready_slot": int((ready > 0).sum()),
            "end_held": int(held.iloc[-1]),
            "end_pending": int(pending.iloc[-1]),
            "end_ready": int(ready.iloc[-1]),
        },
        "funding": {
            "admission_rejections_total": int(rejections.iloc[-1]),
            "sessions_with_funding_rejection": int((reject_delta > 0).sum()),
            "max_rejections_one_session": int(reject_delta.max()),
            "fills_total": int(numeric["slot_funding_fill_count"].iloc[-1]),
            "gap_clipped_fills_total": int(numeric["slot_funding_gap_clipped_count"].iloc[-1]),
            "open_budget_cancels_total": int(numeric["slot_funding_open_budget_cancels"].iloc[-1]),
            "minimum_fill_share_fraction": float(numeric["slot_funding_min_fill_fraction"].min()),
            "reserved_cash_never_exceeds_cash": True,
            "uncommitted_cash_never_negative": True,
        },
        "cash_fraction_of_wealth_core_equity": {
            "mean": float(cash_frac.mean()),
            "median": float(cash_frac.median()),
            "p90": float(cash_frac.quantile(0.90)),
            "max": float(cash_frac.max()),
            "end": float(cash_frac.iloc[-1]),
        },
        "reserved_cash_fraction_of_wealth_core_equity": {
            "mean": float(reserved_frac.mean()),
            "max": float(reserved_frac.max()),
            "end": float(reserved_frac.iloc[-1]),
        },
        "uncommitted_cash_fraction_of_wealth_core_equity": {
            "mean": float(uncommitted_frac.mean()),
            "median": float(uncommitted_frac.median()),
            "max": float(uncommitted_frac.max()),
            "end": float(uncommitted_frac.iloc[-1]),
        },
        "end_book_cash": {
            "cash": float(cash.iloc[-1]),
            "receivables": float(numeric["slot_funding_receivables"].iloc[-1]),
            "reserved_entry_cash": float(reserved.iloc[-1]),
            "uncommitted_cash": float(uncommitted.iloc[-1]),
            "wealth_core_equity": float(equity.iloc[-1]),
        },
    }
    _write(output, result)

    md = output.with_suffix(".md")
    md.write_text(
        "# Corrected Research Champion — structural diagnostics\n\n"
        "Status: **PASS**\n\n"
        f"Measurement: {result['measurement']['start']} through {result['measurement']['end']} "
        f"({result['measurement']['sessions']:,} sessions).\n\n"
        "Performance was deliberately not examined in this phase.\n\n"
        "## Slot/funding behavior\n\n"
        f"- funding-rejected admissions: {result['funding']['admission_rejections_total']:,}\n"
        f"- sessions with a funding rejection: {result['funding']['sessions_with_funding_rejection']:,}\n"
        f"- filled entries: {result['funding']['fills_total']:,}\n"
        f"- next-open gap-clipped fills: {result['funding']['gap_clipped_fills_total']:,}\n"
        f"- next-open reserved-budget cancellations: {result['funding']['open_budget_cancels_total']:,}\n"
        f"- minimum filled/planned share fraction: {result['funding']['minimum_fill_share_fraction']:.8f}\n"
        f"- mean held positions: {result['capacity']['held_mean']:.3f}\n"
        f"- sessions with any vacancy: {result['capacity']['sessions_with_any_vacancy']:,}\n"
        f"- end held/pending/ready: {result['capacity']['end_held']}/"
        f"{result['capacity']['end_pending']}/{result['capacity']['end_ready']}\n"
        f"- ending uncommitted cash / WC equity: "
        f"{result['uncommitted_cash_fraction_of_wealth_core_equity']['end']:.4%}\n\n"
        "Reserved entry cash never exceeded actual cash and uncommitted cash never became materially negative.\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


def _metric(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=float)
    if len(values) < 2 or not np.isfinite(values).all() or values[0] <= 0:
        raise RuntimeError("invalid performance series")
    norm = values / values[0]
    rets = norm[1:] / norm[:-1] - 1.0
    years = 20.0
    cagr = float(norm[-1] ** (1.0 / years) - 1.0)
    peak = np.maximum.accumulate(norm)
    maxdd = float(np.min(norm / peak - 1.0))
    std = float(np.std(rets, ddof=1))
    sharpe = float(np.mean(rets) / std * math.sqrt(252.0)) if std > 0 else float("nan")
    return {
        "cagr": cagr,
        "max_drawdown": maxdd,
        "sharpe": sharpe,
        "ending_multiple": float(norm[-1]),
    }


def performance(root: Path, output: Path) -> int:
    structural_path = root / "slot-funding-structural.json"
    if not structural_path.is_file():
        raise RuntimeError("structural PASS must be materialized before performance phase")
    structural_result = json.loads(structural_path.read_text(encoding="utf-8"))
    if structural_result.get("status") != "PASS" or structural_result.get("performance_examined") is not False:
        raise RuntimeError("structural phase did not pass independently")

    d = _daily(root)
    for col in ("research_nav", "research_wealth_core_equity", "spy_nav"):
        if col not in d.columns:
            raise RuntimeError(f"missing performance column {col}")
    result = {
        "schema": "research.corrected-champion-slot-funding-performance/1",
        "status": "PASS",
        "research_only": True,
        "selection_rule_changed_after_performance": False,
        "measurement": {
            "start": str(d.date.iloc[0].date()),
            "end": str(d.date.iloc[-1].date()),
            "sessions": int(len(d)),
        },
        "research_champion": _metric(d.research_nav.to_numpy(float)),
        "wealth_core": _metric(d.research_wealth_core_equity.to_numpy(float)),
        "spy": _metric(d.spy_nav.to_numpy(float)),
    }
    _write(output, result)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("structural", "performance"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "structural":
        return structural(args.root, args.output)
    return performance(args.root, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
