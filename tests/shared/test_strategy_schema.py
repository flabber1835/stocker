import pytest
from pydantic import ValidationError
from stock_strategy_shared.schemas.strategy import (
    StrategyConfig, FactorWeights, RegimeDetectionConfig, RegimeCondition, VetterConfig,
    FactorEngineConfig, IntradayConfig, UniverseConfig,
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
    assert cfg.universe.source == "av_listing"


# ── VetterConfig ──────────────────────────────────────────────────────────────

def test_vetter_config_defaults():
    cfg = VetterConfig()
    assert cfg.candidate_count == 50
    assert cfg.conviction_max_boost == 0.25
    assert cfg.conviction_boosts == {"high": 0.25, "medium": 0.12, "low": 0.05, "none": 0.0}


def test_vetter_config_custom_boosts():
    cfg = VetterConfig(conviction_boosts={"high": 0.20, "medium": 0.10, "low": 0.03, "none": 0.0})
    assert cfg.conviction_boosts["high"] == 0.20


def test_vetter_config_unknown_boost_key_raises():
    with pytest.raises(ValidationError, match="unknown keys"):
        VetterConfig(conviction_boosts={"high": 0.20, "extreme": 0.50, "none": 0.0})


def test_vetter_config_boost_value_out_of_range_raises():
    with pytest.raises(ValidationError, match="outside \\[0, 1\\]"):
        VetterConfig(conviction_boosts={"high": 1.5, "medium": 0.10, "low": 0.05, "none": 0.0})


def test_vetter_config_in_strategy_config():
    cfg = make_config(vetter={"candidate_count": 75, "conviction_max_boost": 0.30,
                              "conviction_boosts": {"high": 0.30, "medium": 0.15, "low": 0.05, "none": 0.0}})
    assert cfg.vetter.candidate_count == 75
    assert cfg.vetter.conviction_max_boost == 0.30


def test_vetter_config_max_boost_range():
    with pytest.raises(ValidationError):
        VetterConfig(conviction_max_boost=1.5)
    with pytest.raises(ValidationError):
        VetterConfig(conviction_max_boost=-0.1)


# ── FactorEngineConfig ────────────────────────────────────────────────────────

def test_factor_engine_defaults():
    cfg = FactorEngineConfig()
    assert cfg.zscore_clip == 2.5
    assert cfg.momentum_short_window == 21
    assert cfg.momentum_long_window == 252
    assert cfg.volatility_window == 252
    assert cfg.liquidity_window == 20
    assert cfg.pe_pb_cap == 50.0
    assert cfg.spy_price_lookback_days == 600


def test_factor_engine_custom_values():
    cfg = FactorEngineConfig(
        zscore_clip=3.0,
        momentum_short_window=5,
        momentum_long_window=126,
        pe_pb_cap=100.0,
    )
    assert cfg.zscore_clip == 3.0
    assert cfg.momentum_long_window == 126
    assert cfg.pe_pb_cap == 100.0


def test_factor_engine_in_strategy_config():
    cfg = make_config(factor_engine={"zscore_clip": 3.0, "pe_pb_cap": 30.0})
    assert cfg.factor_engine.zscore_clip == 3.0
    assert cfg.factor_engine.pe_pb_cap == 30.0


def test_factor_engine_zscore_clip_bounds():
    with pytest.raises(ValidationError):
        FactorEngineConfig(zscore_clip=0)  # must be > 0
    with pytest.raises(ValidationError):
        FactorEngineConfig(zscore_clip=11)  # must be <= 10


# ── VetterConfig new fields ───────────────────────────────────────────────────

def test_vetter_new_field_defaults():
    cfg = VetterConfig()
    assert cfg.enabled is True
    assert cfg.holding_period_days == 30
    assert cfg.max_searches_per_ticker == 3
    assert cfg.news_lookback_days == 7
    assert cfg.max_articles_per_ticker == 4
    assert cfg.earnings_horizon_days == 90
    assert cfg.strictness == "moderate"


def test_vetter_strictness_values():
    for level in ("strict", "moderate", "permissive"):
        cfg = VetterConfig(strictness=level)
        assert cfg.strictness == level


def test_vetter_strictness_invalid_raises():
    with pytest.raises(ValidationError):
        VetterConfig(strictness="extreme")


def test_vetter_disabled_flag():
    cfg = make_config(vetter={"enabled": False, "conviction_boosts": {"high": 0.25, "medium": 0.12, "low": 0.05, "none": 0.0}})
    assert cfg.vetter.enabled is False


# ── UniverseConfig new fields ─────────────────────────────────────────────────

def test_universe_exclusion_defaults():
    cfg = UniverseConfig()
    assert "ETF" in cfg.exclude_asset_classes
    assert "Future" in cfg.exclude_asset_classes
    assert any("iShares" in p for p in cfg.exclude_name_patterns)


def test_universe_custom_exclusions():
    cfg = UniverseConfig(
        exclude_asset_classes=["ETF"],
        exclude_name_patterns=["ProShares", "Invesco"],
    )
    assert cfg.exclude_asset_classes == ["ETF"]
    assert cfg.exclude_name_patterns == ["ProShares", "Invesco"]


# ── IntradayConfig ────────────────────────────────────────────────────────────

def test_intraday_defaults():
    cfg = IntradayConfig()
    assert cfg.enabled is False
    assert cfg.trim_winners_enabled is False
    assert cfg.trim_winner_threshold_pct == 10.0
    assert cfg.trim_winner_partial_pct == 25.0
    assert cfg.risk_event_action == "reduce"
    assert cfg.benchmark_ticker == "SPY"


def test_intraday_risk_event_action_values():
    for action in ("cut", "reduce", "hold"):
        cfg = IntradayConfig(risk_event_action=action)
        assert cfg.risk_event_action == action


def test_intraday_invalid_action_raises():
    with pytest.raises(ValidationError):
        IntradayConfig(risk_event_action="ignore")


def test_intraday_in_strategy_config():
    cfg = make_config(intraday={"enabled": True, "trim_winners_enabled": True, "trim_winner_threshold_pct": 8.0})
    assert cfg.intraday.enabled is True
    assert cfg.intraday.trim_winner_threshold_pct == 8.0
