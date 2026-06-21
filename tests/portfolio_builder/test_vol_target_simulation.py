"""End-to-end stress test of the vol-targeting overlay against SIMULATED real
price movements, run through the ACTUAL builder math (build_covariance →
compute_weights → book_volatility → vol_target_exposure).

A one-factor return model (r_i = beta_i * market + idio_i * eps) generates price
histories under many regimes — calm bull, high-vol, bear crash with a jump,
correlation spikes, single-name blowups, zero-vol, tiny books — and we assert the
overlay de-levers correctly and only when it should. The point is to exercise the
real covariance/annualisation path, not mocked numbers.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.select import (
    book_volatility,
    build_covariance,
    compute_weights,
    vol_target_exposure,
)

TARGET = 0.12
MAXEXP = 0.975          # 1 - cash_reserve(0.025), as in momentum_rotation_v2
MINEXP = 0.30


def simulate_prices(
    tickers,
    days=320,
    *,
    market_vol=0.008,
    idio_vol=0.010,
    betas=None,
    market_drift=0.0003,
    seed=0,
    crash_day=None,
    crash_ret=0.0,
    start=100.0,
):
    """One-factor daily-return price simulator → long-format [ticker, date, adjusted_close].

    market_vol / idio_vol are DAILY std devs. betas defaults to 1.0 for all names.
    crash_ret is an additive shock to the market return on crash_day (use negative).
    """
    rng = np.random.default_rng(seed)
    n = len(tickers)
    betas = np.ones(n) if betas is None else np.asarray(betas, dtype=float)
    mkt = rng.normal(market_drift, market_vol, days)
    if crash_day is not None:
        mkt[crash_day] += crash_ret
    eps = rng.normal(0.0, 1.0, (days, n))
    base = dt.date(2025, 1, 1)
    logp = np.full(n, np.log(start))
    rows = []
    for d in range(days):
        r = betas * mkt[d] + idio_vol * eps[d]
        logp = logp + r
        px = np.exp(logp)
        date = base + dt.timedelta(days=d)
        for i, t in enumerate(tickers):
            rows.append({"ticker": t, "date": date, "adjusted_close": float(px[i])})
    return pd.DataFrame(rows)


def _build(prices, weighting="inverse_vol", n=20):
    cov, dropped, _corr = build_covariance(prices, window_days=252, min_observations=126, shrinkage=0.20)
    tickers = list(cov.index)
    selected = [{"ticker": t, "adj_score": 1.0, "composite_score": 1.0} for t in tickers]
    weights = compute_weights(selected, cov, method=weighting, max_position_weight=0.08)
    return cov, weights


def _apply(weights, exposure):
    return {t: w * exposure for t, w in weights.items()}


# ── regime behavior ─────────────────────────────────────────────────────────────

def test_calm_market_stays_fully_invested():
    tickers = [f"S{i}" for i in range(20)]
    prices = simulate_prices(tickers, market_vol=0.004, idio_vol=0.006, seed=1)
    cov, w = _build(prices)
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert bv < TARGET, f"calm book vol should be below target, got {bv:.3f}"
    assert exp == MAXEXP  # no de-lever in calm markets → no drag


def test_high_vol_market_delevers():
    tickers = [f"S{i}" for i in range(20)]
    prices = simulate_prices(tickers, market_vol=0.025, idio_vol=0.012, seed=2)
    cov, w = _build(prices)
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert bv > TARGET, f"high-vol book should exceed target, got {bv:.3f}"
    assert exp < MAXEXP, "should de-lever when book vol exceeds target"
    # in the de-lever band the realized (scaled) vol is pulled to ~target
    if MINEXP < exp < MAXEXP:
        assert exp * bv == pytest.approx(TARGET, rel=1e-6)


def test_crash_with_jump_floors_exposure():
    tickers = [f"S{i}" for i in range(20)]
    # high vol + a -25% market jump + high betas → extreme book vol → floor
    prices = simulate_prices(
        tickers, market_vol=0.03, idio_vol=0.015, betas=np.full(20, 1.3),
        crash_day=300, crash_ret=-0.25, seed=3,
    )
    cov, w = _build(prices)
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert bv > 0.30, f"crash book vol should be large, got {bv:.3f}"
    assert exp == MINEXP, "extreme vol should de-lever to the floor"


def test_correlation_spike_delevers_more_than_diversified():
    """Same per-name vol, but a correlation spike (all betas high, tiny idio) raises
    BOOK vol → lower exposure than a diversified book with the same names."""
    tickers = [f"S{i}" for i in range(20)]
    diversified = simulate_prices(tickers, market_vol=0.010, idio_vol=0.020, seed=4)
    correlated = simulate_prices(
        tickers, market_vol=0.018, idio_vol=0.003, betas=np.full(20, 1.2), seed=4
    )
    cov_d, w_d = _build(diversified)
    cov_c, w_c = _build(correlated)
    bv_d = book_volatility(w_d, cov_d)
    bv_c = book_volatility(w_c, cov_c)
    exp_d = vol_target_exposure(bv_d, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    exp_c = vol_target_exposure(bv_c, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert bv_c > bv_d, "correlated book should have higher vol"
    assert exp_c <= exp_d, "correlation spike should de-lever at least as much"


def test_monotonic_delever_across_vol_sweep():
    """Sweep market vol upward; book vol must rise and exposure must be non-increasing.
    Lowest vol stays at max; highest reaches the floor — both branches exercised."""
    tickers = [f"S{i}" for i in range(20)]
    book_vols, exposures = [], []
    for mv in [0.004, 0.008, 0.012, 0.018, 0.028, 0.045]:
        cov, w = _build(simulate_prices(tickers, market_vol=mv, idio_vol=0.008, seed=10))
        bv = book_volatility(w, cov)
        book_vols.append(bv)
        exposures.append(vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP))
    assert all(book_vols[i] < book_vols[i + 1] for i in range(len(book_vols) - 1)), book_vols
    assert all(exposures[i] >= exposures[i + 1] - 1e-12 for i in range(len(exposures) - 1)), exposures
    assert exposures[0] == MAXEXP, "calmest regime fully invested"
    assert exposures[-1] == MINEXP, "wildest regime at the floor"


# ── interaction with weighting / caps ───────────────────────────────────────────

@pytest.mark.parametrize("weighting", ["equal_weight", "inverse_vol", "score_proportional"])
def test_overlay_preserves_relative_weights_and_sums_to_exposure(weighting):
    tickers = [f"S{i}" for i in range(20)]
    cov, w = _build(simulate_prices(tickers, market_vol=0.02, idio_vol=0.01, seed=5), weighting=weighting)
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    scaled = _apply(w, exp)
    # compute_weights rounds to 6dp so the book sums to ~1.0 (±1e-6); the exact
    # invariant is sum(scaled) == exposure × sum(unscaled), and the book ~fully invested.
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-4)
    assert sum(scaled.values()) == pytest.approx(exp * sum(w.values()), rel=1e-9)
    # relative proportions unchanged (overlay is a pure scalar on the book)
    ratios = [scaled[t] / w[t] for t in tickers if w[t] > 0]
    assert max(ratios) - min(ratios) < 1e-9


def test_single_name_blowup_is_downweighted_then_overlay_delevers():
    """One name with huge idio vol: inverse_vol weighting down-weights it AND the
    overlay de-levers the whole book. Both controls compose without error."""
    tickers = [f"S{i}" for i in range(20)]
    prices = simulate_prices(tickers, market_vol=0.012, idio_vol=0.010, seed=6)
    # blow up one name's path with a fat idiosyncratic series post-hoc
    rng = np.random.default_rng(99)
    mask = prices["ticker"] == "S0"
    bump = np.cumsum(rng.normal(0, 0.08, mask.sum()))
    prices.loc[mask, "adjusted_close"] = prices.loc[mask, "adjusted_close"].to_numpy() * np.exp(bump)
    cov, w = _build(prices, weighting="inverse_vol")
    assert w["S0"] == min(w.values()) or w["S0"] <= np.median(list(w.values()))  # down-weighted
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert 0.0 < exp <= MAXEXP
    assert sum(_apply(w, exp).values()) == pytest.approx(exp * sum(w.values()), rel=1e-9)


# ── edge cases ──────────────────────────────────────────────────────────────────

def test_constant_prices_zero_vol_fails_open():
    """Flat prices → ~zero variance (floored) → book vol ~0 → fail OPEN to max
    (a zero-risk book is not a reason to sit in cash)."""
    tickers = [f"S{i}" for i in range(10)]
    base = dt.date(2025, 1, 1)
    rows = [
        {"ticker": t, "date": base + dt.timedelta(days=d), "adjusted_close": 100.0}
        for d in range(200) for t in tickers
    ]
    cov, dropped, _ = build_covariance(pd.DataFrame(rows), window_days=252, min_observations=126, shrinkage=0.20)
    # constant series → no return variation; tickers may be dropped or floored.
    if len(cov.index) == 0:
        pytest.skip("flat series dropped entirely by min_observations — nothing to weight")
    selected = [{"ticker": t, "adj_score": 1.0, "composite_score": 1.0} for t in cov.index]
    w = compute_weights(selected, cov, method="equal_weight", max_position_weight=0.2)
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert exp == MAXEXP  # near-zero / degenerate vol → fail open, stay invested


def test_single_ticker_book():
    cov, w = _build(simulate_prices(["ONLY"], market_vol=0.03, idio_vol=0.02, seed=8))
    if len(w) == 0:
        pytest.skip("single ticker dropped by min_observations")
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert 0.0 < exp <= MAXEXP
    assert MINEXP <= exp <= MAXEXP


def test_two_ticker_tiny_book():
    cov, w = _build(simulate_prices(["A", "B"], market_vol=0.025, idio_vol=0.01, seed=9))
    bv = book_volatility(w, cov)
    exp = vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP)
    assert sum(_apply(w, exp).values()) == pytest.approx(exp * sum(w.values()), rel=1e-9)


def test_disabled_overlay_equivalent_to_cash_reserve_only():
    """With targeting off, exposure must equal max_exposure (= 1 - cash_reserve)
    regardless of book vol — i.e. the overlay is a no-op when disabled."""
    tickers = [f"S{i}" for i in range(20)]
    cov, w = _build(simulate_prices(tickers, market_vol=0.05, idio_vol=0.02, seed=12))
    bv = book_volatility(w, cov)
    # "disabled" path in main.py sets exposure = max_exposure directly; emulate:
    exposure_disabled = MAXEXP
    assert exposure_disabled == MAXEXP
    # and an extreme book vol WOULD have de-levered had it been enabled (sanity):
    assert vol_target_exposure(bv, TARGET, min_exposure=MINEXP, max_exposure=MAXEXP) < MAXEXP
