"""Earnings-surprise (PEAD) factor: SUE, point-in-time, drift window, ranking.

"Buy winners (beats) / sell losers (misses)" — verifies the factor scores recent
beats high and misses low, never looks ahead (reported_date <= score_date), and
neutralizes stale (drifted-out) reports.
"""
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from factors import compute_earnings_surprise, compute_all_factors  # noqa: E402


def _q(ticker, reported_date, reported_eps, estimated_eps):
    return {"ticker": ticker, "reported_date": reported_date,
            "reported_eps": reported_eps, "estimated_eps": estimated_eps}


def _history(ticker, latest_rep, latest_est, latest_date="2026-06-10"):
    """6 flat (no-surprise) quarters + a latest quarter, so SUE is well-defined."""
    rows = [_q(ticker, f"2024-{m:02d}-15", 1.0, 1.0) for m in (3, 6, 9, 12)]
    rows += [_q(ticker, "2025-03-15", 1.0, 1.0), _q(ticker, "2025-09-15", 1.0, 1.0)]
    rows.append(_q(ticker, latest_date, latest_rep, latest_est))
    return rows


def test_beat_scores_higher_than_miss():
    rows = _history("BEAT", 1.5, 1.0) + _history("MISS", 0.5, 1.0)
    s = compute_earnings_surprise(pd.DataFrame(rows), date(2026, 6, 27))
    assert s["BEAT"] > 0 > s["MISS"]
    assert s["BEAT"] > s["MISS"]


def test_drift_window_neutralizes_stale_reports():
    # A big beat reported >90 days before the score date has already drifted → NaN.
    rows = _history("OLD", 2.0, 1.0, latest_date="2026-01-01")
    s = compute_earnings_surprise(pd.DataFrame(rows), date(2026, 6, 27), drift_window_days=90)
    assert np.isnan(s["OLD"])


def test_point_in_time_no_lookahead():
    # As of a date BEFORE the latest report, that report must be invisible. With only
    # the older (in this construction, out-of-window) quarters visible → NaN.
    rows = _history("X", 3.0, 1.0, latest_date="2026-06-20")
    s_after = compute_earnings_surprise(pd.DataFrame(rows), date(2026, 6, 27))
    s_before = compute_earnings_surprise(pd.DataFrame(rows), date(2026, 6, 15))
    assert s_after["X"] > 0                      # beat is visible after the report
    assert np.isnan(s_before.get("X"))           # invisible (and prior quarter out of window)


def test_empty_or_missing_returns_empty():
    assert compute_earnings_surprise(pd.DataFrame(), date(2026, 6, 27)).empty
    assert compute_earnings_surprise(None, date(2026, 6, 27)).empty


def test_fallback_when_too_few_quarters():
    # One quarter only → can't compute a stdev; falls back to normalized surprise.
    rows = [_q("NEW", "2026-06-10", 1.2, 1.0)]
    s = compute_earnings_surprise(pd.DataFrame(rows), date(2026, 6, 27), min_quarters_for_sue=6)
    assert s["NEW"] > 0                          # a beat still registers via fallback


def test_factor_ranks_into_0_1_and_beat_tops_miss():
    # End-to-end through compute_all_factors: the percentiled factor puts the beat
    # above the miss in [0,1].
    prices = pd.DataFrame([
        {"ticker": t, "date": d, "adjusted_close": 100.0, "close": 100.0, "volume": 1e6}
        for t in ("BEAT", "MISS")
        for d in pd.date_range("2025-01-01", periods=300, freq="D")
    ])
    funds = pd.DataFrame([{"ticker": "BEAT"}, {"ticker": "MISS"}])
    earn = pd.DataFrame(_history("BEAT", 1.6, 1.0) + _history("MISS", 0.4, 1.0))
    out = compute_all_factors(prices, funds, earnings=earn, as_of_date=date(2026, 6, 27))
    es = out.set_index("ticker")["earnings_surprise"]
    assert 0.0 <= es["MISS"] < es["BEAT"] <= 1.0


def test_factor_neutral_when_no_earnings_passed():
    # No earnings arg → the factor column is all-NaN (inert / renormalized out).
    prices = pd.DataFrame([
        {"ticker": "A", "date": d, "adjusted_close": 100.0, "close": 100.0, "volume": 1e6}
        for d in pd.date_range("2025-01-01", periods=300, freq="D")
    ])
    out = compute_all_factors(prices, pd.DataFrame([{"ticker": "A"}]))
    assert out.set_index("ticker")["earnings_surprise"].isna().all()
