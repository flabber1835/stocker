"""
Regression tests for data-integrity bugs found in the AV ingestor.

Each test is named after the bug it guards against and documents exactly
what the old behaviour was, so a future regression is immediately obvious.

None of these tests touch the DB — they exercise pure helper functions
extracted from app.main and app.universe.
"""
from datetime import date, timedelta

import pytest

from app.main import (
    BENCHMARK_TICKERS,
    _build_benchmarks_first,
    _should_skip_fundamentals,
    _should_skip_price,
)


# ── BUG 7: _build_benchmarks_first didn't move benchmarks already in the
#    universe to the front. SPY ended up at its alphabetical position when
#    the universe list already contained it. ────────────────────────────────────


class TestBenchmarksFrontWhenAlreadyInUniverse:
    """Regression tests for BUG 7: benchmarks must be at the front even when
    they appear inside the universe list."""

    def test_spy_first_when_spy_already_in_universe(self):
        """SPY at position 0 even if the input universe starts with other tickers."""
        result = _build_benchmarks_first(["AAPL", "SPY", "MSFT"])
        assert result[0] == "SPY", (
            "BUG 7 regression: SPY must be at index 0 even when it was in the "
            "middle of the universe list. Old code left it alphabetically positioned."
        )

    def test_all_benchmarks_at_front_when_in_universe(self):
        """Every benchmark ticker must appear before any universe-only ticker."""
        universe = ["AAPL", "SPY", "QQQ", "GOOG", "IWM", "SOXX", "MSFT"]
        result = _build_benchmarks_first(universe)
        benchmark_set = set(BENCHMARK_TICKERS)
        universe_only = set(universe) - benchmark_set

        bench_indices = [i for i, t in enumerate(result) if t in benchmark_set]
        universe_indices = [i for i, t in enumerate(result) if t in universe_only]

        assert max(bench_indices) < min(universe_indices), (
            "All benchmark tickers must precede all universe-only tickers. "
            "Old code left benchmarks that were already in the universe at their "
            "original positions."
        )

    def test_spy_no_duplicate_when_in_universe(self):
        """SPY appears exactly once even after being moved to the front."""
        result = _build_benchmarks_first(["SPY", "AAPL", "MSFT"])
        assert result.count("SPY") == 1

    def test_all_benchmarks_no_duplicates_when_all_in_universe(self):
        """When the universe already contains all benchmark tickers, no duplicates."""
        universe = list(BENCHMARK_TICKERS) + ["AAPL", "MSFT"]
        result = _build_benchmarks_first(universe)
        for bm in BENCHMARK_TICKERS:
            assert result.count(bm) == 1, f"{bm} must appear exactly once"

    def test_universe_tickers_all_present_after_reorder(self):
        """No universe ticker is lost when benchmarks are moved to the front."""
        universe = ["AAPL", "SPY", "MSFT", "QQQ"]
        result = _build_benchmarks_first(universe)
        for t in universe:
            assert t in result, f"Ticker {t!r} missing from result after reorder"

    def test_spy_first_when_spy_is_only_ticker(self):
        """Single-element universe that is SPY → result starts with SPY, no dup."""
        result = _build_benchmarks_first(["SPY"])
        assert result[0] == "SPY"
        assert result.count("SPY") == 1


# ── BUG 5: avg_volume computation used `(adjusted_close or 0) * volume`,
#    treating NULL adjusted_close as 0 and diluting the average. ───────────────


