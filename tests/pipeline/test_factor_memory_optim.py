"""Regression tests for the factor-step memory optimization (copy_input=False).

The pipeline OOM-loop traced to compute_all_factors holding a *second*
universe-scale copy of the price frame at peak. The fix lets the pipeline hand
off a disposable frame (copy_input=False) so the sort happens in place. These
tests pin the contract: output MUST be identical to the default path, and only
the opt-in path is allowed to mutate the caller's frame.
"""
import os
import sys

import pandas as pd

# Reuse the project's path bootstrap + frame builders from the step-sequence tests.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline"))

from app.factors import compute_all_factors  # noqa: E402


def _prices_long(tickers, n=300):
    dates = pd.bdate_range("2024-01-01", periods=n)
    rows = []
    for ti, t in enumerate(tickers):
        for di, d in enumerate(dates):
            # Deterministic, ticker-distinct trajectory so factors are non-degenerate.
            price = 100.0 + ti * 5 + di * 0.1 + (di % 7) * 0.3
            rows.append({"ticker": t, "date": d.date(), "close": price,
                         "adjusted_close": price, "volume": 1_000_000 + ti})
    return pd.DataFrame(rows)


def _fund(tickers):
    return pd.DataFrame([
        {"ticker": t, "pe_ratio": 15.0 + i, "pb_ratio": 2.0 + i * 0.1,
         "roe": 0.2 - i * 0.01, "debt_to_equity": 0.5 + i * 0.05,
         "revenue_growth": 0.1 + i * 0.01, "eps_growth": 0.12 + i * 0.01}
        for i, t in enumerate(tickers)
    ])


def test_copy_input_false_output_identical():
    """copy_input=False must produce byte-for-byte the same factor table as the
    default copy_input=True path. This is the safety guarantee for the OOM fix."""
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    fund = _fund(tickers)

    # Independent frames so the in-place path can't disturb the reference run.
    res_default = compute_all_factors(_prices_long(tickers), fund.copy(), copy_input=True)
    res_inplace = compute_all_factors(_prices_long(tickers), fund.copy(), copy_input=False)

    pd.testing.assert_frame_equal(
        res_default.sort_values("ticker").reset_index(drop=True),
        res_inplace.sort_values("ticker").reset_index(drop=True),
    )


def test_default_does_not_mutate_caller_frame():
    """Default copy_input=True must preserve the no-mutation contract every other
    caller/test relies on (row order unchanged)."""
    tickers = ["AAA", "BBB"]
    prices = _prices_long(tickers)
    before = prices.copy()
    compute_all_factors(prices, _fund(tickers))  # default True
    pd.testing.assert_frame_equal(prices, before)


def test_copy_input_false_may_mutate_caller_frame():
    """copy_input=False is allowed to mutate (sort) the disposable frame in place —
    that is the whole point (no second universe-scale copy). Document it explicitly."""
    # Build with tickers deliberately out of sorted order so an in-place sort is visible.
    prices = pd.concat([_prices_long(["ZZZ"]), _prices_long(["AAA"])], ignore_index=True)
    before_order = prices["ticker"].tolist()
    compute_all_factors(prices, _fund(["AAA", "ZZZ"]), copy_input=False)
    after_order = prices["ticker"].tolist()
    # The frame was sorted in place by (ticker, date), so the original ZZZ-first
    # ordering must have changed. (If pandas ever stops sorting in place this flags it.)
    assert before_order != after_order
    assert after_order == sorted(after_order)
