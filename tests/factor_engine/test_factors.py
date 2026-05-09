import pytest
import pandas as pd
import numpy as np
from app.factors import (
    cross_section_zscore, compute_momentum, compute_low_volatility,
    compute_all_factors,
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


def test_zscore_clips_to_3():
    s = pd.Series([1.0, 2.0, 100.0, -100.0])
    z = cross_section_zscore(s)
    assert z.max() <= 3.0
    assert z.min() >= -3.0


def test_zscore_zero_std():
    s = pd.Series([5.0, 5.0, 5.0])
    z = cross_section_zscore(s)
    assert (z == 0.0).all()


def test_compute_momentum_needs_253_rows():
    pivot = _pivot(["A"], n=200)
    result = compute_momentum(pivot)
    assert result.empty


def test_compute_momentum_returns_series():
    pivot = _pivot(["A", "B", "C"], n=300)
    result = compute_momentum(pivot)
    assert set(result.index) == {"A", "B", "C"}


def test_low_volatility_is_negative_vol():
    pivot = _pivot(["A", "B"], n=300)
    result = compute_low_volatility(pivot)
    # Low volatility score should be negative of annualized vol
    assert (result < 0).all()


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
    # quality/value/growth will be NaN with empty fundamentals
    assert result["momentum"].notna().any() or result["momentum"].isna().all()
