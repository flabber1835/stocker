#!/usr/bin/env python3
"""Strict-PIT certification orchestrator for production/research/SPY.

Warm-up runs from 1997-01-02 through 1997-12-31 and is never measured.
Measurement starts 1998-01-02. Progress is emitted every calendar quarter
using cumulative CAGR from the measurement start through the reported date.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable

import pandas as pd

WARMUP_START = pd.Timestamp("1997-01-02")
MEASUREMENT_START = pd.Timestamp("1998-01-02")
PRODUCTION_WRAPPER = Path("backtester/run_production_ldrc_corrected_warmup_cash.py")
RESEARCH_WRAPPER = Path("backtester/run_research_ldrc_corrected_warmup_cash.py")


def quarter_end_dates(start: pd.Timestamp, end: pd.Timestamp) -> set[pd.Timestamp]:
    return set(pd.date_range(start=start, end=end, freq="QE").normalize())


def cagr(start_value: float, end_value: float, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float:
    if not all(math.isfinite(v) and v > 0 for v in (start_value, end_value)):
        return float("nan")
    days = (end_date - start_date).days
    if days <= 0:
        return float("nan")
    return (end_value / start_value) ** (365.2425 / days) - 1.0


def read_daily(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    if "nav" not in df.columns:
        raise RuntimeError(f"{path} missing nav column")
    return df.sort_values("date").reset_index(drop=True)


def read_spy(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    value_col = "closeadj" if "closeadj" in df.columns else "close"
    if value_col not in df.columns:
        raise RuntimeError(f"{path} missing closeadj/close")
    return df[["date", value_col]].rename(columns={value_col: "nav"}).sort_values("date")


def value_on_or_before(df: pd.DataFrame, date: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    part = df[df.date <= date]
    if part.empty:
        raise RuntimeError(f"no data on/before {date.date()}")
    row = part.iloc[-1]
    return pd.Timestamp(row.date), float(row.nav)


def emit_warmup_progress(dates: Iterable[pd.Timestamp]) -> None:
    for d in dates:
        print(f"[WARMUP] {d.date()} full machine state accumulating; CAGR=N/A", flush=True)


def emit_progress(prod: pd.DataFrame, research: pd.DataFrame, spy: pd.DataFrame) -> None:
    common_end = min(prod.date.max(), research.date.max(), spy.date.max())
    qends = quarter_end_dates(MEASUREMENT_START, common_end)
    start_prod_date, start_prod = value_on_or_before(prod, MEASUREMENT_START)
    start_research_date, start_research = value_on_or_before(research, MEASUREMENT_START)
    start_spy_date, start_spy = value_on_or_before(spy, MEASUREMENT_START)
    start_date = max(start_prod_date, start_research_date, start_spy_date)

    for q in sorted(qends):
        p_date, p = value_on_or_before(prod, q)
        r_date, r = value_on_or_before(research, q)
        s_date, s = value_on_or_before(spy, q)
        report_date = min(p_date, r_date, s_date)
        if report_date < start_date:
            continue
        pc = cagr(start_prod, p, start_date, report_date)
        rc = cagr(start_research, r, start_date, report_date)
        sc = cagr(start_spy, s, start_date, report_date)
        print(f"[CERTIFICATION PROGRESS] {report_date.date()}", flush=True)
        print(f"Research cumulative CAGR:      {rc*100:10.4f}%", flush=True)
        print(f"Production cumulative CAGR:    {pc*100:10.4f}%", flush=True)
        print(f"SPY cumulative CAGR:           {sc*100:10.4f}%", flush=True)
        print("", flush=True)


def first_divergence(prod: pd.DataFrame, research: pd.DataFrame, tolerance: float) -> dict | None:
    merged = prod[["date", "nav"]].merge(
        research[["date", "nav"]], on="date", suffixes=("_production", "_research"), how="inner"
    )
    merged = merged[merged.date >= MEASUREMENT_START]
    for row in merged.itertuples(index=False):
        delta = abs(float(row.nav_production) - float(row.nav_research))
        scale = max(abs(float(row.nav_production)), abs(float(row.nav_research)), 1.0)
        if delta > tolerance * scale:
            return {
                "date": pd.Timestamp(row.date).date().isoformat(),
                "production_nav": float(row.nav_production),
                "research_nav": float(row.nav_research),
                "absolute_delta": delta,
                "relative_delta": delta / scale,
            }
    return None


def run_wrapper(wrapper: Path, output: Path, env: dict[str, str]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(wrapper), "--mode", "fullpit", "--output", str(output)],
        check=True,
        env=env,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--spy-csv", type=Path, required=True)
    ap.add_argument("--divergence-tolerance", type=float, default=1e-10)
    args = ap.parse_args()

    env = dict(os.environ)
    env["CERTIFICATION_STRICT_PIT"] = "1"
    env["CERTIFICATION_WARMUP_START"] = WARMUP_START.date().isoformat()
    env["CERTIFICATION_MEASUREMENT_START"] = MEASUREMENT_START.date().isoformat()

    prod_out = args.output_root / "production"
    research_out = args.output_root / "research"

    print(f"[CERTIFICATION] strict PIT warmup={WARMUP_START.date()} measurement={MEASUREMENT_START.date()}", flush=True)
    emit_warmup_progress(pd.date_range("1997-03-31", "1997-12-31", freq="QE"))

    prod = subprocess.Popen(
        [sys.executable, str(PRODUCTION_WRAPPER), "--mode", "fullpit", "--output", str(prod_out)],
        env=env,
    )
    research = subprocess.Popen(
        [sys.executable, str(RESEARCH_WRAPPER), "--mode", "fullpit", "--output", str(research_out)],
        env=env,
    )
    p_rc = prod.wait()
    r_rc = research.wait()
    if p_rc != 0 or r_rc != 0:
        raise RuntimeError(f"parallel replay failed production={p_rc} research={r_rc}")

    prod_df = read_daily(prod_out / "daily.csv.gz")
    research_df = read_daily(research_out / "daily.csv.gz")
    spy_df = read_spy(args.spy_csv)
    emit_progress(prod_df, research_df, spy_df)

    divergence = first_divergence(prod_df, research_df, args.divergence_tolerance)
    audit = {
        "warmup_start": WARMUP_START.date().isoformat(),
        "measurement_start": MEASUREMENT_START.date().isoformat(),
        "progress_cadence": "calendar-quarter",
        "cagr_basis": "cumulative from measurement start",
        "research_production_divergence_tolerance": args.divergence_tolerance,
        "first_divergence": divergence,
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "certification_progress_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if divergence is not None:
        print("[CERTIFICATION FAIL] research/production divergence detected", flush=True)
        print(json.dumps(divergence, sort_keys=True), flush=True)
        return 2

    print("[CERTIFICATION PASS] production and research replay equivalent within tolerance", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