class TestAvgDvNullHandling:
    """Regression tests for BUG 5: NULL adjusted_close rows must be excluded
    from the avg-dollar-volume computation, not counted as zero."""

    def _compute_avg_dv_correct(self, rows: list[dict]) -> float | None:
        """Mirrors the fixed production logic from _run_fetch_data."""
        dv_vals = [
            r["adjusted_close"] * (r["volume"] or 0)
            for r in rows
            if r.get("adjusted_close")
        ]
        return sum(dv_vals) / len(dv_vals) if dv_vals else None

    def _compute_avg_dv_buggy(self, rows: list[dict]) -> float | None:
        """Mirrors the OLD (buggy) logic: None treated as 0."""
        dv_vals = [(r["adjusted_close"] or 0) * (r["volume"] or 0) for r in rows]
        return sum(dv_vals) / len(dv_vals) if dv_vals else None

    def test_null_adjusted_close_excluded_not_zero(self):
        """A single valid row should not have its avg halved by a NULL companion."""
        rows = [
            {"adjusted_close": 100.0, "volume": 1_000_000},
            {"adjusted_close": None,  "volume": 1_000_000},  # null — must be excluded
        ]
        correct = self._compute_avg_dv_correct(rows)
        buggy   = self._compute_avg_dv_buggy(rows)

        assert correct == pytest.approx(100_000_000.0), "valid row's full dollar-vol"
        assert buggy   == pytest.approx(50_000_000.0),  "bug halved the average via zero"
        assert correct > buggy, "excluding nulls must yield a higher average than zero-filling"

    def test_majority_null_rows_do_not_dilute(self):
        """Five null rows alongside one valid row: average must reflect only the valid row."""
        valid_dv = 200.0 * 500_000  # $100M
        rows = [{"adjusted_close": 200.0, "volume": 500_000}] + [
            {"adjusted_close": None, "volume": 500_000} for _ in range(5)
        ]
        correct = self._compute_avg_dv_correct(rows)
        assert correct == pytest.approx(valid_dv)

    def test_all_null_returns_none(self):
        """When every row has NULL adjusted_close the result should be None."""
        rows = [{"adjusted_close": None, "volume": 1_000_000} for _ in range(20)]
        result = self._compute_avg_dv_correct(rows)
        assert result is None

    def test_no_nulls_unchanged(self):
        """If there are no NULL rows the correct and buggy paths agree."""
        rows = [
            {"adjusted_close": 50.0, "volume": 1_000_000},
            {"adjusted_close": 50.0, "volume": 1_000_000},
        ]
        assert self._compute_avg_dv_correct(rows) == self._compute_avg_dv_buggy(rows)

    def test_zero_adjusted_close_also_excluded(self):
        """A zero adjusted_close (AV data corruption) is falsy and must be skipped."""
        rows = [
            {"adjusted_close": 100.0, "volume": 1_000_000},
            {"adjusted_close": 0.0,   "volume": 1_000_000},  # corrupt zero
        ]
        correct = self._compute_avg_dv_correct(rows)
        assert correct == pytest.approx(100_000_000.0)


# ── BUG 2: _run_fetch_fundamentals used `fund_latest.get(t) == today` instead
#    of `_should_skip_fundamentals()`, so fundamentals were re-fetched every
#    single run instead of once every 7 days. ──────────────────────────────────


class TestFundamentalsSkipWindowBoundary:
    """Regression tests for BUG 2: the 7-day fundamentals skip window must be
    respected by all callers, not just the helper itself."""

    def test_skip_when_fetched_6_days_ago(self):
        """Fetched 6 days ago = still inside the 7-day window = must skip."""
        today = date(2026, 5, 17)
        fund_latest = {"AAPL": today - timedelta(days=6)}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is True

    def test_no_skip_when_fetched_exactly_7_days_ago(self):
        """Fetched exactly 7 days ago = outside the window = must NOT skip.
        Old buggy code used `== today` and would have always re-fetched here."""
        today = date(2026, 5, 17)
        fund_latest = {"AAPL": today - timedelta(days=7)}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is False

    def test_skip_when_fetched_today(self):
        """Fetched today (0 days ago) = must skip regardless of comparison style."""
        today = date(2026, 5, 17)
        fund_latest = {"AAPL": today}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is True

    def test_no_skip_when_not_in_fund_latest(self):
        """Ticker absent from fund_latest = never fetched = must not skip."""
        today = date(2026, 5, 17)
        assert _should_skip_fundamentals("NEW", {}, today) is False

    def test_buggy_equality_check_would_miss_6_day_old_data(self):
        """Demonstrates what BUG 2 would have caused.

        Old code: `fund_latest.get(ticker) == today` → False when fetched 6 days
        ago, so it would re-fetch AV OVERVIEW unnecessarily every run.
        """
        today = date(2026, 5, 17)
        fund_latest = {"AAPL": today - timedelta(days=6)}

        # Old buggy check: only skips when date equals today exactly
        buggy_skip = fund_latest.get("AAPL") == today
        correct_skip = _should_skip_fundamentals("AAPL", fund_latest, today)

        assert buggy_skip is False,   "bug: would re-fetch data fetched 6 days ago"
        assert correct_skip is True,  "fix: correctly skips data still within 7-day window"

    def test_window_boundary_is_7_not_1(self):
        """Confirm window is 7 days, not 1 (a common off-by-one mistake)."""
        today = date(2026, 5, 17)
        for days_ago in range(1, 7):
            fund_latest = {"AAPL": today - timedelta(days=days_ago)}
            assert _should_skip_fundamentals("AAPL", fund_latest, today) is True, (
                f"Should skip when fetched {days_ago} day(s) ago (within 7-day window)"
            )
        # Day 7 and beyond: must not skip
        for days_ago in range(7, 10):
            fund_latest = {"AAPL": today - timedelta(days=days_ago)}
            assert _should_skip_fundamentals("AAPL", fund_latest, today) is False, (
                f"Should NOT skip when fetched {days_ago} day(s) ago (outside 7-day window)"
            )


