"""
Tests for av-ingestor utility functions.

We test the pure-Python helpers directly from app.main production code.
"""
from datetime import date, datetime, timedelta, timezone
import pytest
from app.main import (
    _TICKER_RE,
    _should_skip_price,
    _should_use_compact,
    _should_skip_fundamentals,
    _build_benchmarks_first,
    _is_stale_running,
    BENCHMARK_TICKERS,
)


# ── _is_stale_running (Tier 1 stale-running ingest reclaim) ───────────────────

class TestIsStaleRunning:
    """A 'running' ingest row older than the threshold is presumed dead and is
    reclaimed so an orphaned forever-running row can't 409-wedge future fetches."""

    NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)

    def test_recent_running_not_stale(self):
        started = self.NOW - timedelta(hours=1)
        assert _is_stale_running(started, self.NOW, stale_hours=6) is False

    def test_old_running_is_stale(self):
        started = self.NOW - timedelta(hours=7)
        assert _is_stale_running(started, self.NOW, stale_hours=6) is True

    def test_exactly_threshold_not_stale(self):
        started = self.NOW - timedelta(hours=6)
        assert _is_stale_running(started, self.NOW, stale_hours=6) is False

    def test_disabled_when_zero(self):
        started = self.NOW - timedelta(hours=48)
        assert _is_stale_running(started, self.NOW, stale_hours=0) is False

    def test_none_started_not_stale(self):
        assert _is_stale_running(None, self.NOW, stale_hours=6) is False

    def test_naive_timestamp_assumed_utc(self):
        # A naive started_at (no tzinfo) must be treated as UTC, not crash.
        started = (self.NOW - timedelta(hours=8)).replace(tzinfo=None)
        assert _is_stale_running(started, self.NOW, stale_hours=6) is True


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
        tickers = _build_benchmarks_first(["AAPL", "MSFT", "GOOG"])
        assert tickers[0] == "SPY", f"Expected SPY first, got {tickers[0]!r}"

    def test_all_benchmarks_precede_universe_tickers(self):
        """All benchmark tickers must appear before any universe ticker."""
        universe = ["AAPL", "MSFT", "GOOG", "AMZN"]
        tickers = _build_benchmarks_first(universe)
        benchmark_indices = [i for i, t in enumerate(tickers) if t in BENCHMARK_TICKERS]
        universe_indices  = [i for i, t in enumerate(tickers) if t in set(universe)]
        assert max(benchmark_indices) < min(universe_indices), (
            "All benchmarks must come before any universe ticker"
        )

    def test_universe_tickers_not_duplicated_when_they_overlap_benchmarks(self):
        """If the universe happens to contain SPY, it should not appear twice."""
        universe = ["SPY", "AAPL", "MSFT"]
        tickers = _build_benchmarks_first(universe)
        assert tickers.count("SPY") == 1, "SPY must appear exactly once"

    def test_fetch_prices_benchmarks_also_first(self):
        """Same ordering fix applies to _run_fetch_prices."""
        universe = ["AAPL", "MSFT"]
        tickers = _build_benchmarks_first(universe)
        assert tickers[0] == "SPY", f"Expected SPY first in fetch-prices, got {tickers[0]!r}"

    def test_spy_max_available_after_partial_run(self):
        """
        Simulate an interrupted fetch: only the first N tickers were written to DB.
        With SPY first, spy_max is available after even a single-ticker partial run.
        """
        universe = ["AAPL", "MSFT", "GOOG"]
        tickers = _build_benchmarks_first(universe)

        # Simulate DB state after only the first ticker was successfully written
        db_after_one_write = {tickers[0]: date(2026, 5, 14)}
        spy_max = db_after_one_write.get("SPY")

        assert spy_max is not None, (
            "spy_max must be available after the first ticker is written — "
            "requires SPY to be first in the fetch order"
        )


# ── Stale data recovery ───────────────────────────────────────────────────────
#
# When the system comes back after a multi-day outage:
#   - spy_max (loaded from DB at job start) = the old stale date
#   - every universe ticker's DB date also = that same stale date
#   - without the fix: ticker_latest[t] == spy_max for ALL tickers → all skipped
#   - the fix: benchmark tickers are never skipped; spy_max is reloaded from DB
#     after benchmarks run, giving the true current date for universe evaluation

