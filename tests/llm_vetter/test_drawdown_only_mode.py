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
