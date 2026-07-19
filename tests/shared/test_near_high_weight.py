"""near_high history in the live momentum_rotation_v2 config.

near_high (proximity to trailing high — the 52-week-high effect, George & Hwang
2004) was introduced as a real scoring factor funded FROM momentum (0.06, momentum
0.42→0.36). The W29 evaluator review then found it NEGATIVE-IC over the live window
and the paired reweight (human-approved via one-click Apply, 2026-07-18, config
977b71415a133c72) zeroed it and moved the weight to low_volatility (0.08→0.14).
This test pins the APPLIED state so the repo mirror and the live config can't
silently drift apart. quality_core_v1 must be unaffected (near_high stays 0).
"""
import os
import yaml

from stock_strategy_shared.schemas.strategy import StrategyConfig

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_v2_config_reflects_w29_applied_reweight():
    cfg = StrategyConfig(**yaml.safe_load(
        open(os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml"))))
    w = cfg.static_factor_weights
    assert w.near_high == 0.0, "W29 reweight zeroed near_high (negative IC live)"
    assert w.low_volatility == 0.14, "freed weight moved to low_volatility"
    assert w.momentum == 0.36, "momentum untouched by the W29 pair"
    weights = w.model_dump(exclude_none=True)
    assert round(sum(weights.values()), 6) == 1.0


def test_core_config_unaffected_near_high_zero():
    cfg = StrategyConfig(**yaml.safe_load(
        open(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))))
    assert cfg.static_factor_weights.near_high == 0
