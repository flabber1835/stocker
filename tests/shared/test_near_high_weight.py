"""near_high enabled in the live momentum_rotation_v2 config.

near_high (proximity to trailing high — the 52-week-high effect, George & Hwang
2004) was previously an optional factor at weight 0 (speculative sleeve only). It's
now a real scoring factor in momentum_rotation_v2, funded FROM momentum (they are
highly correlated, so net trend exposure is ~unchanged) at a small weight.
quality_core_v1 must be unaffected (near_high stays 0).
"""
import os
import yaml

from stock_strategy_shared.schemas.strategy import StrategyConfig

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_v2_config_enables_near_high_funded_from_momentum():
    cfg = StrategyConfig(**yaml.safe_load(
        open(os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml"))))
    w = cfg.static_factor_weights
    assert w.near_high == 0.06, "near_high must carry a real small weight in v2"
    assert w.momentum == 0.36, "momentum trimmed to fund near_high"
    # net trend slice (lagged momentum + fresh near_high) preserved at the old 0.42
    assert round(w.momentum + w.near_high, 6) == 0.42
    assert w.momentum > w.near_high  # lagged momentum still dominant within the trend family


def test_core_config_unaffected_near_high_zero():
    cfg = StrategyConfig(**yaml.safe_load(
        open(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))))
    assert cfg.static_factor_weights.near_high == 0
