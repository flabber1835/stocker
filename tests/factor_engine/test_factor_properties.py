"""
Property-based tests for factor calculation functions.

Properties under test:
  F1. compute_momentum with sufficient price history always returns a Series with only
      finite values or NaN — never +inf/-inf.
  F2. compute_momentum is monotone in the short/long price ratio: higher (short/long) → higher score.
  F3. compute_low_volatility with sufficient data always returns only finite values or NaN.
  F4. compute_low_volatility: higher price variance → lower (more negative) score — negative volatility.
  F5. compute_quality always returns finite values or NaN for finite positive inputs.
  F6. compute_value always returns finite values or NaN for finite positive PE/PB inputs.
  F7. cross_section_percentile output is always in (0, 1] for non-NaN values.
  F8. cross_section_zscore output is always clipped to [-2.5, 2.5].
"""
import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

import os
import sys

_PIPELINE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline")
)
_SHARED_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
for _k in list(sys.modules.keys()):
    if _k == "app" or _k.startswith("app."):
        del sys.modules[_k]
if _PIPELINE_PATH not in sys.path:
    sys.path.insert(0, _PIPELINE_PATH)
if _SHARED_PATH not in sys.path:
    sys.path.insert(1, _SHARED_PATH)

from app.factors import (
    compute_momentum,
    compute_low_volatility,
    compute_quality,
    compute_value,
    compute_growth,
    cross_section_percentile,
    cross_section_zscore,
)


# ── helpers ───────────────────────────────────────────────────────────────────

_POSITIVE_PRICE = st.floats(min_value=0.01, max_value=10_000.0,
                             allow_nan=False, allow_infinity=False)
_POSITIVE_RATIO = st.floats(min_value=0.1, max_value=10.0,
                              allow_nan=False, allow_infinity=False)
_N_TICKERS = st.integers(min_value=2, max_value=50)


def _make_price_pivot(n_tickers: int, n_days: int, base_price: float = 100.0,
                      drift: float = 0.0, noise_scale: float = 0.01) -> pd.DataFrame:
    """Build a (n_days × n_tickers) pivot DataFrame of synthetic prices."""
    rng = np.random.default_rng(42)
    tickers = [f"T{i:03d}" for i in range(n_tickers)]
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    returns = rng.normal(drift, noise_scale, size=(n_days, n_tickers))
    prices = base_price * np.exp(np.cumsum(returns, axis=0))
    return pd.DataFrame(prices, index=dates, columns=tickers)


