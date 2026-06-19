"""Tests for the beta-adjusted (market-relative) falling-knife signal.

excess_drawdown strips the beta-implied SPY move out of a stock's raw drawdown,
so a broad market-down day (which drags everything down via beta) does NOT look
like a stock-specific knife — only an idiosyncratic decline does. estimate_beta
is the supporting OLS regression. Both are pure/dependency-free.
"""
import math

import pytest

from app.drawdown import (
    recent_drawdown,
    estimate_beta,
    excess_drawdown,
    beta_and_idio_vol,
    scaled_excess_threshold,
)


def _series_from_returns(start: float, returns: list[float]) -> list[float]:
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * (1 + r))
    return closes


# ── estimate_beta ─────────────────────────────────────────────────────────────

def test_beta_of_exact_multiple_is_the_multiple():
    """If the stock return is exactly 1.5x SPY every day, beta == 1.5."""
    rng = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, -0.012] * 4
    spy = _series_from_returns(100.0, rng)
    stock = _series_from_returns(50.0, [1.5 * r for r in rng])
    beta = estimate_beta(stock, spy, lookback=120, min_observations=10)
    assert beta == pytest.approx(1.5, abs=1e-6)


def test_beta_none_when_insufficient_history():
    spy = [100.0, 101.0, 100.5]
    stock = [50.0, 50.5, 50.2]
    assert estimate_beta(stock, spy, lookback=120, min_observations=20) is None


def test_beta_none_when_spy_flat():
    spy = [100.0] * 30
    stock = _series_from_returns(50.0, [0.01, -0.01] * 14)
    assert estimate_beta(stock, spy, min_observations=10) is None


# ── excess_drawdown: the SPY-stripping behaviour the user asked for ───────────

def test_market_driven_drop_is_not_a_knife():
    """Stock falls only because SPY fell (beta=1). raw_dd is large and negative,
    but excess_dd ≈ 0 → NOT flagged. This is the whole point."""
    # 120 quiet days to establish beta≈1, then a shared -12% slide over the window.
    base = [0.004, -0.004] * 60
    spy = _series_from_returns(100.0, base)
    stock = _series_from_returns(100.0, base)
    # Append an aligned market-wide decline (both fall together → beta 1).
    slide = [-0.04, -0.04, -0.04]
    spy = _series_from_returns(spy[-1], slide)  # continue from last
    # rebuild full aligned series
    spy_full = _series_from_returns(100.0, base + slide)
    stock_full = _series_from_returns(100.0, base + slide)
    out = excess_drawdown(stock_full, spy_full, window=5, beta_lookback=120)
    assert out["raw_dd"] < -0.10                      # big raw drop
    assert out["excess_dd"] == pytest.approx(0.0, abs=0.02)  # market explains it → ~0


def test_idiosyncratic_drop_is_a_knife():
    """Stock craters while SPY is flat → excess ≈ raw_dd (large) → flagged."""
    base = [0.003, -0.003] * 60          # SPY drifts ~flat
    spy_full = _series_from_returns(100.0, base + [0.0, 0.0, 0.0])
    stock_full = _series_from_returns(100.0, base + [-0.08, -0.08, -0.05])  # -20% on its own
    # baseline_window=0 here: this 5-day window is too short for the 3-day baseline
    # (the crash spans most of the window). Round-trip suppression on a genuine
    # one-way collapse over a realistic 21d window is covered in
    # tests/shared/test_drawdown_baseline.py and the real-DB integration test.
    out = excess_drawdown(stock_full, spy_full, window=5, beta_lookback=120, baseline_window=0)
    assert out["raw_dd"] < -0.18
    assert out["excess_dd"] < -0.15      # market did NOT explain it → still a knife


def test_high_beta_market_drop_exempted():
    """A 1.5-beta stock that falls 15% when SPY falls 10% (expected -15%) → excess ~0."""
    base = [1.5 * r for r in ([0.01, -0.01] * 60)]
    spy_base = [0.01, -0.01] * 60
    spy_full = _series_from_returns(100.0, spy_base + [-0.04, -0.04, -0.025])      # ~-10%
    stock_full = _series_from_returns(100.0, base + [-0.06, -0.06, -0.038])         # ~-15%
    out = excess_drawdown(stock_full, spy_full, window=5, beta_lookback=120)
    assert out["beta"] == pytest.approx(1.5, abs=0.1)
    assert out["excess_dd"] == pytest.approx(0.0, abs=0.03)   # beta explains the 15%


def test_beta_none_falls_back_to_raw_only():
    """Too little history for beta → excess_dd None, raw_dd still present (caller
    then uses the absolute floor)."""
    spy = [100.0, 101.0, 99.0, 98.0]
    stock = [50.0, 50.5, 47.0, 46.0]
    out = excess_drawdown(stock, spy, window=4, beta_lookback=120)
    assert out is not None
    assert out["raw_dd"] is not None
    assert out["excess_dd"] is None


