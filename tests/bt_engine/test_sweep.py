"""Phase 5 sweep: deterministic grid enumeration, walk-forward window guard,
per-config execution with overfit-gap math, and the anti-overfit mechanism on a
regime-flip dataset (in-sample winner degrades out-of-sample, visibly)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.sweep import (SweepWindows, apply_diff, enumerate_grid,
                       merge_extra_configs, run_config_both_windows)
from stock_strategy_shared.schemas.strategy import StrategyConfig

_REGIMES = {
    "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
    "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
}
_W = {"momentum": 0.9, "quality": 0.025, "value": 0.025, "growth": 0.025, "low_volatility": 0.025}


def _base_cfg() -> dict:
    return StrategyConfig(**{
        "strategy_id": "sweep_test",
        "min_non_null_factors": 1,
        "universe": {"source": "av_listing", "min_price": 1.0, "min_avg_dollar_volume_20d": 0.0},
        "regime_detection": {"slow_sma": 20, "vol_window": 5, "vol_threshold": 0.8,
                             "confirmation_days": 1, "regimes": _REGIMES},
        "factor_weights": {"bull_calm": _W, "bull_stress": _W,
                           "bear_stress": _W, "bear_calm": _W},
        "regime_weighting_enabled": False,
        "static_factor_weights": _W,
        "portfolio_builder": {
            "method": "greedy_score_per_port_vol", "max_positions": 3,
            "max_position_weight": 0.6, "max_sector_weight": 1.0,
            "weighting": "equal_weight", "candidate_count": 10,
            "covariance_window_days": 40, "min_covariance_observations": 20,
            "covariance_shrinkage": 0.2, "cluster_correlation_threshold": 0.99,
            "max_cluster_weight": 1.0, "max_tickers_per_cluster": None,
        },
        "vetter": {"candidate_count": 10},
    }).model_dump(mode="json")


def _flip_data(n_days=560, flip_at=470):
    """HOT has a strong drift through the tune window, then reverses hard in the
    validate window; the others stay steady. A config more exposed to HOT wins
    in-sample and degrades out-of-sample — the gap the leaderboard must expose."""
    days = pd.bdate_range("2024-01-02", periods=n_days)
    spec = {"HOT": 0.0016, "AAA": 0.0005, "BBB": 0.0006, "CCC": 0.0004,
            "DDD": 0.0005, "SPY": 0.0005}
    rows = []
    for t, drift in spec.items():
        px = 100.0
        for i, d in enumerate(days):
            dr = drift
            if t == "HOT" and i >= flip_at:
                dr = -0.004
            # NOT hash(): string hashing is PYTHONHASHSEED-randomized per process,
            # which made this "deterministic" dataset differ run-to-run (flaky).
            wiggle = 0.002 * np.sin(i / 7.0 + sum(map(ord, t)) % 10)
            px = px * (1.0 + dr + wiggle)
            rows.append({"ticker": t, "date": d, "open": px * 0.999, "close": px,
                         "adjusted_close": px, "volume": 1_000_000.0})
    prices = pd.DataFrame(rows)
    fnd = pd.DataFrame([
        {"ticker": t, "as_of_date": days[0], "pe_ratio": 15.0, "pb_ratio": 2.0,
         "roe": 0.15, "debt_to_equity": 0.5, "revenue_growth": 0.05, "eps_growth": 0.05}
        for t in spec if t != "SPY"])
    return prices, fnd, days, flip_at


# ── grid enumeration ──────────────────────────────────────────────────────────

def test_grid_product_and_deterministic_order():
    grid = {"b.two": [1, 2], "a.one": ["x", "y", "z"]}
    diffs = enumerate_grid(grid)
    assert len(diffs) == 6
    assert diffs == enumerate_grid(grid)                 # identical order every call
    assert diffs[0] == {"a.one": "x", "b.two": 1}        # sorted keys, positional


def test_grid_sampling_bounded_and_seeded():
    grid = {"p": list(range(30)), "q": list(range(30))}   # 900 combos
    s1 = enumerate_grid(grid, max_configs=50, sample_seed=7)
    s2 = enumerate_grid(grid, max_configs=50, sample_seed=7)
    s3 = enumerate_grid(grid, max_configs=50, sample_seed=8)
    assert len(s1) == 50 and s1 == s2
    assert s1 != s3                                       # different seed, different subset


def test_empty_grid_is_single_baseline():
    assert enumerate_grid({}) == [{}]


# ── apply_diff ────────────────────────────────────────────────────────────────

def test_apply_diff_valid_and_invalid():
    base = _base_cfg()
    out, err = apply_diff(base, {"portfolio_builder.max_positions": 4})
    assert err is None and out["portfolio_builder"]["max_positions"] == 4
    out, err = apply_diff(base, {"portfolio_builder.max_position_weight": 9.0})
    assert out is None and "invalid config" in err


# ── merge_extra_configs (experiment queue, Phase 6b) ──────────────────────────

def test_extra_configs_appended_not_multiplied():
    grid_diffs = enumerate_grid({"portfolio_builder.max_positions": [3, 4]})
    merged, dropped = merge_extra_configs(
        grid_diffs, [{"portfolio_builder.max_position_weight": 0.5}], _base_cfg())
    assert len(merged) == 3 and dropped == 0           # 2 grid + 1 extra, no product
    assert merged[-1] == {"portfolio_builder.max_position_weight": 0.5}


def test_extra_configs_drop_invalid_dup_and_junk_without_killing_sweep():
    grid_diffs = enumerate_grid({"portfolio_builder.max_positions": [3]})
    merged, dropped = merge_extra_configs(grid_diffs, [
        {"portfolio_builder.max_positions": 3},          # dup of grid diff
        {"portfolio_builder.max_position_weight": 9.0},  # schema-invalid
        {},                                              # empty
        "not-a-dict",                                    # junk
        {"portfolio_builder.max_positions": 5},          # valid — survives
    ], _base_cfg())
    assert dropped == 4
    assert merged == grid_diffs[:1] + [{"portfolio_builder.max_positions": 5}]


# ── walk-forward window guard ─────────────────────────────────────────────────

def test_overlapping_windows_rejected():
    w = SweepWindows(date(2025, 1, 1), date(2025, 6, 1),
                     date(2025, 5, 1), date(2025, 9, 1))   # validate starts inside tune
    assert "walk-forward" in (w.validate() or "")
    ok = SweepWindows(date(2025, 1, 1), date(2025, 6, 1),
                      date(2025, 6, 1), date(2025, 9, 1))
    assert ok.validate() is None


# ── per-config execution ──────────────────────────────────────────────────────

def _windows(days, flip_at):
    return SweepWindows(
        tune_start=days[430].date(), tune_end=days[flip_at - 1].date(),
        validate_start=days[flip_at].date(), validate_end=days[-1].date())


_SIM_KW = dict(tx_cost_bps=0, fill_timing="close", starting_capital=100_000.0,
               rebalance_every=5)


def test_run_config_shape_gap_math_and_determinism():
    prices, fnd, days, flip_at = _flip_data()
    w = _windows(days, flip_at)
    r1 = run_config_both_windows(prices, fnd, {}, _base_cfg(), {}, w, _SIM_KW)
    r2 = run_config_both_windows(prices, fnd, {}, _base_cfg(), {}, w, _SIM_KW)
    assert r1 == r2                                           # deterministic
    assert r1["error_message"] is None
    assert r1["overfit_gap"] == pytest.approx(
        round(r1["is_sharpe"] - r1["oos_sharpe"], 4))
    for k in ("in_sample", "out_sample", "oos_return", "oos_max_drawdown"):
        assert r1[k] is not None


def test_invalid_config_becomes_error_row_not_crash():
    prices, fnd, days, flip_at = _flip_data(n_days=560)
    w = _windows(days, flip_at)
    r = run_config_both_windows(prices, fnd, {}, _base_cfg(),
                                {"portfolio_builder.not_a_knob": 1}, w, _SIM_KW)
    assert r["error_message"] and "invalid config" in r["error_message"]
    assert "oos_sharpe" not in r or r.get("oos_sharpe") is None


def test_regime_flip_exposes_overfit_gap():
    """The concentrated config (2 names, HOT-heavy) must show a LARGER in-vs-out
    degradation than the diversified one on the flip dataset — the exact signal
    the leaderboard's overfit_gap column exists to surface."""
    prices, fnd, days, flip_at = _flip_data()
    w = _windows(days, flip_at)
    concentrated = run_config_both_windows(
        prices, fnd, {}, _base_cfg(),
        {"portfolio_builder.max_positions": 2}, w, _SIM_KW)
    diversified = run_config_both_windows(
        prices, fnd, {}, _base_cfg(),
        {"portfolio_builder.max_positions": 5,
         "portfolio_builder.max_position_weight": 0.35}, w, _SIM_KW)
    assert concentrated["error_message"] is None
    assert diversified["error_message"] is None
    # Both ride HOT in-sample; the 2-name book carries ~2x the HOT weight, so its
    # out-of-sample crash exposure — and therefore its overfit gap — is larger.
    assert concentrated["overfit_gap"] > diversified["overfit_gap"]
