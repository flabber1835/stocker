"""
Tests for _build_benchmarks_first and related ordering helpers in app.main.

These complement tests/av_ingestor/test_main.py which already covers
_build_fetch_data_price_tickers / _build_fetch_prices_all_tickers.

We test _build_benchmarks_first directly because it is the canonical
implementation of the "benchmarks come first" ordering guarantee.
"""
import pytest

from app.main import _build_benchmarks_first, BENCHMARK_TICKERS


# ── _build_benchmarks_first ───────────────────────────────────────────────────

class TestBuildBenchmarksFirst:

    def test_benchmarks_at_front(self):
        """Benchmark tickers that are not in the universe are prepended."""
        universe = ["AAPL", "MSFT", "GOOG"]
        result = _build_benchmarks_first(universe)
        # All benchmark tickers must appear before the first universe ticker
        benchmark_indices = [i for i, t in enumerate(result) if t in set(BENCHMARK_TICKERS)]
        universe_only = [t for t in universe if t not in set(BENCHMARK_TICKERS)]
        universe_indices = [i for i, t in enumerate(result) if t in set(universe_only)]
        if benchmark_indices and universe_indices:
            assert max(benchmark_indices) < min(universe_indices), (
                "All benchmark tickers must precede all universe-only tickers"
            )

    def test_spy_is_first(self):
        """SPY (the first benchmark ticker) must appear at position 0."""
        result = _build_benchmarks_first(["AAPL", "MSFT"])
        assert result[0] == "SPY", f"Expected SPY at index 0, got {result[0]!r}"

    def test_adds_missing_benchmarks(self):
        """Benchmark tickers absent from the universe are added to the front."""
        universe = ["AAPL", "MSFT"]
        result = _build_benchmarks_first(universe)
        for bm in BENCHMARK_TICKERS:
            assert bm in result, f"Benchmark {bm!r} should be in result even if not in universe"

    def test_no_duplication_when_universe_contains_benchmark(self):
        """If the universe already contains a benchmark ticker, it must not appear twice."""
        universe = ["SPY", "AAPL", "MSFT"]
        result = _build_benchmarks_first(universe)
        assert result.count("SPY") == 1, "SPY must appear exactly once"

    def test_no_duplication_for_all_benchmarks(self):
        """None of the benchmark tickers should be duplicated."""
        # Universe includes all benchmarks
        universe = list(BENCHMARK_TICKERS) + ["AAPL", "MSFT"]
        result = _build_benchmarks_first(universe)
        for bm in BENCHMARK_TICKERS:
            assert result.count(bm) == 1, f"{bm!r} must appear exactly once"

    def test_universe_tickers_preserved(self):
        """All universe tickers are present in the result."""
        universe = ["AAPL", "MSFT", "GOOG", "AMZN"]
        result = _build_benchmarks_first(universe)
        for ticker in universe:
            assert ticker in result, f"Universe ticker {ticker!r} missing from result"

    def test_empty_universe_returns_only_benchmarks(self):
        """An empty universe produces a list containing only the benchmark tickers."""
        result = _build_benchmarks_first([])
        assert set(result) == set(BENCHMARK_TICKERS)

    def test_universe_order_preserved_after_benchmarks(self):
        """
        The relative order of universe tickers must be preserved after the
        benchmark prefix — insertion order in the universe list is maintained.
        """
        universe = ["AMZN", "AAPL", "TSLA"]
        result = _build_benchmarks_first(universe)
        # Strip out benchmark tickers to isolate the universe portion
        universe_portion = [t for t in result if t not in set(BENCHMARK_TICKERS)]
        assert universe_portion == universe, (
            "Universe tickers must appear in their original order after benchmarks"
        )

    def test_result_is_list(self):
        """Return type must be a list."""
        result = _build_benchmarks_first(["AAPL"])
        assert isinstance(result, list)

    def test_benchmarks_contiguous_at_front(self):
        """
        Extra benchmarks (those missing from the universe) are all prepended
        together, forming a contiguous block at the start.
        """
        universe = ["AAPL"]  # no benchmarks in universe
        result = _build_benchmarks_first(universe)
        # The first len(BENCHMARK_TICKERS) elements must be the benchmarks
        # (since none of them were in the universe, they are all prepended)
        front_block = set(result[: len(BENCHMARK_TICKERS)])
        assert front_block == set(BENCHMARK_TICKERS), (
            "All benchmark tickers must form the leading block"
        )
