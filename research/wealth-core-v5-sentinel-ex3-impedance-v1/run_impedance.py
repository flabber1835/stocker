#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
V5_DIR = HERE.parent / "wealth-core-v5-affordability-fix-v1"
if str(V5_DIR) not in sys.path:
    sys.path.insert(0, str(V5_DIR))

from v5_execution_harness import (
    CLOSE_ADMISSION_RULE,
    _V4,
    apply_v5_open_time_whole_share_10bp,
    assert_exact_v5_delta,
)

CONTROL_10BP_SOURCE_SHA256 = "5f61d5ed5afd784bfb247d554344199743de11dcf9b31956430c6a77b91fedf7"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
INITIAL_CAPITAL = 100_000.0
SLOTS = 20
ENTRY_W = 0.05
BASELINE_TX_SHA256 = "0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da"
BASELINE_CLOSE_SHA256 = "d1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724"
BASELINE_CORE_TAPE_SHA256 = "3b40a23a7e499e0314f1d6e86b767fba648136758fdd106cdfd0ff27620b545f"
BASELINE_EX3_20Y = {
    "cagr": 0.20725062417242723,
    "max_drawdown": -0.28449191381677585,
    "sharpe_daily_252": 1.0945954949104486,
}
CORE_COLUMNS = [
    "date", "shadow_equity", "open_equity", "wc_dd", "damaged", "green",
    "eligible_count", "leadership_population", "held_count",
    "research_eligible_universe", "research_ranking_count",
    "research_ranking_sha256", "research_selected_positions_sha256",
    "research_selected_positions",
]

