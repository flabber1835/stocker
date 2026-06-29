"""/validate-llm-change: the gate that makes direct LLM edits to the strategy file
safe. A proposal must pass schema + safety AND change only LLM-tunable fields.
"""
import copy
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def client():
    from app import main
    main.app.router.lifespan_context = _noop_lifespan
    return TestClient(main.app)


BASELINE = {
    "strategy_id": "test_valid_v1",
    "regime_detection": {
        "regimes": {
            "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
            "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
            "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
            "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
        },
    },
    "factor_weights": {
        "bull_calm":   {"momentum": 0.35, "quality": 0.25, "value": 0.15, "growth": 0.15, "low_volatility": 0.10},
        "bull_stress": {"momentum": 0.20, "quality": 0.35, "value": 0.15, "growth": 0.10, "low_volatility": 0.20},
        "bear_calm":   {"momentum": 0.20, "quality": 0.30, "value": 0.30, "growth": 0.10, "low_volatility": 0.10},
        "bear_stress": {"momentum": 0.10, "quality": 0.40, "value": 0.15, "growth": 0.05, "low_volatility": 0.30},
    },
    "max_positions": 30,
    "portfolio_builder": {"max_positions": 30, "max_position_weight": 0.10,
                          "max_sector_weight": 0.30, "weighting": "equal_weight",
                          "method": "greedy_score_per_port_vol"},
    "vetter": {"enabled": True, "candidate_count": 50},
    "delta_engine": {"entry_rank": 25, "exit_rank": 40, "confirmation_days": 3},
}


def test_identical_proposal_passes(client):
    r = client.post("/validate-llm-change", json={"baseline": BASELINE, "proposed": copy.deepcopy(BASELINE)})
    assert r.status_code == 200, r.json()
    assert r.json()["valid"] is True
    assert r.json()["changed_protected_fields"] == []


def test_tunable_change_passes(client):
    p = copy.deepcopy(BASELINE)
    p["factor_weights"]["bull_calm"] = {"momentum": 0.45, "quality": 0.25, "value": 0.05,
                                        "growth": 0.15, "low_volatility": 0.10}
    p["vetter"]["candidate_count"] = 80
    r = client.post("/validate-llm-change", json={"baseline": BASELINE, "proposed": p})
    assert r.status_code == 200, r.json()
    assert r.json()["valid"] is True


def test_protected_strategy_id_change_rejected(client):
    p = copy.deepcopy(BASELINE); p["strategy_id"] = "sneaky_v2"
    r = client.post("/validate-llm-change", json={"baseline": BASELINE, "proposed": p})
    assert r.status_code == 422
    assert r.json()["changed_protected_fields"] == ["strategy_id"]


def test_protected_falling_knife_change_rejected(client):
    p = copy.deepcopy(BASELINE)
    p["vetter"]["falling_knife"] = {"backstop_pct": 0.95}   # try to defang the veto
    r = client.post("/validate-llm-change", json={"baseline": BASELINE, "proposed": p})
    assert r.status_code == 422
    assert "vetter.falling_knife.backstop_pct" in r.json()["changed_protected_fields"]


def test_schema_invalid_proposal_rejected(client):
    p = copy.deepcopy(BASELINE)
    p["factor_weights"]["bull_calm"]["momentum"] = 0.99   # weights no longer sum to 1
    r = client.post("/validate-llm-change", json={"baseline": BASELINE, "proposed": p})
    assert r.status_code == 422
    assert r.json()["valid"] is False
    assert r.json()["changed_protected_fields"] == []   # failed on schema, not partition


def test_unsafe_proposal_rejected(client):
    p = copy.deepcopy(BASELINE)
    p["portfolio_builder"]["max_position_weight"] = 0.9   # exceeds hard safety limit
    r = client.post("/validate-llm-change", json={"baseline": BASELINE, "proposed": p})
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_missing_keys_rejected(client):
    r = client.post("/validate-llm-change", json={"proposed": BASELINE})
    assert r.status_code == 422