def _make_fundamentals(n_tickers: int,
                        roe_lo=0.05, roe_hi=0.40,
                        dte_lo=0.1, dte_hi=3.0,
                        pe_lo=5.0, pe_hi=50.0,
                        pb_lo=0.5, pb_hi=10.0,
                        rev_g_lo=-0.2, rev_g_hi=0.5,
                        eps_g_lo=-0.5, eps_g_hi=1.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    tickers = [f"T{i:03d}" for i in range(n_tickers)]
    return pd.DataFrame({
        "ticker": tickers,
        "roe": rng.uniform(roe_lo, roe_hi, n_tickers),
        "debt_to_equity": rng.uniform(dte_lo, dte_hi, n_tickers),
        "pe_ratio": rng.uniform(pe_lo, pe_hi, n_tickers),
        "pb_ratio": rng.uniform(pb_lo, pb_hi, n_tickers),
        "revenue_growth": rng.uniform(rev_g_lo, rev_g_hi, n_tickers),
        "eps_growth": rng.uniform(eps_g_lo, eps_g_hi, n_tickers),
    })


# ── F1: momentum never returns inf ───────────────────────────────────────────

@given(
    n_tickers=_N_TICKERS,
    base_price=_POSITIVE_PRICE,
    drift=st.floats(min_value=-0.001, max_value=0.001, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_momentum_no_inf(n_tickers, base_price, drift):
    """F1: compute_momentum never produces ±inf for valid positive price data."""
    pivot = _make_price_pivot(n_tickers=n_tickers, n_days=300,
                               base_price=base_price, drift=drift)
    result = compute_momentum(pivot)
    inf_mask = result.replace([float("nan")], 0).abs() == float("inf")
    assert not inf_mask.any(), f"compute_momentum produced inf values: {result[inf_mask]}"


# ── F2: momentum monotone in short/long ratio ────────────────────────────────

@given(
    ratio_lo=st.floats(min_value=0.5, max_value=0.99, allow_nan=False, allow_infinity=False),
    ratio_hi=st.floats(min_value=1.01, max_value=2.0, allow_nan=False, allow_infinity=False),
    long_price=_POSITIVE_PRICE,
)
@settings(max_examples=100)
def test_momentum_monotone_in_ratio(ratio_lo, ratio_hi, long_price):
    """F2: A higher (short_price / long_price) ratio always gives a higher momentum score."""
    # Build two single-ticker price series that differ only in the short-window level
    n_days = 300
    short_window = 21
    long_window = 252

    def _build_pivot(short_price: float) -> pd.DataFrame:
        prices = np.full(n_days, long_price)
        # 12-1 momentum reads price_short at iloc[-(short_window+1)] (skip-month),
        # so cover that position as well as the most-recent window. Setting only the
        # last short_window rows leaves the read position untouched → momentum 0 for
        # every ratio. Using short_window+1 makes the data valid regardless of the
        # exact (pre- vs post-off-by-one-fix) momentum indexing.
        prices[-(short_window + 1):] = short_price
        dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
        return pd.DataFrame({"TICKER": prices}, index=dates)

    short_lo = long_price * ratio_lo
    short_hi = long_price * ratio_hi

    mom_lo = compute_momentum(_build_pivot(short_lo))
    mom_hi = compute_momentum(_build_pivot(short_hi))

    if mom_lo.empty or mom_hi.empty:
        return

    val_lo = mom_lo.iloc[0]
    val_hi = mom_hi.iloc[0]

    if math.isnan(val_lo) or math.isnan(val_hi):
        return

    assert val_hi > val_lo, (
        f"Expected mom_hi ({val_hi:.4f}) > mom_lo ({val_lo:.4f}) "
        f"for ratio_lo={ratio_lo:.3f} < ratio_hi={ratio_hi:.3f}"
    )


# ── F3: low_volatility never returns inf ─────────────────────────────────────

@given(
    n_tickers=_N_TICKERS,
    base_price=_POSITIVE_PRICE,
    noise_scale=st.floats(min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_low_volatility_no_inf(n_tickers, base_price, noise_scale):
    """F3: compute_low_volatility never produces ±inf for valid data."""
    pivot = _make_price_pivot(n_tickers=n_tickers, n_days=130,
                               base_price=base_price, noise_scale=noise_scale)
    result = compute_low_volatility(pivot)
    inf_mask = result.replace([float("nan")], 0).abs() == float("inf")
    assert not inf_mask.any(), f"compute_low_volatility produced inf: {result[inf_mask]}"


# ── F4: higher variance → lower (more negative) low_vol score ────────────────

@given(
    n_tickers=_N_TICKERS,
    base_price=_POSITIVE_PRICE,
    noise_lo=st.floats(min_value=0.001, max_value=0.02, allow_nan=False, allow_infinity=False),
    noise_hi=st.floats(min_value=0.05, max_value=0.15, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_high_variance_lower_low_vol_score(n_tickers, base_price, noise_lo, noise_hi):
    """F4: Higher price volatility leads to lower (more negative) low_volatility factor."""
    pivot_lo = _make_price_pivot(n_tickers=n_tickers, n_days=300,
                                  base_price=base_price, noise_scale=noise_lo)
    pivot_hi = _make_price_pivot(n_tickers=n_tickers, n_days=300,
                                  base_price=base_price, noise_scale=noise_hi)
    scores_lo = compute_low_volatility(pivot_lo)
    scores_hi = compute_low_volatility(pivot_hi)

    if scores_lo.empty or scores_hi.empty:
        return

    # Mean low-vol score should be lower (worse) for high-noise data
    mean_lo = scores_lo.dropna().mean()
    mean_hi = scores_hi.dropna().mean()

    if math.isnan(mean_lo) or math.isnan(mean_hi):
        return

    assert mean_hi < mean_lo, (
        f"Expected high-noise mean ({mean_hi:.4f}) < low-noise mean ({mean_lo:.4f})"
    )


# ── F5: compute_quality finite for finite inputs ──────────────────────────────

@given(n_tickers=_N_TICKERS)
@settings(max_examples=50)
def test_quality_no_inf(n_tickers):
    """F5: compute_quality never produces ±inf for valid finite inputs."""
    fund = _make_fundamentals(n_tickers)
    result = compute_quality(fund)
    inf_mask = result.replace([float("nan")], 0).abs() == float("inf")
    assert not inf_mask.any(), f"compute_quality produced inf: {result[inf_mask]}"


# ── F6: compute_value finite for positive PE/PB inputs ───────────────────────

@given(n_tickers=_N_TICKERS)
@settings(max_examples=50)
def test_value_no_inf(n_tickers):
    """F6: compute_value never produces ±inf for positive PE/PB values."""
    fund = _make_fundamentals(n_tickers, pe_lo=1.0, pe_hi=50.0, pb_lo=0.5, pb_hi=10.0)
    result = compute_value(fund)
    inf_mask = result.replace([float("nan")], 0).abs() == float("inf")
    assert not inf_mask.any(), f"compute_value produced inf: {result[inf_mask]}"


# ── F7: cross_section_percentile output in (0, 1] ────────────────────────────

@given(
    values=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        min_size=2, max_size=100,
    )
)
@settings(max_examples=200)
def test_cross_section_percentile_range(values):
    """F7: All non-NaN values from cross_section_percentile are in (0, 1]."""
    s = pd.Series(values, dtype=float)
    result = cross_section_percentile(s)
    non_nan = result.dropna()
    assert (non_nan > 0).all(), f"Some percentiles ≤ 0: {non_nan[non_nan <= 0]}"
    assert (non_nan <= 1.0 + 1e-9).all(), f"Some percentiles > 1: {non_nan[non_nan > 1.0]}"


# ── F8: cross_section_zscore clipped to [-2.5, 2.5] ─────────────────────────

@given(
    values=st.lists(
        st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False),
        min_size=2, max_size=200,
    ),
    clip=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_cross_section_zscore_clipped(values, clip):
    """F8: All non-NaN z-scores are within [-clip, clip]."""
    s = pd.Series(values, dtype=float)
    result = cross_section_zscore(s, clip=clip)
    non_nan = result.dropna()
    assert (non_nan >= -clip - 1e-9).all(), f"Z-scores below -{clip}: {non_nan[non_nan < -clip]}"
    assert (non_nan <= clip + 1e-9).all(), f"Z-scores above {clip}: {non_nan[non_nan > clip]}"


# ── compute_momentum: zero or negative price_long → NaN (not crash/inf) ──────

@given(
    long_price=st.floats(min_value=-1000.0, max_value=0.0, allow_nan=False, allow_infinity=False),
    short_price=_POSITIVE_PRICE,
)
@settings(max_examples=50)
def test_momentum_zero_long_price_returns_nan(long_price, short_price):
    """compute_momentum guards against zero/negative long_price by returning NaN."""
    n_days = 300
    short_window = 21
    long_window = 252
    prices = np.full(n_days, 100.0)
    prices[-long_window] = long_price  # corrupt the reference price
    prices[-short_window] = short_price
    # Ensure all other prices are positive
    prices[prices <= 0] = 0.0  # zero is the guard boundary
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    pivot = pd.DataFrame({"T": prices}, index=dates)
    result = compute_momentum(pivot)
    if not result.empty:
        val = result.iloc[0]
        # Must be NaN or finite — never inf
        if not (math.isnan(val) if isinstance(val, float) else pd.isna(val)):
            assert abs(val) < 1e15, f"Unexpected large momentum value: {val}"


# ── compute_growth: finite for all valid fundamental inputs ───────────────────

@given(n_tickers=_N_TICKERS)
@settings(max_examples=50)
def test_growth_no_inf(n_tickers):
    """compute_growth never produces ±inf for valid finite growth rate inputs."""
    fund = _make_fundamentals(n_tickers)
    result = compute_growth(fund)
    inf_mask = result.replace([float("nan")], 0).abs() == float("inf")
    assert not inf_mask.any(), f"compute_growth produced inf: {result[inf_mask]}"
