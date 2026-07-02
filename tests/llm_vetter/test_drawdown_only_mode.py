"""Tests for the vetter's drawdown-only mode (VETTER_LLM_ENABLED=false).

In this mode the vetter skips all LLM/Tavily/AV-news work and every candidate
defaults to keep; the deterministic falling-knife backstop is the only entry
block. These tests verify:
  - the env flag parser (_env_bool)
  - that a neutral "keep" result fed through the live backstop rule still
    force-excludes a severe-drawdown ENTRY (so drawdown remains the sole block)
    and never touches a held position.
"""
import importlib
import os


def _import_vetter():
    import app.main as vetter_main
    return importlib.reload(vetter_main)


def test_env_bool_parsing(monkeypatch):
    monkeypatch.delenv("VETTER_LLM_ENABLED", raising=False)
    m = _import_vetter()
    assert m._env_bool("VETTER_LLM_ENABLED", True) is True   # unset → default
    for v in ("false", "0", "no", "off", "FALSE", " False "):
        monkeypatch.setenv("VETTER_LLM_ENABLED", v)
        assert m._env_bool("VETTER_LLM_ENABLED", True) is False
    for v in ("true", "1", "yes", "on"):
        monkeypatch.setenv("VETTER_LLM_ENABLED", v)
        assert m._env_bool("VETTER_LLM_ENABLED", True) is True


def test_default_keeps_llm_enabled(monkeypatch):
    monkeypatch.delenv("VETTER_LLM_ENABLED", raising=False)
    m = _import_vetter()
    assert m.VETTER_LLM_ENABLED is True


def test_flag_disables_llm(monkeypatch):
    monkeypatch.setenv("VETTER_LLM_ENABLED", "false")
    m = _import_vetter()
    assert m.VETTER_LLM_ENABLED is False


# ── drawdown-only still blocks falling knives via the backstop ──────────────────
# The neutral keep result produced in drawdown-only mode, fed through the same
# backstop condition used in _do_vet.

def _neutral_keep(ticker="AMD"):
    return {"ticker": ticker, "exclude": False, "risk_type": "none",
            "reason": "LLM vetting disabled (drawdown-only mode)."}


def _apply_backstop(result, dd, held, threshold=0.25):
    """Mirror of the override condition in main._do_vet."""
    if threshold > 0 and dd is not None and dd <= -threshold and not held and not result.get("exclude"):
        result = {**result, "exclude": True, "risk_type": "drawdown"}
    return result


def test_drawdown_only_entry_still_blocked_by_backstop():
    out = _apply_backstop(_neutral_keep(), dd=-0.30, held=False)
    assert out["exclude"] is True
    assert out["risk_type"] == "drawdown"


def test_drawdown_only_mild_pullback_kept():
    out = _apply_backstop(_neutral_keep(), dd=-0.10, held=False)
    assert out["exclude"] is False


def test_drawdown_only_held_position_never_excluded():
    out = _apply_backstop(_neutral_keep(), dd=-0.50, held=True)
    assert out["exclude"] is False


# ── vetter.mode (strategy-YAML) × VETTER_LLM_ENABLED (env) resolution ───────────
# Architecture decision: mode defaults to drawdown_only; the LLM runs ONLY when
# BOTH the YAML mode is 'llm' AND the env gate allows it. Either alone forces
# drawdown-only, so a deploy-level kill switch survives the config-driven mode.

class _FakeStrategy:
    def __init__(self, mode):
        from types import SimpleNamespace
        self.vetter = SimpleNamespace(mode=mode)


def test_llm_active_requires_both_gates(monkeypatch):
    monkeypatch.setenv("VETTER_LLM_ENABLED", "true")
    m = _import_vetter()
    m.strategy = _FakeStrategy("llm")
    assert m._llm_active() is True
    m.strategy = _FakeStrategy("drawdown_only")
    assert m._llm_active() is False          # YAML alone forces drawdown-only


def test_env_gate_overrides_yaml_llm_mode(monkeypatch):
    monkeypatch.setenv("VETTER_LLM_ENABLED", "false")
    m = _import_vetter()
    m.strategy = _FakeStrategy("llm")
    assert m._llm_active() is False          # env kill switch wins


def test_no_strategy_loaded_defers_to_env(monkeypatch):
    monkeypatch.setenv("VETTER_LLM_ENABLED", "true")
    m = _import_vetter()
    m.strategy = None
    assert m._llm_active() is True           # pre-load fallback = old behavior


def test_schema_mode_defaults_to_drawdown_only():
    from stock_strategy_shared.schemas.strategy import VetterConfig
    assert VetterConfig().mode == "drawdown_only"
    assert VetterConfig(mode="llm").mode == "llm"
    import pytest as _pytest
    with _pytest.raises(Exception):
        VetterConfig(mode="hybrid")          # unknown mode rejected


def test_active_config_is_drawdown_only():
    """The deployed strategy file pins the decision explicitly."""
    import os
    from stock_strategy_shared.loader import load_strategy
    path = os.path.join(os.path.dirname(__file__), "..", "..", "strategies", "momentum_rotation_v2.yaml")
    cfg, _ = load_strategy(path)
    assert cfg.vetter.mode == "drawdown_only"
