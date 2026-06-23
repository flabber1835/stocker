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


def test_regime_weighting_enabled_defaults_true():
    cfg = make_config()
    assert cfg.regime_weighting_enabled is True
    # Resolver returns the per-regime vector when rotation is on.
    assert cfg.effective_factor_weights("bull_calm").momentum == 0.35
    assert cfg.effective_factor_weights("bear_stress").low_volatility == 0.35


def test_static_weights_required_when_regime_disabled():
    with pytest.raises(ValidationError, match="static_factor_weights is not set"):
        make_config(regime_weighting_enabled=False)


def test_static_weights_used_in_all_regimes_when_disabled():
    cfg = make_config(
        regime_weighting_enabled=False,
        static_factor_weights={"momentum": 0.16, "quality": 0.24, "value": 0.18,
                               "growth": 0.11, "low_volatility": 0.21, "liquidity": 0.10},
    )
    assert cfg.regime_weighting_enabled is False
    for regime in ("bull_calm", "bull_stress", "bear_stress", "bear_calm"):
        w = cfg.effective_factor_weights(regime)
        assert w.quality == 0.24 and w.momentum == 0.16


def test_static_weights_must_sum_to_one():
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_config(
            regime_weighting_enabled=False,
            static_factor_weights={"momentum": 0.50, "quality": 0.50, "value": 0.18,
                                   "growth": 0.11, "low_volatility": 0.21, "liquidity": 0.10},
        )


def test_static_weights_liquidity_required_factor_enforced():
    """When liquidity is required but the STATIC vector has 0 liquidity, reject."""
    with pytest.raises(ValidationError, match="liquidity weight 0.0"):
        make_config(
            required_factors=["liquidity"],
            regime_weighting_enabled=False,
            static_factor_weights={"momentum": 0.20, "quality": 0.25, "value": 0.20,
                                   "growth": 0.15, "low_volatility": 0.20, "liquidity": 0.0},
        )


def test_issuance_factor_weight_optional_and_summed():
    """The optional issuance weight defaults to 0 (back-compat) and is included in
    the sum-to-1 check when set."""
    fw = FactorWeights(momentum=0.2, quality=0.2, value=0.2, growth=0.2, low_volatility=0.2)
    assert fw.issuance == 0.0  # default, existing 6-factor configs still sum to 1.0
    # Explicit issuance weight must be counted in the sum.
    ok = FactorWeights(momentum=0.2, quality=0.2, value=0.2, growth=0.15,
                       low_volatility=0.15, liquidity=0.05, issuance=0.05)
    assert ok.issuance == 0.05
    with pytest.raises(ValidationError, match="sum to 1.0"):
        FactorWeights(momentum=0.2, quality=0.2, value=0.2, growth=0.2,
                      low_volatility=0.2, issuance=0.1)  # sums to 1.1


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


def test_vetter_config_in_strategy_config():
    cfg = make_config(vetter={"candidate_count": 75})
    assert cfg.vetter.candidate_count == 75


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
    # Sector neutralization of value/quality is ON by default; gross-profitability
    # quality stays OFF (opt-in pending backtest validation).
    assert cfg.industry_neutral_factors == ["value", "quality"]
    assert cfg.min_sector_group_size == 10
    assert cfg.quality_use_gross_profitability is False


def test_industry_neutral_factors_accepts_value_quality_growth():
    cfg = FactorEngineConfig(industry_neutral_factors=["value", "quality", "growth"])
    assert set(cfg.industry_neutral_factors) == {"value", "quality", "growth"}


@pytest.mark.parametrize("bad", ["momentum", "low_volatility", "liquidity"])
def test_industry_neutral_factors_rejects_momentum_lowvol_liquidity(bad):
    """The asymmetry rule is enforced at the schema: momentum is partly industry
    momentum (Moskowitz-Grinblatt), so neutralizing it deletes signal and must be
    rejected — likewise low_volatility/liquidity."""
    with pytest.raises(ValidationError):
        FactorEngineConfig(industry_neutral_factors=["value", bad])


def test_industry_neutral_factors_rejects_unknown():
    with pytest.raises(ValidationError):
        FactorEngineConfig(industry_neutral_factors=["nonsense"])


def test_min_sector_group_size_bounds():
    with pytest.raises(ValidationError):
        FactorEngineConfig(min_sector_group_size=1)  # must be >= 2
    with pytest.raises(ValidationError):
        FactorEngineConfig(min_sector_group_size=501)  # must be <= 500


def test_quality_gross_profitability_flag_settable():
    cfg = FactorEngineConfig(quality_use_gross_profitability=True)
    assert cfg.quality_use_gross_profitability is True


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
    assert cfg.risk_horizon_days == 90
    assert cfg.system_prompt_file is None
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
    cfg = make_config(vetter={"enabled": False})
    assert cfg.vetter.enabled is False


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


# ── audit P2: delta_engine.max_positions must cover portfolio_builder ────────────

def test_delta_cap_below_builder_rejected():
    with pytest.raises(ValidationError) as ei:
        make_config(
            portfolio_builder={"max_positions": 35, "max_position_weight": 0.08},
            delta_engine={"max_positions": 30},
        )
    assert "delta_engine.max_positions" in str(ei.value)


def test_delta_cap_equal_to_builder_ok():
    cfg = make_config(
        portfolio_builder={"max_positions": 35, "max_position_weight": 0.08},
        delta_engine={"max_positions": 35},
    )
    assert cfg.delta_engine.max_positions == cfg.portfolio_builder.max_positions == 35


def test_delta_cap_above_builder_ok():
    cfg = make_config(
        portfolio_builder={"max_positions": 30, "max_position_weight": 0.10},
        delta_engine={"max_positions": 35},
    )
    assert cfg.delta_engine.max_positions == 35
    assert cfg.portfolio_builder.max_positions == 30
