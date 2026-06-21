"""Unit / property / edge-case tests for the volatility-targeting overlay
(book_volatility + vol_target_exposure) — the Barroso & Santa-Clara constant-vol
crash control added to the portfolio builder.

These are pure-function tests (no DB). The simulated-price end-to-end stress tests
live in test_vol_target_simulation.py.
"""
import math

import numpy as np
import pandas as pd
import pytest

from app.select import book_volatility, vol_target_exposure


def _cov(diag, corr=None, tickers=None):
    """Build an annualised cov matrix from per-name vols (sqrt of diag) and a
    correlation matrix (default identity)."""
    n = len(diag)
    tickers = tickers or [f"T{i}" for i in range(n)]
    vols = np.sqrt(np.array(diag, dtype=float))
    if corr is None:
        corr = np.eye(n)
    corr = np.array(corr, dtype=float)
    cov = corr * np.outer(vols, vols)
    return pd.DataFrame(cov, index=tickers, columns=tickers)


# ── book_volatility ────────────────────────────────────────────────────────────

def test_book_vol_known_value_uncorrelated():
    # two names, var 0.04 each (vol 0.2), zero corr, equal 0.5 weights
    cov = _cov([0.04, 0.04])
    w = {"T0": 0.5, "T1": 0.5}
    # var = 0.25*0.04 + 0.25*0.04 = 0.02 → vol = 0.141421
    assert book_volatility(w, cov) == pytest.approx(math.sqrt(0.02), rel=1e-9)


def test_book_vol_scales_linearly_with_gross_exposure():
    cov = _cov([0.04, 0.09], corr=[[1, 0.3], [0.3, 1]])
    w = {"T0": 0.5, "T1": 0.5}
    base = book_volatility(w, cov)
    doubled = book_volatility({t: v * 2 for t, v in w.items()}, cov)
    assert doubled == pytest.approx(2.0 * base, rel=1e-9)


def test_book_vol_correlation_raises_vol():
    diag = [0.04, 0.04]
    w = {"T0": 0.5, "T1": 0.5}
    uncorr = book_volatility(w, _cov(diag, [[1, 0.0], [0.0, 1]]))
    corr = book_volatility(w, _cov(diag, [[1, 0.9], [0.9, 1]]))
    assert corr > uncorr  # positive correlation → less diversification → higher vol


def test_book_vol_ignores_tickers_absent_from_cov():
    cov = _cov([0.04, 0.04])
    w = {"T0": 0.5, "T1": 0.5, "GHOST": 5.0}  # GHOST not in cov → ignored
    assert book_volatility(w, cov) == pytest.approx(math.sqrt(0.02), rel=1e-9)


def test_book_vol_empty_or_no_overlap_returns_zero():
    cov = _cov([0.04, 0.04])
    assert book_volatility({}, cov) == 0.0
    assert book_volatility({"NOPE": 1.0}, cov) == 0.0


def test_book_vol_nan_in_cov_returns_zero():
    cov = _cov([0.04, 0.04])
    cov.iloc[0, 1] = float("nan")
    cov.iloc[1, 0] = float("nan")
    assert book_volatility({"T0": 0.5, "T1": 0.5}, cov) == 0.0


def test_book_vol_single_name():
    cov = _cov([0.09])  # vol 0.3
    assert book_volatility({"T0": 1.0}, cov) == pytest.approx(0.3, rel=1e-9)


# ── vol_target_exposure: core behavior ──────────────────────────────────────────

def test_exposure_capped_at_max_when_calm():
    # book_vol below target → would lever up, but long-only caps at max_exposure
    assert vol_target_exposure(0.06, 0.12, min_exposure=0.3, max_exposure=1.0) == 1.0
    assert vol_target_exposure(0.06, 0.12, min_exposure=0.3, max_exposure=0.975) == 0.975


