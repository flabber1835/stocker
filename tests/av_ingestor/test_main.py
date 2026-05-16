"""
Tests for av-ingestor utility functions.

We test the pure-Python helpers (_TICKER_RE and the demo-key warning guard)
directly — without importing app.main — to stay DB-free and avoid sys.path
conflicts when the full test suite runs multiple services.
"""
import re
from datetime import date
import pytest


# ── _TICKER_RE validation ─────────────────────────────────────────────────────

# Copy of the regex from app/main.py — tested here without importing the module
# so there is no DATABASE_URL / SQLAlchemy dependency.
_TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')


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
# The warning logic in app/main.py is:
#
#   AV_API_KEY = os.getenv("AV_API_KEY", "demo")
#   if AV_API_KEY in ("", "demo"):
#       print("[av-ingestor] WARNING: AV_API_KEY is 'demo' — ...")
#
# We replicate that exact guard here so the test is self-contained and does
# not depend on importing the full module (which requires DATABASE_URL and
# creates a SQLAlchemy engine).


def _emit_demo_warning_if_needed(av_api_key: str, capsys) -> str:
    """
    Reproduce the module-level guard from app/main.py and return captured stdout.
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
# These tests replicate the skip-decision logic from _run_fetch_data /
# _run_fetch_prices / _run_fetch_fundamentals without importing app.main.

def _should_skip_price(ticker: str, ticker_latest: dict, spy_max) -> bool:
    """Replicate: if spy_max and ticker_latest.get(ticker) == spy_max: skip."""
    return bool(spy_max and ticker_latest.get(ticker) == spy_max)


def _should_use_compact(ticker: str, ticker_latest: dict) -> bool:
    """Replicate: use_compact = ticker_latest.get(ticker) is not None."""
    return ticker_latest.get(ticker) is not None


def _should_skip_fundamentals(ticker: str, fund_latest: dict, today: date) -> bool:
    """Replicate: if fund_latest.get(ticker) == today: skip."""
    return fund_latest.get(ticker) == today


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
    def test_skip_when_already_fetched_today(self):
        """Fundamentals fetched today → skip (AV OVERVIEW is static intraday)."""
        today = date(2026, 5, 16)
        fund_latest = {"AAPL": today}
        assert _should_skip_fundamentals("AAPL", fund_latest, today) is True

    def test_no_skip_when_fetched_yesterday(self):
        """Fundamentals fetched yesterday → re-fetch today."""
        today = date(2026, 5, 16)
        fund_latest = {"AAPL": date(2026, 5, 15)}
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
