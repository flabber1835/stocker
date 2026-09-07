#!/usr/bin/env python3
"""Run one frozen Champion alpha variant against the corrected certified PIT base."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from experiment_overlay import ARMS, apply_arm, arm_dimensions  # noqa: E402
from backtester import champion_full_classification_control as control  # noqa: E402
from backtester.production_equivalent_economic_overlay import (  # noqa: E402
    install,
    assert_contract,
    assert_one_session_dividend_lag,
)
from backtester.champion_economic_prefix_audit import (  # noqa: E402
    EXPECTED_CORPUS,
    PROFILE,
    PROFILE_HASH,
    RUNTIME,
    SOURCE,
    normalized_ast,
)

BASELINE_RUN_ID = 34071569702
BASELINE_ARTIFACT_ID = 10001317230
BASELINE_HEAD = "1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d"
BASELINE_NORMALIZED_SHA256 = "435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde"
EXPECTED_PACKAGE = "ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c"
EXPECTED_SECURITY_COUNTS = {
    "auto_common": 6143427,
    "manual_common": 0,
    "manual_non_common": 2,
    "unknown_ineligible": 1082978,
}
EXPECTED_CANDIDATE_COVERAGE = {
    "base_candidates": 7226407,
    "known_classifications": 6143429,
    "unknown_classifications": 1082978,
    "sessions": 5050,
    "sessions_with_unknown": 5050,
}
BASELINE_20Y = {
    "cagr": 0.18800888800126314,
    "ending_multiple": 31.363500124285768,
    "max_drawdown": -0.2491366167248561,
    "sharpe_daily_252": 1.0363365863293037,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def metrics(frame: pd.DataFrame, col: str) -> dict:
    nav = frame[col].astype(float)
    if len(nav) < 2 or not np.isfinite(nav).all() or (nav <= 0).any():
        raise RuntimeError(f"invalid NAV path for {col}")
    years = (frame.date.iloc[-1] - frame.date.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    rets = nav.pct_change().dropna()
    vol = float(rets.std(ddof=1))
    return {
        "start": str(frame.date.iloc[0].date()),
        "end": str(frame.date.iloc[-1].date()),
        "sessions": int(len(frame)),
        "cagr": multiple ** (1.0 / years) - 1.0,
        "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
        "sharpe_daily_252": float(rets.mean() / vol * np.sqrt(252)) if vol > 0 else None,
    }


def holding_stats(frame: pd.DataFrame) -> dict:
    full = frame.A_allocation.astype(float).eq(1.0)
    return {
        "average_held_count": float(frame.held_count.mean()),
        "full_allocation_average_held_count": float(frame.loc[full, "held_count"].mean()) if full.any() else None,
        "full_allocation_under_25_fraction": float((frame.loc[full, "held_count"] < 25).mean()) if full.any() else None,
        "zero_allocation_sessions": int(frame.A_allocation.astype(float).eq(0.0).sum()),
        "average_A_allocation": float(frame.A_allocation.astype(float).mean()),
    }


def zero_episodes(frame: pd.DataFrame) -> list[dict]:
    zero = frame.A_allocation.astype(float).eq(0.0).to_numpy()
    out = []
    i = 0
    while i < len(frame):
        if not zero[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(frame) and zero[j + 1]:
            j += 1
        out.append({
            "start": str(frame.date.iloc[i].date()),
            "end": str(frame.date.iloc[j].date()),
            "sessions": int(j - i + 1),
            "strategy_endpoint_return": float(frame.A_nav.iloc[j] / frame.A_nav.iloc[i] - 1.0),
            "spy_endpoint_return": float(frame.spy_nav.iloc[j] / frame.spy_nav.iloc[i] - 1.0),
            "worst_spy_change_from_start": float(frame.spy_nav.iloc[i:j+1].min() / frame.spy_nav.iloc[i] - 1.0),
        })
        i = j + 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", required=True, choices=ARMS)
    p.add_argument("--candidate-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine_build = out / "engine-build"
    engine_build.mkdir()
    engine = out / "engine"
    engine.mkdir()

    if os.environ.get("RESEARCH_REPLAY_MODE") not in (None, "", "fullpit"):
        raise RuntimeError("unexpected externally supplied replay mode")

    dataset_root = Path(os.environ["CANONICAL_PIT_DATASET"])
    manifest = json.loads((dataset_root / "manifest.json").read_text())
    if manifest.get("dataset_hash") != EXPECTED_CORPUS:
        raise RuntimeError("canonical PIT dataset hash mismatch")

    candidate = subprocess.check_output(
        ["git", "-C", str(args.candidate_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if candidate != SOURCE["candidate"]:
        raise RuntimeError(f"candidate source pin mismatch: {candidate}")

    baseline, capacity_off, prior = control.build_source(engine_build, args.candidate_root)
    if "_research_capacity_guard(" in capacity_off:
        raise RuntimeError("capacity-off source still contains executable capacity guard")
    certified_base = install(prior)
    assert_contract(certified_base)
    if assert_one_session_dividend_lag(certified_base) != 1:
        raise RuntimeError("corrected base is not exact one-session dividend settlement")
    base_norm = sha(normalized_ast(certified_base).encode())
    if base_norm != BASELINE_NORMALIZED_SHA256:
        raise RuntimeError(f"corrected base identity mismatch: {base_norm}")

    variant = apply_arm(certified_base, args.arm)
    assert_contract(variant)
    if assert_one_session_dividend_lag(variant) != 1:
        raise RuntimeError("variant changed the dividend settlement contract")
    variant_raw_sha = sha(variant.encode())
    variant_norm_sha = sha(normalized_ast(variant).encode())

    (out / "certified-base-generated.py").write_text(certified_base)
    (out / "experiment-generated.py").write_text(variant)

    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    module = types.ModuleType(f"champion_alpha_{args.arm.lower()}")
    sys.modules[module.__name__] = module
    exec(compile(variant, str(out / "experiment-generated.py"), "exec"), module.__dict__)
    if getattr(module, "MODE", None) != "fullpit" or getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError("variant runtime did not enter full PIT mode")

    # The generated formal harness contains a fixed historical output path.  The
    # experiment changes this runtime variable only after compilation; it is an
    # output location, not an economic input or decision seam.
    module.OUT = engine
    module.run()

    daily = engine / "daily.csv"
    summary_path = engine / "summary.json"
    if not daily.exists() or not summary_path.exists():
        raise RuntimeError("experiment did not emit required daily/summary evidence")
    frame = pd.read_csv(daily, parse_dates=["date"])
    if (
        len(frame) != 5032
        or str(frame.date.iloc[0].date()) != "2006-07-31"
        or str(frame.date.iloc[-1].date()) != "2026-07-31"
        or frame.date.duplicated().any()
        or not frame.date.is_monotonic_increasing
    ):
        raise RuntimeError("full-horizon witness mismatch")

    summary = json.loads(summary_path.read_text())
    if summary.get("replay_mode") != "fullpit":
        raise RuntimeError("engine summary is not full PIT")
    if summary.get("canonical_pit_dataset_hash") != EXPECTED_CORPUS:
        raise RuntimeError("engine summary corpus mismatch")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError("engine summary dividend lag changed")
    if summary.get("strict_security_type_counts") != EXPECTED_SECURITY_COUNTS:
        raise RuntimeError("security-type traversal differs from certified baseline")
    coverage = summary.get("strict_candidate_security_type_coverage") or {}
    for key, expected in EXPECTED_CANDIDATE_COVERAGE.items():
        if coverage.get(key) != expected:
            raise RuntimeError(f"candidate classification coverage changed for {key}: {coverage.get(key)} != {expected}")

    windows = {}
    for years in (5, 10, 15, 20):
        start = frame.date.iloc[-1] - pd.DateOffset(years=years)
        part = frame[frame.date >= start]
        windows[str(years)] = {
            "strategy": metrics(part, "A_nav"),
            "spy": metrics(part, "spy_nav"),
        }

    report = {
        "schema": "champion.alpha-experiment-result/1",
        "status": "PASS_FRESH_CAUSAL_PIT_REPLAY",
        "arm": args.arm,
        "dimensions": arm_dimensions(args.arm),
        "baseline_reference": {
            "workflow_run_id": BASELINE_RUN_ID,
            "artifact_id": BASELINE_ARTIFACT_ID,
            "source_head": BASELINE_HEAD,
            "normalized_generated_source_sha256": BASELINE_NORMALIZED_SHA256,
            "strategy_20y": BASELINE_20Y,
        },
        "source": {
            "formal_source_sha": SOURCE["certified"],
            "candidate_source_sha": candidate,
            "runtime_sha": RUNTIME,
            "profile": PROFILE,
            "profile_sha256": PROFILE_HASH,
            "experiment_code_sha": os.environ.get("GITHUB_SHA"),
            "base_generated_normalized_ast_sha256": base_norm,
            "variant_generated_sha256": variant_raw_sha,
            "variant_generated_normalized_ast_sha256": variant_norm_sha,
        },
        "data": {
            "canonical_pit_dataset_hash": EXPECTED_CORPUS,
            "canonical_pit_package": EXPECTED_PACKAGE,
            "measurement_start": "2006-07-31",
            "measurement_end": "2026-07-31",
            "sessions": 5032,
            "pit": True,
            "prerecorded_decisions_used": False,
        },
        "dividend_lag_sessions": 1,
        "classification": {
            "strict_security_type_counts": summary["strict_security_type_counts"],
            "candidate_coverage": coverage,
            "classification_expansion_required": False,
        },
        "windows": windows,
        "holdings": holding_stats(frame),
        "zero_stock_episodes": zero_episodes(frame),
        "engine": {
            "buys": summary.get("buys"),
            "sells": summary.get("sells"),
            "transition_counts": summary.get("transition_counts"),
            "modeled_allocation_transition_cost_sum": summary.get("modeled_allocation_transition_cost_sum"),
            "candidate_A_episodes": summary.get("candidate_A_episodes"),
            "candidate_A_concordance_releases": summary.get("candidate_A_concordance_releases"),
            "alpha_recovery_state": summary.get("alpha_recovery_state"),
        },
        "performance_target_used": False,
    }
    (out / "RESULT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "SHA256.json").write_text(json.dumps({
        p.name: sha(p.read_bytes()) for p in sorted(out.iterdir())
        if p.is_file() and p.name != "SHA256.json"
    }, indent=2, sort_keys=True) + "\n")
    print("[ALPHA_EXPERIMENT_RESULT] " + json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
