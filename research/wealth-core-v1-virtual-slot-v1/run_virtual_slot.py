#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd
from virtual_patch import *
def metrics(frame: pd.DataFrame) -> dict:
    nav = frame["shadow_equity"].astype(float)
    years = (frame.date.iloc[-1] - frame.date.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    r = nav.pct_change().dropna(); vol = float(r.std(ddof=1))
    occ = frame["held_count"].astype(float)
    real = frame["real_held_count"].astype(float)
    virt = frame["virtual_slot_count"].astype(float)
    return {
        "start": str(frame.date.iloc[0].date()), "end": str(frame.date.iloc[-1].date()), "sessions": int(len(frame)),
        "cagr": multiple ** (1 / years) - 1, "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1).min()),
        "sharpe_daily_252": float(r.mean() / vol * np.sqrt(252)) if vol > 0 else None,
        "average_slot_occupancy": float(occ.mean()), "median_slot_occupancy": float(occ.median()),
        "full_slot_sessions": int((occ >= 25).sum()),
        "average_real_holdings": float(real.mean()), "minimum_real_holdings": int(real.min()),
        "average_virtual_slots": float(virt.mean()), "sessions_with_virtual_slots": int((virt > 0).sum()),
        "max_virtual_slots": int(virt.max()), "ending_virtual_slots": int(virt.iloc[-1]),
        "average_virtual_cash_locked": float(frame["virtual_cash_locked"].astype(float).mean()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    ap.add_argument("--candidate-root", type=Path)
    ap.add_argument("--engine", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--patch-only-source", type=Path)
    args = ap.parse_args()

    if args.patch_only_source:
        patched = patch_source(args.patch_only_source.read_text(), args.variant)
        args.output.mkdir(parents=True, exist_ok=True)
        p = args.output / f"wealth-core-{args.variant}-generated.py"; p.write_text(patched)
        subprocess.run([sys.executable, "-m", "py_compile", str(p)], check=True)
        print(p)
        return 0

    if args.candidate_root is None or args.engine is None:
        raise RuntimeError("candidate-root and engine required for replay")

    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install, assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast

    engine = args.engine.resolve(); output = args.output.resolve(); engine.mkdir(parents=True, exist_ok=True); output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256: raise RuntimeError("canonical PIT dataset mismatch")

    _, _, prior = control.build_source(engine, args.candidate_root.resolve())
    v1 = install(prior); assert_contract(v1)
    if assert_one_session_dividend_lag(v1) != 1: raise RuntimeError("baseline dividend semantics mismatch")
    if sha(v1.encode()) != CONTROL_SOURCE_SHA256: raise RuntimeError(f"V1 source mismatch: {sha(v1.encode())}")
    if sha(normalized_ast(v1).encode()) != CONTROL_NORMALIZED_AST_SHA256: raise RuntimeError("V1 AST mismatch")

    exp = patch_source(v1, args.variant); assert_contract(exp)
    if assert_one_session_dividend_lag(exp) != 1: raise RuntimeError("experiment changed dividend semantics")
    exp_path = output / f"wealth-core-{args.variant}-generated.py"; exp_path.write_text(exp)
    subprocess.run([sys.executable, "-m", "py_compile", str(exp_path)], check=True)

    for stale in (engine / "daily.csv", engine / "summary.json"):
        if stale.exists(): stale.unlink()
    env = os.environ.copy(); env["RESEARCH_REPLAY_MODE"] = "fullpit"
    subprocess.run([sys.executable, str(exp_path)], cwd=Path.cwd(), env=env, check=True)

    frame = pd.read_csv(engine / "daily.csv", parse_dates=["date"])
    if len(frame) != 5032 or str(frame.date.iloc[0].date()) != "2006-07-31" or str(frame.date.iloc[-1].date()) != "2026-07-31": raise RuntimeError("full-horizon witness mismatch")
    summary = json.loads((engine / "summary.json").read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256: raise RuntimeError("dataset mismatch")
    if summary.get("financial_grade_dividend_lag_sessions") != 1: raise RuntimeError("dividend summary mismatch")
    telemetry = summary.get("wealth_core_virtual_slot_experiment") or {}
    if telemetry.get("variant") != args.variant: raise RuntimeError("virtual telemetry identity mismatch")
    if telemetry.get("real_micro_executions") != 0: raise RuntimeError(f"real microscopic execution survived: {telemetry}")

    m = metrics(frame); m["buys"] = int(summary["buys"]); m["sells"] = int(summary["sells"])
    if int(frame["virtual_slot_count"].max()) <= 0: raise RuntimeError("experiment never exercised virtual slot path")

    result = {
        "schema": "research.wealth-core-v1-virtual-slot/1", "status": "PASS", "variant": args.variant,
        "hypothesis": VARIANTS[args.variant], "economic_scope": "WEALTH_CORE_ONLY", "metric_authority": "shadow_equity",
        "sentinel_metrics_used": False, "dataset_sha256": DATASET_SHA256, "micro_fraction": MICRO_FRACTION,
        "wealth_core_v1_control": {**CONTROL_METRICS, "control_commit": CONTROL_COMMIT, "control_run_id": CONTROL_RUN_ID, "control_artifact_id": CONTROL_ARTIFACT_ID, "control_artifact_digest": CONTROL_ARTIFACT_DIGEST, "generated_source_sha256": CONTROL_SOURCE_SHA256, "certified_daily_sha256": CONTROL_DAILY_SHA256, "certified_summary_sha256": CONTROL_SUMMARY_SHA256},
        "experiment": {**m, "generated_source_sha256": sha(exp.encode()), "telemetry": telemetry},
        "delta_vs_v1": {
            "cagr_percentage_points": (m["cagr"] - CONTROL_METRICS["cagr"]) * 100,
            "max_drawdown_percentage_points": (m["max_drawdown"] - CONTROL_METRICS["max_drawdown"]) * 100,
            "sharpe": m["sharpe_daily_252"] - CONTROL_METRICS["sharpe_daily_252"],
            "slot_occupancy": m["average_slot_occupancy"] - CONTROL_METRICS["average_held_count"],
            "buys": m["buys"] - CONTROL_METRICS["buys"], "sells": m["sells"] - CONTROL_METRICS["sells"],
        },
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    shutil.copy2(engine / "daily.csv", output / "daily.csv"); shutil.copy2(engine / "summary.json", output / "summary.json")
    (output / "SHA256.json").write_text(json.dumps({p.name: sha(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file() and p.name != "SHA256.json"}, indent=2, sort_keys=True) + "\n")
    print("[WEALTH_CORE_VIRTUAL_SLOT] " + json.dumps(result, sort_keys=True), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