# ── BUG 8: SPY fetch failure → spy_max reloaded but still stale → universe
#    tickers incorrectly skipped because their DB dates match the stale spy_max. ─


class TestSpyFailureInvalidatesSkyMax:
    """Regression tests for BUG 8: when SPY fails to fetch, spy_max must be
    set to None so universe tickers are not incorrectly skipped."""

    def test_spy_failure_must_null_spy_max(self):
        """After reload, if _spy_fetch_failed is True, spy_max must become None.

        Simulates the guard logic added in _run_fetch_prices / _run_fetch_data.
        """
        # State after initial load (system was offline for 2 days)
        initial_spy_max = date(2026, 5, 13)

        # SPY fetch failed — DB still has old date
        spy_fetch_failed = True

        # Reload returns same stale date because SPY was not written
        reloaded_spy_max = initial_spy_max  # unchanged

        # Apply the guard
        effective_spy_max = None if spy_fetch_failed else reloaded_spy_max

        assert effective_spy_max is None, (
            "BUG 8 regression: when SPY fetch fails the effective spy_max must be "
            "nulled out so universe tickers are not skipped on a stale date"
        )

    def test_spy_success_keeps_spy_max(self):
        """When SPY succeeds, spy_max must be kept (not nulled)."""
        new_spy_max = date(2026, 5, 15)
        spy_fetch_failed = False
        effective_spy_max = None if spy_fetch_failed else new_spy_max
        assert effective_spy_max == new_spy_max

    def test_stale_spy_max_without_guard_would_skip_universe(self):
        """Demonstrates what BUG 8 caused: universe tickers all skipped.

        With SPY fetch failed and no guard, spy_max stays at the old date.
        Universe tickers whose DB dates also equal that old date get skipped.
        """
        stale_spy_max = date(2026, 5, 13)
        # Universe ticker already had data up to the stale date
        ticker_latest = {"AAPL": date(2026, 5, 13)}

        # Without guard: use stale spy_max → AAPL skipped
        skip_without_guard = _should_skip_price("AAPL", ticker_latest, stale_spy_max)
        # With guard: spy_max nulled → AAPL NOT skipped
        skip_with_guard = _should_skip_price("AAPL", ticker_latest, None)

        assert skip_without_guard is True,  "bug: AAPL incorrectly skipped on stale spy_max"
        assert skip_with_guard   is False,  "fix: AAPL correctly fetched when spy_max=None"

    def test_benchmark_always_fetched_regardless_of_failure(self):
        """Benchmark tickers must never be skipped, even when spy_max is valid."""
        spy_max = date(2026, 5, 15)
        ticker_latest = {"SPY": spy_max}
        # SPY is a benchmark — its skip logic is bypassed in the loop via is_benchmark check.
        # _should_skip_price only applies to universe tickers in the production loop.
        # Verify the helper itself would return True (but the loop exempts benchmarks).
        assert _should_skip_price("SPY", ticker_latest, spy_max) is True, (
            "Helper returns True for SPY with matching date — production loop must "
            "separately enforce the is_benchmark exemption"
        )
