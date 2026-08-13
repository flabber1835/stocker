"""#12 — freshness is a SESSION question, and it was being answered in days.

THE FAILURE, written before the fix.

```python
MAX_FRONTIER_AGE_DAYS = 4      # "covers a normal weekend plus a holiday"
age = (today - frontier).days
if age > MAX_FRONTIER_AGE_DAYS: FAIL
```

A calendar-day budget cannot express "a session I should have". It has to be
wide enough for the longest legitimate gap — a holiday against a weekend — and
once it is that wide it is also wide enough to hide real outages inside an
ordinary trading week:

```text
frontier   Tue      the last successful fetch
today      Fri      Wed and Thu were full XNYS sessions
age        3 days   <= 4, so PASS
```

Two sessions missing, the evening's book planned on Tuesday's prices, and the
check whose entire job is to notice reports green. Widening or narrowing the
budget does not fix it — it only changes WHICH outages fit inside, and detects
none of them. The same arithmetic that lets a three-day hole pass will fail a
perfectly healthy corpus over Christmas, so the number is wrong in both
directions at once and cannot be tuned to be right in either.

The question the check is actually trying to ask has an exact answer:

    is the corpus frontier the latest XNYS session that has already CLOSED?

No slack, no budget, no holiday reasoning of our own — the calendar already
knows which days were sessions, and the clock knows which of them are finished.
A market that did not trade cannot make the corpus stale, and a session that
traded and is missing is stale by exactly one session.

THE PROPERTY BEING BOUGHT: the check distinguishes *the market was closed* from
*our fetch is failing*, which a day count structurally cannot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.source import code_of  # noqa: E402

from sentinel.feed import calendar as C  # noqa: E402


def skip_without_calendar():
    try:
        C.sessions_in_range("2024-01-02", "2024-01-03")
    except C.CalendarUnavailable as exc:                      # pragma: no cover
        pytest.skip(f"exchange_calendars unavailable: {exc}")


# Anchors chosen from the real XNYS calendar and asserted below, so a calendar
# upgrade that moved a holiday fails HERE rather than silently weakening a test.
#
#   2024-11-28  Thanksgiving Thursday   (closed)
#   2024-11-29  the half day after      (a SESSION)
#   2024-12-25  Christmas Wednesday     (closed)
#   2024-03-29  Good Friday             (closed)


class TestTheAnchorsAreReal:
    def test_the_calendar_agrees_with_the_dates_this_file_reasons_about(self):
        skip_without_calendar()
        nov = C.sessions_in_range("2024-11-25", "2024-12-02")
        assert "2024-11-28" not in nov, "Thanksgiving"
        assert "2024-11-29" in nov, "the half day is a session"
        assert "2024-12-25" not in C.sessions_in_range("2024-12-23", "2024-12-27")
        assert "2024-03-29" not in C.sessions_in_range("2024-03-27", "2024-04-01")

    def test_half_day_close_is_read_from_the_real_xnys_schedule(self):
        """A constant 16:00 boundary gets this production session wrong."""
        skip_without_calendar()
        opened, closed = C.session_window("2024-11-29")

        assert (opened.hour, opened.minute) == (9, 30)
        assert (closed.hour, closed.minute) == (13, 0)
        assert C.latest_closed_session("2024-11-29T12:59:00-05:00") \
            == "2024-11-27"
        assert C.latest_closed_session("2024-11-29T13:01:00-05:00") \
            == "2024-11-29"


class TestTheFailure:
    """Each case states the frontier, the moment, and what a DAY COUNT said."""

    def test_a_three_session_hole_inside_one_week_is_STALE(self):
        """The headline. Tue frontier, Fri evening, Wed/Thu/Fri all traded.

        A 4-day budget scored this 3 and passed it.
        """
        skip_without_calendar()
        v = C.freshness("2024-06-04", now_et="2024-06-07T18:00:00-04:00")
        assert not v.fresh
        assert v.missing_sessions == ("2024-06-05", "2024-06-06", "2024-06-07")
        assert v.sessions_behind == 3

    def test_the_evening_BEFORE_the_close_is_not_stale(self):
        """16:00 ET has not happened, so today is not a session anyone owes.

        Anchoring on `today` rather than on the latest CLOSED session would
        report every corpus as one session behind for most of every weekday —
        an alarm that is true 60% of the time is an alarm nobody reads.
        """
        skip_without_calendar()
        v = C.freshness("2024-06-06", now_et="2024-06-07T09:30:00-04:00")
        assert v.fresh and v.sessions_behind == 0
        assert v.expected_session == "2024-06-06"

    def test_after_the_close_the_SAME_DAY_is_owed(self):
        skip_without_calendar()
        v = C.freshness("2024-06-06", now_et="2024-06-07T16:30:00-04:00")
        assert not v.fresh and v.sessions_behind == 1
        assert v.expected_session == "2024-06-07"

    def test_a_weekend_does_not_make_a_current_corpus_stale(self):
        """Friday's close is still the latest session all weekend."""
        skip_without_calendar()
        for when in ("2024-06-08T12:00:00-04:00",      # Saturday
                     "2024-06-09T23:00:00-04:00"):     # Sunday night
            v = C.freshness("2024-06-07", now_et=when)
            assert v.fresh, when
            assert v.expected_session == "2024-06-07"

    def test_thanksgiving_does_not_make_a_current_corpus_stale(self):
        """Wednesday's close, then Thursday closed. Nothing is owed on Thursday
        evening — and a day count could only get this right by being wide
        enough to also swallow the three-session hole above."""
        skip_without_calendar()
        v = C.freshness("2024-11-27", now_et="2024-11-28T20:00:00-05:00")
        assert v.fresh and v.expected_session == "2024-11-27"

    def test_but_the_HALF_DAY_after_thanksgiving_is_still_owed(self):
        """The case a holiday-shaped budget gets exactly backwards: the market
        DID trade on the 29th, so a corpus stopping at the 27th is stale — while
        `(29 - 27).days == 2` is comfortably inside any budget."""
        skip_without_calendar()
        v = C.freshness("2024-11-27", now_et="2024-11-29T18:00:00-05:00")
        assert not v.fresh and v.missing_sessions == ("2024-11-29",)

    def test_the_christmas_stretch_does_not_false_alarm(self):
        """Tue 24th (a session) then Wed 25th closed. On Christmas night the
        corpus is current, and `(25 - 24).days` happens to agree — the point is
        that this one is right for the RIGHT reason, not by budget."""
        skip_without_calendar()
        v = C.freshness("2024-12-24", now_et="2024-12-25T22:00:00-05:00")
        assert v.fresh and v.expected_session == "2024-12-24"

    def test_a_FUTURE_session_is_an_anomaly_not_freshness(self):
        """A frontier dated past today means a clock is wrong — ours or the
        vendor's. Reported in its own right rather than folded into `fresh`,
        because the remedy is not 'run the fetch again'."""
        skip_without_calendar()
        v = C.freshness("2024-06-07", now_et="2024-06-06T18:00:00-04:00")
        assert v.ahead and not v.fresh and v.sessions_behind == 0

    def test_a_day_XNYS_NEVER_HELD_is_an_anomaly_too(self):
        """A vendor row dated on a Saturday. Same bucket, different cause, and
        the reason says which."""
        skip_without_calendar()
        v = C.freshness("2024-06-08", now_et="2024-06-09T18:00:00-04:00")
        assert v.ahead and "not an XNYS session" in v.reason

    def test_TODAYS_session_before_the_close_is_EARLY_not_anomalous(self):
        """The case the first cut of this got wrong. An ingest that lands at
        15:00 ET holds a session the 16:00 boundary does not yet consider owed
        — that corpus is current, not broken. Treating it as an anomaly flagged
        every early fetch, which is a false alarm on the healthy path."""
        skip_without_calendar()
        v = C.freshness("2024-06-07", now_et="2024-06-07T15:00:00-04:00")
        assert v.early and v.fresh and not v.ahead
        assert v.expected_session == "2024-06-06"


