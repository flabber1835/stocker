"""Schema + config tests for the earnings_surprise (PEAD) factor weight.

Default 0 (back-compat), participates in the sum=1 validator, and the live
momentum_rotation_v2 config gives it a real non-zero weight.
"""
import os

import pytest
import yaml
from pydantic import ValidationError

from stock_strategy_shared.schemas.strategy import FactorWeights, StrategyConfig

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_earnings_surprise_defaults_zero():
    w = FactorWeights(momentum=0.19, quality=0.22, value=0.19, growth=0.10,
                      low_volatility=0.13, liquidity=0.11, issuance=0.06)
    assert w.earnings_surprise == 0


def test_earnings_surprise_participates_in_sum_validation():
    # adding the weight without rebalancing must break the sum=1 check
    with pytest.raises(ValidationError):
        FactorWeights(momentum=0.19, quality=0.22, value=0.19, growth=0.10,
                      low_volatility=0.13, liquidity=0.11, issuance=0.06,
                      earnings_surprise=0.20)  # now sums to 1.20


def test_earnings_surprise_weights_validate_when_balanced():
    w = FactorWeights(momentum=0.42, earnings_surprise=0.12, quality=0.20,
                      low_volatility=0.08, value=0.08, liquidity=0.06, growth=0.04)
    assert w.earnings_surprise == 0.12


def test_live_v2_config_has_real_earnings_weight():
    cfg = StrategyConfig(**yaml.safe_load(
        open(os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml"))))
    w = cfg.static_factor_weights
    assert w.earnings_surprise > 0, "v2 must give earnings_surprise a real weight"
    assert w.momentum > w.earnings_surprise  # momentum still dominant
    assert cfg.factor_engine.earnings_drift_window_days == 90


def test_core_config_unaffected_earnings_zero():
    cfg = StrategyConfig(**yaml.safe_load(
        open(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))))
    assert cfg.static_factor_weights.earnings_surprise == 0
