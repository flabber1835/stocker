#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

VARIANTS = (
    "current",
    "native_base_anchor",
    "native_base_duration",
    "native_slow_persistence",
    "native_recovery_ramp",
    "ex3_episode_memory",
    "ex3_latch_memory",
)
ABLATIONS = VARIANTS[1:]


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


def _positions(raw) -> set[str]:
    if pd.isna(raw):
        return set()
    value = json.loads(str(raw))
    if not isinstance(value, list):
        raise RuntimeError("research_selected_positions must be a JSON list")
    return set(map(str, value))


def holding_delta(base: pd.DataFrame, case: pd.DataFrame) -> dict:
    b = [_positions(x) for x in base.research_selected_positions]
    c = [_positions(x) for x in case.research_selected_positions]
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
    a = base[col].astype(float).to_numpy()
    b = case[col].astype(float).to_numpy()
    d = np.abs(a - b)
    mask = d > 1e-12
    ix = np.flatnonzero(mask)
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


def validate_result(package: Path, expected_kind: str, expected_index: int | None, expected_source_hash: str) -> dict:
    rp = package / "RESULT.json"
    sp = package / "selected-source-sha256.txt"
    mp = package / "metadata.json"
    if not rp.exists() or not sp.exists() or not mp.exists():
        raise RuntimeError(f"incomplete package {package}")
    if sp.read_text().strip() != expected_source_hash:
        raise RuntimeError(f"instrumented selected-source hash mismatch in {package}")
    meta = json.loads(mp.read_text())
    if meta.get("kind") != expected_kind:
        raise RuntimeError(f"wrong package kind in {package}: {meta}")
    if expected_index is not None and int(meta.get("index", -99)) != expected_index:
        raise RuntimeError(f"wrong case index in {package}: {meta}")
    result = json.loads(rp.read_text())
    if result.get("status") != "PASS":
        raise RuntimeError(f"non-PASS result in {package}")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    baseline_packages = [p.parent for p in args.inputs.rglob("metadata.json") if json.loads(p.read_text()).get("kind") == "baseline"]
    case_packages = [p.parent for p in args.inputs.rglob("metadata.json") if json.loads(p.read_text()).get("kind") == "case"]
    if len(baseline_packages) != 1 or len(case_packages) != 7:
        raise RuntimeError(f"expected 1 baseline + 7 cases, got {len(baseline_packages)} + {len(case_packages)}")

    bp = baseline_packages[0]
    source_hash = (bp / "selected-source-sha256.txt").read_text().strip()
    if len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash):
        raise RuntimeError(f"invalid baseline instrumented source hash: {source_hash}")
    validate_result(bp, "baseline", None, source_hash)
    base = pd.read_csv(find_one(bp, "ablation-daily.csv"), parse_dates=["date"])
    if len(base) != 5032 or str(base.date.iloc[0].date()) != "2006-07-31" or str(base.date.iloc[-1].date()) != "2026-07-31":
        raise RuntimeError("baseline horizon mismatch")
    if base.date.duplicated().any() or not base.date.is_monotonic_increasing:
        raise RuntimeError("baseline date ordering invalid")

    expected_cols = {"date", "research_selected_positions", "shadow_equity", "current_allocation", "current_nav"}
    for name in ABLATIONS:
        expected_cols |= {f"{name}_allocation", f"{name}_nav"}
    missing = expected_cols - set(base.columns)
    if missing:
        raise RuntimeError(f"baseline missing columns: {sorted(missing)}")

    baseline_economics = {}
    baseline_relative = {}
    for name in VARIANTS:
        nav_col = "current_nav" if name == "current" else f"{name}_nav"
        baseline_economics[name] = nav_metrics(base, nav_col)
    current = baseline_economics["current"]
    if abs(current["cagr"] - 0.215572258056) > 5e-10:
        raise RuntimeError(f"current baseline CAGR parity failed: {current}")
    if abs(current["max_drawdown"] - (-0.273755457386)) > 5e-10:
        raise RuntimeError(f"current baseline MDD parity failed: {current}")
    for name, m in baseline_economics.items():
        baseline_relative[name] = {
            "cagr_delta_vs_current": float(m["cagr"] - current["cagr"]),
            "max_drawdown_delta_vs_current": float(m["max_drawdown"] - current["max_drawdown"]),
            "sharpe_delta_vs_current": float(m["sharpe_daily_252"] - current["sharpe_daily_252"]),
            "ending_multiple_ratio_vs_current": float(m["ending_multiple"] / current["ending_multiple"]),
        }

    cases = []
    seen = set()
    for package in case_packages:
        meta = json.loads((package / "metadata.json").read_text())
        idx = int(meta.get("index", -1))
        if idx in seen or idx not in range(7):
            raise RuntimeError(f"invalid/duplicate case index {idx}")
        seen.add(idx)
        validate_result(package, "case", idx, source_hash)
        case = pd.read_csv(find_one(package, "ablation-daily.csv"), parse_dates=["date"])
        if len(case) != len(base) or not np.array_equal(base.date.to_numpy(), case.date.to_numpy()):
            raise RuntimeError(f"date mismatch for case {idx}")
        row = {
            "index": idx,
            "case": meta["case"],
            "fault": meta.get("fault"),
            "wealth_core": holding_delta(base, case),
            "tracks": {},
        }
        for name in VARIANTS:
            alloc_col = "current_allocation" if name == "current" else f"{name}_allocation"
            nav_col = "current_nav" if name == "current" else f"{name}_nav"
            ad = allocation_delta(base, case, alloc_col)
            cm = nav_metrics(case, nav_col)
            bm = baseline_economics[name]
            ad["economics"] = cm
            ad["economic_delta_from_no_fault"] = {
                "cagr": float(cm["cagr"] - bm["cagr"]),
                "max_drawdown": float(cm["max_drawdown"] - bm["max_drawdown"]),
                "sharpe_daily_252": float(cm["sharpe_daily_252"] - bm["sharpe_daily_252"]),
                "ending_multiple_ratio": float(cm["ending_multiple"] / bm["ending_multiple"]),
            }
            row["tracks"][name] = ad
        current_area = row["tracks"]["current"]["absolute_area"]
        for name in ABLATIONS:
            area = row["tracks"][name]["absolute_area"]
            row["tracks"][name]["area_reduction_vs_current"] = (
                None if current_area <= 1e-12 else float(1.0 - area / current_area)
            )
        cases.append(row)
    cases.sort(key=lambda x: x["index"])
    if seen != set(range(7)):
        raise RuntimeError(f"case index set mismatch: {seen}")

    agg = {}
    current_affected = [c for c in cases if c["tracks"]["current"]["absolute_area"] > 1e-12]
    for name in VARIANTS:
        rows = [c["tracks"][name] for c in cases]
        agg[name] = {
            "affected_cases": int(sum(r["absolute_area"] > 1e-12 for r in rows)),
            "median_difference_sessions": median([r["difference_sessions"] for r in rows]),
            "median_difference_fraction": median([r["difference_fraction"] for r in rows]),
            "median_absolute_area": median([r["absolute_area"] for r in rows]),
            "max_absolute_area": max(float(r["absolute_area"]) for r in rows),
            "median_abs_cagr_fault_delta": median([abs(r["economic_delta_from_no_fault"]["cagr"]) for r in rows]),
            "max_abs_cagr_fault_delta": max(abs(float(r["economic_delta_from_no_fault"]["cagr"])) for r in rows),
            "median_abs_mdd_fault_delta": median([abs(r["economic_delta_from_no_fault"]["max_drawdown"]) for r in rows]),
            "terminal_equal_cases": int(sum(r["terminal_equal"] for r in rows)),
        }
        if name != "current":
            reductions = [c["tracks"][name]["area_reduction_vs_current"] for c in current_affected]
            agg[name]["median_area_reduction_vs_current_on_current_affected_cases"] = median(reductions)
            agg[name]["cases_with_lower_area_than_current"] = int(sum(
                c["tracks"][name]["absolute_area"] + 1e-12 < c["tracks"]["current"]["absolute_area"]
                for c in current_affected
            ))
            agg[name]["cases_with_higher_area_than_current"] = int(sum(
                c["tracks"][name]["absolute_area"] > c["tracks"]["current"]["absolute_area"] + 1e-12
                for c in current_affected
            ))

    candidate_screen = {}
    for name in ABLATIONS:
        br = baseline_relative[name]
        rr = agg[name]["median_area_reduction_vs_current_on_current_affected_cases"]
        candidate_screen[name] = {
            "median_area_reduction_at_least_50pct": bool(rr is not None and rr >= 0.50),
            "baseline_cagr_loss_within_1pp": bool(br["cagr_delta_vs_current"] >= -0.01),
            "baseline_mdd_delta_vs_current": br["max_drawdown_delta_vs_current"],
            "meets_robustness_and_cagr_screen": bool(
                rr is not None and rr >= 0.50 and br["cagr_delta_vs_current"] >= -0.01
            ),
        }

    summary = {
        "schema": "research.wealth-core-v5-ex3-v6-state-component-ablation-v1/aggregate-1",
        "status": "PASS",
        "question": "Which carried Sentinel state components amplify Wealth Core faults, and what economic value do they contribute?",
        "instrumented_selected_source_sha256": source_hash,
        "baseline_economics": baseline_economics,
        "baseline_relative_to_current": baseline_relative,
        "aggregate_fault_robustness": agg,
        "candidate_screen": candidate_screen,
        "cases": cases,
        "interpretation_guard": (
            "Research attribution only. Each variant intentionally removes one state mechanism. "
            "No ablation is a production design or automatic promotion candidate."
        ),
    }
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Sentinel state-component ablation — results",
        "",
        "| Track | Baseline CAGR | Baseline MDD | Sharpe | Median fault area | Area reduction vs current* |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in VARIANTS:
        b = baseline_economics[name]
        a = agg[name]
        reduction = None if name == "current" else a["median_area_reduction_vs_current_on_current_affected_cases"]
        redtxt = "—" if reduction is None else f"{reduction:.2%}"
        lines.append(
            f"| {name} | {b['cagr']:.4%} | {b['max_drawdown']:.4%} | "
            f"{b['sharpe_daily_252']:.4f} | {a['median_absolute_area']:.2f} | {redtxt} |"
        )
    lines += [
        "",
        "*Area reduction is evaluated on the cases where current Sentinel was affected.",
        "",
        "## Target screen",
        "",
        "Target screen: >=50% median fault-area reduction and <=1 percentage point absolute baseline CAGR loss. MDD is reported separately, not hidden in the gate.",
        "",
    ]
    for name in ABLATIONS:
        x = candidate_screen[name]
        b = baseline_relative[name]
        r = agg[name]["median_area_reduction_vs_current_on_current_affected_cases"]
        lines.append(
            f"- {name}: area reduction {r:.2%}; CAGR delta {b['cagr_delta_vs_current']:+.2%}; "
            f"MDD delta {b['max_drawdown_delta_vs_current']:+.2%}; "
            f"screen={'PASS' if x['meets_robustness_and_cagr_screen'] else 'FAIL'}."
        )
    lines += ["", "No automatic promotion.", ""]
    (out / "SUMMARY.md").write_text("\n".join(lines))
    print(json.dumps({
        "status": "PASS",
        "cases": len(cases),
        "candidate_screen": candidate_screen,
        "aggregate_fault_robustness": agg,
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
