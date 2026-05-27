"""
Tests for the stuck-ticker quarantine logic (migration 0006 / Option B).

Covers two pure helpers and the SQL-side upsert via an in-memory dict-based
fake of `_record_fetch_outcome` semantics. The actual SQL is exercised
end-to-end in the harness (tests/harness/) — these unit tests pin down the
decision boundaries: when does a ticker enter quarantine, when does it
leave, and which tickers does the universe filter drop.

The helpers under test:
  - app.main._is_quarantined
  - app.main._filter_chronic_stuck

Defaults:
  QUARANTINE_THRESHOLD_DAYS = 3
  QUARANTINE_DURATION_DAYS = 7
  UNIVERSE_DROP_THRESHOLD_DAYS = 30
"""
from datetime import date, timedelta

import pytest

from app.main import (
    _filter_chronic_stuck,
    _is_quarantined,
)


TODAY = date(2026, 5, 27)


# ── _is_quarantined ──────────────────────────────────────────────────────────


class TestIsQuarantined:

    def test_empty_state_returns_false(self):
        """Tickers we've never consulted are not quarantined."""
        assert _is_quarantined("AAPL", {}, TODAY) is False

    def test_no_quarantine_field_returns_false(self):
        """State exists but quarantined_until is None — not quarantined."""
        state = {"AAPL": {"quarantined_until": None, "consecutive_empty_days": 2}}
        assert _is_quarantined("AAPL", state, TODAY) is False

    def test_future_quarantine_returns_true(self):
        """quarantined_until > today → quarantined."""
        state = {
            "AAPL": {
                "quarantined_until": TODAY + timedelta(days=3),
                "consecutive_empty_days": 5,
            }
        }
        assert _is_quarantined("AAPL", state, TODAY) is True

    def test_expired_quarantine_returns_false(self):
        """quarantined_until in the past → quarantine has ended; re-fetch eligible."""
        state = {
            "AAPL": {
                "quarantined_until": TODAY - timedelta(days=1),
                "consecutive_empty_days": 5,
            }
        }
        assert _is_quarantined("AAPL", state, TODAY) is False

    def test_today_is_not_quarantined(self):
        """quarantined_until == today means the quarantine has expired today.

        The skip rule uses `> today`, so a ticker whose quarantine ends today
        is eligible for a fresh attempt (give it a chance to recover).
        """
        state = {
            "AAPL": {
                "quarantined_until": TODAY,
                "consecutive_empty_days": 5,
            }
        }
        assert _is_quarantined("AAPL", state, TODAY) is False

    def test_per_ticker_isolation(self):
        """Quarantine applies only to the specific ticker, not its neighbours."""
        state = {
            "AAPL": {"quarantined_until": TODAY + timedelta(days=5), "consecutive_empty_days": 4},
            "MSFT": {"quarantined_until": None, "consecutive_empty_days": 0},
        }
        assert _is_quarantined("AAPL", state, TODAY) is True
        assert _is_quarantined("MSFT", state, TODAY) is False
        assert _is_quarantined("GOOG", state, TODAY) is False  # absent from state


# ── _filter_chronic_stuck ────────────────────────────────────────────────────


def _row(ticker: str, **extra) -> dict:
    """Helper to build a LISTING_STATUS-shaped row."""
    return {"ticker": ticker, "name": f"{ticker} Inc", **extra}