VARIANTS = {
    "baseline": {"rec": 8, "r40_floor": 0.00, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m02_rec8": {"rec": 8, "r40_floor": -0.02, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m03_rec8": {"rec": 8, "r40_floor": -0.03, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m04_rec8": {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m05_rec8": {"rec": 8, "r40_floor": -0.05, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m04_rec7": {"rec": 7, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m04_rec9": {"rec": 9, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m04_rec10": {"rec": 10, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63},
    "r40_m04_rec8_fast90": {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.90, "healthy_damaged": 0.63},
    "r40_m04_rec8_healthy65": {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.65},
}

FROZEN = {
    "ldrc_r20": -0.085,
    "ldrc_v": 0.11,
    "ldrc_dd": -0.10,
    "ldrc_ceiling": 0.55,
    "divergence_spy_floor": 0.0,
    "native_ordinary_dd": -0.155,
    "native_fast_green": 0.20,
    "native_fast_r5": -0.05,
    "native_fast_r10": -0.08,
    "native_fast_damaged_delta5": 0.30,
    "native_fast_volacc": 0.04,
    "native_fast_spy20": -0.01,
    "native_fast_r10confirm": -0.10,
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, observed {count}")
    return src.replace(old, new, 1)


def parameterize_20_slots(src: str) -> str:
    src = replace_once(src, "N_SLOTS = 25", "N_SLOTS = 20", "20-slot count")
    src = replace_once(src, "ENTRY_W = 0.04", "ENTRY_W = 0.05", "20-slot equal weight")
    return src


def apply_variant(src: str, cfg: dict) -> str:
    out = src
    out = replace_once(out, "LDRC_REC=8", f"LDRC_REC={int(cfg['rec'])}", "LDRC recovery sessions")
    out = replace_once(
        out,
        "and recent_r20>0 and recent_r40>0.0)",
        f"and recent_r20>0 and recent_r40>{repr(float(cfg['r40_floor']))})",
        "EX3 full-recovery r40 floor",
    )
    out = replace_once(
        out,
        "'dam':0.88",
        f"'dam':{repr(float(cfg['fast_damaged']))}",
        "native FAST damaged threshold",
    )
    out = replace_once(
        out,
        "dam<=0.63 and green>=.20",
        f"dam<={repr(float(cfg['healthy_damaged']))} and green>=.20",
        "native healthy damaged ceiling",
    )
    return out


def metrics(frame: pd.DataFrame, col: str) -> dict:
    nav = frame[col].astype(float)
    dates = pd.to_datetime(frame["date"])
    if len(nav) < 2 or not np.isfinite(nav).all() or (nav <= 0).any():
        raise RuntimeError(f"invalid NAV path: {col}")
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    r = nav.pct_change().dropna()
    vol = float(r.std(ddof=1))
    return {
        "start": str(dates.iloc[0].date()),
        "end": str(dates.iloc[-1].date()),
        "sessions": int(len(nav)),
        "cagr": multiple ** (1.0 / years) - 1.0,
        "ending_multiple": multiple,
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
        "sharpe_daily_252": float(r.mean() / vol * np.sqrt(252)) if vol > 0 else None,
    }


def windows(frame: pd.DataFrame, col: str) -> dict:
    dates = pd.to_datetime(frame["date"])
    end = dates.iloc[-1]
    out = {}
    for years in (5, 10, 15, 20):
        start = end - pd.DateOffset(years=years)
        out[str(years)] = metrics(frame.loc[dates >= start].copy(), col)
    return out


def core_tape_hash(frame: pd.DataFrame) -> str:
    missing = [c for c in CORE_COLUMNS if c not in frame.columns]
    if missing:
        raise RuntimeError(f"core parity columns missing: {missing}")
    payload = frame[CORE_COLUMNS].to_csv(index=False, float_format="%.17g", na_rep="").encode()
    return sha_bytes(payload)


def allocation_counts(frame: pd.DataFrame) -> dict:
    x = frame["A_allocation"].astype(float)
    vals = {}
    for v in (0.0, 0.55, 0.65, 1.0):
        vals[str(v)] = int(np.isclose(x.to_numpy(), v, atol=1e-12).sum())
    changes = int((x.diff().abs() > 1e-12).sum())
    return {"average": float(x.mean()), "sessions_by_level": vals, "transitions": changes}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    cfg = VARIANTS[args.variant]

    from backtester.production_equivalent_economic_overlay import assert_contract, assert_one_session_dividend_lag

    out = args.output.resolve()
    engine = out / "engine"
    out.mkdir(parents=True, exist_ok=False)
    engine.mkdir()
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    (workspace / "final-output").mkdir(parents=True, exist_ok=True)

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256:
        raise RuntimeError("canonical PIT dataset hash mismatch")

    raw = args.control_source.read_text()
    if sha_bytes(raw.encode()) != CONTROL_10BP_SOURCE_SHA256:
        raise RuntimeError("10bp source authority mismatch")
    assert_contract(raw)
    if assert_one_session_dividend_lag(raw) != 1:
        raise RuntimeError("raw source dividend lag mismatch")

    median = load_module(args.median_overlay.resolve(), "impedance_median5_overlay")
    median5 = median.apply_arm(raw, "MEDIAN5_CANONICAL")
    assert_contract(median5)

    v4 = _V4.apply_open_time_whole_share_10bp(median5)
    v5 = apply_v5_open_time_whole_share_10bp(median5)
    assert_exact_v5_delta(v4, v5)
    v4 = parameterize_20_slots(v4)
    v5 = parameterize_20_slots(v5)
    assert_exact_v5_delta(v4, v5)
    if assert_one_session_dividend_lag(v5) != 1:
        raise RuntimeError("V5 source dividend lag mismatch")

    candidate = apply_variant(v5, cfg)
    if args.variant == "baseline" and candidate != v5:
        raise RuntimeError("baseline impedance arm is not byte-identical to frozen V5+EX3 source")

    for marker in (
        "N_SLOTS = 20", "ENTRY_W = 0.05",
        "if float(book.cash)+1e-12<_one_share_close_cost:",
        "q=float(math.floor(_execution_budget/(float(px)*(1+COST))))",
        "return _median_top3(_durable,_hist,5)",
    ):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"frozen V5 marker missing/duplicated: {marker}")
    assert_contract(candidate)

    generated = out / f"v5-ex3-impedance-{args.variant}.py"
    generated.write_text(candidate)
    compile(candidate, str(generated), "exec")

    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    module = types.ModuleType(f"v5_ex3_impedance_{args.variant}")
    module.__file__ = str(generated)
    sys.modules[module.__name__] = module
    exec(compile(candidate, str(generated), "exec"), module.__dict__)
    if getattr(module, "MODE", None) != "fullpit" or getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError("generated source did not enter full-PIT mode")
    module.OUT = engine
    module.run()

    daily = engine / "daily.csv"
    summary_p = engine / "summary.json"
    tx_p = engine / "transactions.csv"
    close_p = engine / "close-decisions.csv"
    telemetry_p = engine / "open-sizing-telemetry.json"
    for p in (daily, summary_p, tx_p, close_p, telemetry_p):
        if not p.exists():
            raise RuntimeError(f"required evidence missing: {p.name}")

    frame = pd.read_csv(daily, parse_dates=["date"])
    if len(frame) != 5032 or str(frame.date.iloc[0].date()) != "2006-07-31" or str(frame.date.iloc[-1].date()) != "2026-07-31":
        raise RuntimeError("measurement horizon mismatch")
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise RuntimeError("daily tape ordering failure")

    summary = json.loads(summary_p.read_text())
    telemetry = json.loads(telemetry_p.read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256:
        raise RuntimeError("summary dataset mismatch")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError("summary dividend lag mismatch")
    if telemetry.get("close_admission_rule") != CLOSE_ADMISSION_RULE or telemetry.get("close_admission_rule_cash_basis") != "TOTAL_CASH":
        raise RuntimeError("V5 affordability contract mismatch")

    core_hash = core_tape_hash(frame)
    tx_hash = sha_bytes(tx_p.read_bytes())
    close_hash = sha_bytes(close_p.read_bytes())
    if core_hash != BASELINE_CORE_TAPE_SHA256:
        raise RuntimeError(f"Wealth Core tape changed: {core_hash}")
    if tx_hash != BASELINE_TX_SHA256:
        raise RuntimeError(f"Wealth Core transactions changed: {tx_hash}")
    if close_hash != BASELINE_CLOSE_SHA256:
        raise RuntimeError(f"Wealth Core close decisions changed: {close_hash}")

    core_w = windows(frame, "shadow_equity")
    ex3_w = windows(frame, "A_nav")
    if args.variant == "baseline":
        b = ex3_w["20"]
        for k, expected in BASELINE_EX3_20Y.items():
            if abs(float(b[k]) - expected) > 5e-12:
                raise RuntimeError(f"baseline EX3 parity failed for {k}: {b[k]} vs {expected}")

    result = {
        "schema": "research.wealth-core-v5-sentinel-ex3-impedance/1",
        "status": "PASS_FRESH_CAUSAL_PIT_REPLAY",
        "variant": args.variant,
        "experiment_slot": list(VARIANTS).index(args.variant) + 1,
        "experiment_budget": 10,
        "measurement": {"start": "2006-07-31", "end": "2026-07-31", "sessions": 5032},
        "dataset_sha256": DATASET_SHA256,
        "wealth_core_v5": {
            "slots": SLOTS,
            "entry_weight": ENTRY_W,
            "median_rank_lookback": 5,
            "cash_buffer_basis_points": 10.0,
            "position_sizing": "NEXT_VALID_OPEN_WHOLE_SHARES",
            "affordability_cash_basis": "TOTAL_CASH",
            "windows": core_w,
            "core_tape_sha256": core_hash,
            "transactions_sha256": tx_hash,
            "close_decisions_sha256": close_hash,
        },
        "sentinel_ex3": {
            "configuration": {**FROZEN, **cfg},
            "windows": ex3_w,
            "allocation": allocation_counts(frame),
            "candidate_A_episodes": summary.get("candidate_A_episodes"),
            "candidate_A_concordance_releases": summary.get("candidate_A_concordance_releases"),
            "transition_counts": summary.get("transition_counts"),
            "modeled_allocation_transition_cost_sum": summary.get("modeled_allocation_transition_cost_sum"),
        },
        "validation": {
            "fresh_full_pit_replay": True,
            "wealth_core_v5_tape_exact_parity": True,
            "wealth_core_transactions_exact_parity": True,
            "wealth_core_close_decisions_exact_parity": True,
            "controller_only_research_seams": True,
            "baseline_exact_ex3_parity": True if args.variant == "baseline" else None,
            "performance_target_used_at_runtime": False,
        },
        "source": {
            "control_10bp_sha256": CONTROL_10BP_SOURCE_SHA256,
            "v5_generated_sha256": sha_bytes(v5.encode()),
            "candidate_generated_sha256": sha_bytes(candidate.encode()),
            "experiment_head": os.environ.get("GITHUB_SHA"),
        },
    }
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    for src, name in ((daily, "daily.csv"), (summary_p, "summary.json"), (tx_p, "transactions.csv"), (close_p, "close-decisions.csv"), (telemetry_p, "open-sizing-telemetry.json")):
        shutil.copy2(src, out / name)
    (out / "SHA256.json").write_text(json.dumps({
        p.name: sha_bytes(p.read_bytes()) for p in sorted(out.iterdir())
        if p.is_file() and p.name != "SHA256.json"
    }, indent=2, sort_keys=True) + "\n")
    print("[V5_EX3_IMPEDANCE_RESULT] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
