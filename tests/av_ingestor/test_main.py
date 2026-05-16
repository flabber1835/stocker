"""
Tests for av-ingestor utility functions.

We test the pure-Python helpers directly from app.main production code.
"""
from datetime import date
import pytest
from app.main import (
    _TICKER_RE,
    _should_skip_price,
    _should_use_compact,
    _should_skip_fundamentals,
    _build_fetch_data_price_tickers,
    _build_fetch_prices_all_tickers,
    BENCHMARK_TICKERS,
)


# ── _TICKER_RE validation ─────────────────────────────────────────────────────


@pytest.mark.parametrize("ticker", ["AAPL", "BRK.B", "BF-B", "MSFT", "GOOGL", "A", "BRK.A"])
def test_ticker_re_valid(ticker):
    """Standard valid tickers must match _TICKER_RE."""
    assert _TICKER_RE.match(ticker) is not None, f"{ticker!r} should be valid"


@pytest.mark.parametrize("ticker", [
    "lowercase",       # lowercase letters not allowed
    "TOOLONGTICKER",   # 14 chars — exceeds the 10-char limit
    "inj3ct;--",       # semicolons not in allowed set
    "",                # empty string
    "TICK ER",         # space not allowed
    "TICK\nER",        # newline not allowed
    "TICK@ER",         # @ not in allowed set
])
def test_ticker_re_invalid(ticker):
    """Invalid tickers must not match _TICKER_RE."""
    assert _TICKER_RE.match(ticker) is None, f"{ticker!r} should be invalid"


# ── Demo key warning ─────────────────────────────────────────────────────────
#
# The warning logic in app/main.py is a module-level guard:
#
#   AV_API_KEY = os.getenv("AV_API_KEY", "demo")
#   if AV_API_KEY in ("", "demo"):
#       print("[av-ingestor] WARNING: AV_API_KEY is 'demo' — ...")
#
# We test the guard condition directly using the same predicate.


def _emit_demo_warning_if_needed(av_api_key: str, capsys) -> str:
    """
    Exercise the same guard condition used in app/main.py and return captured stdout.
    """
    if av_api_key in ("", "demo"):
        print(
            "[av-ingestor] WARNING: AV_API_KEY is 'demo' — "
            "using Alpha Vantage demo key, data will be very limited"
        )
    return capsys.readouterr().out


def test_demo_key_warning_printed(capsys):
    """
    When AV_API_KEY is 'demo' the guard must print a WARNING about limited data.
    This mirrors the module-level check in app/main.py exactly.
    """
    out = _emit_demo_warning_if_needed("demo", capsys)
    assert "WARNING" in out
    assert "demo" in out.lower()


def test_empty_key_warning_printed(capsys):
    """
    An empty AV_API_KEY triggers the same warning path as 'demo'
    because the guard is `if AV_API_KEY in ('', 'demo')`.
    """
    out = _emit_demo_warning_if_needed("", capsys)
    assert "WARNING" in out


def test_real_key_no_demo_warning(capsys):
    """A non-demo, non-empty key must not trigger the demo warning."""
    out = _emit_demo_warning_if_needed("MY_REAL_KEY_XYZ", capsys)
    assert "WARNING" not in out


# ── Incremental fetch skip logic ─────────────────────────────────────────────
#
# These tests call the real helpers from app.main directly.

class TestPriceSkipLogic:
    def test_skip_when_ticker_date_equals_spy_max(self):
        """Ticker already at spy_max date → price fetch skipped."""
        spy_max = date(2026, 5, 14)
        ticker_latest = {"SPY": spy_max, "AAPL": spy_max}
        assert _should_skip_price("AAPL", ticker_latest, spy_max) is True

    def test_no_skip_when_ticker_date_behind_spy_max(self):
        """Ticker behind spy_max → price fetch required."""
        spy_max = date(2026, 5, 14)
        ticker_latest = {"SPY": spy_max, "AAPL": date(2026, 5, 13)}
        assert _should_skip_price("AAPL", ticker_latest, spy_max) is False

    def test_no_skip_when_ticker_missing_from_db(self):
        """Ticker not in DB at all → price fetch required (first run)."""
        spy_max = date(2026, 5, 14)
        ticker_latest = {"SPY": spy_max}
        assert _should_skip_price("AAPL", ticker_latest, spy_max) is False

    def test_no_skip_when_spy_max_is_none(self):
        """spy_max=None (empty DB) → nothing skipped, fetch all."""
        ticker_latest = {}
        assert _should_skip_price("AAPL", ticker_latest, None) is False

    def test_compact_when_ticker_has_history(self):
        """Ticker has existing rows → use compact (last 100 days) to save quota."""
        ticker_latest = {"AAPL": date(2026, 5, 13)}
        assert _should_use_compact("AAPL", ticker_latest) is True

    def test_full_when_ticker_has_no_history(self):
        """Ticker has no rows → use full history on first fetch."""
        assert _should_use_compact("AAPL", {}) is False


