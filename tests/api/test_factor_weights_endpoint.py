"""/strategy/factor-weights exposes the active strategy's weights so the detail card
can annotate every generic-engine factor. regime rotation off → static vector;
missing file → degrades to weights:null (annotation simply absent, never an error).
"""
import os

import pytest

from app import main

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
V2 = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")


@pytest.mark.asyncio
async def test_static_weights_returned_for_regime_off(monkeypatch):
    monkeypatch.setattr(main, "STRATEGY_CONFIG_PATH", V2)
    res = await main.get_factor_weights()
    assert res["regime_weighting_enabled"] is False
    w = res["weights"]
    # all generic-engine factors present (incl. dormant ones at 0)
    for f in ("momentum", "quality", "value", "growth", "low_volatility", "liquidity",
              "earnings_surprise", "near_high", "issuance", "small_cap",
              "volume_surge", "high_volatility"):
        assert f in w, f
    # W29 applied reweight: near_high zeroed, weight moved to low_volatility.
    assert w["momentum"] == 0.36 and w["near_high"] == 0.0
    assert w["low_volatility"] == 0.14
    assert w["issuance"] == 0.0 and w["small_cap"] == 0.0   # dormant
    # registry-ordered (key,label) list drives the dashboard chips generically
    from stock_strategy_shared.factor_registry import FACTOR_NAMES, FACTOR_LABELS
    factors = res["factors"]
    assert [f["key"] for f in factors] == list(FACTOR_NAMES)
    assert all(f["label"] == FACTOR_LABELS[f["key"]] for f in factors)


@pytest.mark.asyncio
async def test_missing_file_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(main, "STRATEGY_CONFIG_PATH", "/no/such/strategy.yaml")
    res = await main.get_factor_weights()
    assert res["weights"] is None
    assert res["strategy_id"] is None
