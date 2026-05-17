"""
Regression tests for compute_liquidity bugs found in the factor engine review.

H2: liquidity used adjusted_close × volume instead of close × volume.
    adjusted_close is split-adjusted; a post-split stock's dollar volume was
    10x understated. Tests prove the score tracks close×volume, not adjusted.

H4: tail(window) takes the last N rows by position, not by date. A halted
    or delisted stock with old rows in the DB would get a valid liquidity
    score from stale data. Tests prove stale tickers are excluded.

Also covers: log1p transformation, empty-input handling, window size contract.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.factors import compute_liquidity


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_prices_long(
    tickers: list[str],
    n_days: int = 30,
    close: float = 100.0,
    adjusted_close: float = 100.0,
    volume: int = 1_000_000,
    reference_date: date | None = None,
) -> pd.DataFrame:
    """Build a prices_long DataFrame with identical values for every ticker."""
    if reference_date is None:
        reference_date = date(2026, 5, 15)
    dates = [reference_date - timedelta(days=i) for i in range(n_days - 1, -1, -1)]
    rows = []
    for ticker in tickers:
        for d in dates:
            rows.append({
                "ticker": ticker,
                "date": pd.Timestamp(d),
                "close": close,
                "adjusted_close": adjusted_close,
                "volume": volume,
            })
    return pd.DataFrame(rows)


# ── H2: must use close not adjusted_close ────────────────────────────────────


class TestLiquidityUsesClose:
    """Regression tests for H2: dollar volume must use unadjusted close price."""

    def test_score_differs_when_close_vs_adjusted_close_differ(self):
        """When close ≠ adjusted_close the liquidity score must track close.

        Scenario: a stock had a 10:1 split so adjusted_close = close / 10.
        The actual dollars that traded are based on close (the real price),
        not adjusted_close.
        """
        close_price      = 100.0
        adjusted_price   = 10.0   # 10:1 split
        volume           = 1_000_000

        # Build prices_long with split-adjusted prices
        df = _make_prices_long(["SPLIT"], close=close_price,
                               adjusted_close=adjusted_price, volume=volume)

        score = compute_liquidity(df, window=20)

        # The correct score is log1p(close × volume) = log1p(100M)
        expected = np.log1p(close_price * volume)

        assert "SPLIT" in score.index, "SPLIT ticker must produce a score"
        assert score["SPLIT"] == pytest.approx(expected, rel=1e-6), (
            "H2 regression: liquidity must be based on close×volume, not "
            f"adjusted_close×volume. Expected log1p({close_price}×{volume}) = "
            f"{expected:.4f}, got {score['SPLIT']:.4f}"
        )

    def test_adjusted_close_score_would_be_lower_after_split(self):
        """Demonstrates the magnitude of the H2 bug for a 10:1 split.

        Old code produced a score 10x too small (log scale still differs ~2.3).
        """
        close_price    = 100.0
        adjusted_price = 10.0
        volume         = 1_000_000

        correct_score  = np.log1p(close_price    * volume)
        buggy_score    = np.log1p(adjusted_price * volume)

        assert correct_score > buggy_score, (
            "Using adjusted_close for a recently split stock underestimates "
            "dollar volume, producing an artificially low liquidity score."
        )
        # The difference is log1p(100M) - log1p(10M) ≈ 2.3 (one decade on log scale)
        assert correct_score - buggy_score == pytest.approx(np.log(10), rel=0.01)

    def test_no_split_both_columns_identical(self):
        """When close == adjusted_close the score is consistent (regression baseline)."""
        df = _make_prices_long(["NORMAL"], close=50.0, adjusted_close=50.0, volume=2_000_000)
        score = compute_liquidity(df, window=20)
        expected = np.log1p(50.0 * 2_000_000)
        assert score["NORMAL"] == pytest.approx(expected, rel=1e-6)

    def test_two_tickers_split_vs_unsplit_relative_ordering(self):
        """A split stock and an unsplit stock with equal real dollar volume must
        score equally — only if we use close, not adjusted_close."""
        # Both trade $100M in dollar volume per day (close × volume)
        df_split   = _make_prices_long(["SPLIT"],   close=100.0, adjusted_close=10.0,  volume=1_000_000)
        df_unsplit = _make_prices_long(["UNSPLIT"],  close=10.0,  adjusted_close=10.0,  volume=10_000_000)

        df = pd.concat([df_split, df_unsplit], ignore_index=True)
        score = compute_liquidity(df, window=20)

        # Both have close×volume = 100M → equal liquidity
        assert score["SPLIT"] == pytest.approx(score["UNSPLIT"], rel=1e-6), (
            "H2 regression: two stocks with equal real dollar-volume must score "
            "equally when using close. Old adjusted_close code would score SPLIT "
            "10x lower than UNSPLIT."
        )


# ── H4: stale tickers must be excluded (tail by date, not by count) ───────────


class TestLiquidityStalenessFilter:
    """Regression tests for H4: tickers with stale data must not receive a
    liquidity score just because they have some old rows in the DB."""

    def _make_fresh_and_stale(
        self,
        fresh_days_back: int = 0,
        stale_days_back: int = 60,
        n_rows: int = 25,
        window: int = 20,
    ) -> pd.Series:
        """Build prices_long with one fresh ticker and one stale ticker."""
        reference = date(2026, 5, 15)
        fresh_latest = reference - timedelta(days=fresh_days_back)
        stale_latest = reference - timedelta(days=stale_days_back)

        rows = []
        for i in range(n_rows):
            rows.append({
                "ticker": "FRESH",
                "date": pd.Timestamp(fresh_latest - timedelta(days=(n_rows - 1 - i))),
                "close": 100.0,
                "adjusted_close": 100.0,
                "volume": 1_000_000,
            })
            rows.append({
                "ticker": "STALE",
                "date": pd.Timestamp(stale_latest - timedelta(days=(n_rows - 1 - i))),
                "close": 100.0,
                "adjusted_close": 100.0,
                "volume": 1_000_000,
            })

        df = pd.DataFrame(rows)
        return compute_liquidity(df, window=window, max_staleness_days=7)

    def test_stale_ticker_excluded_from_score(self):
        """A ticker whose latest data is 60 days old must not appear in the output."""
        score = self._make_fresh_and_stale(fresh_days_back=0, stale_days_back=60)
        assert "STALE" not in score.index or pd.isna(score.get("STALE")), (
            "H4 regression: STALE ticker (60 days old data) must not get a "
            "liquidity score. Old tail(window) code would score it from stale rows."
        )

    def test_fresh_ticker_retained(self):
        """A fresh ticker must always receive a score regardless of staleness filter."""
        score = self._make_fresh_and_stale(fresh_days_back=0, stale_days_back=60)
        assert "FRESH" in score.index and pd.notna(score["FRESH"]), (
            "FRESH ticker (current data) must receive a liquidity score"
        )

    def test_ticker_at_staleness_boundary_excluded(self):
        """A ticker exactly at max_staleness_days + 1 must be excluded."""
        score = self._make_fresh_and_stale(fresh_days_back=0, stale_days_back=8)
        # 8 days > 7 day threshold → stale
        assert "STALE" not in score.index or pd.isna(score.get("STALE")), (
            "Ticker with data 8 days old must be excluded (threshold=7 days)"
        )

    def test_ticker_within_staleness_boundary_retained(self):
        """A ticker with data 6 days old (within threshold) must be retained."""
        reference = date(2026, 5, 15)
        n_rows = 25
        rows = []
        for i in range(n_rows):
            rows.append({
                "ticker": "FRESH",
                "date": pd.Timestamp(reference - timedelta(days=(n_rows - 1 - i))),
                "close": 100.0, "adjusted_close": 100.0, "volume": 1_000_000,
            })
            # MARGINAL: latest date is reference - 6 days (within 7-day window)
            latest = reference - timedelta(days=6)
            rows.append({
                "ticker": "MARGINAL",
                "date": pd.Timestamp(latest - timedelta(days=(n_rows - 1 - i))),
                "close": 100.0, "adjusted_close": 100.0, "volume": 1_000_000,
            })
        df = pd.DataFrame(rows)
        score = compute_liquidity(df, window=20, max_staleness_days=7)
        assert "MARGINAL" in score.index and pd.notna(score.get("MARGINAL")), (
            "Ticker with data 6 days old (within 7-day threshold) must not be excluded"
        )

    def test_without_staleness_guard_stale_ticker_would_score(self):
        """Demonstrates the H4 bug: without the date guard, tail(window)
        returns old rows and the stale ticker gets a non-NaN score."""
        reference = date(2026, 5, 15)
        stale_latest = reference - timedelta(days=60)
        n_rows = 25

        rows = []
        for i in range(n_rows):
            rows.append({
                "ticker": "FRESH",
                "date": pd.Timestamp(reference - timedelta(days=(n_rows - 1 - i))),
                "close": 100.0, "adjusted_close": 100.0, "volume": 1_000_000,
            })
            rows.append({
                "ticker": "STALE",
                "date": pd.Timestamp(stale_latest - timedelta(days=(n_rows - 1 - i))),
                "close": 100.0, "adjusted_close": 100.0, "volume": 1_000_000,
            })
        df = pd.DataFrame(rows)

        # Using a very large staleness window effectively disables the guard
        score_without_guard = compute_liquidity(df, window=20, max_staleness_days=9999)
        # With correct guard
        score_with_guard = compute_liquidity(df, window=20, max_staleness_days=7)

        assert pd.notna(score_without_guard.get("STALE")), (
            "Without the guard, stale ticker is scored (this is the old buggy behavior)"
        )
        assert "STALE" not in score_with_guard.index or pd.isna(score_with_guard.get("STALE")), (
            "With the guard, stale ticker must be excluded"
        )

    def test_stale_excluded_when_fresh_anchor_present(self):
        """Stale ticker is excluded when a fresh anchor (like SPY) anchors the reference date.

        In production, prices_long always contains SPY whose latest date defines the
        reference. A halted stock with data 60 days old is excluded relative to SPY.
        If the only ticker in the dataset is stale, the reference date IS that stale
        date — the filter is relative, not absolute. This test reflects the realistic case.
        """
        reference = date(2026, 5, 15)
        rows = []
        # Fresh anchor: latest date = reference
        for i in range(25):
            rows.append({
                "ticker": "SPY",
                "date": pd.Timestamp(reference - timedelta(days=24 - i)),
                "close": 450.0, "adjusted_close": 450.0, "volume": 50_000_000,
            })
        # Stale ticker: latest date = 60 days before reference
        stale_latest = reference - timedelta(days=60)
        for i in range(25):
            rows.append({
                "ticker": "HALT",
                "date": pd.Timestamp(stale_latest - timedelta(days=24 - i)),
                "close": 10.0, "adjusted_close": 10.0, "volume": 100_000,
            })
        df = pd.DataFrame(rows)
        score = compute_liquidity(df, window=20, max_staleness_days=7)
        assert "SPY" in score.index and pd.notna(score["SPY"]), "fresh anchor must score"
        assert "HALT" not in score.index or pd.isna(score.get("HALT")), (
            "halted ticker (60 days old) must be excluded when SPY anchors the reference date"
        )


# ── Correctness baseline ──────────────────────────────────────────────────────


class TestLiquidityMath:
    """Tests for the mathematical correctness of the liquidity computation."""

    def test_log1p_of_avg_dollar_volume(self):
        """Score must equal log(1 + mean(close × volume)) over the window."""
        close, volume = 150.0, 2_000_000
        n_days, window = 30, 20
        df = _make_prices_long(["AAPL"], n_days=n_days, close=close,
                               adjusted_close=close, volume=volume)
        score = compute_liquidity(df, window=window)
        expected = np.log1p(close * volume)  # all rows identical → mean = row value
        assert score["AAPL"] == pytest.approx(expected, rel=1e-6)

    def test_higher_dollar_volume_higher_score(self):
        """A ticker with 10x more dollar volume must have a strictly higher score."""
        df_low  = _make_prices_long(["LOW"],  close=10.0,  volume=100_000)
        df_high = _make_prices_long(["HIGH"], close=100.0, volume=1_000_000)
        df = pd.concat([df_low, df_high], ignore_index=True)
        score = compute_liquidity(df, window=20)
        assert score["HIGH"] > score["LOW"]

    def test_window_uses_last_n_rows(self):
        """Liquidity is computed from the last `window` rows only, not all rows."""
        reference = date(2026, 5, 15)
        rows = []
        for i in range(40):
            d = reference - timedelta(days=39 - i)
            # First 20 rows: low volume; last 20 rows: high volume
            volume = 100_000 if i < 20 else 1_000_000
            rows.append({"ticker": "T", "date": pd.Timestamp(d),
                         "close": 100.0, "adjusted_close": 100.0, "volume": volume})
        df = pd.DataFrame(rows)
        score = compute_liquidity(df, window=20)
        expected = np.log1p(100.0 * 1_000_000)  # only last 20 rows counted
        assert score["T"] == pytest.approx(expected, rel=1e-6)

    def test_empty_dataframe_returns_empty_series(self):
        """Empty input must not raise — return an empty Series."""
        df = pd.DataFrame(columns=["ticker", "date", "close", "adjusted_close", "volume"])
        score = compute_liquidity(df, window=20)
        assert isinstance(score, pd.Series)
        assert score.empty

    def test_score_is_always_non_negative(self):
        """log1p of a non-negative value is always non-negative."""
        df = _make_prices_long(["A", "B", "C"], close=50.0, volume=500_000)
        score = compute_liquidity(df, window=20)
        assert (score >= 0).all()