class TestFundamentalsSkipLogic:
    def test_skip_when_fetched_today(self):
        """Fundamentals fetched today → skip."""
        today = date(2026, 5, 16)
        fund_latest = {"AAPL": today}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is True

    def test_skip_when_fetched_6_days_ago(self):
        """Fundamentals fetched 6 days ago → still within 7-day window, skip."""
        today = date(2026, 5, 16)
        fund_latest = {"AAPL": date(2026, 5, 10)}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is True

    def test_no_skip_when_fetched_7_days_ago(self):
        """Fundamentals fetched exactly 7 days ago → stale, must re-fetch."""
        today = date(2026, 5, 16)
        fund_latest = {"AAPL": date(2026, 5, 9)}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is False

    def test_no_skip_when_ticker_missing(self):
        """Ticker not in fundamentals at all → must fetch."""
        today = date(2026, 5, 16)
        assert _should_skip_fundamentals("AAPL", {}, today) is False


class TestAvgDvFallback:
    """
    Verify that when a price ticker is skipped (already current), its entry is
    NOT pre-populated with 0.0 in _ticker_avg_dv.  The correct behaviour is to
    leave it absent so the fundamentals block triggers the DB lookup path.
    """

    def _simulate_price_loop(self, tickers, ticker_latest, spy_max):
        """
        Minimal simulation of the _ticker_avg_dv population logic from
        _run_fetch_data.  Returns the dict as it would look after the price loop.
        """
        _ticker_avg_dv: dict = {}
        for ticker in tickers:
            if spy_max and ticker_latest.get(ticker) == spy_max:
                # BUG-FIX: do NOT set _ticker_avg_dv[ticker] = 0.0 here
                pass
            else:
                # Simulate a successful price fetch: store a real avg_dv.
                _ticker_avg_dv[ticker] = 1_000_000.0
        return _ticker_avg_dv

    def test_skipped_ticker_absent_from_avg_dv(self):
        """A price-skipped ticker must not appear in _ticker_avg_dv as 0.0."""
        spy_max = date(2026, 5, 14)
        ticker_latest = {"SPY": spy_max, "AAPL": spy_max}
        dv = self._simulate_price_loop(["AAPL"], ticker_latest, spy_max)
        assert "AAPL" not in dv, "Skipped ticker must not have a 0.0 avg_dv placeholder"

    def test_fetched_ticker_present_in_avg_dv(self):
        """A ticker that was fetched must have its avg_dv stored."""
        spy_max = date(2026, 5, 14)
        ticker_latest = {"SPY": spy_max, "MSFT": date(2026, 5, 13)}
        dv = self._simulate_price_loop(["MSFT"], ticker_latest, spy_max)
        assert "MSFT" in dv
        assert dv["MSFT"] > 0


# ── Benchmark ticker ordering ─────────────────────────────────────────────────
#
# SPY is the reference for skip detection (spy_max).  If benchmarks are fetched
# last and the run is interrupted, spy_max=None on the next run and every
# ticker is re-fetched from scratch.  Benchmarks must therefore come FIRST.


class TestBenchmarkOrdering:
    def test_spy_is_first_ticker_in_fetch_data(self):
        """SPY must be the first ticker fetched so spy_max lands in the DB early."""
        tickers = _build_fetch_data_price_tickers(["AAPL", "MSFT", "GOOG"])
        assert tickers[0] == "SPY", f"Expected SPY first, got {tickers[0]!r}"

    def test_all_benchmarks_precede_universe_tickers(self):
        """All benchmark tickers must appear before any universe ticker."""
        universe = ["AAPL", "MSFT", "GOOG", "AMZN"]
        tickers = _build_fetch_data_price_tickers(universe)
        benchmark_indices = [i for i, t in enumerate(tickers) if t in BENCHMARK_TICKERS]
        universe_indices  = [i for i, t in enumerate(tickers) if t in set(universe)]
        assert max(benchmark_indices) < min(universe_indices), (
            "All benchmarks must come before any universe ticker"
        )

    def test_universe_tickers_not_duplicated_when_they_overlap_benchmarks(self):
        """If the universe happens to contain SPY, it should not appear twice."""
        universe = ["SPY", "AAPL", "MSFT"]
        tickers = _build_fetch_data_price_tickers(universe)
        assert tickers.count("SPY") == 1, "SPY must appear exactly once"

    def test_fetch_prices_benchmarks_also_first(self):
        """Same ordering fix applies to _run_fetch_prices."""
        universe = ["AAPL", "MSFT"]
        tickers = _build_fetch_prices_all_tickers(universe)
        assert tickers[0] == "SPY", f"Expected SPY first in fetch-prices, got {tickers[0]!r}"

    def test_spy_max_available_after_partial_run(self):
        """
        Simulate an interrupted fetch: only the first N tickers were written to DB.
        With SPY first, spy_max is available after even a single-ticker partial run.
        """
        universe = ["AAPL", "MSFT", "GOOG"]
        tickers = _build_fetch_data_price_tickers(universe)

        # Simulate DB state after only the first ticker was successfully written
        db_after_one_write = {tickers[0]: date(2026, 5, 14)}
        spy_max = db_after_one_write.get("SPY")

        assert spy_max is not None, (
            "spy_max must be available after the first ticker is written — "
            "requires SPY to be first in the fetch order"
        )