class TestDegradation:
    def test_no_calendar_is_UNKNOWN_rather_than_fresh(self, monkeypatch):
        """A freshness check with no calendar has not established freshness.
        Answering a question it can no longer ask is the defect the continuity
        rewrite already removed one function over."""
        def boom():
            raise C.CalendarUnavailable("pinned out")
        monkeypatch.setattr(C, "_calendar", boom)

        v = C.freshness("2024-06-04", now_et="2024-06-07T18:00:00-04:00")
        assert v.evaluable is False
        assert v.fresh is False, "UNKNOWN must never read as fresh"
        assert "calendar" in v.reason.lower()

    def test_an_empty_corpus_is_not_evaluable_either(self):
        skip_without_calendar()
        v = C.freshness(None, now_et="2024-06-07T18:00:00-04:00")
        assert v.evaluable is False and v.fresh is False


class TestReadinessUsesIt:
    def test_the_day_budget_is_GONE(self):
        """The constant itself, not just its call site. Leaving it importable
        invites the next freshness question to be answered in days again."""
        from sentinel.feed import readiness

        assert not hasattr(readiness, "MAX_FRONTIER_AGE_DAYS"), (
            "a calendar-day budget cannot express 'a session I should have'")

    def test_freshness_reports_SESSIONS_not_days(self):
        from sentinel.feed import readiness

        src = code_of(readiness.check_readiness)
        assert ".days" not in src, (
            "freshness is measured in sessions; a day subtraction here is the "
            "old arithmetic returning")


class TestThePanelAgrees:
    """The operator's view and the gate must count the same thing. Two
    components holding different views of one fact, each individually
    defensible, is the defect shape this whole batch keeps finding."""

    def test_the_panels_sessions_behind_counts_SESSIONS(self):
        """It was `(utcnow().date() - frontier).days` under a field named
        `sessions_behind`. On a Monday evening holding Friday's data — the
        HEALTHY state — it read 3; on a Friday holding Tuesday's, with two
        sessions genuinely missing, it also read 3."""
        from sentinel.panel import sources

        src = code_of(sources._feed_rows)
        assert "utcnow" not in src and "now(timezone.utc).date()" not in src, (
            "an exchange question answered on a UTC clock adds a day for the "
            "four evening hours the ingest actually runs")
        assert "freshness" in src, "count sessions, via the one calendar"

    def test_a_monday_holding_fridays_data_is_ZERO_behind(self):
        skip_without_calendar()
        assert C.freshness("2024-06-07",
                           now_et="2024-06-10T09:00:00-04:00").sessions_behind == 0

    def test_and_the_old_arithmetic_would_have_said_three(self):
        """Pinned so the two answers stay visibly different. If this ever
        matches, the fix has been undone."""
        import datetime as dt

        naive = (dt.date(2024, 6, 10) - dt.date(2024, 6, 7)).days
        assert naive == 3
        skip_without_calendar()
        assert C.freshness("2024-06-07",
                           now_et="2024-06-10T09:00:00-04:00").sessions_behind != naive
