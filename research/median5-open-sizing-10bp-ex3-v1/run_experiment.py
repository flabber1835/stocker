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

from canonical_execution_harness import CONTRACT_VERSION, apply_open_time_whole_share_10bp

CONTROL_10BP_SOURCE_SHA256 = "5f61d5ed5afd784bfb247d554344199743de11dcf9b31956430c6a77b91fedf7"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
INITIAL_CAPITAL = 100_000.0


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


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
        "start_equity": float(nav.iloc[0]),
        "end_equity": float(nav.iloc[-1]),
    }


def windows(frame: pd.DataFrame, col: str) -> dict:
    dates = pd.to_datetime(frame["date"])
    end = dates.iloc[-1]
    out = {}
    for years in (5, 10, 15, 20):
        start = end - pd.DateOffset(years=years)
        part = frame.loc[dates >= start].copy()
        out[str(years)] = metrics(part, col)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    from backtester.production_equivalent_economic_overlay import assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast

    out = args.output.resolve()
    engine = out / "engine"
    out.mkdir(parents=True, exist_ok=False)
    engine.mkdir()
    fixed_parent = Path(os.environ.get("GITHUB_WORKSPACE", ".")) / "final-output"
    fixed_parent.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((Path(os.environ["CANONICAL_PIT_DATASET"]) / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256:
        raise RuntimeError("canonical PIT dataset hash mismatch")

    raw = args.control_source.read_text()
    if sha(raw.encode()) != CONTROL_10BP_SOURCE_SHA256:
        raise RuntimeError(f"10bp source authority mismatch: {sha(raw.encode())}")
    assert_contract(raw)
    if assert_one_session_dividend_lag(raw) != 1:
        raise RuntimeError("10bp source dividend lag is not one session")

    median = load_module(args.median_overlay.resolve(), "median5_overlay_exact")
    median5 = median.apply_arm(raw, "MEDIAN5_CANONICAL")
    assert_contract(median5)
    if assert_one_session_dividend_lag(median5) != 1:
        raise RuntimeError("Median-5 changed dividend semantics")

    variant = apply_open_time_whole_share_10bp(median5)
    assert_contract(variant)
    if assert_one_session_dividend_lag(variant) != 1:
        raise RuntimeError("canonical execution harness changed dividend semantics")

    required = (
        "N_SLOTS = 20",
        "ENTRY_W = 0.05",
        "return _median_top3(_durable,_hist,5)",
        "for tid0 in _harden_order(durable,score,_rank_order_hist):",
        "_buffer_required_close=max(0.0,float(eq)*0.001)",
        "_one_share_close_cost=float(px)*(1+COST)",
        "WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE",
        "outcome':'PLAN_OPEN_SIZE'",
        "q=float(math.floor(_execution_budget/(float(px)*(1+COST))))",
        "a_d,a_reason=ca.step",
        "pend['A']=a_d",
    )
    for marker in required:
        if variant.count(marker) != 1:
            raise RuntimeError(f"required economic marker missing/duplicated: {marker}")

    generated = out / "median5-open-sizing-10bp-generated.py"
    generated.write_text(variant)
    compile(variant, str(generated), "exec")

    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    module = types.ModuleType("median5_open_sizing_10bp_fullpit")
    module.__file__ = str(generated)
    sys.modules[module.__name__] = module
    exec(compile(variant, str(generated), "exec"), module.__dict__)
    if getattr(module, "MODE", None) != "fullpit" or getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError("generated source did not enter full-PIT mode")
    module.OUT = engine
    module.run()

    daily_path = engine / "daily.csv"
    summary_path = engine / "summary.json"
    tx_path = engine / "transactions.csv"
    close_decisions_path = engine / "close-decisions.csv"
    open_telemetry_path = engine / "open-sizing-telemetry.json"
    events_path = engine / "open-sizing-events.csv"
    for p in (daily_path, summary_path, tx_path, close_decisions_path, open_telemetry_path, events_path):
        if not p.exists():
            raise RuntimeError(f"required evidence missing: {p.name}")

    frame = pd.read_csv(daily_path, parse_dates=["date"])
    if (
        len(frame) != 5032
        or str(frame.date.iloc[0].date()) != "2006-07-31"
        or str(frame.date.iloc[-1].date()) != "2026-07-31"
        or frame.date.duplicated().any()
        or not frame.date.is_monotonic_increasing
    ):
        raise RuntimeError("full-horizon witness mismatch")
    for col in ("shadow_equity", "A_nav", "A_allocation"):
        if col not in frame.columns:
            raise RuntimeError(f"required daily column missing: {col}")

    summary = json.loads(summary_path.read_text())
    if summary.get("replay_mode") != "fullpit":
        raise RuntimeError("summary replay mode mismatch")
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256:
        raise RuntimeError("summary dataset mismatch")
    if summary.get("financial_grade_dividend_lag_sessions") != 1:
        raise RuntimeError("summary dividend lag mismatch")

    scale = summary.get("wealth_core_capital_scale") or {}
    if abs(float(scale.get("initial_capital", -1.0)) - INITIAL_CAPITAL) > 1e-8:
        raise RuntimeError("initial capital telemetry mismatch")

    telemetry = json.loads(open_telemetry_path.read_text())
    if telemetry.get("mode") != "whole" or telemetry.get("fractional_shares_allowed") is not False:
        raise RuntimeError("whole-share execution contract mismatch")
    if float(telemetry.get("buffer_basis_points", -1.0)) != 10.0:
        raise RuntimeError("10bp buffer telemetry mismatch")
    if telemetry.get("close_admission_rule") != "REQUIRE_ONE_WHOLE_SHARE_AFFORDABLE_AT_CLOSE_ABOVE_10BP_RESERVE":
        raise RuntimeError("close affordability admission rule missing")

    tx = pd.read_csv(tx_path)
    buys = pd.to_numeric(tx.loc[tx["Buy or sell"].eq("BUY"), "Amount of shares"], errors="raise").to_numpy()
    if not np.allclose(buys, np.round(buys), atol=1e-9):
        raise RuntimeError("fractional BUY detected")

    core_windows = windows(frame, "shadow_equity")
    ex3_windows = windows(frame, "A_nav")
    contribution = {}
    for horizon in ("5", "10", "15", "20"):
        c = core_windows[horizon]
        a = ex3_windows[horizon]
        contribution[horizon] = {
            "cagr_percentage_points": (a["cagr"] - c["cagr"]) * 100.0,
            "max_drawdown_percentage_points": (a["max_drawdown"] - c["max_drawdown"]) * 100.0,
            "sharpe_delta": a["sharpe_daily_252"] - c["sharpe_daily_252"],
            "ending_multiple_delta": a["ending_multiple"] - c["ending_multiple"],
        }

    result = {
        "schema": "research.median5-open-sizing-10bp-ex3/2",
        "status": "PASS_FRESH_CAUSAL_PIT_REPLAY",
        "economic_scope": "MEDIAN5_WEALTH_CORE_PLUS_PARALLEL_EX3",
        "initial_capital": INITIAL_CAPITAL,
        "measurement_start": "2006-07-31",
        "measurement_end": "2026-07-31",
        "sessions": 5032,
        "dataset_sha256": DATASET_SHA256,
        "dividend_lag_sessions": 1,
        "execution_harness_contract": CONTRACT_VERSION,
        "wealth_core": {
            "configuration": {
                "slots": 20,
                "target_entry_weight": 0.05,
                "median_rank_lookback": 5,
                "hardened_front_count": 3,
                "cash_buffer_basis_points": 10.0,
                "position_sizing": "NEXT_VALID_OPEN_WHOLE_SHARES",
                "fractional_shares": False,
                "close_admission_rule": "REQUIRE_ONE_WHOLE_SHARE_AFFORDABLE_AT_CLOSE_ABOVE_10BP_RESERVE",
                "close_admission_rule_is_quantity_binding": False,
            },
            "windows": core_windows,
            "open_sizing_telemetry": telemetry,
            "capital_scale_telemetry": scale,
        },
        "sentinel_ex3": {
            "controller_path": "CandidateA / A_nav",
            "windows": ex3_windows,
            "average_allocation": float(frame["A_allocation"].astype(float).mean()),
            "zero_allocation_sessions": int(frame["A_allocation"].astype(float).eq(0.0).sum()),
            "transition_counts": summary.get("transition_counts"),
            "modeled_allocation_transition_cost_sum": summary.get("modeled_allocation_transition_cost_sum"),
            "candidate_A_episodes": summary.get("candidate_A_episodes"),
            "candidate_A_concordance_releases": summary.get("candidate_A_concordance_releases"),
        },
        "sentinel_incremental_contribution": contribution,
        "transactions": {
            "rows": int(len(tx)),
            "buys": int(tx["Buy or sell"].eq("BUY").sum()),
            "sells": int(tx["Buy or sell"].eq("SELL").sum()),
            "all_buy_share_amounts_integer": True,
        },
        "source": {
            "control_10bp_sha256": CONTROL_10BP_SOURCE_SHA256,
            "median5_generated_sha256": sha(median5.encode()),
            "final_generated_sha256": sha(variant.encode()),
            "final_generated_normalized_ast_sha256": sha(normalized_ast(variant).encode()),
            "experiment_head": os.environ.get("GITHUB_SHA"),
        },
        "performance_target_used": False,
    }
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    for src, name in (
        (daily_path, "daily.csv"),
        (summary_path, "summary.json"),
        (tx_path, "transactions.csv"),
        (close_decisions_path, "close-decisions.csv"),
        (open_telemetry_path, "open-sizing-telemetry.json"),
        (events_path, "open-sizing-events.csv"),
    ):
        shutil.copy2(src, out / name)

    (out / "SHA256.json").write_text(json.dumps({
        p.name: sha(p.read_bytes()) for p in sorted(out.iterdir())
        if p.is_file() and p.name != "SHA256.json"
    }, indent=2, sort_keys=True) + "\n")
    print("[MEDIAN5_OPEN_10BP_EX3_RESULT] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