class TestFilterChronicStuck:

    def test_empty_inputs(self):
        """Empty ticker list returns ([], [])."""
        kept, dropped = _filter_chronic_stuck([], {}, 30)
        assert kept == []
        assert dropped == []

    def test_no_state_keeps_all(self):
        """A ticker absent from fetch_state has no streak, so it is kept."""
        rows = [_row("AAPL"), _row("MSFT")]
        kept, dropped = _filter_chronic_stuck(rows, {}, 30)
        assert {r["ticker"] for r in kept} == {"AAPL", "MSFT"}
        assert dropped == []

    def test_below_threshold_kept(self):
        """consecutive_empty_days < threshold → kept."""
        rows = [_row("AAPL"), _row("MSFT")]
        state = {
            "AAPL": {"consecutive_empty_days": 29, "quarantined_until": None},
            "MSFT": {"consecutive_empty_days": 0, "quarantined_until": None},
        }
        kept, dropped = _filter_chronic_stuck(rows, state, 30)
        assert {r["ticker"] for r in kept} == {"AAPL", "MSFT"}
        assert dropped == []

    def test_at_threshold_dropped(self):
        """consecutive_empty_days == threshold → dropped."""
        rows = [_row("DEAD")]
        state = {"DEAD": {"consecutive_empty_days": 30, "quarantined_until": None}}
        kept, dropped = _filter_chronic_stuck(rows, state, 30)
        assert kept == []
        assert dropped == ["DEAD"]

    def test_above_threshold_dropped(self):
        """consecutive_empty_days > threshold → dropped."""
        rows = [_row("ZOMBIE")]
        state = {"ZOMBIE": {"consecutive_empty_days": 90, "quarantined_until": None}}
        kept, dropped = _filter_chronic_stuck(rows, state, 30)
        assert kept == []
        assert dropped == ["ZOMBIE"]

    def test_mixed_keeps_only_healthy(self):
        """Mixed input → only healthy tickers survive."""
        rows = [_row("HEALTHY"), _row("STUCK"), _row("FRESH"), _row("ZOMBIE")]
        state = {
            "HEALTHY": {"consecutive_empty_days": 0, "quarantined_until": None},
            "STUCK": {"consecutive_empty_days": 45, "quarantined_until": None},
            "FRESH": {"consecutive_empty_days": 5, "quarantined_until": None},
            "ZOMBIE": {"consecutive_empty_days": 100, "quarantined_until": None},
        }
        kept, dropped = _filter_chronic_stuck(rows, state, 30)
        assert {r["ticker"] for r in kept} == {"HEALTHY", "FRESH"}
        assert set(dropped) == {"STUCK", "ZOMBIE"}

    def test_preserves_row_metadata(self):
        """Filter must not mutate the row dicts it returns."""
        rows = [_row("AAPL", sector="Tech", exchange="NASDAQ")]
        kept, _ = _filter_chronic_stuck(rows, {}, 30)
        assert kept == [{"ticker": "AAPL", "name": "AAPL Inc", "sector": "Tech", "exchange": "NASDAQ"}]

    def test_threshold_zero_drops_anyone_with_streak(self):
        """Zero threshold drops tickers with any non-zero streak."""
        rows = [_row("ZERO"), _row("ONE")]
        state = {
            "ZERO": {"consecutive_empty_days": 0, "quarantined_until": None},
            "ONE":  {"consecutive_empty_days": 1, "quarantined_until": None},
        }
        kept, dropped = _filter_chronic_stuck(rows, state, 0)
        # ZERO has streak=0, falsy → kept. ONE has streak=1, >=0 → dropped.
        assert {r["ticker"] for r in kept} == {"ZERO"}
        assert dropped == ["ONE"]

    def test_accepts_string_tickers(self):
        """For symmetry: ticker may be a bare string rather than a dict."""
        rows = ["AAPL", "DEAD", "MSFT"]
        state = {"DEAD": {"consecutive_empty_days": 50, "quarantined_until": None}}
        kept, dropped = _filter_chronic_stuck(rows, state, 30)
        assert kept == ["AAPL", "MSFT"]
        assert dropped == ["DEAD"]


# ── Skip-decision behaviour against the live fetch-data path ────────────────


class TestSkipPriority:
    """
    Sanity check on how the three skip conditions interact for a single
    ticker on the fetch-data code path.

    The runtime decision order is:
       1. `ticker_latest[T] == spy_max`        → skip (already current)
       2. else if `_is_quarantined(T)`         → skip (Option B)
       3. else                                 → call AV

    These tests exercise the *boundaries* of conditions 1 and 2 because
    they're what determine whether the API call happens. The deeper API
    path is exercised end-to-end in the harness.
    """

    def test_current_ticker_skips_even_if_quarantine_field_set(self):
        """If we already have today's data, no API call regardless of quarantine."""
        ticker_latest = {"AAPL": TODAY}
        spy_max = TODAY
        fetch_state = {"AAPL": {"quarantined_until": TODAY + timedelta(days=30),
                                "consecutive_empty_days": 99}}

        # Condition 1 hits first → skip.
        condition_1 = bool(spy_max and ticker_latest.get("AAPL") == spy_max)
        assert condition_1 is True
        # Quarantine would have caught it anyway; behaviour is consistent.
        assert _is_quarantined("AAPL", fetch_state, TODAY) is True

    def test_stale_quarantined_ticker_skips(self):
        """Stale price + quarantined → skip."""
        ticker_latest = {"OLD": TODAY - timedelta(days=10)}
        spy_max = TODAY
        fetch_state = {"OLD": {"quarantined_until": TODAY + timedelta(days=5),
                               "consecutive_empty_days": 3}}

        condition_1 = bool(spy_max and ticker_latest.get("OLD") == spy_max)
        assert condition_1 is False
        assert _is_quarantined("OLD", fetch_state, TODAY) is True

    def test_stale_not_quarantined_would_fetch(self):
        """Stale price + not quarantined → no skip → API will be called."""
        ticker_latest = {"WAITING": TODAY - timedelta(days=1)}
        spy_max = TODAY
        fetch_state = {}

        condition_1 = bool(spy_max and ticker_latest.get("WAITING") == spy_max)
        assert condition_1 is False
        assert _is_quarantined("WAITING", fetch_state, TODAY) is False

    def test_no_price_history_not_quarantined_would_fetch(self):
        """A brand-new ticker (no price history yet, no state) should be fetched."""
        ticker_latest: dict = {}
        spy_max = TODAY
        fetch_state: dict = {}

        condition_1 = bool(spy_max and ticker_latest.get("NEWLY") == spy_max)
        assert condition_1 is False
        assert _is_quarantined("NEWLY", fetch_state, TODAY) is False


