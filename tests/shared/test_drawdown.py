"""Tests for the shared drawdown math + a guard that the vetter (veto) and pipeline
(display) both SOURCE it from the shared module rather than reimplementing it — the
anti-divergence guard for the falling-knife "card lies vs veto" bug class.
"""
from pathlib import Path

from stock_strategy_shared.drawdown import (
    recent_drawdown,
    scaled_excess_threshold,
    excess_drawdown,
    beta_and_idio_vol,
)

ROOT = Path(__file__).resolve().parents[2]


# ── shared math (smoke) ─────────────────────────────────────────────────────────

def test_recent_drawdown_at_peak_zero_and_below():
    # At a fresh high → 0 regardless of baseline mode.
    assert recent_drawdown([100, 105, 110]) == 0.0
    # baseline_window=0 → pure peak-to-now (the legacy behaviour).
    assert recent_drawdown([100, 120, 90], baseline_window=0) == 90 / 120 - 1.0


def test_recent_drawdown_window_and_empty():
    assert recent_drawdown([100, 120, 90], window=2, baseline_window=0) == 90 / 120 - 1.0
    assert recent_drawdown([]) is None
    assert recent_drawdown([0, -5]) is None


def test_scaled_excess_threshold_clamps_and_falls_back():
    # vol-scaled within [lo, hi]; None idio_vol → flat base
    assert scaled_excess_threshold(0.35, base=0.10, anchor=0.35, lo=0.07, hi=0.20) == 0.10
    assert scaled_excess_threshold(0.70, base=0.10, anchor=0.35, lo=0.07, hi=0.20) == 0.20   # hi clamp
    assert scaled_excess_threshold(0.10, base=0.10, anchor=0.35, lo=0.07, hi=0.20) == 0.07   # lo clamp
    assert scaled_excess_threshold(None, base=0.13, anchor=0.35) == 0.13                      # fallback


def test_excess_drawdown_strips_market():
    # stock fell 10% while SPY fell 10% over the same span, beta≈1 → excess ≈ 0
    n = 130
    spy = [100.0 * (0.999 ** i) for i in range(n)]
    stock = [50.0 * (0.999 ** i) for i in range(n)]   # perfectly tracks SPY → beta 1, excess ~0
    res = excess_drawdown(stock, spy, window=21)
    assert res is not None and res["excess_dd"] is not None
    assert abs(res["excess_dd"]) < 0.02


# ── anti-divergence guard: both services source the shared module ───────────────

def test_vetter_reexports_shared_not_reimplements():
    src = (ROOT / "services" / "llm-vetter" / "app" / "drawdown.py").read_text()
    assert "from stock_strategy_shared.drawdown import" in src
    assert "def recent_drawdown" not in src      # must NOT redefine — re-export only
    assert "def excess_drawdown" not in src


def test_pipeline_uses_shared_drawdown():
    src = (ROOT / "services" / "pipeline" / "app" / "main.py").read_text()
    assert "from stock_strategy_shared.drawdown import" in src
    # the old local copies must be gone (replaced by the shared functions)
    assert "def _recent_drawdown(" not in src
    assert "_recent_drawdown = recent_drawdown" in src   # backward-compat alias only
