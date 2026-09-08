#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

CONTROL_SOURCE_SHA256 = "bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077"
CONTROL_NORMALIZED_AST_SHA256 = "435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
BASELINE_SOURCE_SHA256 = "32cd228010e09b5be42271cd6d0c38831fe7fbc74e725f592949146c48104e0f"
BASELINE_DAILY_SHA256 = "8a2e4f948720674a56737ee6291df0aff12e02a74d74b1ec5f0c75f9929adee6"
BASELINE_SUMMARY_SHA256 = "929ed3baacd1bb66e8174d7a6822e362e5c90da75355177d33bab3ac9f201878"
BASELINE_CAGR = 0.1454603836086088
CAPITAL = 100_000.0
MICRO_FRACTION = 0.01


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_module_functions(path: Path) -> dict:
    ns = {"__name__": f"loaded_{path.stem}", "__file__": str(path)}
    exec(compile(path.read_text(), str(path), "exec"), ns)
    return ns


def metrics(nav: pd.Series, dates: pd.Series) -> dict:
    nav = nav.astype(float); dates = pd.to_datetime(dates)
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    r = nav.pct_change().dropna(); vol = float(r.std(ddof=1))
    return {
        "start": str(dates.iloc[0].date()), "end": str(dates.iloc[-1].date()), "sessions": int(len(nav)),
        "cagr": multiple ** (1 / years) - 1, "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1).min()),
        "sharpe_daily_252": float(r.mean() / vol * np.sqrt(252)) if vol > 0 else None,
        "start_equity": float(nav.iloc[0]), "end_equity": float(nav.iloc[-1]),
    }


def compare_common_cells(base_path: Path, clean_path: Path) -> None:
    # Compare emitted text cells directly. The earlier diagnostic incorrectly parsed
    # and re-serialized floats/dates before hashing, creating a false path failure.
    base = pd.read_csv(base_path, dtype=str, keep_default_na=False)
    clean = pd.read_csv(clean_path, dtype=str, keep_default_na=False)
    missing = [c for c in base.columns if c not in clean.columns]
    if missing: raise RuntimeError(f"clean output lost V1 columns: {missing}")
    witness = clean[list(base.columns)]
    if base.shape != witness.shape: raise RuntimeError(f"shape mismatch: {base.shape} != {witness.shape}")
    neq = base.ne(witness)
    if bool(neq.to_numpy().any()):
        r, c = np.argwhere(neq.to_numpy())[0]; col = base.columns[int(c)]
        raise RuntimeError(f"V1 path divergence row={int(r)} col={col}: baseline={base.iloc[int(r),int(c)]!r} clean={witness.iloc[int(r),int(c)]!r}")


