"""Live integration tests for the strategy-validator service (port 8005).

These validate the running Docker container accepts good configs and rejects
bad ones. The validator is stateless so all tests are safe to run in parallel.
"""
import textwrap

import pytest
import requests

BASE = "http://localhost:8005"

VALID_CONFIG = {
    "strategy_id": "integ_test_v1",
    "description": "Integration test strategy",
    "regime_detection": {
        "slow_sma": 200,
        "vol_window": 20,
        "vol_threshold": 0.20,
        "confirmation_days": 5,
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
    "portfolio_builder": {
        "max_positions": 30,
        "max_position_weight": 0.10,
        "max_sector_weight": 0.30,
        "weighting": "equal_weight",
        "method": "greedy_score_per_port_vol",
    },
    "vetter": {"enabled": True, "candidate_count": 50},
    "delta_engine": {"entry_rank": 25, "exit_rank": 40, "confirmation_days": 3},
}


def _up():
    try:
        return requests.get(f"{BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Strategy-validator not reachable on :8005")


def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["service"] == "strategy-validator"


def test_valid_config_accepted():
    r = requests.post(f"{BASE}/validate", json=VALID_CONFIG)
    assert r.status_code == 200
    d = r.json()
    assert d["valid"] is True
    assert d["strategy_id"] == "integ_test_v1"


def test_yaml_body_accepted():
    yaml_body = textwrap.dedent("""\
        strategy_id: yaml_integ_v1
        regime_detection:
          regimes:
            bull_calm:   {spy_above_slow_sma: true,  vol_above_threshold: false}
            bull_stress: {spy_above_slow_sma: true,  vol_above_threshold: true}
            bear_calm:   {spy_above_slow_sma: false, vol_above_threshold: false}
            bear_stress: {spy_above_slow_sma: false, vol_above_threshold: true}
        factor_weights:
          bull_calm:   {momentum: 0.35, quality: 0.25, value: 0.15, growth: 0.15, low_volatility: 0.10}
          bull_stress: {momentum: 0.20, quality: 0.35, value: 0.15, growth: 0.10, low_volatility: 0.20}
          bear_calm:   {momentum: 0.20, quality: 0.30, value: 0.30, growth: 0.10, low_volatility: 0.10}
          bear_stress: {momentum: 0.10, quality: 0.40, value: 0.15, growth: 0.05, low_volatility: 0.30}
        max_positions: 20
        portfolio_builder:
          max_positions: 20
          max_position_weight: 0.15
          max_sector_weight: 0.40
    """)
    r = requests.post(f"{BASE}/validate",
                      data=yaml_body.encode(),
                      headers={"Content-Type": "application/yaml"})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_unsafe_max_positions_rejected():
    bad = dict(VALID_CONFIG)
    bad["max_positions"] = 250
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    d = r.json()
    assert d["valid"] is False
    assert any("max_positions" in e or "200" in e for e in d.get("errors", []))


def test_unsafe_position_weight_rejected():
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["portfolio_builder"]["max_position_weight"] = 0.75
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_unsafe_sector_weight_rejected():
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["portfolio_builder"]["max_sector_weight"] = 0.90
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_weights_not_summing_to_one_rejected():
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["factor_weights"]["bull_calm"]["momentum"] = 0.99  # sum > 1
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_missing_regime_in_factor_weights_rejected():
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    del bad["factor_weights"]["bear_stress"]
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_extra_regime_in_factor_weights_rejected():
    """factor_weights key that doesn't match any regime_detection regime must be rejected."""
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["factor_weights"]["phantom_regime"] = {
        "momentum": 0.35, "quality": 0.25, "value": 0.15, "growth": 0.15, "low_volatility": 0.10
    }
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_inverted_entry_exit_rank_rejected():
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["delta_engine"]["entry_rank"] = 50
    bad["delta_engine"]["exit_rank"] = 30  # exit < entry — no buffer zone
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_missing_regime_combination_rejected():
    """If only 3 of 4 regime combinations are covered, must be rejected."""
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    del bad["regime_detection"]["regimes"]["bear_calm"]
    del bad["factor_weights"]["bear_calm"]
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_unknown_field_rejected():
    """LLM-injected unknown fields must be rejected, not silently ignored."""
    bad = {**VALID_CONFIG, "override_risk_limits": True, "execute_live": True}
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_empty_body_rejected():
    r = requests.post(f"{BASE}/validate", json={})
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_vetter_candidate_count_below_max_positions_rejected():
    """vetter.candidate_count must be >= portfolio_builder.max_positions."""
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["portfolio_builder"]["max_positions"] = 60
    bad["vetter"]["candidate_count"] = 30  # less than max_positions
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False


def test_invalid_weighting_method_rejected():
    import copy
    bad = copy.deepcopy(VALID_CONFIG)
    bad["portfolio_builder"]["weighting"] = "martingale_weight"
    r = requests.post(f"{BASE}/validate", json=bad)
    assert r.status_code == 422
    assert r.json()["valid"] is False
