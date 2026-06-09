"""Schema + config tests for the speculative-style factors.

Backwards-compat guarantee: the four new factors default to weight 0, so existing
strategies (and quality_core_v1.yaml) are unaffected and still validate.
"""
import os

import pytest
import yaml
from pydantic import ValidationError

from stock_strategy_shared.schemas.strategy import FactorWeights, StrategyConfig

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_new_factors_default_zero():
    # A "classic" weight set that omits the new factors must still validate (they
    # default to 0) — this is what keeps quality_core_v1 working unchanged.
    w = FactorWeights(momentum=0.19, quality=0.22, value=0.19, growth=0.10,
                      low_volatility=0.13, liquidity=0.11, issuance=0.06)
    assert w.small_cap == 0 and w.volume_surge == 0 and w.near_high == 0 and w.high_volatility == 0


def test_speculative_weights_validate():
    w = FactorWeights(momentum=0.30, growth=0.20, liquidity=0.10, quality=0, value=0,
                      low_volatility=0, small_cap=0.10, volume_surge=0.10,
                      near_high=0.10, high_volatility=0.10)
    assert abs(sum([w.momentum, w.growth, w.liquidity, w.small_cap, w.volume_surge,
                    w.near_high, w.high_volatility]) - 1.0) < 1e-9


def test_sum_validation_includes_new_factors():
    # adding a new-factor weight without rebalancing must break the sum=1 check
    with pytest.raises(ValidationError):
        FactorWeights(momentum=0.19, quality=0.22, value=0.19, growth=0.10,
                      low_volatility=0.13, liquidity=0.11, issuance=0.06,
                      small_cap=0.20)   # now sums to 1.20


def test_both_strategy_configs_load():
    for fname in ("quality_core_v1.yaml", "speculative_growth_v1.yaml"):
        cfg = StrategyConfig(**yaml.safe_load(open(os.path.join(ROOT, "strategies", fname))))
        assert cfg.strategy_id


def test_core_config_unaffected_new_factors_zero():
    cfg = StrategyConfig(**yaml.safe_load(open(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))))
    w = cfg.static_factor_weights
    assert w.small_cap == 0 and w.volume_surge == 0 and w.near_high == 0 and w.high_volatility == 0
    assert cfg.factor_engine.momentum_method == "residual_riskadj"  # core unchanged


def test_speculative_config_has_expected_shape():
    cfg = StrategyConfig(**yaml.safe_load(open(os.path.join(ROOT, "strategies", "speculative_growth_v1.yaml"))))
    assert cfg.factor_engine.momentum_method == "raw"
    w = cfg.static_factor_weights
    assert w.quality == 0 and w.value == 0 and w.low_volatility == 0
    assert w.high_volatility > 0 and w.small_cap > 0
    assert "quality" not in cfg.required_factors and "value" not in cfg.required_factors
