"""Restore-grade DAY-order fence tests independent of Alpaca pagination."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sentinel.execution.alpaca import postmaster_day_order_fence_reason
from sentinel.feed import calendar

ET = ZoneInfo(calendar.EXCHANGE_TZ)


class Cursor:
    def __init__(self, started):
        self.started = started

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        assert sql == "SELECT pg_postmaster_start_time()"
        assert params is None

    def fetchone(self):
        return (self.started,)


class Conn:
    def __init__(self, started):
        self.started = started

    def cursor(self):
        return Cursor(self.started)


def test_intraday_database_restart_fences_increases_for_that_session():
    session = date(2026, 8, 19)
    started = datetime(2026, 8, 19, 11, 15, tzinfo=ET)
    reason = postmaster_day_order_fence_reason(Conn(started), session)
    assert "restarted during XNYS session" in reason
    assert "DAY order" in reason


def test_preopen_restart_does_not_extend_predecessor_day_orders():
    session = date(2026, 8, 19)
    started = datetime(2026, 8, 19, 7, 0, tzinfo=ET)
    assert postmaster_day_order_fence_reason(Conn(started), session) == ""


def test_prior_session_restart_is_harmless_for_current_rerisk():
    session = date(2026, 8, 19)
    started = datetime(2026, 8, 18, 11, 0, tzinfo=ET)
    assert postmaster_day_order_fence_reason(Conn(started), session) == ""
