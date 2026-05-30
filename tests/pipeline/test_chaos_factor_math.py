"""
Chaos/property fuzz of the factor engine math (compute_all_factors and the
individual factor computations) — the per-ticker math that feeds ranking.

Every raw factor is percentile-ranked at the end, so the contract is:
each factor output is NaN or strictly inside (0, 1] — never inf, never >1, never
≤0 — no matter how corrupt the price/fundamental inputs are (zeros, negatives,
NaN, huge values, short history, missing columns, halted tickers). Also asserts
the documented duplicate-(date,ticker) integrity guard raises.
"""
import math
import random

import numpy as np
import pandas as pd
import pytest

from app.factors import (
    compute_all_factors,
    compute_quality,
    compute_value,
    compute_growth,
    compute_momentum,
    compute_low_volatility,
)

FACTOR_COLS = ["momentum", "low_volatility", "liquidity", "quality", "value", "growth"]


def _chaos_price(rng):
    r = rng.random()
    if r < 0.08:
        return 0.0
    if r < 0.12:
        return -rng.uniform(1, 100)         # corrupt negative price
    if r < 0.16:
        return float("nan")
    if r < 0.19:
        return rng.uniform(1e8, 1e10)        # extreme
    return round(rng.uniform(1, 500), 2)


def _chaos_vol(rng):
    r = rng.random()
    if r < 0.1:
        return 0.0
    if r < 0.13:
        return -rng.uniform(1, 1e6)          # corrupt negative volume
    if r < 0.16:
        return float("nan")
    return float(rng.randint(0, 50_000_000))


def _chaos_fund(rng):
    r = rng.random()
    if r < 0.25:
        return float("nan")
    if r < 0.32:
        return 0.0
    if r < 0.42:
        return -rng.uniform(0.1, 500)
    if r < 0.48:
        return rng.uniform(1e6, 1e9)
    return rng.uniform(-50, 200)


def _make_prices(rng):
    n_tickers = rng.randint(1, 25)
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    total_days = rng.randint(1, 400)
    base = pd.Timestamp("2024-01-01")
    dates = [base + pd.Timedelta(days=d) for d in range(total_days)]
    rows = []
    for t in tickers:
        hist = rng.randint(1, total_days)
        for dt in dates[-hist:]:
            rows.append({
                "ticker": t, "date": dt,
                "adjusted_close": _chaos_price(rng),
                "close": _chaos_price(rng),
                "volume": _chaos_vol(rng),
            })
    return pd.DataFrame(rows), tickers


def _make_funds(tickers, rng):
    cols = ["roe", "debt_to_equity", "pe_ratio", "pb_ratio", "revenue_growth", "eps_growth"]
    # sometimes drop columns entirely (sparse fundamentals)
    present = [c for c in cols if rng.random() > 0.2] or [rng.choice(cols)]
    rows = []
    for t in tickers:
        if rng.random() < 0.1:               # ticker missing from fundamentals
            continue
        row = {"ticker": t}
        for c in present:
            row[c] = _chaos_fund(rng)
        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame({"ticker": []})


def _assert_factor_range(series, label):
    for t, v in series.items():
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        assert math.isfinite(v), f"{label}: non-finite {v} for {t}"
        assert 0.0 < v <= 1.0 + 1e-9, f"{label}: {v} out of (0,1] for {t}"


def test_compute_all_factors_fuzz():
    rng = random.Random(31)
    ran = 0
    for _ in range(250):
        prices, tickers = _make_prices(rng)
        funds = _make_funds(tickers, rng)
        out = compute_all_factors(prices, funds)
        ran += 1
        # compute_all_factors returns `ticker` as a column (reset_index at the end)
        assert "ticker" in out.columns
        assert set(out["ticker"]) == set(tickers), "factor ticker set != price tickers"
        for col in FACTOR_COLS:
            assert col in out.columns, f"missing factor column {col}"
            _assert_factor_range(out.set_index("ticker")[col], col)
            # no inf anywhere
            assert not np.isinf(out[col].to_numpy(dtype=float)).any(), f"inf in {col}"
    assert ran == 250


def test_duplicate_date_ticker_raises():
    """Data-integrity guard: pivot() must raise on duplicate (date, ticker)."""
    base = pd.Timestamp("2024-01-01")
    rows = [
        {"ticker": "A", "date": base, "adjusted_close": 10.0, "close": 10.0, "volume": 1000},
        {"ticker": "A", "date": base, "adjusted_close": 11.0, "close": 11.0, "volume": 1000},
    ]
    with pytest.raises(Exception):
        compute_all_factors(pd.DataFrame(rows), pd.DataFrame({"ticker": ["A"]}))


def test_individual_fundamental_factors_fuzz():
    rng = random.Random(37)
    for _ in range(600):
        n = rng.randint(1, 30)
        tickers = [f"F{i:02d}" for i in range(n)]
        funds = _make_funds(tickers, rng)
        if funds.empty or "ticker" not in funds.columns or funds["ticker"].empty:
            continue
        for fn, label in ((compute_quality, "quality"),
                          (compute_value, "value"),
                          (compute_growth, "growth")):
            res = fn(funds)
            _assert_factor_range(res, label)
            assert not np.isinf(res.to_numpy(dtype=float)).any(), f"inf in raw {label}"


def test_momentum_and_lowvol_never_inf():
    rng = random.Random(41)
    for _ in range(400):
        n = rng.randint(1, 15)
        tickers = [f"P{i:02d}" for i in range(n)]
        days = rng.randint(1, 320)
        idx = pd.date_range("2024-01-01", periods=days, freq="D")
        data = {t: [_chaos_price(rng) for _ in range(days)] for t in tickers}
        pivot = pd.DataFrame(data, index=idx)
        for raw in (compute_momentum(pivot), compute_low_volatility(pivot)):
            arr = raw.to_numpy(dtype=float)
            assert not np.isinf(arr).any(), "raw factor produced inf"
