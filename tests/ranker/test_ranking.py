import pytest
import pandas as pd
import numpy as np
from app.rank import rank_universe, FACTORS
from stock_strategy_shared.schemas.strategy import StrategyConfig

VALID_CONFIG = StrategyConfig(**{
    "strategy_id": "test_v1",
    "min_non_null_factors": 3,
    "regime_detection": {
        "slow_sma": 200, "vol_window": 20, "vol_threshold": 0.20, "confirmation_days": 5,
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


def _scores(**kwargs) -> pd.DataFrame:
    rows = []
    for ticker, scores in kwargs.items():
        row = {"ticker": ticker}
        for f in FACTORS:
            row[f] = scores.get(f, float("nan"))
        rows.append(row)
    return pd.DataFrame(rows)


def test_rank_orders_by_composite_score():
    df = _scores(
        BEST={"momentum": 3.0, "quality": 2.0, "value": 1.0, "growth": 1.0, "low_volatility": 1.0},
        WORST={"momentum": -3.0, "quality": -2.0, "value": -1.0, "growth": -1.0, "low_volatility": -1.0},
        MID={"momentum": 0.0, "quality": 0.0, "value": 0.0, "growth": 0.0, "low_volatility": 0.0},
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    assert result.iloc[0]["ticker"] == "BEST"
    assert result.iloc[-1]["ticker"] == "WORST"


def test_rank_applies_regime_weights():
    # In bull_calm, momentum weight=0.35 dominates
    # Ticker A: high momentum, low quality
    # Ticker B: low momentum, high quality
    df = _scores(
        A={"momentum": 3.0, "quality": -2.0, "value": 0.0, "growth": 0.0, "low_volatility": 0.0},
        B={"momentum": -3.0, "quality": 2.0, "value": 0.0, "growth": 0.0, "low_volatility": 0.0},
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    assert result.iloc[0]["ticker"] == "A"  # momentum-heavy regime favors A

    # In bear_stress, low_volatility weight=0.35 dominates
    result2 = rank_universe(df, "bear_stress", VALID_CONFIG)
    # both have low_volatility=0.0, so quality breaks the tie for B
    assert result2.iloc[0]["ticker"] == "B"


def test_min_non_null_factors_excludes_sparse_tickers():
    # Ticker with only 2 non-null factors (below min of 3) should be dropped entirely
    df = _scores(
        FULL={"momentum": 1.0, "quality": 1.0, "value": 1.0, "growth": 1.0, "low_volatility": 1.0},
        SPARSE={"momentum": 1.0, "quality": 1.0},  # only 2 factors
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    assert "SPARSE" not in result["ticker"].values
    assert "FULL" in result["ticker"].values


def test_percentile_range():
    df = _scores(
        A={"momentum": 2.0, "quality": 1.0, "value": 0.5, "growth": 0.5, "low_volatility": 0.5},
        B={"momentum": 0.0, "quality": 0.0, "value": 0.0, "growth": 0.0, "low_volatility": 0.0},
        C={"momentum": -2.0, "quality": -1.0, "value": -0.5, "growth": -0.5, "low_volatility": -0.5},
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    assert result["percentile"].max() == pytest.approx(1.0)
    assert result["percentile"].min() == pytest.approx(0.0)


def test_unrankable_tickers_excluded_from_output():
    # Ticker with too few factors should be dropped entirely, not appear at the bottom
    df = _scores(
        FULL={"momentum": 1.0, "quality": 1.0, "value": 1.0, "growth": 1.0, "low_volatility": 1.0},
        SPARSE={"momentum": 1.0, "quality": 1.0},  # only 2 factors, below min of 3
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    assert "SPARSE" not in result["ticker"].values
    assert "FULL" in result["ticker"].values
    assert result["composite_score"].notna().all()


def test_percentile_excludes_unrankable():
    # Percentile should be computed only over rankable tickers
    df = _scores(
        A={"momentum": 2.0, "quality": 1.0, "value": 1.0, "growth": 1.0, "low_volatility": 1.0},
        B={"momentum": -2.0, "quality": -1.0, "value": -1.0, "growth": -1.0, "low_volatility": -1.0},
        SPARSE={"momentum": 0.5},  # unrankable
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    assert len(result) == 2
    assert result["percentile"].max() == pytest.approx(1.0)
    assert result["percentile"].min() == pytest.approx(0.0)
