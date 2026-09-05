#!/usr/bin/env python3
"""Zero-budget Stage 6B: mechanistic premium-budget sensitivity after Stage 6 NO-GO.

This diagnostic does not supersede or reopen the preregistered Stage 6 gate. It asks
one bounded question: did Stage 6 fail because the full-systematic-delta construction
was allowed to consume too much natural Wealth Core cash as option premium?

The premium caps are exactly the cash thresholds already frozen in Stage 4 before
Stage 6: 0.25%, 0.5%, 1%, 2%, and 4% of the active control account sleeve. No new
threshold is fitted here. Results are diagnostic-only and cannot spend/open E8.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

from backtester import run_wc_targeted_hedge_stage6_strict_cash as strict

LABEL = "WC_TARGETED_HEDGE_STAGE6B_PREMIUM_CAP_SENSITIVITY_ZERO_BUDGET"
CAPS = (0.0025, 0.005, 0.01, 0.02, 0.04)
SHAPES = ("ATM_90D", "OTM5_120D", "OTM10_180D")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for ch in iter(lambda: f.read(1024 * 1024), b""):
            h.update(ch)
    return h.hexdigest()


def capped_source(cap: float) -> str:
    text = strict.transformed_source()
    old_import = "import argparse, hashlib, itertools, json, math, zipfile"
    new_import = "import argparse, hashlib, itertools, json, math, os, zipfile"
    if text.count(old_import) != 1:
        raise RuntimeError(f"Stage6B import seam count={text.count(old_import)}")
    text = text.replace(old_import, new_import, 1)

    anchor = "INITIAL_ACCOUNT_DOLLARS=100_000_000.0"
    replacement = anchor + f"\nPREMIUM_CAP_FRACTION={cap!r}"
    if text.count(anchor) != 1:
        raise RuntimeError(f"Stage6B premium-cap anchor count={text.count(anchor)}")
    text = text.replace(anchor, replacement, 1)

    old_budget = "        initial_budget=max(account_value*max(next_alloc,0.0)*cash_frac,0.0)"
    new_budget = (
        "        initial_budget=min("
        "max(account_value*max(next_alloc,0.0)*cash_frac,0.0),"
        "account_value*max(next_alloc,0.0)*PREMIUM_CAP_FRACTION)"
    )
    if text.count(old_budget) != 1:
        raise RuntimeError(f"Stage6B strict budget seam count={text.count(old_budget)}")
    text = text.replace(old_budget, new_budget, 1)
    return text


def frozen_gate(rows: pd.DataFrame, episode_rows: pd.DataFrame, shape: str) -> bool:
    q = rows[(rows["shape"] == shape) & (rows["stress"] == "CONSERVATIVE")].copy()
    by = {str(r.window): r for r in q.itertuples(index=False)}
    if "20" not in by or "max" not in by:
        return False
    target = episode_rows[
        (episode_rows["variant"] == f"{shape}__CONSERVATIVE")
        & (episode_rows["target"].isin(["2011", "2020", "2024_JULAUG", "2025"]))
    ]
    positive = int((target["improvement"] > 0).sum())
    return bool(
        float(by["max"].relative_maxdd_improvement) >= 0.20
        and float(by["20"].relative_maxdd_improvement) >= 0.20
        and float(by["max"].cagr_delta) >= -0.01
        and float(by["20"].cagr_delta) >= -0.01
        and positive >= 2
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage4-root", type=Path, required=True)
    ap.add_argument("--stage5-root", type=Path, required=True)
    ap.add_argument("--vix-root", type=Path, required=True)
    ap.add_argument("--sfp", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)

    metric_parts = []
    episode_parts = []
    trade_parts = []
    cap_summaries = {}

    for cap in CAPS:
        tag = f"cap_{cap:.4f}"
        sub = a.output / tag
        sub.mkdir(parents=True, exist_ok=True)
        generated = Path("/tmp") / f"wc_targeted_hedge_stage6b_{tag}.py"
        generated.write_text(capped_source(cap), encoding="utf-8")
        cmd = [
            sys.executable,
            str(generated),
            "--stage4-root", str(a.stage4_root),
            "--stage5-root", str(a.stage5_root),
            "--vix-root", str(a.vix_root),
            "--sfp", str(a.sfp),
            "--output", str(sub),
        ]
        print(f"[RUN] {LABEL} premium_cap={cap:.4%}", flush=True)
        subprocess.run(cmd, check=True, env=dict(os.environ))

        m = pd.read_csv(sub / "modeled_put_metrics.csv", dtype={"window": str})
        e = pd.read_csv(sub / "modeled_put_target_episodes.csv")
        t = pd.read_csv(sub / "modeled_put_trade_ledger.csv")
        m.insert(0, "premium_cap_fraction", cap)
        e.insert(0, "premium_cap_fraction", cap)
        t.insert(0, "premium_cap_fraction", cap)
        metric_parts.append(m)
        episode_parts.append(e)
        trade_parts.append(t)

        gates = {shape: frozen_gate(m, e, shape) for shape in SHAPES}
        cap_summaries[f"{cap:.4f}"] = {
            "premium_cap_fraction": cap,
            "frozen_stage6_gate_by_shape": gates,
            "any_shape_passes_frozen_gate": any(gates.values()),
        }

        # Curves are intermediate and deterministic; aggregate tables retain the
        # decision evidence while keeping the immutable Stage6B artifact compact.
        for p in sub.glob("curve_*.csv.gz"):
            p.unlink()

    metrics = pd.concat(metric_parts, ignore_index=True)
    episodes = pd.concat(episode_parts, ignore_index=True)
    trades = pd.concat(trade_parts, ignore_index=True)
    metrics.to_csv(a.output / "stage6b_modeled_put_metrics.csv", index=False)
    episodes.to_csv(a.output / "stage6b_target_episodes.csv", index=False)
    trades.to_csv(a.output / "stage6b_trade_ledger.csv.gz", index=False,
                  compression={"method": "gzip", "compresslevel": 6, "mtime": 0})

    plateau = {}
    for shape in SHAPES:
        passed = [cap for cap in CAPS if cap_summaries[f"{cap:.4f}"]["frozen_stage6_gate_by_shape"][shape]]
        adjacent_pairs = [
            [CAPS[i], CAPS[i + 1]]
            for i in range(len(CAPS) - 1)
            if CAPS[i] in passed and CAPS[i + 1] in passed
        ]
        plateau[shape] = {
            "passing_caps": passed,
            "adjacent_passing_pairs": adjacent_pairs,
            "broad_plateau_present": bool(adjacent_pairs),
        }

    report = {
        "status": "PASS",
        "label": LABEL,
        "zero_budget_diagnostic": True,
        "strategy_mechanics_changed": False,
        "experiment_budget_consumed": False,
        "e8_spent": False,
        "stage6_preregistered_gate_remains_authoritative": True,
        "stage6_result": "CLOSED_MODELED_ECONOMICS_NO_GO",
        "purpose": "mechanistic sensitivity only: determine whether Stage6 failure is driven by oversized premium deployment",
        "premium_caps": list(CAPS),
        "premium_cap_origin": "exact Stage4 frozen cash-availability thresholds",
        "selection_contract": "no best cap is selected; only broad adjacent-cap plateaus are reported",
        "frozen_gate_contract": {
            "max_history_relative_maxdrawdown_improvement_min": 0.20,
            "twenty_year_relative_maxdrawdown_improvement_min": 0.20,
            "max_history_cagr_delta_min": -0.01,
            "twenty_year_cagr_delta_min": -0.01,
            "positive_target_episode_improvements_min": 2,
        },
        "cap_summaries": cap_summaries,
        "shape_plateaus": plateau,
        "interpretation": {
            "may_open_e8": False,
            "if_no_plateau": "targeted long-put concept remains NO-GO under tested mechanics",
            "if_plateau": "evidence that full-delta premium size caused Stage6 failure; requires a separately frozen validation before E8",
        },
    }
    (a.output / "stage6b_summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    files = [
        a.output / "stage6b_modeled_put_metrics.csv",
        a.output / "stage6b_target_episodes.csv",
        a.output / "stage6b_trade_ledger.csv.gz",
        a.output / "stage6b_summary.json",
    ]
    (a.output / "STAGE6B_SHA256SUMS.txt").write_text(
        "".join(f"{sha256(p)}  {p.name}\n" for p in files), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    show = metrics[(metrics.stress == "CONSERVATIVE") & (metrics.window.isin(["20", "max"]))]
    print(show[["premium_cap_fraction", "shape", "window", "cagr_delta", "max_drawdown", "relative_maxdd_improvement"]].to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
