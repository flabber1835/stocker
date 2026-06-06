"""Tests for the net-share-issuance factor (compute_issuance) and its wiring
into compute_all_factors."""
import numpy as np
import pandas as pd

from app.factors import compute_issuance, compute_all_factors


def test_buybacks_rank_above_dilution():
    """Net repurchaser (shares shrank) scores higher than a dilutive issuer."""
    fund = pd.DataFrame([
        {"ticker": "BUYBACK", "shares_outstanding": 90.0,  "shares_outstanding_prior": 100.0},  # -10% issuance
        {"ticker": "FLAT",    "shares_outstanding": 100.0, "shares_outstanding_prior": 100.0},  #   0%
        {"ticker": "DILUTE",  "shares_outstanding": 115.0, "shares_outstanding_prior": 100.0},  # +15% issuance
    ])
    f = compute_issuance(fund)
    assert f["BUYBACK"] > f["FLAT"] > f["DILUTE"]
    # factor = -net_issuance
    assert f["BUYBACK"] == np.float64(-(90.0 / 100.0 - 1.0))


def test_missing_or_nonpositive_shares_give_nan():
    fund = pd.DataFrame([
        {"ticker": "NOPRIOR", "shares_outstanding": 100.0, "shares_outstanding_prior": None},
        {"ticker": "ZERO",    "shares_outstanding": 100.0, "shares_outstanding_prior": 0.0},
        {"ticker": "OK",      "shares_outstanding": 95.0,  "shares_outstanding_prior": 100.0},
    ])
    f = compute_issuance(fund)
    assert np.isnan(f["NOPRIOR"])
    assert np.isnan(f["ZERO"])
    assert not np.isnan(f["OK"])


def test_absent_columns_returns_all_nan():
    """Pre-backfill fundamentals (no shares columns) → all-NaN, never raises."""
    fund = pd.DataFrame([{"ticker": "A", "pe_ratio": 10.0}, {"ticker": "B", "pe_ratio": 20.0}])
    f = compute_issuance(fund)
    assert f.isna().all()


def test_issuance_column_present_in_compute_all_factors():
    """The factor is wired through compute_all_factors and percentile-ranked."""
    rng = np.random.default_rng(0)
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    rows = []
    for t in ("A", "B", "C"):
        px = 100 * np.cumprod(1 + rng.normal(0.0004, 0.012, 300))
        for d, p in zip(dates, px):
            rows.append({"ticker": t, "date": d.date(), "close": p,
                         "adjusted_close": p, "volume": int(1e6)})
    prices = pd.DataFrame(rows)
    fund = pd.DataFrame([
        {"ticker": "A", "shares_outstanding": 90.0,  "shares_outstanding_prior": 100.0},
        {"ticker": "B", "shares_outstanding": 100.0, "shares_outstanding_prior": 100.0},
        {"ticker": "C", "shares_outstanding": 120.0, "shares_outstanding_prior": 100.0},
    ])
    result = compute_all_factors(prices, fund).set_index("ticker")
    assert "issuance" in result.columns
    # Percentile rank preserves the order: A (buyback) highest, C (dilution) lowest.
    assert result.loc["A", "issuance"] > result.loc["C", "issuance"]
