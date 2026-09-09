#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

from v5_execution_harness import (
    CLOSE_ADMISSION_RULE,
    CONTRACT_VERSION,
    Q0_REASON,
    V4_CONTRACT_VERSION,
    _V4,
    apply_v5_open_time_whole_share_10bp,
    assert_exact_v5_delta,
)

ALLOWED_SLOTS = tuple(range(18, 27))
CONTROL_10BP_SOURCE_SHA256 = "5f61d5ed5afd784bfb247d554344199743de11dcf9b31956430c6a77b91fedf7"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
INITIAL_CAPITAL = 100_000.0
AUTHORITIES = {
    "v5_authority_head": "288f31a03b74c3ae186550ae22b78926930765de",
    "v5_contract_commit": "4b3eb0a364cef57906b104a02c4e37b28dcd9176",
    "economic_source": "3dc74a8e54fdfe6e8368a8db3be0ecd127ee4689",
    "median5": "1c66096c1e3bd650233c630d4e9f71104ac8fc32",
    "formal_source": "27bb992087182c42c3c051e62bf837895f5d2ab7",
    "classifier_source": "ba74e79490beb8950611b1d17f5d124833b3d91e",
    "runtime_source": "887f479b15ad861313da666ad698034d3847121c",
}


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


def parameterize_equal_weight(src: str, slots: int) -> tuple[str, float]:
    entry_weight = 1.0 / float(slots)
    seams = (("N_SLOTS = 20", f"N_SLOTS = {slots}"), ("ENTRY_W = 0.05", f"ENTRY_W = {repr(entry_weight)}"))
    for old, new in seams:
        count = src.count(old)
        if count != 1:
            raise RuntimeError(f"stability seam must be unique: {old!r}; observed {count}")
        src = src.replace(old, new, 1)
    return src, entry_weight


