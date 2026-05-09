import pytest
from pydantic import ValidationError
from stock_strategy_shared.schemas.strategy import (
    StrategyConfig, FactorWeights, RegimeDetectionConfig, RegimeCondition,
)

VALID_REGIME_DETECTION = {
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
}

VALID_WEIGHTS = {
    "bull_calm":   {"momentum": 0.35, "quality": 0.25, "growth": 0.20, "value": 0.10, "low_volatility": 0.10},
    "bull_stress": {"quality": 0.35, "low_volatility": 0.25, "momentum": 0.20, "value": 0.10, "growth": 0.10},
    "bear_stress": {"low_volatility": 0.35, "quality": 0.30, "value": 0.20, "growth": 0.10, "momentum": 0.05},
    "bear_calm":   {"value": 0.30, "quality": 0.30, "low_volatility": 0.20, "momentum": 0.10, "growth": 0.10},
}


def make_config(**overrides):
    base = {
        "strategy_id": "test_v1",
        "regime_detection": VALID_REGIME_DETECTION,
        "factor_weights": VALID_WEIGHTS,
    }
    base.update(overrides)
    return StrategyConfig(**base)


def test_valid_config_loads():
    cfg = make_config()
    assert cfg.strategy_id == "test_v1"
    assert set(cfg.regime_detection.regimes.keys()) == {"bull_calm", "bull_stress", "bear_stress", "bear_calm"}


def test_weights_must_sum_to_one():
    bad_weights = {**VALID_WEIGHTS, "bull_calm": {"momentum": 0.50, "quality": 0.50, "growth": 0.20, "value": 0.10, "low_volatility": 0.10}}
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_config(factor_weights=bad_weights)


def test_missing_regime_weight_raises():
    weights_missing_regime = {k: v for k, v in VALID_WEIGHTS.items() if k != "bear_calm"}
    with pytest.raises(ValidationError, match="factor_weights missing entries"):
        make_config(factor_weights=weights_missing_regime)


def test_regimes_must_cover_all_four_combinations():
    detection_missing_combo = {**VALID_REGIME_DETECTION, "regimes": {
        "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
        "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
        "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
        # bear_calm missing
    }}
    with pytest.raises(ValidationError, match="missing conditions"):
        make_config(regime_detection=detection_missing_combo)


def test_min_non_null_factors_default():
    cfg = make_config()
    assert cfg.min_non_null_factors == 3


def test_min_non_null_factors_custom():
    cfg = make_config(min_non_null_factors=4)
    assert cfg.min_non_null_factors == 4


def test_universe_config_defaults():
    cfg = make_config()
    assert cfg.universe.min_price == 5.0
    assert cfg.universe.min_avg_dollar_volume_20d == 20_000_000
    assert cfg.universe.etf_ticker == "IWV"
