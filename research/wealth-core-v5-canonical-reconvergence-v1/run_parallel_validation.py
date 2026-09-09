#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_reconvergence as rr

SCHEMA = "research.wealth-core-v5-canonical-reconvergence-parallel/1"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_single(args) -> dict:
    root = args.output.resolve()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    base = json.loads((args.baseline_input / "RESULT.json").read_text())
    selected = rr.adv.build_selected(args.control_source, args.median_overlay)
    src = selected if args.arm == "old" else rr.apply_reconvergence(selected)

    security_id = None
    if args.case_kind == "loo":
        security_id = str(args.case_value)
        src = rr.adv.patch_exclusion(src, {security_id})
        case_key = f"loo:{security_id}"
    elif args.case_kind == "dropout":
        seed = int(args.case_value)
        src = rr.adv.patch_dropout(src, 0.01, seed)
        case_key = f"dropout:{seed}"
    elif args.case_kind == "cost":
        bp = int(args.case_value)
        src = rr.adv.patch_execution(src, "cost", bp / 10000.0)
        case_key = f"cost:{bp}"
    else:
        raise RuntimeError(args.case_kind)

    tag = f"{args.arm}_{args.case_kind}_{str(args.case_value).replace(':','_')}"
    event = rr.adv.execute(src, root / "run", tag, keep_raw=True)
    ref = rr.load_daily(args.baseline_input / args.arm / "daily.csv")
    var = rr.load_daily(root / "run" / "daily.csv")
    result = {
        "schema": SCHEMA,
        "suite": "single",
        "status": "PASS",
        "arm": args.arm,
        "case_kind": args.case_kind,
        "case_value": str(args.case_value),
        "case_key": case_key,
        "security_id": security_id,
        "event": event,
        "delta": rr.metric_delta(base["old" if args.arm == "old" else "reconvergence"], event),
        "path": rr.path_metrics(ref, var, security_id),
        "performance_selection": "FORBIDDEN_VALIDATION_ONLY",
    }
    write_json(root / "RESULT.json", result)
    return result


def _median(xs):
    vals = [float(x) for x in xs if x is not None and np.isfinite(float(x))]
    return None if not vals else float(np.median(vals))