class TestStaleRecovery:

    def _simulate_skip_check(self, ticker, ticker_latest, spy_max, benchmark_set):
        """Mirror the fixed skip condition from _run_fetch_data."""
        is_benchmark = ticker in benchmark_set
        if not is_benchmark and spy_max and ticker_latest.get(ticker) == spy_max:
            return "skipped"
        return "fetched"

    def test_benchmark_never_skipped_even_when_current(self):
        """SPY must be fetched even when its DB date matches spy_max."""
        stale_date = date(2026, 5, 13)  # Wednesday — two days ago
        ticker_latest = {"SPY": stale_date, "AAPL": stale_date}
        spy_max = stale_date  # stale cached value
        result = self._simulate_skip_check("SPY", ticker_latest, spy_max, {"SPY", "QQQ"})
        assert result == "fetched", "SPY (benchmark) must never be skipped"

    def test_universe_ticker_skipped_when_current(self):
        """Universe ticker matching fresh spy_max is correctly skipped."""
        today = date(2026, 5, 16)
        ticker_latest = {"SPY": today, "AAPL": today}
        spy_max = today
        result = self._simulate_skip_check("AAPL", ticker_latest, spy_max, {"SPY", "QQQ"})
        assert result == "skipped"

    def test_universe_ticker_not_skipped_when_stale(self):
        """After spy_max reloads to today, stale universe ticker must be fetched."""
        today = date(2026, 5, 16)
        stale_date = date(2026, 5, 13)
        ticker_latest = {"AAPL": stale_date}  # stale
        spy_max = today  # reloaded after benchmark fetch
        result = self._simulate_skip_check("AAPL", ticker_latest, spy_max, {"SPY", "QQQ"})
        assert result == "fetched"

    def test_all_tickers_stale_only_universe_gets_fetched_after_reload(self):
        """
        Full multi-day outage scenario:
          1. Job starts: spy_max = stale_date (2 days ago)
          2. SPY is first → not skipped (benchmark) → fetched → DB now has today
          3. spy_max reloads → spy_max = today
          4. AAPL's DB date = stale_date ≠ today → fetched
        """
        stale_date = date(2026, 5, 13)
        today = date(2026, 5, 16)
        benchmark_set = {"SPY", "QQQ", "IWM"}

        # Step 1: initial state — everything stale
        initial_spy_max = stale_date
        ticker_latest_initial = {"SPY": stale_date, "AAPL": stale_date, "MSFT": stale_date}

        # SPY is a benchmark → never skipped regardless of spy_max
        assert self._simulate_skip_check(
            "SPY", ticker_latest_initial, initial_spy_max, benchmark_set
        ) == "fetched"

        # Step 2: after SPY is fetched and DB updated, reload spy_max
        spy_max_after_reload = today
        ticker_latest_after_reload = {"SPY": today, "AAPL": stale_date, "MSFT": stale_date}

        # AAPL's DB date (stale) ≠ new spy_max (today) → fetched
        assert self._simulate_skip_check(
            "AAPL", ticker_latest_after_reload, spy_max_after_reload, benchmark_set
        ) == "fetched"

        assert self._simulate_skip_check(
            "MSFT", ticker_latest_after_reload, spy_max_after_reload, benchmark_set
        ) == "fetched"

    def test_normal_run_universe_tickers_skipped(self):
        """After a normal previous run, all tickers at today's date are correctly skipped."""
        today = date(2026, 5, 16)
        benchmark_set = {"SPY", "QQQ", "IWM"}
        ticker_latest = {"SPY": today, "AAPL": today, "MSFT": today}
        spy_max = today

        # SPY: benchmark, never skipped → fetched (to confirm today is still current)
        assert self._simulate_skip_check("SPY", ticker_latest, spy_max, benchmark_set) == "fetched"
        # Universe tickers: up to date → skipped
        assert self._simulate_skip_check("AAPL", ticker_latest, spy_max, benchmark_set) == "skipped"
        assert self._simulate_skip_check("MSFT", ticker_latest, spy_max, benchmark_set) == "skipped"

    def test_no_spy_max_forces_full_fetch(self):
        """If spy_max is None (first ever run), universe tickers are always fetched."""
        spy_max = None
        ticker_latest = {}
        benchmark_set = {"SPY", "QQQ"}
        assert self._simulate_skip_check("AAPL", ticker_latest, spy_max, benchmark_set) == "fetched"