# ── Recurrence semantics (streak counter behaviour) ─────────────────────────


class TestStreakSemantics:
    """
    Defines what we expect from the *aggregate* behaviour of the streak
    counter, even though the actual increment happens in SQL. These tests
    keep the contract explicit: a fake of _record_fetch_outcome's intent.
    """

    @staticmethod
    def _apply(state: dict, ticker: str, new_rows: int, today: date,
               qt: int = 3, qd: int = 7) -> dict:
        """Pure-Python emulation of _record_fetch_outcome's UPSERT."""
        prev = state.get(ticker, {})
        if new_rows > 0:
            state[ticker] = {
                "last_consulted_date": today,
                "consecutive_empty_days": 0,
                "quarantined_until": None,
            }
        else:
            streak = (prev.get("consecutive_empty_days") or 0) + 1
            new_q = prev.get("quarantined_until")
            if streak >= qt:
                new_q = today + timedelta(days=qd)
            state[ticker] = {
                "last_consulted_date": today,
                "consecutive_empty_days": streak,
                "quarantined_until": new_q,
            }
        return state

    def test_first_empty_response_no_quarantine_yet(self):
        state: dict = {}
        self._apply(state, "X", 0, TODAY)
        assert state["X"]["consecutive_empty_days"] == 1
        assert state["X"]["quarantined_until"] is None

    def test_threshold_triggers_quarantine(self):
        state: dict = {}
        self._apply(state, "X", 0, TODAY)              # streak=1
        self._apply(state, "X", 0, TODAY + timedelta(days=1))  # streak=2
        d3 = TODAY + timedelta(days=2)
        self._apply(state, "X", 0, d3)                 # streak=3 → quarantine
        assert state["X"]["consecutive_empty_days"] == 3
        assert state["X"]["quarantined_until"] == d3 + timedelta(days=7)

    def test_new_data_resets_streak_and_clears_quarantine(self):
        state: dict = {}
        for i in range(5):
            self._apply(state, "X", 0, TODAY + timedelta(days=i))
        assert state["X"]["consecutive_empty_days"] == 5
        assert state["X"]["quarantined_until"] is not None

        self._apply(state, "X", 1, TODAY + timedelta(days=5))
        assert state["X"]["consecutive_empty_days"] == 0
        assert state["X"]["quarantined_until"] is None

    def test_streak_persists_during_quarantine(self):
        """If we ever do call AV during quarantine and it's still empty, the
        streak increments. (This shouldn't happen via fetch-data, which now
        skips quarantined tickers — but the semantics should still hold.)"""
        state: dict = {}
        for i in range(4):
            self._apply(state, "X", 0, TODAY + timedelta(days=i))
        assert state["X"]["consecutive_empty_days"] == 4
        assert state["X"]["quarantined_until"] == TODAY + timedelta(days=3) + timedelta(days=7)

    def test_streak_threshold_configurable(self):
        """Threshold of 1 triggers quarantine on the first empty response."""
        state: dict = {}
        self._apply(state, "X", 0, TODAY, qt=1, qd=2)
        assert state["X"]["consecutive_empty_days"] == 1
        assert state["X"]["quarantined_until"] == TODAY + timedelta(days=2)


# ── Universe re-entry: chronic stuck → AV returns data → kept ───────────────


class TestUniverseReEntry:
    """
    The whole point of streak-based dropping vs. a hard delisted list is
    that a ticker can come back. These tests exercise that round trip.
    """

    def test_streak_at_drop_threshold_then_data_arrives_keeps_ticker(self):
        """A ticker at the drop threshold survives the next universe filter
        run if AV produced data in the most recent fetch-data (streak reset)."""
        rows = [_row("BACK")]
        # Pre-state: at drop threshold; would be dropped.
        state_before = {"BACK": {"consecutive_empty_days": 30, "quarantined_until": None}}
        kept_before, dropped_before = _filter_chronic_stuck(rows, state_before, 30)
        assert dropped_before == ["BACK"]
        assert kept_before == []

        # After fetch-data returns new rows the streak resets.
        state_after = {"BACK": {"consecutive_empty_days": 0, "quarantined_until": None}}
        kept_after, dropped_after = _filter_chronic_stuck(rows, state_after, 30)
        assert dropped_after == []
        assert kept_after == [{"ticker": "BACK", "name": "BACK Inc"}]