def run_aggregate(args) -> dict:
    base = json.loads((args.baseline_input / "RESULT.json").read_text())
    singles = []
    for p in sorted(args.cases_root.rglob("RESULT.json")):
        try:
            r = json.loads(p.read_text())
        except Exception:
            continue
        if r.get("suite") == "single" and r.get("status") == "PASS":
            singles.append(r)

    grouped = {}
    for r in singles:
        grouped.setdefault(r["case_key"], {})[r["arm"]] = r
    paired = {k: v for k, v in grouped.items() if set(v) == {"old", "reconvergence"}}
    loo = [v for k, v in paired.items() if k.startswith("loo:")]
    drop = [v for k, v in paired.items() if k.startswith("dropout:")]
    costs = {int(k.split(":",1)[1]): v for k, v in paired.items() if k.startswith("cost:")}

    old_post = [x["old"]["path"].get("post_last_holding_mean_symmetric_difference") for x in loo]
    new_post = [x["reconvergence"]["path"].get("post_last_holding_mean_symmetric_difference") for x in loo]
    improved = 0
    for x in loo:
        a = x["old"]["path"].get("post_last_holding_mean_symmetric_difference")
        b = x["reconvergence"]["path"].get("post_last_holding_mean_symmetric_difference")
        if a is not None and b is not None and b < a:
            improved += 1

    old_amp = [x["old"]["delta"].get("sentinel_to_core_abs_cagr_impact_ratio") for x in loo]
    new_amp = [x["reconvergence"]["delta"].get("sentinel_to_core_abs_cagr_impact_ratio") for x in loo]
    old_drop_core = [abs(x["old"]["delta"]["core"]["cagr_delta"]) for x in drop]
    new_drop_core = [abs(x["reconvergence"]["delta"]["core"]["cagr_delta"]) for x in drop]
    old_drop_full = [abs(x["old"]["delta"]["sentinel"]["cagr_delta"]) for x in drop]
    new_drop_full = [abs(x["reconvergence"]["delta"]["sentinel"]["cagr_delta"]) for x in drop]

    old_post_med = _median(old_post); new_post_med = _median(new_post)
    old_amp_med = _median(old_amp); new_amp_med = _median(new_amp)
    old_dc = _median(old_drop_core); new_dc = _median(new_drop_core)
    old_df = _median(old_drop_full); new_df = _median(new_drop_full)

    gates = {
        "all_6_untouched_loo_completed": len(loo) == rr.HOLDOUT_COUNT,
        "all_3_dropout_completed": len(drop) == 3,
        "all_cost_cases_completed": set(costs) == {15, 25},
        "loo_majority_path_improves": improved >= 4,
        "loo_median_path_dispersion_halved": (new_post_med is not None and old_post_med is not None and new_post_med <= 0.5 * old_post_med),
        "sentinel_amplification_not_worse": (new_amp_med is not None and old_amp_med is not None and new_amp_med <= old_amp_med),
        "dropout_core_median_impact_reduced": (new_dc is not None and old_dc is not None and new_dc < old_dc),
        "dropout_full_median_impact_reduced": (new_df is not None and old_df is not None and new_df < old_df),
        "reconvergence_cost_response_monotonic_15_to_25bp": False,
    }
    old_cost_monotonic = None
    if set(costs) == {15, 25}:
        gates["reconvergence_cost_response_monotonic_15_to_25bp"] = (
            costs[25]["reconvergence"]["event"]["sentinel"]["20"]["cagr"]
            <= costs[15]["reconvergence"]["event"]["sentinel"]["20"]["cagr"]
        )
        old_cost_monotonic = (
            costs[25]["old"]["event"]["sentinel"]["20"]["cagr"]
            <= costs[15]["old"]["event"]["sentinel"]["20"]["cagr"]
        )

    verdict = "PASS" if all(gates.values()) else "FAIL"
    summary = {
        "singles_completed": len(singles),
        "paired_cases_completed": len(paired),
        "loo_completed": len(loo),
        "dropout_completed": len(drop),
        "cost_bps_completed": sorted(costs),
        "loo_cases_with_lower_path_dispersion": improved,
        "loo_old_median_post_last_symdiff": old_post_med,
        "loo_reconvergence_median_post_last_symdiff": new_post_med,
        "loo_old_median_sentinel_to_core_impact_ratio": old_amp_med,
        "loo_reconvergence_median_sentinel_to_core_impact_ratio": new_amp_med,
        "dropout_old_median_abs_core_cagr_delta": old_dc,
        "dropout_reconvergence_median_abs_core_cagr_delta": new_dc,
        "dropout_old_median_abs_full_cagr_delta": old_df,
        "dropout_reconvergence_median_abs_full_cagr_delta": new_df,
        "old_cost_response_monotonic_15_to_25bp": old_cost_monotonic,
    }
    result = {
        "schema": SCHEMA,
        "suite": "aggregate",
        "status": "PASS",
        "verdict": verdict,
        "baseline": base,
        "summary": summary,
        "gates": gates,
        "paired_cases": paired,
        "interpretation_contract": "Robustness-first; same precommitted holdouts and gates; parallel execution only.",
    }
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    write_json(out / "RESULT.json", result)
    lines = [
        "# Wealth Core V5 canonical reconvergence v1 — parallel validation",
        "",
        f"**Verdict: {verdict}**",
        "",
        "## Robustness summary",
        "",
        f"- Untouched LOO: {len(loo)}/{rr.HOLDOUT_COUNT}",
        f"- LOO cases with lower path dispersion: {improved}/{len(loo)}",
        f"- Median post-exclusion symmetric difference: {old_post_med} -> {new_post_med}",
        f"- Median Sentinel/Core impact ratio: {old_amp_med} -> {new_amp_med}",
        f"- Median 1% dropout |Core CAGR delta|: {old_dc} -> {new_dc}",
        f"- Median 1% dropout |full CAGR delta|: {old_df} -> {new_df}",
        f"- Old 15->25bp monotonic: {old_cost_monotonic}",
        "",
        "## Precommitted gates",
        "",
    ]
    lines += [f"- {'PASS' if v else 'FAIL'} — {k}" for k, v in gates.items()]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["single", "aggregate"])
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--baseline-input", required=True, type=Path)
    ap.add_argument("--control-source", type=Path)
    ap.add_argument("--median-overlay", type=Path)
    ap.add_argument("--cases-root", type=Path)
    ap.add_argument("--arm", choices=["old", "reconvergence"])
    ap.add_argument("--case-kind", choices=["loo", "dropout", "cost"])
    ap.add_argument("--case-value")
    args = ap.parse_args()
    if args.suite == "single":
        if args.control_source is None or args.median_overlay is None or args.arm is None or args.case_kind is None or args.case_value is None:
            raise RuntimeError("single inputs missing")
        result = run_single(args)
    else:
        if args.cases_root is None:
            raise RuntimeError("aggregate cases root missing")
        result = run_aggregate(args)
    print("[PARALLEL_RECONV_RESULT] " + json.dumps({"suite": args.suite, "status": result.get("status"), "verdict": result.get("verdict")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