def test_exposure_delevers_proportionally_above_target():
    # book_vol = 2x target → invest half
    assert vol_target_exposure(0.24, 0.12, min_exposure=0.0, max_exposure=1.0) == pytest.approx(0.5)
    # book_vol = 1.5x target → 2/3
    assert vol_target_exposure(0.18, 0.12, min_exposure=0.0, max_exposure=1.0) == pytest.approx(2 / 3)


def test_exposure_floored_at_min_in_extreme_vol():
    assert vol_target_exposure(0.80, 0.12, min_exposure=0.30, max_exposure=1.0) == 0.30


def test_exposure_at_target_is_max():
    # book_vol exactly == target → ratio 1.0 → capped at max
    assert vol_target_exposure(0.12, 0.12, min_exposure=0.3, max_exposure=1.0) == 1.0


def test_realized_vol_hits_target_in_delever_band():
    # When neither bound binds, exposure * book_vol == target (the whole point)
    book = 0.20
    exp = vol_target_exposure(book, 0.12, min_exposure=0.1, max_exposure=1.0)
    assert exp * book == pytest.approx(0.12, rel=1e-9)


# ── vol_target_exposure: fail-open / degenerate inputs ──────────────────────────

def test_target_zero_or_negative_disables():
    assert vol_target_exposure(0.5, 0.0, max_exposure=0.9) == 0.9
    assert vol_target_exposure(0.5, -1.0, max_exposure=0.9) == 0.9


@pytest.mark.parametrize("bad", [0.0, -0.1, float("nan"), float("inf"), None])
def test_degenerate_book_vol_fails_open(bad):
    # unknown/degenerate risk must NOT dump the book to cash — fail OPEN to max
    assert vol_target_exposure(bad, 0.12, min_exposure=0.3, max_exposure=0.95) == 0.95


def test_max_exposure_zero_returns_zero():
    assert vol_target_exposure(0.2, 0.12, min_exposure=0.3, max_exposure=0.0) == 0.0


def test_min_above_max_is_clamped_not_inverted():
    # contradictory config: min 0.8 > max 0.4 → exposure must never exceed max
    e = vol_target_exposure(0.80, 0.12, min_exposure=0.8, max_exposure=0.4)
    assert e == 0.4


# ── property / invariant fuzz ───────────────────────────────────────────────────

def test_exposure_monotonic_non_increasing_in_book_vol():
    prev = None
    for bv in np.linspace(0.01, 1.0, 60):
        e = vol_target_exposure(float(bv), 0.12, min_exposure=0.2, max_exposure=0.95)
        if prev is not None:
            assert e <= prev + 1e-12
        prev = e


def test_exposure_always_within_bounds_fuzz():
    rng = np.random.default_rng(7)
    for _ in range(2000):
        bv = float(rng.uniform(0, 1.5))
        tgt = float(rng.uniform(0.01, 0.5))
        mn = float(rng.uniform(0, 1))
        mx = float(rng.uniform(0, 1))
        e = vol_target_exposure(bv, tgt, min_exposure=mn, max_exposure=mx)
        assert e <= max(mx, 0.0) + 1e-12          # never exceeds max
        assert e >= 0.0 - 1e-12                    # never negative
        # if max>0 and both bounds sane, exposure is within the clamped band
        if mx > 0:
            lo = max(0.0, min(mn, mx))
            assert lo - 1e-12 <= e <= mx + 1e-12


def test_exposure_relationship_holds_fuzz():
    """For finite positive book_vol and positive target: exposure is exactly
    clamp(target/book_vol, clamped_min, max)."""
    rng = np.random.default_rng(11)
    for _ in range(2000):
        bv = float(rng.uniform(0.001, 1.5))
        tgt = float(rng.uniform(0.01, 0.5))
        mn = float(rng.uniform(0, 0.9))
        mx = float(rng.uniform(0.1, 1.0))
        e = vol_target_exposure(bv, tgt, min_exposure=mn, max_exposure=mx)
        lo = max(0.0, min(mn, mx))
        expected = min(mx, max(lo, tgt / bv))
        assert e == pytest.approx(expected, rel=1e-9, abs=1e-12)