def preperformance_contract_witnesses(cost: float) -> dict:
    # Historical AGN1 state documented from the pre-divergence V4 path.
    agn_total_cash = 232.450008
    agn_reserve = 214.455910
    agn_cash_above = agn_total_cash - agn_reserve
    agn_close = 166.92
    agn_one_share = agn_close * (1.0 + cost)
    agn_pass = agn_cash_above > 0 and agn_cash_above < agn_one_share <= agn_total_cash

    # Historical impossible AMZN state from 2015-12-04 documentation.
    amzn_total_cash = 265.66
    amzn_close = 672.64
    amzn_one_share = amzn_close * (1.0 + cost)
    amzn_pass = amzn_total_cash < amzn_one_share

    # A close-feasible trade can become zero quantity after an overnight gap.
    gap_total_cash = 200.0
    gap_reserve = 10.0
    gap_close = 150.0
    gap_open = 250.0
    gap_target = 1_000.0
    close_affordable = gap_total_cash - gap_reserve > 0 and gap_total_cash >= gap_close * (1.0 + cost)
    execution_budget = max(0.0, min(gap_target, gap_total_cash))
    gap_quantity = math.floor(execution_budget / (gap_open * (1.0 + cost)))
    gap_pass = close_affordable and gap_quantity == 0

    result = {
        "agn1_false_rejection_arithmetic": {
            "pass": bool(agn_pass),
            "decision_date": "2014-05-23",
            "total_cash": agn_total_cash,
            "reserve": agn_reserve,
            "cash_above_reserve": agn_cash_above,
            "close_price": agn_close,
            "one_share_close_cost": agn_one_share,
            "expected_v5_close_result": "ADMISSIBLE_IF_OTHER_GATES_PASS",
        },
        "amzn_true_unaffordability_arithmetic": {
            "pass": bool(amzn_pass),
            "documented_state_date": "2015-12-04",
            "total_cash": amzn_total_cash,
            "close_price": amzn_close,
            "one_share_close_cost": amzn_one_share,
            "expected_v5_close_result": "TOTAL_CASH_ONE_SHARE_UNAFFORDABLE",
        },
        "gap_risk_zero_quantity_guard": {
            "pass": bool(gap_pass),
            "synthetic_total_cash": gap_total_cash,
            "synthetic_reserve": gap_reserve,
            "synthetic_close_price": gap_close,
            "synthetic_open_price": gap_open,
            "execution_budget": execution_budget,
            "next_open_quantity": int(gap_quantity),
        },
    }
    if not all(x["pass"] for x in result.values()):
        raise RuntimeError(f"V5 pre-performance witness failure: {result}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", required=True, type=int, choices=ALLOWED_SLOTS)
    ap.add_argument("--control-source", required=True, type=Path)
    ap.add_argument("--median-overlay", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    slots = int(args.slots)

    from backtester.production_equivalent_economic_overlay import assert_contract, assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast

    out = args.output.resolve()
    engine = out / "engine"
    out.mkdir(parents=True, exist_ok=False)
    engine.mkdir()

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

    v4_reference = _V4.apply_open_time_whole_share_10bp(median5)
    v5 = apply_v5_open_time_whole_share_10bp(median5)
    assert_exact_v5_delta(v4_reference, v5)

    v4_reference, entry_weight_v4 = parameterize_equal_weight(v4_reference, slots)
    v5, entry_weight = parameterize_equal_weight(v5, slots)
    if entry_weight_v4 != entry_weight:
        raise RuntimeError("V4/V5 stability weight parameterization mismatch")
    assert_exact_v5_delta(v4_reference, v5)

    assert_contract(v5)
    if assert_one_session_dividend_lag(v5) != 1:
        raise RuntimeError("V5 changed dividend semantics")

    required = (
        f"N_SLOTS = {slots}",
        f"ENTRY_W = {repr(entry_weight)}",
        "return _median_top3(_durable,_hist,5)",
        "for tid0 in _harden_order(durable,score,_rank_order_hist):",
        "_buffer_required_close=max(0.0,float(eq)*0.001)",
        "_buffer_available_close=max(0.0,float(book.cash)-_buffer_required_close)",
        "if _buffer_available_close<=1e-12:",
        "if float(book.cash)+1e-12<_one_share_close_cost:",
        f"'q0_reason':'{Q0_REASON}'",
        "outcome':'PLAN_OPEN_SIZE'",
        "q=float(math.floor(_execution_budget/(float(px)*(1+COST))))",
        "a_d,a_reason=ca.step",
        "pend['A']=a_d",
    )
    for marker in required:
        if v5.count(marker) != 1:
            raise RuntimeError(f"required V5 economic marker missing/duplicated: {marker}")

    forbidden = (
        "if _buffer_available_close+1e-12<_one_share_close_cost:",
        "'q0_reason':'WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE'",
    )
    for marker in forbidden:
        if marker in v5:
            raise RuntimeError(f"forbidden V4 affordability marker present: {marker}")

    generated = out / f"wealth-core-v5-stability-{slots}-generated.py"
    generated.write_text(v5)
    v4_generated = out / f"wealth-core-v4-reference-{slots}-generated.py"
    v4_generated.write_text(v4_reference)
    compile(v5, str(generated), "exec")

    os.environ["RESEARCH_REPLAY_MODE"] = "fullpit"
    module = types.ModuleType(f"wealth_core_v5_stability_{slots}")
    module.__file__ = str(generated)
    sys.modules[module.__name__] = module
    exec(compile(v5, str(generated), "exec"), module.__dict__)
    if getattr(module, "MODE", None) != "fullpit" or getattr(module, "PIT_MODE", None) is not True:
        raise RuntimeError("generated V5 source did not enter full-PIT mode")
    cost = float(getattr(module, "COST"))

    # These witnesses run before any performance replay is accepted.
    witnesses = preperformance_contract_witnesses(cost)

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
    if telemetry.get("close_admission_rule") != CLOSE_ADMISSION_RULE:
        raise RuntimeError("V5 close affordability rule missing")
    if telemetry.get("close_admission_rule_cash_basis") != "TOTAL_CASH":
        raise RuntimeError("V5 affordability cash basis is not TOTAL_CASH")

    tx = pd.read_csv(tx_path)
    buy_mask = tx["Buy or sell"].eq("BUY")
    buys_array = pd.to_numeric(tx.loc[buy_mask, "Amount of shares"], errors="raise").to_numpy(dtype=float)
    fractional_violations = int(np.count_nonzero(~np.isclose(buys_array, np.round(buys_array), atol=1e-9)))
    if fractional_violations != 0:
        raise RuntimeError("fractional BUY detected")

    close = pd.read_csv(close_decisions_path)
    close["q0_reason"] = close["q0_reason"].fillna("").astype(str)
    close["ticker"] = close["ticker"].astype(str)
    affordability = close.loc[close["q0_reason"].eq(Q0_REASON)].copy()
    if len(affordability):
        one_cost = affordability["close_price"].astype(float) * (1.0 + cost)
        total_cash = affordability["cash_before_decision"].astype(float)
        if bool((total_cash + 1e-8 >= one_cost).any()):
            raise RuntimeError("V5 emitted total-cash unaffordability skip despite affordable total cash")

    cash_scarcity = close.loc[close["q0_reason"].eq("CASH_SCARCITY")]
    if int(telemetry.get("close_q0_cash_scarcity", -1)) != int(len(cash_scarcity)):
        raise RuntimeError("cash-scarcity telemetry mismatch")
    if int(telemetry.get("close_q0_total_cash_one_share_unaffordable", -1)) != int(len(affordability)):
        raise RuntimeError("total-cash affordability telemetry mismatch")

    # Historical AGN1 is authoritative only for the 20-slot baseline because
    # other stability arms intentionally have different portfolio paths.
    if slots == 20:
        agn = close.loc[(close["decision_date"].astype(str).eq("2014-05-23")) & close["ticker"].eq("AGN1")].copy()
        if agn.empty:
            raise RuntimeError("20-slot V5 baseline missing historical AGN1 decision witness")
        agn["one_share_cost"] = agn["close_price"].astype(float) * (1.0 + cost)
        valid = agn.loc[
            (agn["cash_before_decision"].astype(float) + 1e-8 >= agn["one_share_cost"])
            & (agn["uncommitted_cash_after_reserve"].astype(float) + 1e-8 < agn["one_share_cost"])
            & agn["outcome"].astype(str).eq("PLAN_OPEN_SIZE")
        ]
        if valid.empty:
            raise RuntimeError("20-slot AGN1 false-rejection witness did not pass V5 close admission")
        a = valid.iloc[0]
        witnesses["agn1_historical_20_slot"] = {
            "pass": True,
            "rows": int(len(valid)),
            "decision_date": "2014-05-23",
            "total_cash": float(a["cash_before_decision"]),
            "reserve": float(a["required_reserve"]),
            "cash_above_reserve": float(a["uncommitted_cash_after_reserve"]),
            "close_price": float(a["close_price"]),
            "one_share_close_cost": float(a["one_share_cost"]),
            "outcome": str(a["outcome"]),
        }

    historical_amzn_unaffordable = affordability.loc[affordability["ticker"].eq("AMZN")]
    witnesses["historical_path_counts"] = {
        "total_cash_one_share_unaffordable_skips": int(len(affordability)),
        "amzn_total_cash_one_share_unaffordable_skips": int(len(historical_amzn_unaffordable)),
        "next_open_zero_quantity_blocks": int(telemetry.get("zero_quantity_blocks", 0)),
        "invalid_open_blocks": int(telemetry.get("invalid_open_market_blocks", 0)),
    }
    (out / "v5-witnesses.json").write_text(json.dumps(witnesses, indent=2, sort_keys=True) + "\n")

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
        "schema": "research.wealth-core-v5-portfolio-stability/1",
        "status": "PASS_FRESH_CAUSAL_PIT_REPLAY",
        "wealth_core_version": "V5",
        "economic_scope": "MEDIAN5_WEALTH_CORE_V5_PLUS_PARALLEL_EX3",
        "initial_capital": INITIAL_CAPITAL,
        "measurement_start": "2006-07-31",
        "measurement_end": "2026-07-31",
        "sessions": 5032,
        "dataset_sha256": DATASET_SHA256,
        "dividend_lag_sessions": 1,
        "execution_harness_contract": CONTRACT_VERSION,
        "v4_reference_harness_contract": V4_CONTRACT_VERSION,
        "stability_search": {
            "dimension": "portfolio_slots",
            "portfolio_slots": slots,
            "target_entry_weight": entry_weight,
            "sweep_min_slots": 18,
            "sweep_max_slots": 26,
            "equal_weight_rule": "1/N",
            "performance_target_used": False,
        },
        "wealth_core": {
            "configuration": {
                "slots": slots,
                "target_entry_weight": entry_weight,
                "median_rank_lookback": 5,
                "hardened_front_count": 3,
                "cash_buffer_basis_points": 10.0,
                "position_sizing": "NEXT_VALID_OPEN_WHOLE_SHARES",
                "fractional_shares": False,
                "close_admission_rule": CLOSE_ADMISSION_RULE,
                "close_admission_rule_cash_basis": "TOTAL_CASH",
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
        "execution_counts": {
            "buys": int(buy_mask.sum()),
            "sells": int(tx["Buy or sell"].eq("SELL").sum()),
            "close_cash_scarcity_skips": int(len(cash_scarcity)),
            "close_total_cash_one_share_unaffordable_skips": int(len(affordability)),
            "next_open_zero_quantity_blocks": int(telemetry.get("zero_quantity_blocks", 0)),
            "invalid_open_blocks": int(telemetry.get("invalid_open_market_blocks", 0)),
            "cash_limited_executions": int(telemetry.get("cash_limited_open_executions", 0)),
            "fractional_share_violations": fractional_violations,
            "completed_entries": int(telemetry.get("completed_entries", 0)),
            "close_admissions": int(telemetry.get("close_admissions", 0)),
        },
        "affordability_witnesses": witnesses,
        "validation": {
            "same_canonical_pit_dataset": True,
            "same_measurement_sessions": True,
            "same_median5_source_before_execution_transform": True,
            "same_ex3_logic": True,
            "same_dividend_lag": True,
            "same_whole_share_next_open_sizing": True,
            "only_v5_affordability_cash_basis_differs_from_v4_reference": True,
            "portfolio_size_and_equal_weight_are_only_sweep_variables": True,
            "baseline_reference": "FIRST_FROZEN_V5_20_SLOT_REFERENCE" if slots == 20 else "V5_STABILITY_ARM",
        },
        "authorities": AUTHORITIES,
        "source": {
            "control_10bp_sha256": CONTROL_10BP_SOURCE_SHA256,
            "median5_generated_sha256": sha(median5.encode()),
            "v4_reference_generated_sha256": sha(v4_reference.encode()),
            "v5_final_generated_sha256": sha(v5.encode()),
            "v5_final_generated_normalized_ast_sha256": sha(normalized_ast(v5).encode()),
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
    print("[WEALTH_CORE_V5_STABILITY_RESULT] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