def test_beta_clipped_to_floor():
    """A negative raw beta is clipped to 0 so a market drop can't ADD to the knife
    via a perverse sign."""
    # Stock moves opposite SPY (negative beta) historically.
    spy_base = [0.01, -0.01] * 60
    stock_base = [-0.01, 0.01] * 60
    spy_full = _series_from_returns(100.0, spy_base + [-0.03, -0.03])
    stock_full = _series_from_returns(100.0, stock_base + [-0.05, -0.05])
    out = excess_drawdown(stock_full, spy_full, window=4, beta_lookback=120, beta_floor=0.0)
    assert out["beta"] == 0.0                  # clipped from negative
    assert out["excess_dd"] == pytest.approx(out["raw_dd"], abs=1e-9)  # no market credit


# ── beta_and_idio_vol: residual (idiosyncratic) volatility ────────────────────

def test_idio_vol_zero_when_stock_is_pure_beta():
    """If the stock is EXACTLY beta*SPY every day there is no residual → idio_vol≈0."""
    rng = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, -0.012] * 4
    spy = _series_from_returns(100.0, rng)
    stock = _series_from_returns(50.0, [1.5 * r for r in rng])
    beta, idio_vol = beta_and_idio_vol(stock, spy, lookback=120, min_observations=10)
    assert beta == pytest.approx(1.5, abs=1e-6)
    assert idio_vol == pytest.approx(0.0, abs=1e-6)


def test_idio_vol_positive_when_stock_has_own_noise():
    """Stock = beta*SPY + idiosyncratic noise → idio_vol > 0 and annualized."""
    rng = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, -0.012] * 6
    noise = [0.01, -0.01] * (len(rng) // 2)
    spy = _series_from_returns(100.0, rng)
    stock = _series_from_returns(50.0, [r + noise[i] for i, r in enumerate(rng)])
    beta, idio_vol = beta_and_idio_vol(stock, spy, lookback=200, min_observations=10)
    assert idio_vol is not None and idio_vol > 0
    # Daily residual ~1% → annualized ≈ 0.01 * sqrt(252) ≈ 0.16; sanity range.
    assert 0.05 < idio_vol < 0.40


def test_idio_vol_none_when_insufficient_history():
    spy = [100.0, 101.0, 100.5]
    stock = [50.0, 50.5, 50.2]
    beta, idio_vol = beta_and_idio_vol(stock, spy, min_observations=20)
    assert beta is None and idio_vol is None


def test_excess_drawdown_exposes_idio_vol():
    """excess_drawdown carries idio_vol through for the vol-scaled threshold."""
    base = [0.003, -0.003] * 60
    spy_full = _series_from_returns(100.0, base + [0.0, 0.0, 0.0])
    stock_full = _series_from_returns(100.0, base + [-0.08, -0.08, -0.05])
    out = excess_drawdown(stock_full, spy_full, window=5, beta_lookback=120)
    assert "idio_vol" in out
    assert out["idio_vol"] is not None and out["idio_vol"] >= 0


# ── scaled_excess_threshold: the vol-scaled per-ticker limit ───────────────────

def test_scaled_threshold_typical_vol_keeps_base():
    """idio_vol == anchor → limit is exactly the base."""
    assert scaled_excess_threshold(0.35, 0.15, anchor=0.35) == pytest.approx(0.15)


def test_scaled_threshold_calm_name_tighter():
    """Half the anchor vol → half the base limit (but not below the floor)."""
    # base 0.15 * (0.175/0.35) = 0.075 → clamped up to lo=0.10
    assert scaled_excess_threshold(0.175, 0.15, anchor=0.35, lo=0.10, hi=0.30) == pytest.approx(0.10)
    # base 0.30 * (0.175/0.35) = 0.15, above lo → unclamped
    assert scaled_excess_threshold(0.175, 0.30, anchor=0.35, lo=0.10, hi=0.30) == pytest.approx(0.15)


def test_scaled_threshold_wild_name_more_rope_capped():
    """High vol loosens the limit, but it is capped at hi."""
    # base 0.15 * (1.40/0.35) = 0.60 → clamped to hi=0.30
    assert scaled_excess_threshold(1.40, 0.15, anchor=0.35, lo=0.10, hi=0.30) == pytest.approx(0.30)
    # base 0.15 * (0.70/0.35) = 0.30 → exactly at hi
    assert scaled_excess_threshold(0.70, 0.15, anchor=0.35, lo=0.10, hi=0.30) == pytest.approx(0.30)


def test_scaled_threshold_falls_back_to_base_when_idio_vol_unknown():
    assert scaled_excess_threshold(None, 0.15, anchor=0.35) == 0.15


def test_scaled_threshold_falls_back_to_base_on_invalid_anchor():
    assert scaled_excess_threshold(0.50, 0.15, anchor=0.0) == 0.15
    assert scaled_excess_threshold(0.50, 0.15, anchor=None) == 0.15
