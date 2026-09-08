#!/usr/bin/env python3
"""Wealth Core V1/V2 A/B on the corrected one-session-dividend V1 lineage."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

CONTROL_COMMIT = "1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d"
CONTROL_RUN_ID = 34071569702
CONTROL_ARTIFACT_ID = 10001317230
CONTROL_ARTIFACT_DIGEST = "sha256:803b1b8288d77fc9c275cec5ebac91f8bac23ba030dad3dfb5d523fceed2415f"
CONTROL_SOURCE_SHA256 = "bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077"
CONTROL_NORMALIZED_AST_SHA256 = "435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde"
CONTROL_DAILY_SHA256 = "2fc1137529a7bb6e4c596d42a7af9bb0e3c891c3126116d15c342b8988235dfe"
CONTROL_SUMMARY_SHA256 = "d49d28069647097dea6c1c3417213a5dc9333e1ea33c8ef651f015b718cb22da"
CONTROL_WEALTH_CORE_CAGR = 0.1524665012369839
V2_PATCH_COMMIT = "26b324f4da0f80cf790048103a0d92c1c0df3920"
V2_PROFILE = "wealth-core-v2-full-whole-share-target-v1"
EXPECTED_V2_SOURCE_SHA256 = "c4aa2213ec2448f2af6e71158da5339c7b04681486a0e4aad3ee2dd4919b026a"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_v2_patch(path: Path):
    spec = importlib.util.spec_from_file_location("wealth_core_v2_patch_authority", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V2 patch authority")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if getattr(module, "PROFILE", None) != V2_PROFILE:
        raise RuntimeError("unexpected V2 patch profile")
    return module


def metrics(frame: pd.DataFrame, col: str) -> dict:
    nav = frame[col].astype(float)
    if len(nav) < 2 or not np.isfinite(nav).all() or (nav <= 0).any():
        raise RuntimeError(f"invalid {col} path")
    years = (frame.date.iloc[-1] - frame.date.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    r = nav.pct_change().dropna()
    vol = float(r.std(ddof=1))
    return {
        "start": str(frame.date.iloc[0].date()),
        "end": str(frame.date.iloc[-1].date()),
        "sessions": int(len(frame)),
        "cagr": multiple ** (1 / years) - 1,
        "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1).min()),
        "sharpe_daily_252": float(r.mean() / vol * np.sqrt(252)) if vol > 0 else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-root", required=True, type=Path)
    ap.add_argument("--v2-patch-source", required=True, type=Path)
    ap.add_argument("--engine", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install, assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast

    engine = args.engine.resolve()
    output = args.output.resolve()
    engine.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256:
        raise RuntimeError("canonical PIT dataset mismatch")

    # Rebuild the current V1 executable from the same pinned components as the
    # successful certification. Byte-exact source identity is the V1 control gate.
    _, _, prior = control.build_source(engine, args.candidate_root.resolve())
    v1 = install(prior)
    assert_contract(v1)
    if assert_one_session_dividend_lag(v1) != 1:
        raise RuntimeError("V1 is not the corrected one-session-dividend lineage")
    v1_sha = sha(v1.encode())
    if v1_sha != CONTROL_SOURCE_SHA256:
        raise RuntimeError(f"V1 source mismatch: {v1_sha}")
    v1_ast = sha(normalized_ast(v1).encode())
    if v1_ast != CONTROL_NORMALIZED_AST_SHA256:
        raise RuntimeError(f"V1 normalized AST mismatch: {v1_ast}")

    patch = load_v2_patch(args.v2_patch_source.resolve())
    v2 = patch.apply_v2_patch(v1)
    assert_contract(v2)
    if assert_one_session_dividend_lag(v2) != 1:
        raise RuntimeError("V2 changed dividend semantics")
    v2_sha = sha(v2.encode())
    if v2_sha != EXPECTED_V2_SOURCE_SHA256:
        raise RuntimeError(f"V2 source identity mismatch: {v2_sha}")

    (output / "wealth-core-v1-control-generated.py").write_text(v1)
    v2_path = output / "wealth-core-v2-generated.py"
    v2_path.write_text(v2)

    for stale in (engine / "daily.csv", engine / "summary.json"):
        if stale.exists():
            stale.unlink()
    env = os.environ.copy()
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    subprocess.run([sys.executable, str(v2_path)], cwd=Path.cwd(), env=env, check=True)

    daily = engine / "daily.csv"
    summary_path = engine / "summary.json"
    frame = pd.read_csv(daily, parse_dates=["date"])
    if len(frame) != 5032 or str(frame.date.iloc[0].date()) != "2006-07-31" or str(frame.date.iloc[-1].date()) != "2026-07-31":
        raise RuntimeError("V2 full-horizon witness mismatch")
    summary = json.loads(summary_path.read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256:
        raise RuntimeError("V2 dataset mismatch")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError("V2 dividend summary mismatch")
    funding = summary.get("wealth_core_entry_funding") or {}
    if funding.get("profile") != V2_PROFILE:
        raise RuntimeError(f"V2 funding identity missing: {funding}")

    v2_metrics = metrics(frame, "shadow_equity")
    result = {
        "schema": "research.wealth-core-v1-v2-current-baseline-ab/1",
        "status": "PASS",
        "changed_economic_domain": "wealth_core_entry_slot_funding",
        "dataset_sha256": DATASET_SHA256,
        "wealth_core_v1": {
            "cagr": CONTROL_WEALTH_CORE_CAGR,
            "control_commit": CONTROL_COMMIT,
            "control_run_id": CONTROL_RUN_ID,
            "control_artifact_id": CONTROL_ARTIFACT_ID,
            "control_artifact_digest": CONTROL_ARTIFACT_DIGEST,
            "generated_source_sha256": CONTROL_SOURCE_SHA256,
            "normalized_ast_sha256": CONTROL_NORMALIZED_AST_SHA256,
            "certified_daily_sha256": CONTROL_DAILY_SHA256,
            "certified_summary_sha256": CONTROL_SUMMARY_SHA256,
            "control_reproduction_gate": "PASS_BYTE_EXACT_GENERATED_SOURCE",
        },
        "wealth_core_v2": {
            **v2_metrics,
            "generated_source_sha256": v2_sha,
            "patch_authority_commit": V2_PATCH_COMMIT,
            "funding": funding,
        },
        "delta_cagr_percentage_points": (v2_metrics["cagr"] - CONTROL_WEALTH_CORE_CAGR) * 100,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    shutil.copy2(daily, output / "v2-daily.csv")
    shutil.copy2(summary_path, output / "v2-summary.json")
    (output / "SHA256.json").write_text(json.dumps({
        p.name: sha(p.read_bytes()) for p in sorted(output.iterdir())
        if p.is_file() and p.name != "SHA256.json"
    }, indent=2, sort_keys=True) + "\n")
    print("[WEALTH_CORE_V1_V2_CURRENT_AB] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
