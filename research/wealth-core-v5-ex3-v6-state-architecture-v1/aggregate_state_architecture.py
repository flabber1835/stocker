#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ARCH = {
    "current": ("A_allocation", "A_nav"),
    "state_minimal_60": ("B_allocation", "B_nav"),
    "stateless_1": ("control_allocation", "control_nav"),
}


def nav_metrics(frame: pd.DataFrame, col: str) -> dict:
    nav = frame[col].astype(float)
    dates = pd.to_datetime(frame.date)
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    ret = nav.pct_change().dropna()
    sd = float(ret.std(ddof=1))
    dd = nav / nav.cummax() - 1.0
    return {
        "cagr": float(multiple ** (1.0 / years) - 1.0),
        "max_drawdown": float(dd.min()),
        "sharpe_daily_252": float(ret.mean() / sd * math.sqrt(252)) if sd > 0 else None,
        "ending_multiple": multiple,
    }


def load_positions(raw) -> set[str]:
    if pd.isna(raw):
        return set()
    try:
        return set(map(str, json.loads(str(raw))))
    except Exception:
        return set()


def holding_delta(base: pd.DataFrame, case: pd.DataFrame) -> dict:
    b = [load_positions(x) for x in base.research_selected_positions]
    c = [load_positions(x) for x in case.research_selected_positions]
    anydiff = np.asarray([x != y for x, y in zip(b, c)], dtype=bool)
    sym = np.asarray([len(x ^ y) for x, y in zip(b, c)], dtype=float)
    jac = np.asarray([1.0 if not (x | y) else len(x & y) / len(x | y) for x, y in zip(b, c)], dtype=float)
    return {
        "any_set_difference_sessions": int(anydiff.sum()),
        "any_set_difference_fraction": float(anydiff.mean()),
        "mean_symmetric_name_difference": float(sym.mean()),
        "mean_jaccard": float(jac.mean()),
    }


def allocation_delta(base: pd.DataFrame, case: pd.DataFrame, col: str) -> dict:
    a = base[col].astype(float).to_numpy(); b = case[col].astype(float).to_numpy()
    d = np.abs(a - b); mask = d > 1e-12; ix = np.flatnonzero(mask)
    tail = 0
    for flag in mask[::-1]:
        if flag:
            break
        tail += 1
    return {
        "difference_sessions": int(mask.sum()),
        "difference_fraction": float(mask.mean()),
        "absolute_area": float(d.sum()),
        "mean_abs": float(d.mean()),
        "first": None if not len(ix) else str(pd.Timestamp(base.date.iloc[int(ix[0])]).date()),
        "last": None if not len(ix) else str(pd.Timestamp(base.date.iloc[int(ix[-1])]).date()),
        "terminal_equal": bool(not mask[-1]),
        "terminal_equal_tail_sessions": int(tail),
    }


def find_one(root: Path, name: str) -> Path:
    xs = list(root.rglob(name))
    if len(xs) != 1:
        raise RuntimeError(f"expected one {name} under {root}, found {len(xs)}")
    return xs[0]


