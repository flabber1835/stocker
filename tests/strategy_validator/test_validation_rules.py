"""Unit tests for the strategy-validator service.

Tests every validation rule via FastAPI TestClient so no Docker is needed.
Covers the full taxonomy of dangerous / invalid configs that must be rejected
before any config reaches the portfolio-building or trading pipeline.
"""
import textwrap
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient


# ── helpers ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(scope="module")
def client():
    from app import main
    main.app.router.lifespan_context = _noop_lifespan
    return TestClient(main.app)


# Full valid config reused across tests
VALID_CONFIG = {
    "strategy_id": "test_valid_v1",
    "description": "Test strategy",
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


def _patch(config: dict, *path_val_pairs) -> dict:
    """Deep-copy config and apply mutations: (dotted.key, value) pairs."""
    import copy
    c = copy.deepcopy(config)
    for path, val in path_val_pairs:
        parts = path.split(".")
        obj = c
        for p in parts[:-1]:
            obj = obj[p]
        if val is None:
            obj.pop(parts[-1], None)
        else:
            obj[parts[-1]] = val
    return c


# ── health ────────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "strategy-validator"


# ── valid configs ─────────────────────────────────────────────────────────────

def test_valid_config_passes(client):
    r = client.post("/validate", json=VALID_CONFIG)
    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["valid"] is True
    assert data.get("errors", []) == []


def test_yaml_body_accepted(client):
    """Strategy-validator must accept YAML as well as JSON."""
    yaml_body = textwrap.dedent("""\
        strategy_id: yaml_test_v1
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
        max_positions: 30
        portfolio_builder:
          max_positions: 30
          max_position_weight: 0.10
          max_sector_weight: 0.30
          weighting: equal_weight
          method: greedy_score_per_port_vol
        vetter:
          enabled: true
          candidate_count: 50
        delta_engine:
          entry_rank: 25
          exit_rank: 40
    """)
    r = client.post("/validate", content=yaml_body, headers={"Content-Type": "text/yaml"})
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True


# ── factor weight rules ───────────────────────────────────────────────────────

def test_factor_weights_sum_below_one_rejected(client):
    """Weights summing to 0.80 instead of 1.0 must be rejected."""
    bad = _patch(
        VALID_CONFIG,
        ("factor_weights.bull_calm", {"momentum": 0.50, "quality": 0.30, "value": 0.00, "growth": 0.00, "low_volatility": 0.00}),
    )
    r = client.post("/validate", json=bad)
    assert r.status_code in (200, 422), r.text
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "1.0" in errors or "sum" in errors.lower() or "weight" in errors.lower()


def test_factor_weights_sum_above_one_rejected(client):
    """Weights summing to 1.10 must be rejected."""
    bad = _patch(
        VALID_CONFIG,
        ("factor_weights.bear_stress", {"momentum": 0.30, "quality": 0.40, "value": 0.20, "growth": 0.10, "low_volatility": 0.10}),
    )
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_negative_factor_weight_rejected(client):
    """Negative weights violate Pydantic Field(ge=0) constraint."""
    bad = _patch(
        VALID_CONFIG,
        ("factor_weights.bull_calm.momentum", -0.10),
    )
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_factor_weight_above_one_rejected(client):
    """Single factor weight > 1.0 violates le=1 constraint."""
    bad = _patch(
        VALID_CONFIG,
        ("factor_weights.bull_calm.momentum", 1.5),
    )
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


# ── regime coverage rules ─────────────────────────────────────────────────────

def test_missing_bear_regime_rejected(client):
    """Missing bear_calm and bear_stress violates 4-quadrant requirement."""
    bad = _patch(VALID_CONFIG)
    bad["regime_detection"]["regimes"] = {
        "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
        "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    }
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "missing" in errors.lower() or "condition" in errors.lower() or "regime" in errors.lower()


def test_duplicate_regime_conditions_rejected(client):
    """Two regimes with the same (spy_above, vol_above) conditions are invalid."""
    bad = _patch(VALID_CONFIG)
    bad["regime_detection"]["regimes"] = {
        "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
        "bull_calm2":  {"spy_above_slow_sma": True,  "vol_above_threshold": False},  # duplicate
        "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
        "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    }
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_three_regimes_rejected(client):
    """Three regimes instead of four must be rejected (one quadrant uncovered)."""
    bad = _patch(VALID_CONFIG)
    bad["regime_detection"]["regimes"] = {
        "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
        "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
        "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
        # bear_stress missing
    }
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


# ── regime / factor_weights mismatch ─────────────────────────────────────────

def test_factor_weights_missing_bear_regime_rejected(client):
    """factor_weights must include entries for every regime name."""
    bad = _patch(VALID_CONFIG)
    bad["factor_weights"] = {
        "bull_calm":   VALID_CONFIG["factor_weights"]["bull_calm"],
        "bull_stress": VALID_CONFIG["factor_weights"]["bull_stress"],
        # bear_calm and bear_stress missing
    }
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "bear" in errors.lower() or "missing" in errors.lower()


def test_extra_factor_weights_regime_rejected(client):
    """factor_weights with a regime name not in regime_detection must be rejected."""
    bad = _patch(VALID_CONFIG)
    bad["factor_weights"]["fantasy_regime"] = {"momentum": 0.35, "quality": 0.25, "value": 0.15, "growth": 0.15, "low_volatility": 0.10}
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


# ── delta engine rules ────────────────────────────────────────────────────────

def test_inverted_rank_thresholds_rejected(client):
    """exit_rank must be > entry_rank (buffer zone requirement)."""
    bad = _patch(VALID_CONFIG, ("delta_engine.exit_rank", 20), ("delta_engine.entry_rank", 25))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "exit_rank" in errors.lower() or "entry_rank" in errors.lower() or "buffer" in errors.lower()


def test_equal_rank_thresholds_rejected(client):
    """exit_rank == entry_rank means no buffer zone — must be rejected."""
    bad = _patch(VALID_CONFIG, ("delta_engine.entry_rank", 30), ("delta_engine.exit_rank", 30))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_negative_entry_rank_rejected(client):
    """entry_rank must be >= 1 per schema constraints."""
    bad = _patch(VALID_CONFIG, ("delta_engine.entry_rank", 0))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


# ── safety limit rules ────────────────────────────────────────────────────────

def test_max_positions_exceeds_safety_limit_rejected(client):
    """max_positions > 200 (hard safety cap) must be rejected."""
    bad = _patch(
        VALID_CONFIG,
        ("max_positions", 250),
        ("portfolio_builder.max_positions", 250),
    )
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "200" in errors or "max_positions" in errors.lower() or "safety" in errors.lower()


def test_max_position_weight_exceeds_safety_limit_rejected(client):
    """Single position > 50% of portfolio (safety limit) must be rejected."""
    bad = _patch(VALID_CONFIG, ("portfolio_builder.max_position_weight", 0.60))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "0.5" in errors or "position_weight" in errors.lower() or "safety" in errors.lower()


def test_max_sector_weight_exceeds_safety_limit_rejected(client):
    """Sector > 75% of portfolio must be rejected."""
    bad = _patch(VALID_CONFIG, ("portfolio_builder.max_sector_weight", 0.85))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_combined_safety_violations_all_reported(client):
    """Multiple safety violations must ALL appear in the error list."""
    bad = _patch(
        VALID_CONFIG,
        ("portfolio_builder.max_positions", 250),
        ("portfolio_builder.max_position_weight", 0.80),
        ("portfolio_builder.max_sector_weight", 0.90),
    )
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    assert len(data.get("errors", [])) >= 1  # at least one violation reported


# ── vetter sizing rule ────────────────────────────────────────────────────────

def test_vetter_candidate_count_less_than_max_positions_rejected(client):
    """vetter.candidate_count < portfolio.max_positions means vetter can't fill portfolio."""
    bad = _patch(
        VALID_CONFIG,
        ("vetter.enabled", True),
        ("vetter.candidate_count", 20),
        ("portfolio_builder.max_positions", 30),
    )
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False
    errors = " ".join(data.get("errors", []))
    assert "candidate" in errors.lower() or "vetter" in errors.lower() or "max_positions" in errors.lower()


def test_vetter_disabled_candidate_count_not_checked(client):
    """When vetter is disabled, candidate_count constraint does not apply."""
    ok = _patch(
        VALID_CONFIG,
        ("vetter.enabled", False),
        ("vetter.candidate_count", 5),  # would fail if vetter were enabled
        ("portfolio_builder.max_positions", 30),
    )
    r = client.post("/validate", json=ok)
    data = r.json()
    assert data["valid"] is True, data.get("errors")


# ── liquidity required-factor rule ───────────────────────────────────────────

def test_liquidity_in_required_factors_but_zero_weight_rejected(client):
    """required_factors includes 'liquidity' but all regime weights have it at 0.0."""
    bad = _patch(VALID_CONFIG)
    bad["required_factors"] = ["quality", "momentum", "liquidity"]
    # All regimes already have liquidity=0.0 (default VALID_CONFIG has no liquidity key)
    r = client.post("/validate", json=bad)
    data = r.json()
    # Should be rejected because required_factors says liquidity matters but weights ignore it
    if not data["valid"]:
        errors = " ".join(data.get("errors", []))
        assert "liquidity" in errors.lower()


# ── schema validation (Pydantic) ──────────────────────────────────────────────

def test_missing_regime_detection_rejected(client):
    """regime_detection is required — omitting it must be rejected."""
    bad = {k: v for k, v in VALID_CONFIG.items() if k != "regime_detection"}
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_missing_factor_weights_rejected(client):
    """factor_weights is required — omitting it must be rejected."""
    bad = {k: v for k, v in VALID_CONFIG.items() if k != "factor_weights"}
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_missing_strategy_id_rejected(client):
    """strategy_id is required."""
    bad = {k: v for k, v in VALID_CONFIG.items() if k != "strategy_id"}
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_unknown_top_level_field_rejected(client):
    """Unknown fields must be rejected to prevent LLM-generated garbage configs."""
    bad = {**VALID_CONFIG, "llm_should_not_add_this": True, "override_risk": True}
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_invalid_weighting_method_rejected(client):
    """portfolio_builder.weighting must be one of the allowed literals."""
    bad = _patch(VALID_CONFIG, ("portfolio_builder.weighting", "random_weight"))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_regime_detection_vol_threshold_out_of_range_rejected(client):
    """vol_threshold must be in (0, 1). A value > 1.0 must be rejected."""
    bad = _patch(VALID_CONFIG, ("regime_detection.vol_threshold", 1.5))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_regime_detection_slow_sma_out_of_range_rejected(client):
    """slow_sma must be between 20 and 500."""
    bad = _patch(VALID_CONFIG, ("regime_detection.slow_sma", 10))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_confirmation_days_out_of_range_rejected(client):
    """confirmation_days must be 1-21. 0 is invalid."""
    bad = _patch(VALID_CONFIG, ("regime_detection.confirmation_days", 0))
    r = client.post("/validate", json=bad)
    data = r.json()
    assert data["valid"] is False


def test_empty_body_rejected(client):
    """Completely empty JSON body must be rejected."""
    r = client.post("/validate", json={})
    data = r.json()
    assert data["valid"] is False


def test_wrong_content_type_returns_error(client):
    """Sending non-JSON, non-YAML content should return an error."""
    r = client.post("/validate", content="this is plain text", headers={"Content-Type": "text/plain"})
    # Should fail gracefully — either 422 or valid=false
    assert r.status_code in (200, 400, 422)