def run_source(path: Path, cwd: Path, env: dict) -> None:
    subprocess.run([sys.executable, str(path)], cwd=cwd, env=env, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--candidate-root", type=Path, required=True); ap.add_argument("--engine", type=Path, required=True); ap.add_argument("--output", type=Path, required=True); args = ap.parse_args()
    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install, assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast

    here = Path(__file__).resolve().parents[1]
    cap = load_module_functions(here / "wealth-core-v1-capital-scale-v1" / "run_capital_scale.py")
    prior_clean = load_module_functions(here / "wealth-core-v1-path-preserving-clean-v1" / "run_path_preserving.py")
    engine = args.engine.resolve(); output = args.output.resolve(); engine.mkdir(parents=True, exist_ok=True); output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256: raise RuntimeError("canonical PIT dataset mismatch")
    _, _, prior = control.build_source(engine, args.candidate_root.resolve()); v1 = install(prior); assert_contract(v1)
    if assert_one_session_dividend_lag(v1) != 1: raise RuntimeError("baseline dividend mismatch")
    if sha(v1.encode()) != CONTROL_SOURCE_SHA256: raise RuntimeError("V1 source mismatch")
    if sha(normalized_ast(v1).encode()) != CONTROL_NORMALIZED_AST_SHA256: raise RuntimeError("V1 AST mismatch")

    # Reproduce the exact successful $100k authority first.
    baseline = cap["patch_source"](v1, CAPITAL); assert_contract(baseline)
    if sha(baseline.encode()) != BASELINE_SOURCE_SHA256: raise RuntimeError(f"$100k source authority mismatch: {sha(baseline.encode())}")
    baseline_src = output / "wealth-core-v1-100k-baseline-generated.py"; baseline_src.write_text(baseline)
    env = os.environ.copy(); env["RESEARCH_REPLAY_MODE"] = "fullpit"
    for stale in (engine / "daily.csv", engine / "summary.json"):
        if stale.exists(): stale.unlink()
    run_source(baseline_src, Path.cwd(), env)
    base_daily = output / "baseline-daily.csv"; base_summary = output / "baseline-summary.json"
    shutil.copy2(engine / "daily.csv", base_daily); shutil.copy2(engine / "summary.json", base_summary)
    if sha(base_daily.read_bytes()) != BASELINE_DAILY_SHA256: raise RuntimeError(f"$100k daily authority mismatch: {sha(base_daily.read_bytes())}")
    if sha(base_summary.read_bytes()) != BASELINE_SUMMARY_SHA256: raise RuntimeError(f"$100k summary authority mismatch: {sha(base_summary.read_bytes())}")
    base_frame = pd.read_csv(base_daily); base_m = metrics(base_frame.shadow_equity, base_frame.date)
    if abs(base_m["cagr"] - BASELINE_CAGR) > 1e-12: raise RuntimeError(f"$100k CAGR authority mismatch: {base_m['cagr']}")

    # Reuse the already-preregistered path-preserving dual-ledger instrumentation,
    # changing only both ledgers' starting capital to the new standing $100k authority.
    clean = prior_clean["patch_source"](v1)
    old = "    cash:float=100_000_000.; receivables:list=field(default_factory=list); clean_cash:float=100_000_000.; clean_receivables:list=field(default_factory=list)"
    new = "    cash:float=100000.0; receivables:list=field(default_factory=list); clean_cash:float=100000.0; clean_receivables:list=field(default_factory=list)"
    if clean.count(old) != 1: raise RuntimeError("clean capital seam mismatch")
    clean = clean.replace(old, new, 1)
    if clean.count("clean_min_cash=100_000_000.0") != 1: raise RuntimeError("clean min-cash seam mismatch")
    clean = clean.replace("clean_min_cash=100_000_000.0", "clean_min_cash=100_000.0", 1)
    compile(clean, "<wealth-core-v1-clean-100k>", "exec"); assert_contract(clean)
    if assert_one_session_dividend_lag(clean) != 1: raise RuntimeError("clean instrumentation changed dividend semantics")
    clean_src = output / "wealth-core-v1-clean-100k-generated.py"; clean_src.write_text(clean)
    subprocess.run([sys.executable, "-m", "py_compile", str(clean_src)], check=True)
    for stale in (engine / "daily.csv", engine / "summary.json"):
        if stale.exists(): stale.unlink()
    run_source(clean_src, Path.cwd(), env)
    clean_daily = engine / "daily.csv"; clean_summary = engine / "summary.json"
    compare_common_cells(base_daily, clean_daily)

    # Capital-scale summary adds telemetry; remove only that known diagnostic object
    # before comparing the unchanged V1 economic summary with the clean run.
    bs = json.loads(base_summary.read_text()); cs = json.loads(clean_summary.read_text())
    bs.pop("wealth_core_capital_scale", None)
    if bs != cs: raise RuntimeError("V1 summary economics diverged under clean instrumentation")

    frame = pd.read_csv(clean_daily); clean_m = metrics(frame.clean_equity, frame.date)
    virtual_entries = int(frame.clean_virtual_entries_cum.iloc[-1]); breaches = int(frame.clean_affordability_breaches_cum.iloc[-1])
    result = {
        "schema": "research.wealth-core-v1-clean-100k/1", "status": "PASS" if breaches == 0 else "FAIL_SELF_FINANCING",
        "economic_scope": "WEALTH_CORE_V1_ONLY", "sentinel_metrics_used": False, "initial_capital": CAPITAL,
        "micro_fraction": MICRO_FRACTION, "decision_path": "EXACT_100K_V1_COMMON_CELLS",
        "dataset_sha256": DATASET_SHA256,
        "baseline_authority": {"run_id": 34267327656, "artifact_id": 10073578819, "source_sha256": BASELINE_SOURCE_SHA256, "daily_sha256": BASELINE_DAILY_SHA256, "summary_sha256": BASELINE_SUMMARY_SHA256},
        "v1_100k": base_m, "clean_no_micro": clean_m,
        "delta_vs_v1": {"cagr_percentage_points": (clean_m["cagr"] - base_m["cagr"]) * 100, "ending_equity": clean_m["end_equity"] - base_m["end_equity"]},
        "telemetry": {"virtual_entries": virtual_entries, "real_micro_entries": 0, "omitted_gross_capital_cumulative": float(frame.clean_omitted_gross_cum.iloc[-1]), "affordability_breaches": breaches, "minimum_clean_cash": float(frame.clean_min_cash_cum.min()), "minimum_micro_fraction": float(frame.clean_micro_min_fraction_cum.dropna().min()) if virtual_entries else None, "maximum_micro_fraction": float(frame.clean_micro_max_fraction_cum.dropna().max()) if virtual_entries else None, "max_concurrent_virtual": int(frame.clean_virtual_count.max()), "sessions_with_virtual": int((frame.clean_virtual_count > 0).sum())},
        "clean_source_sha256": sha(clean.encode()),
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    shutil.copy2(clean_daily, output / "clean-daily.csv"); shutil.copy2(clean_summary, output / "clean-summary.json")
    print("[WEALTH_CORE_V1_CLEAN_100K] " + json.dumps(result, sort_keys=True), flush=True)
    if breaches: raise RuntimeError(f"clean ledger is not self-financing: {breaches} affordability breaches")
    return 0


if __name__ == "__main__": raise SystemExit(main())
