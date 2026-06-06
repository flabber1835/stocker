import pytest
import pandas as pd
import numpy as np
from app.rank import rank_universe, FACTORS
from stock_strategy_shared.schemas.strategy import StrategyConfig, FactorWeights

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


def test_static_weights_ignore_regime_when_rotation_disabled():
    """With regime_weighting_enabled=False, the SAME static vector scores every
    regime — so the ranking is identical regardless of the regime argument."""
    cfg = VALID_CONFIG.model_copy(update={
        "regime_weighting_enabled": False,
        "static_factor_weights": FactorWeights(
            momentum=0.35, quality=0.25, growth=0.20, value=0.10, low_volatility=0.10,
        ),
    })
    df = _scores(
        A={"momentum": 3.0, "quality": -2.0, "value": 0.0, "growth": 0.0, "low_volatility": 0.0},
        B={"momentum": -3.0, "quality": 2.0, "value": 0.0, "growth": 0.0, "low_volatility": 0.0},
    )
    bull = rank_universe(df, "bull_calm", cfg)
    bear = rank_universe(df, "bear_stress", cfg)
    # Momentum-heavy static vector favors A in BOTH regimes (rotation is off), and
    # the composite scores are identical across the two regime calls.
    assert bull.iloc[0]["ticker"] == "A"
    assert bear.iloc[0]["ticker"] == "A"
    bull_scores = dict(zip(bull["ticker"], bull["composite_score"]))
    bear_scores = dict(zip(bear["ticker"], bear["composite_score"]))
    assert bull_scores == pytest.approx(bear_scores)


def test_effective_factor_weights_resolver():
    """The resolver returns per-regime vectors when enabled, the static vector when not."""
    assert VALID_CONFIG.effective_factor_weights("bull_calm").momentum == 0.35
    assert VALID_CONFIG.effective_factor_weights("bear_stress").low_volatility == 0.35
    static_cfg = VALID_CONFIG.model_copy(update={
        "regime_weighting_enabled": False,
        "static_factor_weights": FactorWeights(
            momentum=0.20, quality=0.20, growth=0.20, value=0.20, low_volatility=0.20,
        ),
    })
    # Same vector regardless of which regime is asked for.
    for regime in ("bull_calm", "bull_stress", "bear_stress", "bear_calm"):
        w = static_cfg.effective_factor_weights(regime)
        assert w.momentum == 0.20 and w.low_volatility == 0.20


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


def test_weight_renormalization_with_missing_factor():
    """
    A ticker missing one non-required factor should still be ranked but its effective
    weights must sum to 1.0 (weight re-normalization). The composite score should differ
    from a fully-covered ticker with identical values on shared factors.
    """
    df = _scores(
        FULL={"momentum": 1.0, "quality": 1.0, "value": 1.0, "growth": 1.0, "low_volatility": 1.0},
        PARTIAL={"momentum": 1.0, "quality": 1.0, "value": float("nan"), "growth": 1.0, "low_volatility": 1.0},
    )
    result = rank_universe(df, "bull_calm", VALID_CONFIG)
    # Both should be ranked — PARTIAL satisfies min_non_null_factors=3
    assert "FULL" in result["ticker"].values
    assert "PARTIAL" in result["ticker"].values
    # All composite scores must be finite
    assert result["composite_score"].notna().all()


def test_weight_renormalization_composite_is_weighted_sum():
    """
    For a ticker with one null factor, the composite score must equal the weighted sum
    of available factors, re-normalized so available weights sum to 1.
    """
    config_w = VALID_CONFIG  # bull_calm: momentum=0.35, quality=0.25, growth=0.20, value=0.10, low_vol=0.10
    df = _scores(
        TICKER={"momentum": 2.0, "quality": 1.0, "value": float("nan"), "growth": 0.5, "low_volatility": -0.5},
    )
    result = rank_universe(df, "bull_calm", config_w)
    row = result[result["ticker"] == "TICKER"].iloc[0]

    weights = {"momentum": 0.35, "quality": 0.25, "growth": 0.20, "low_volatility": 0.10}
    w_sum = sum(weights.values())  # 0.90
    expected = sum((w / w_sum) * {"momentum": 2.0, "quality": 1.0, "growth": 0.5, "low_volatility": -0.5}[f]
                   for f, w in weights.items())
    assert abs(row["composite_score"] - expected) < 1e-6


def test_required_factors_excludes_missing():
    # Ticker missing a required factor should be dropped even if it has enough non-null count
    config_with_required = StrategyConfig(**{
        "strategy_id": "test_required",
        "min_non_null_factors": 3,
        "required_factors": ["quality"],
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
    df = _scores(
        # Has quality — should rank
        WITH_QUALITY={"momentum": 1.0, "quality": 0.5, "value": 0.5, "growth": 0.5, "low_volatility": 0.5},
        # Missing quality but has 4 other factors — must be excluded
        NO_QUALITY={"momentum": 2.0, "value": 1.0, "growth": 1.0, "low_volatility": 1.0},
    )
    result = rank_universe(df, "bull_calm", config_with_required)
    assert "NO_QUALITY" not in result["ticker"].values
    assert "WITH_QUALITY" in result["ticker"].values
