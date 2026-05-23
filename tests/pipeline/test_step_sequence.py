"""
Tests for the unified pipeline service step logic.

These tests import factors.py, rank.py, and engine.py from services/pipeline/
and verify that the pipeline module exposes identical behaviour to the three
separate services it replaced (factor-engine, ranker, delta-engine).
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.factors import (
    compute_all_factors,
    compute_growth,
    compute_momentum,
    compute_quality,
    compute_value,
    cross_section_zscore,
)
from app.rank import FACTORS, rank_universe
from app.engine import (
    DeltaDecision,
    RankObservation,
    _consecutive_in_zone,
    evaluate_all,
    evaluate_ticker,
)
from app.regime import detect_regime
from stock_strategy_shared.schemas.strategy import DeltaEngineConfig, StrategyConfig


# ── Strategy config fixture ───────────────────────────────────────────────────

VALID_CONFIG = StrategyConfig(**{
    "strategy_id": "pipeline_test_v1",
    "min_non_null_factors": 3,
    "regime_detection": {
        "slow_sma": 200,
        "vol_window": 20,
        "vol_threshold": 0.20,
        "confirmation_days": 5,
        "regimes": {
            "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
            "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
            "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
            "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
        },
    },
    "factor_weights": {
        "bull_calm":   {"momentum": 0.35, "quality": 0.25, "growth": 0.20, "value": 0.10, "low_volatility": 0.10},
        "bull_stress": {"quality": 0.35, "low_volatility": 0.25, "momentum": 0.20, "value": 0.10, "growth": 0.10},
        "bear_stress": {"low_volatility": 0.35, "quality": 0.30, "value": 0.20, "growth": 0.10, "momentum": 0.05},
        "bear_calm":   {"value": 0.30, "quality": 0.30, "low_volatility": 0.20, "momentum": 0.10, "growth": 0.10},
    },
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pivot(tickers: list[str], n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    data = {}
    for t in tickers:
        start = rng.uniform(50, 300)
        returns = rng.normal(0.0003, 0.015, n)
        prices = start * np.cumprod(1 + returns)
        data[t] = prices
    return pd.DataFrame(data, index=dates)


def _prices_long(tickers: list[str], n: int = 300) -> pd.DataFrame:
    pivot = _pivot(tickers, n)
    rows = []
    for ticker in tickers:
        for d, price in pivot[ticker].items():
            rows.append({
                "ticker": ticker,
                "date": d.date(),
                "close": price,
                "adjusted_close": price,
                "volume": int(1e6),
            })
    return pd.DataFrame(rows)


def _fund(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ticker": t,
            "pe_ratio": 20.0, "pb_ratio": 2.5,
            "roe": 0.2, "debt_to_equity": 0.5,
            "revenue_growth": 0.10, "eps_growth": 0.12,
        }
        for t in tickers
    ])


def _factor_scores(**kwargs) -> pd.DataFrame:
    rows = []
    for ticker, scores in kwargs.items():
        row = {"ticker": ticker}
        for f in FACTORS:
            row[f] = scores.get(f, float("nan"))
        rows.append(row)
    return pd.DataFrame(rows)


def _obs(rank: int, score: float = 1.0, days_ago: int = 0) -> RankObservation:
    base = date(2026, 5, 17)
    return RankObservation(
        run_date=base - timedelta(days=days_ago),
        rank=rank,
        composite_score=score,
    )


def _history(*ranks) -> list[RankObservation]:
    return [_obs(r, days_ago=i) for i, r in enumerate(ranks)]


# ── Step 1: factors ────────────────────────────────────────────────────────────

class TestFactorStep:
    """Verify pipeline/app/factors.py produces correct factor z-scores."""

    def test_cross_section_zscore_clips_to_2_5(self):
        s = pd.Series([1.0, 2.0, 100.0, -100.0])
        z = cross_section_zscore(s)
        assert z.max() <= 2.5
        assert z.min() >= -2.5

    def test_compute_all_factors_columns_present(self):
        tickers = ["AAPL", "MSFT", "GOOG"]
        prices = _prices_long(tickers, n=300)
        fund = _fund(tickers)
        result = compute_all_factors(prices, fund)
        assert "ticker" in result.columns
        for col in ("momentum", "quality", "value", "growth", "low_volatility", "liquidity"):
            assert col in result.columns
        assert len(result) == 3

    def test_compute_all_factors_empty_fundamentals(self):
        tickers = ["X", "Y"]
        prices = _prices_long(tickers, n=300)
        fund = pd.DataFrame(
            columns=["ticker", "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
                     "revenue_growth", "eps_growth"]
        )
        result = compute_all_factors(prices, fund)
        assert len(result) == 2
        for col in ("quality", "value", "growth"):
            assert result[col].isna().all(), f"{col} should be NaN with empty fundamentals"

    def test_quality_nan_for_null_fundamentals(self):
        fund = pd.DataFrame([{
            "ticker": "EMPTY",
            "roe": float("nan"), "debt_to_equity": float("nan"),
            "pe_ratio": float("nan"), "pb_ratio": float("nan"),
            "revenue_growth": float("nan"), "eps_growth": float("nan"),
        }])
        assert pd.isna(compute_quality(fund)["EMPTY"])
        assert pd.isna(compute_value(fund)["EMPTY"])
        assert pd.isna(compute_growth(fund)["EMPTY"])

    def test_momentum_needs_253_rows(self):
        pivot = _pivot(["A"], n=200)
        assert compute_momentum(pivot).empty


# ── Step 2: ranking ────────────────────────────────────────────────────────────

class TestRankStep:
    """Verify pipeline/app/rank.py produces correct rankings."""

    def test_rank_orders_by_composite_score(self):
        df = _factor_scores(
            BEST={"momentum": 3.0, "quality": 2.0, "value": 1.0,
                  "growth": 1.0, "low_volatility": 1.0},
            WORST={"momentum": -3.0, "quality": -2.0, "value": -1.0,
                   "growth": -1.0, "low_volatility": -1.0},
            MID={"momentum": 0.0, "quality": 0.0, "value": 0.0,
                 "growth": 0.0, "low_volatility": 0.0},
        )
        result = rank_universe(df, "bull_calm", VALID_CONFIG)
        assert result.iloc[0]["ticker"] == "BEST"
        assert result.iloc[-1]["ticker"] == "WORST"

    def test_min_non_null_factors_drops_sparse(self):
        df = _factor_scores(
            FULL={"momentum": 1.0, "quality": 1.0, "value": 1.0,
                  "growth": 1.0, "low_volatility": 1.0},
            SPARSE={"momentum": 1.0, "quality": 1.0},
        )
        result = rank_universe(df, "bull_calm", VALID_CONFIG)
        assert "SPARSE" not in result["ticker"].values
        assert "FULL" in result["ticker"].values

    def test_regime_weights_affect_ordering(self):
        # In bull_calm, momentum weight=0.35 dominates
        df = _factor_scores(
            HIGH_MOM={"momentum": 3.0, "quality": -2.0, "value": 0.0,
                      "growth": 0.0, "low_volatility": 0.0},
            HIGH_QUAL={"momentum": -3.0, "quality": 2.0, "value": 0.0,
                       "growth": 0.0, "low_volatility": 0.0},
        )
        result = rank_universe(df, "bull_calm", VALID_CONFIG)
        assert result.iloc[0]["ticker"] == "HIGH_MOM"

    def test_percentile_between_0_and_1(self):
        df = _factor_scores(
            A={"momentum": 2.0, "quality": 1.0, "value": 0.5,
               "growth": 0.5, "low_volatility": 0.5},
            B={"momentum": 0.0, "quality": 0.0, "value": 0.0,
               "growth": 0.0, "low_volatility": 0.0},
        )
        result = rank_universe(df, "bull_calm", VALID_CONFIG)
        for _, row in result.iterrows():
            assert 0.0 <= row["percentile"] <= 1.0


# ── Step 3: delta engine ───────────────────────────────────────────────────────

class TestDeltaStep:
    """Verify pipeline/app/engine.py produces correct delta decisions."""

    def test_entry_confirmed_after_confirmation_days(self):
        obs = _history(10, 10, 10)
        d = evaluate_ticker(
            "AAPL", obs,
            current_weight=None,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
        )
        assert d.action == "entry"

    def test_entry_not_enough_days_gives_watch(self):
        obs = _history(10, 10)
        d = evaluate_ticker(
            "AAPL", obs,
            current_weight=None,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
        )
        assert d.action == "watch"

    def test_exit_confirmed_after_confirmation_days(self):
        obs = _history(50, 50, 50)
        d = evaluate_ticker(
            "AAPL", obs,
            current_weight=0.05,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
        )
        assert d.action == "exit"

    def test_hold_in_buffer_zone(self):
        obs = _history(30, 30, 30)
        d = evaluate_ticker(
            "AAPL", obs,
            current_weight=0.05,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
        )
        assert d.action == "hold"

    def test_capacity_blocks_new_entry(self):
        obs = _history(5, 5, 5)
        d = evaluate_ticker(
            "NEW", obs,
            current_weight=None,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=True,
        )
        assert d.action == "watch"

    def test_evaluate_all_returns_all_tickers(self):
        universe = {
            "AAPL": _history(5, 5, 5),
            "MSFT": _history(50, 50, 50),
            "GOOG": _history(30, 30, 30),
        }
        current_portfolio = {"MSFT": 0.05, "GOOG": 0.04}
        decisions = evaluate_all(
            universe=universe,
            current_portfolio=current_portfolio,
            entry_rank=25,
            exit_rank=40,
            confirmation_days=3,
            max_positions=30,
        )
        # evaluate_all returns dict[str, DeltaDecision]
        assert set(decisions.keys()) == {"AAPL", "MSFT", "GOOG"}
        assert decisions["AAPL"].action == "entry"
        assert decisions["MSFT"].action == "exit"
        assert decisions["GOOG"].action == "hold"


# ── Step ordering: factors → rank → delta uses consistent data ─────────────────

class TestStepOrdering:
    """Verify that factor scores feed correctly into ranking and delta."""

    def test_factor_scores_feed_rank(self):
        """compute_all_factors output can be passed directly to rank_universe."""
        tickers = ["AAPL", "MSFT", "GOOG"]
        prices = _prices_long(tickers, n=300)
        fund = _fund(tickers)

        factor_df = compute_all_factors(prices, fund)
        # Drop tickers with < min_non_null_factors non-null scores
        result = rank_universe(factor_df, "bull_calm", VALID_CONFIG)

        # At least some tickers should survive the filter
        assert len(result) > 0
        # Ranks should start from 1
        assert result["rank"].min() == 1

    def test_rank_output_feeds_delta(self):
        """Rankings can be converted to RankObservations for delta evaluation."""
        df = _factor_scores(
            AAPL={"momentum": 2.0, "quality": 1.0, "value": 0.5,
                  "growth": 0.5, "low_volatility": 0.5},
            MSFT={"momentum": -1.0, "quality": -0.5, "value": -0.3,
                  "growth": -0.3, "low_volatility": -0.3},
        )
        ranked = rank_universe(df, "bull_calm", VALID_CONFIG)

        # Build history from ranked output (simulate two identical days)
        universe = {}
        for _, row in ranked.iterrows():
            obs = RankObservation(
                run_date=date(2026, 5, 17),
                rank=row["rank"],
                composite_score=row["composite_score"],
            )
            universe[row["ticker"]] = [obs, obs, obs]

        decisions = evaluate_all(
            universe=universe,
            current_portfolio={},
            entry_rank=len(ranked),  # all qualify for entry
            exit_rank=len(ranked) + 5,
            confirmation_days=3,
            max_positions=30,
        )
        assert len(decisions) == len(ranked)
        # All should be entries (current_portfolio empty, all within entry_rank)
        for ticker, d in decisions.items():
            assert d.action == "entry", f"{ticker} expected entry, got {d.action}"


# ── Cold-start TRIM regression ─────────────────────────────────────────────────

class TestColdStartTrimRegression:
    """
    Regression: when the pipeline delta runs before portfolio-builder exists, it uses
    cold_start mode which seeds live positions as {ticker: 0.0}.  With current_weight=0.0
    and actual_weight=2.73%, drift = +2.73% > threshold → spurious sell_trim.

    The fix: drift rebalancing is skipped when current_weight is 0 or None
    (no real portfolio target exists yet).
    """

    def test_cold_start_held_position_is_not_trimmed(self):
        """Held position with current_weight=0.0 (cold-start sentinel) must be HOLD, not TRIM."""
        obs = _history(5, 5, 5)  # rank=5, well inside entry zone
        d = evaluate_ticker(
            "SNDK", obs,
            current_weight=0.0,       # cold-start sentinel: held but no target weight
            actual_weight=0.0273,     # 2.73% at broker
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
            drift_threshold=0.02,
        )
        assert d.action == "hold", (
            f"Expected hold (cold-start, no real target weight), got {d.action}. "
            f"current_weight=0.0 is the sentinel for 'held at broker, no portfolio target yet' — "
            f"drift vs. 0% target must not generate a sell_trim."
        )

    def test_cold_start_held_below_exit_zone_is_not_trimmed(self):
        """Rank #7 with current_weight=0.0 must be HOLD even with actual_weight > drift threshold."""
        obs = _history(7, 7, 7)
        d = evaluate_ticker(
            "WDC", obs,
            current_weight=0.0,
            actual_weight=0.0255,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
            drift_threshold=0.02,
        )
        assert d.action == "hold"

    def test_real_target_weight_does_trigger_trim(self):
        """A genuine positive target weight with overweight actual SHOULD still generate sell_trim."""
        obs = _history(5, 5, 5)
        d = evaluate_ticker(
            "AAPL", obs,
            current_weight=0.03,   # real target: 3%
            actual_weight=0.06,    # overweight: 6%
            entry_rank=25, exit_rank=40, confirmation_days=3,
            portfolio_at_capacity=False,
            drift_threshold=0.02,
        )
        assert d.action == "sell_trim"

    def test_evaluate_all_cold_start_portfolio_no_trim(self):
        """evaluate_all in cold-start mode must not produce sell_trim for held positions."""
        universe = {
            "SNDK": _history(1, 1, 1),
            "WDC":  _history(2, 2, 2),
            "MU":   _history(7, 7, 7),
        }
        cold_start_portfolio = {"SNDK": 0.0, "WDC": 0.0, "MU": 0.0}
        live_weights = {"SNDK": 0.0273, "WDC": 0.0255, "MU": 0.018}
        decisions = evaluate_all(
            universe=universe,
            current_portfolio=cold_start_portfolio,
            entry_rank=25, exit_rank=40, confirmation_days=3,
            max_positions=30,
            actual_weights=live_weights,
            drift_threshold=0.02,
        )
        for ticker in cold_start_portfolio:
            action = decisions[ticker].action
            assert action == "hold", (
                f"{ticker}: cold-start portfolio produced '{action}' — "
                f"expected 'hold' (no real target weight, must not rebalance)"
            )