def median(xs):
    vals = [float(x) for x in xs if x is not None and np.isfinite(float(x))]
    return None if not vals else float(np.median(vals))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out = args.out; out.mkdir(parents=True, exist_ok=True)

    metas = []
    for p in args.inputs.rglob("metadata.json"):
        metas.append((p, json.loads(p.read_text())))
    baseline_meta = [(p, m) for p, m in metas if m.get("kind") == "baseline"]
    case_meta = sorted([(p, m) for p, m in metas if m.get("kind") == "case"], key=lambda x: int(x[1]["index"]))
    if len(baseline_meta) != 1 or len(case_meta) != 7:
        raise RuntimeError(f"expected 1 baseline + 7 cases, got {len(baseline_meta)} + {len(case_meta)}")

    bp, _bm = baseline_meta[0]
    base_csv = find_one(bp.parent, "architecture-daily.csv")
    base = pd.read_csv(base_csv, parse_dates=["date"])
    if len(base) != 5032:
        raise RuntimeError(f"baseline sessions {len(base)} != 5032")

    baseline_economics = {name: nav_metrics(base, nav_col) for name, (_alloc, nav_col) in ARCH.items()}
    baseline_relative = {}
    cur = baseline_economics["current"]
    for name, metrics in baseline_economics.items():
        baseline_relative[name] = {
            "cagr_delta_vs_current": float(metrics["cagr"] - cur["cagr"]),
            "max_drawdown_delta_vs_current": float(metrics["max_drawdown"] - cur["max_drawdown"]),
            "sharpe_delta_vs_current": float(metrics["sharpe_daily_252"] - cur["sharpe_daily_252"]),
            "ending_multiple_ratio_vs_current": float(metrics["ending_multiple"] / cur["ending_multiple"]),
        }

    cases = []
    for mp, meta in case_meta:
        cp = find_one(mp.parent, "architecture-daily.csv")
        case = pd.read_csv(cp, parse_dates=["date"])
        if len(case) != len(base) or not np.array_equal(base.date.to_numpy(), case.date.to_numpy()):
            raise RuntimeError(f"date mismatch for case {meta}")
        row = {"index": int(meta["index"]), "case": meta["case"], "fault": meta.get("fault"), "wealth_core": holding_delta(base, case), "architectures": {}}
        for name, (alloc_col, nav_col) in ARCH.items():
            ad = allocation_delta(base, case, alloc_col)
            cm = nav_metrics(case, nav_col); bmtr = baseline_economics[name]
            ad["economics"] = cm
            ad["economic_delta_from_no_fault"] = {
                "cagr": float(cm["cagr"] - bmtr["cagr"]),
                "max_drawdown": float(cm["max_drawdown"] - bmtr["max_drawdown"]),
                "sharpe_daily_252": float(cm["sharpe_daily_252"] - bmtr["sharpe_daily_252"]),
                "ending_multiple_ratio": float(cm["ending_multiple"] / bmtr["ending_multiple"]),
            }
            row["architectures"][name] = ad
        ca = row["architectures"]["current"]["absolute_area"]
        for name in ("state_minimal_60", "stateless_1"):
            va = row["architectures"][name]["absolute_area"]
            row["architectures"][name]["area_reduction_vs_current"] = None if ca <= 1e-12 else float(1.0 - va / ca)
        cases.append(row)

    agg = {}
    for name in ARCH:
        agg[name] = {
            "median_difference_sessions": median([c["architectures"][name]["difference_sessions"] for c in cases]),
            "median_difference_fraction": median([c["architectures"][name]["difference_fraction"] for c in cases]),
            "median_absolute_area": median([c["architectures"][name]["absolute_area"] for c in cases]),
            "max_absolute_area": max(float(c["architectures"][name]["absolute_area"]) for c in cases),
            "median_abs_cagr_fault_delta": median([abs(c["architectures"][name]["economic_delta_from_no_fault"]["cagr"]) for c in cases]),
            "max_abs_cagr_fault_delta": max(abs(float(c["architectures"][name]["economic_delta_from_no_fault"]["cagr"])) for c in cases),
            "median_abs_mdd_fault_delta": median([abs(c["architectures"][name]["economic_delta_from_no_fault"]["max_drawdown"]) for c in cases]),
        }
    for name in ("state_minimal_60", "stateless_1"):
        agg[name]["median_area_reduction_vs_current"] = median([c["architectures"][name].get("area_reduction_vs_current") for c in cases])

    summary = {
        "schema": "research.wealth-core-v5-ex3-v6-state-architecture-v1/aggregate-1",
        "status": "PASS",
        "question": "How much of Sentinel fault amplification requires carried internal state?",
        "architectures": {
            "current": "authoritative Native + EX3 V6 with full carried state",
            "state_minimal_60": "exact controller logic rebuilt from only the most recent 60 observable sessions",
            "stateless_1": "exact controller logic rebuilt from only the current observable session",
        },
        "baseline_economics": baseline_economics,
        "baseline_relative_to_current": baseline_relative,
        "aggregate_fault_robustness": agg,
        "cases": cases,
        "interpretation_guard": "Research attribution only. No architecture is promoted automatically; robustness gains must be weighed against baseline economic changes.",
    }
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Sentinel state architecture experiment — results",
        "",
        "Research-only comparison on the same Wealth Core V5 fault tapes.",
        "",
        "| Architecture | Baseline CAGR | Baseline MDD | Sharpe | Median fault allocation area | Median abs CAGR fault delta |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ARCH:
        b = baseline_economics[name]; a = agg[name]
        lines.append(f"| {name} | {b['cagr']:.4%} | {b['max_drawdown']:.4%} | {b['sharpe_daily_252']:.4f} | {a['median_absolute_area']:.2f} | {a['median_abs_cagr_fault_delta']:.4%} |")
    lines += ["", "## Robustness change vs current", ""]
    for name in ("state_minimal_60", "stateless_1"):
        v = agg[name]["median_area_reduction_vs_current"]
        lines.append(f"- {name}: median integrated allocation-divergence area reduction = {('N/A' if v is None else f'{v:.2%}')}.")
    lines += ["", "No automatic promotion. See SUMMARY.json for all seven deterministic cases and economic deltas.", ""]
    (out / "SUMMARY.md").write_text("\n".join(lines))
    print(json.dumps({"status":"PASS","cases":len(cases),"aggregate_fault_robustness":agg}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
