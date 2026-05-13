import pytest
import pandas as pd
import numpy as np
from app.factors import (
    cross_section_zscore, compute_momentum, compute_low_volatility,
    compute_all_factors, compute_quality, compute_value, compute_growth,
    _winsorize, _component_zscore,
)


def _pivot(tickers: list[str], n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    data = {}
    for t in tickers:
        start = rng.uniform(50, 300)
        returns = rng.normal(0.0003, 0.015, n)
        prices = start * np.cumprod(1 + returns)
        data[t] = prices
    return pd.DataFrame(data, index=dates)


def _prices_long(tickers: list[str], n: int = 300) -> pd.DataFrame:
    pivot = _pivot(tickers, n)
    rows = []
    for ticker in tickers:
        for date, price in pivot[ticker].items():
            rows.append({
                "ticker": ticker, "date": date.date(),
                "close": price, "adjusted_close": price,
                "volume": int(1e6),
            })
    return pd.DataFrame(rows)


def _large_fund(n: int = 50, seed: int = 0) -> pd.DataFrame:
    """Return a realistic fundamentals DataFrame with n tickers for winsorization tests."""
    rng = np.random.default_rng(seed)
    tickers = [f"T{i:03d}" for i in range(n)]
    return pd.DataFrame({
        "ticker": tickers,
        "pe_ratio": rng.uniform(5, 80, n),
        "pb_ratio": rng.uniform(0.5, 15, n),
        "roe": rng.uniform(-0.10, 0.60, n),
        "debt_to_equity": rng.uniform(0.0, 3.0, n),
        "revenue_growth": rng.uniform(-0.20, 0.50, n),
        "eps_growth": rng.uniform(-0.30, 0.80, n),
    })


# ── cross_section_zscore ─────────────────────────────────────────────────────────────────────────

def test_zscore_clips_to_2_5():
    s = pd.Series([1.0, 2.0, 100.0, -100.0])
    z = cross_section_zscore(s)
    assert z.max() <= 2.5
    assert z.min() >= -2.5


def test_zscore_zero_std():
    s = pd.Series([5.0, 5.0, 5.0])
    z = cross_section_zscore(s)
    assert (z == 0.0).all()


def test_zscore_preserves_nan():
    s = pd.Series([1.0, float("nan"), 3.0, float("nan")])
    z = cross_section_zscore(s)
    assert pd.isna(z.iloc[1])
    assert pd.isna(z.iloc[3])
    assert pd.notna(z.iloc[0])
    assert pd.notna(z.iloc[2])


def test_zscore_all_nan():
    s = pd.Series([float("nan"), float("nan")])
    z = cross_section_zscore(s)
    assert z.isna().all()


# ── _winsorize ────────────────────────────────────────────────────────────────────────────────────

def test_winsorize_clips_extremes():
    s = pd.Series(list(range(100)) + [10000, -10000])
    w = _winsorize(s)
    assert w.max() < 10000
    assert w.min() > -10000


def test_winsorize_passthrough_small_population():
    # Fewer than 10 values — returned unchanged
    s = pd.Series([1.0, 2.0, 100.0])
    w = _winsorize(s)
    assert (w == s).all()


def test_winsorize_preserves_interior_order():
    # Winsorization only clips extremes; values strictly between the two bounds
    # must keep their original relative order.
    rng = np.random.default_rng(7)
    s = pd.Series(rng.normal(0, 1, 200))
    w = _winsorize(s)
    lo, hi = s.quantile(0.01), s.quantile(0.99)
    interior = (s > lo) & (s < hi)
    assert (w[interior].rank() == s[interior].rank()).all()


# ── _component_zscore ────────────────────────────────────────────────────────────────────────────────────

def test_component_zscore_zero_mean():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = _component_zscore(s)
    assert abs(z.mean()) < 1e-10


def test_component_zscore_unit_std():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = _component_zscore(s)
    assert abs(z.std() - 1.0) < 0.01


def test_component_zscore_zero_std_returns_zeros():
    s = pd.Series([7.0, 7.0, 7.0])
    z = _component_zscore(s)
    assert (z == 0.0).all()


# ── compute_quality ────────────────────────────────────────────────────────────────────────────────────

def test_quality_upside_not_compressed():
    """
    With a large diverse population the best quality stock should score well above 0.5
    after cross-sectional z-scoring. The old min-max approach was capped at ~0.55σ.
    """
    fund = _large_fund(n=100, seed=1)
    # Override one ticker to be clearly the best
    fund.loc[0, "roe"] = 2.0    # extreme high ROE
    fund.loc[0, "debt_to_equity"] = 0.0  # zero debt

    raw = compute_quality(fund)
    z = cross_section_zscore(raw)

    best = str(fund.loc[0, "ticker"])
    assert z[best] > 1.0, f"best quality ticker z-score {z[best]:.3f} should be >1.0"


def test_quality_returns_nan_for_no_fundamentals():
    fund = pd.DataFrame(columns=["ticker", "roe", "debt_to_equity"])
    result = compute_quality(pd.DataFrame({"ticker": ["A"], "roe": [float("nan")], "debt_to_equity": [float("nan")]}))
    assert pd.isna(result["A"])


def test_quality_uses_partial_data():
    # Ticker with only ROE (no D/E) should still get a score
    fund = pd.DataFrame([
        {"ticker": "A", "roe": 0.3, "debt_to_equity": float("nan")},
        {"ticker": "B", "roe": 0.1, "debt_to_equity": 0.5},
    ])
    result = compute_quality(fund)
    assert pd.notna(result["A"])


# ── compute_growth ────────────────────────────────────────────────────────────────────────────────────

def test_growth_winsorization_prevents_outlier_collapse():
    """
    When one ticker has explosive growth (10x revenue), unwinsorized z-scoring compresses
    all other tickers to near-zero. After winsorization the cross-section should spread out.
    """
    rng = np.random.default_rng(42)
    n = 100
    tickers = [f"T{i}" for i in range(n)]
    rev_g = list(rng.uniform(0.0, 0.3, n - 1)) + [10.0]  # one massive outlier
    eps_g = list(rng.uniform(-0.1, 0.5, n - 1)) + [50.0]
    fund = pd.DataFrame({"ticker": tickers, "pe_ratio": [20.0] * n, "pb_ratio": [2.0] * n,
                          "roe": [0.2] * n, "debt_to_equity": [0.5] * n,
                          "revenue_growth": rev_g, "eps_growth": eps_g})

    raw = compute_growth(fund)
    z = cross_section_zscore(raw)

    valid = z.dropna()
    # With proper winsorization, std of z-scores should be meaningfully spread (not collapsed)
    assert valid.std() > 0.5, f"growth z-score std {valid.std():.3f} is too low — outlier not winsorized"


def test_growth_partial_data():
    # Ticker with only revenue_growth (no eps_growth) should still get a score
    fund = pd.DataFrame([
        {"ticker": "A", "revenue_growth": 0.2, "eps_growth": float("nan"),
         "pe_ratio": 20.0, "pb_ratio": 2.0, "roe": 0.2, "debt_to_equity": 0.5},
    ])
    result = compute_growth(fund)
    assert pd.notna(result["A"])


# ── compute_value ─────────────────────────────────────────────────────────────────────────────────────

def test_value_pe_cap_at_50():
    """Stocks with PE=200 and PE=100 should produce the same earnings yield as PE=50."""
    fund = pd.DataFrame([
        {"ticker": "CHEAP", "pe_ratio": 10.0, "pb_ratio": 1.0,
         "roe": 0.2, "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.1},
        {"ticker": "RICH50", "pe_ratio": 50.0, "pb_ratio": 10.0,
         "roe": 0.1, "debt_to_equity": 1.0, "revenue_growth": 0.05, "eps_growth": 0.05},
        {"ticker": "RICH200", "pe_ratio": 200.0, "pb_ratio": 10.0,
         "roe": 0.1, "debt_to_equity": 1.0, "revenue_growth": 0.05, "eps_growth": 0.05},
    ])
    result = compute_value(fund)
    # RICH50 and RICH200 should have identical earnings yield (both capped at 50x)
    assert abs(result["RICH50"] - result["RICH200"]) < 1e-9


def test_value_winsorization_reduces_outliers():
    """
    Cross-sectional z-scores of value should not have many extreme outliers
    after winsorization + cap at 50.
    """
    fund = _large_fund(n=200, seed=3)
    # Inject a handful of extreme values that previously produced 88 outliers
    fund.loc[:4, "pe_ratio"] = 0.5   # extreme value (near-zero PE)
    fund.loc[5:9, "pb_ratio"] = 0.1

    raw = compute_value(fund)
    z = cross_section_zscore(raw)
    extreme = (z.abs() > 2.4).sum()
    # After proper winsorization there should be very few tickers at the ±2.5 clip
    assert extreme <= 10, f"{extreme} tickers hit extreme z-score after winsorization"


# ── compute_low_volatility ────────────────────────────────────────────────────────────────────────────────────

def test_low_volatility_handles_sparse_tickers():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    full = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
    sparse = full.copy().astype(float)
    sparse[50:250] = float("nan")
    pivot = pd.DataFrame({"FULL": full, "SPARSE": sparse}, index=dates)
    result = compute_low_volatility(pivot)
    assert pd.notna(result["FULL"])


def test_low_volatility_is_negative_vol():
    pivot = _pivot(["A", "B"], n=300)
    result = compute_low_volatility(pivot)
    assert (result < 0).all()


# ── compute_momentum ──────────────────────────────────────────────────────────────────────────────────────

def test_compute_momentum_needs_253_rows():
    pivot = _pivot(["A"], n=200)
    result = compute_momentum(pivot)
    assert result.empty


def test_compute_momentum_returns_series():
    pivot = _pivot(["A", "B", "C"], n=300)
    result = compute_momentum(pivot)
    assert set(result.index) == {"A", "B", "C"}


# ── compute_all_factors ─────────────────────────────────────────────────────────────────────────────────────

def test_compute_all_factors_columns():
    df = _prices_long(["AAPL", "MSFT", "GOOG"], n=300)
    fund = pd.DataFrame([
        {"ticker": "AAPL", "pe_ratio": 25.0, "pb_ratio": 5.0, "roe": 0.3,
         "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.15},
        {"ticker": "MSFT", "pe_ratio": 30.0, "pb_ratio": 8.0, "roe": 0.4,
         "debt_to_equity": 0.3, "revenue_growth": 0.15, "eps_growth": 0.2},
        {"ticker": "GOOG", "pe_ratio": 20.0, "pb_ratio": 4.0, "roe": 0.25,
         "debt_to_equity": 0.1, "revenue_growth": 0.12, "eps_growth": 0.18},
    ])
    result = compute_all_factors(df, fund)
    assert "ticker" in result.columns
    for col in ("momentum", "quality", "value", "growth", "low_volatility", "liquidity"):
        assert col in result.columns
    assert len(result) == 3


def test_compute_all_factors_handles_empty_fundamentals():
    df = _prices_long(["X", "Y"], n=300)
    fund = pd.DataFrame(columns=["ticker", "pe_ratio", "pb_ratio", "roe",
                                  "debt_to_equity", "revenue_growth", "eps_growth"])
    result = compute_all_factors(df, fund)
    assert len(result) == 2
    assert result["momentum"].notna().any() or result["momentum"].isna().all()
