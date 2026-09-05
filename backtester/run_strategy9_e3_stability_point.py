#!/usr/bin/env python3
"""Exact full-history Strategy 9 + E3 replay at one stability-basin point.

This is a robustness diagnostic. It changes only explicitly supplied scalar
thresholds in the generated research replay, then executes the same broad
full-PIT-estimate chronology and reports A/E3 economics for the point.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

from backtester import experiment_architecture_recovery_concordance_e3 as e3
from backtester import run_research_ldrc_corrected_warmup_cash as corrected


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, got {count}")
    return text.replace(old, new, 1)


def build_source(output: Path, args: argparse.Namespace) -> str:
    text = e3.transformed_source(output)

    old_constants = "LDRC_DD=-.10; LDRC_R20=-.08; LDRC_CEIL=.55; LDRC_REC=7; LDRC_V=.11"
    new_constants = (
        f"LDRC_DD={args.ldrc_dd!r}; LDRC_R20={args.ldrc_r20!r}; "
        f"LDRC_CEIL=.55; LDRC_REC={args.ldrc_rec}; LDRC_V={args.ldrc_v!r}"
    )
    text = replace_once(text, old_constants, new_constants, "LD-RC constants")

    text = replace_once(
        text,
        "and recent_r20>0 and recent_r40>0)",
        f"and recent_r20>0 and recent_r40>{args.full_r40_floor!r})",
        "E3 persistence r40 floor",
    )
    text = replace_once(
        text,
        "and recent_r20<=LDRC_R20 and spy20>=0.",
        f"and recent_r20<=LDRC_R20 and spy20>={args.div_spy_floor!r}",
        "E3 divergence SPY floor",
    )

    old_fast = "FAST = {'dd':-.10,'dam':.875,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10}"
    new_fast = (
        "FAST = {'dd':-.10,'dam':" + repr(args.fast_damaged) +
        ",'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10}"
    )
    text = replace_once(text, old_fast, new_fast, "FAST damaged threshold")

    text = replace_once(
        text,
        "healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=.625 and green>=.20",
        "healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<="
        + repr(args.healthy_damaged) + " and green>=.20",
        "healthy damaged threshold",
    )
    return text


def metric_rows(daily: pd.DataFrame) -> pd.DataFrame:
    starts = {
        "5": ("2021-07-30", 5.0),
        "10": ("2016-07-29", 10.0),
        "15": ("2011-07-29", 15.0),
        "20": ("2006-07-31", 20.0),
        "max": ("1998-01-02", None),
    }
    rows = []
    for window, (start, years) in starts.items():
        rows.append({
            "window_years": window,
            **corrected.old.metric_block(daily, "A_nav", start, years),
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--ldrc-rec", type=int, required=True)
    ap.add_argument("--ldrc-v", type=float, required=True)
    ap.add_argument("--ldrc-dd", type=float, required=True)
    ap.add_argument("--ldrc-r20", type=float, required=True)
    ap.add_argument("--div-spy-floor", type=float, required=True)
    ap.add_argument("--full-r40-floor", type=float, required=True)
    ap.add_argument("--fast-damaged", type=float, required=True)
    ap.add_argument("--healthy-damaged", type=float, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp") / f"strategy9_e3_stability_{args.name}.py"
    generated.write_text(build_source(args.output, args), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(
        "[RUN] stability-point "
        f"name={args.name} rec={args.ldrc_rec} v={args.ldrc_v} dd={args.ldrc_dd} "
        f"r20={args.ldrc_r20} spy_floor={args.div_spy_floor} "
        f"full_r40={args.full_r40_floor} fast_dam={args.fast_damaged} "
        f"healthy_dam={args.healthy_damaged}",
        flush=True,
    )
    subprocess.run([sys.executable, str(generated)], check=True, env=env)

    # The generated replay emits the raw retained-research files. Convert them
    # into the canonical daily.csv.gz surface before the stability analysis.
    corrected.old.postprocess("fullpit", args.output)
    corrected.finalize("fullpit", args.output)

    daily = pd.read_csv(args.output / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    metrics = metric_rows(daily)
    metrics.insert(0, "name", args.name)
    metrics.to_csv(args.output / "stability_metrics.csv", index=False)

    release_mask = daily["A_reason"].astype(str).str.contains(
        "FULL_RISK_CERTIFIED_CROSS_SURFACE", regex=False
    )
    divergence_mask = daily["A_reason"].astype(str).str.contains(
        "LD_ENTER_DIVERGENCE", regex=False
    )
    transitions = int((daily["A_allocation"].astype(float).diff().abs() > 1e-12).sum())
    config = {
        "name": args.name,
        "ldrc_rec": args.ldrc_rec,
        "ldrc_v": args.ldrc_v,
        "ldrc_dd": args.ldrc_dd,
        "ldrc_r20": args.ldrc_r20,
        "div_spy_floor": args.div_spy_floor,
        "full_r40_floor": args.full_r40_floor,
        "fast_damaged": args.fast_damaged,
        "healthy_damaged": args.healthy_damaged,
    }
    summary = {
        "schema": "backtester.strategy9-e3-stability-point/1",
        "status": "PASS",
        "diagnostic_only": True,
        "strategy": "Strategy 9 + E3 broad universe",
        "source_e3_head": "3f27834db427e71d9bb8d0b6160c8835b739c906",
        "config": config,
        "sessions": int(len(daily)),
        "allocation_transitions": transitions,
        "cross_surface_releases": int(release_mask.sum()),
        "divergence_entries": int(divergence_mask.sum()),
        "fast_signal_sessions": int(daily["fast_signal"].astype(bool).sum()),
        "slow_signal_sessions": int(daily["slow_signal"].astype(bool).sum()),
    }
    (args.output / "stability_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    files = [
        args.output / "daily.csv.gz",
        args.output / "stability_metrics.csv",
        args.output / "stability_summary.json",
    ]
    (args.output / "STABILITY_SHA256SUMS.txt").write_text(
        "".join(f"{corrected.old.sha256(p)}  {p.name}\n" for p in files),
        encoding="utf-8",
    )

    if args.name == "baseline":
        r20 = metrics[metrics.window_years.astype(str).eq("20")].iloc[0]
        rmax = metrics[metrics.window_years.astype(str).eq("max")].iloc[0]
        assert abs(float(r20.cagr) - 0.2032767188459037) < 5e-10, r20
        assert abs(float(r20.max_drawdown) - (-0.2861859296712328)) < 5e-10, r20
        assert abs(float(rmax.ending_multiple) - 181.1220290928661) < 5e-8, rmax
        print("[BASELINE-PARITY] PASS", flush=True)

    print(metrics.to_string(index=False), flush=True)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())