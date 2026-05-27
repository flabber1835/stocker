"""Tests for the OPG submission window helpers.

The trade-executor parks orders as 'deferred' when Alpaca's MOO window is
closed (weekdays 09:28–19:00 ET). The background worker submits them at the
top of the window. These tests pin the boundary behaviour so a future tweak
to the time math doesn't silently start auto-submitting into the dead zone.
"""
import zoneinfo
from datetime import datetime

import pytest

from app.main import is_opg_window_open, next_opg_window_open

_ET = zoneinfo.ZoneInfo("America/New_York")


def _et(year, month, day, hour, minute):
    """Build a UTC datetime that corresponds to the given local-ET wall time.
    Uses zoneinfo for the conversion so DST is handled correctly."""
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


class TestIsOpgWindowOpen:
    def test_open_after_19_00_et(self):
        assert is_opg_window_open(_et(2026, 5, 27, 19, 0)) is True
        assert is_opg_window_open(_et(2026, 5, 27, 20, 30)) is True
        assert is_opg_window_open(_et(2026, 5, 27, 23, 59)) is True

    def test_open_overnight_through_09_28_et(self):
        # Window wraps past midnight: 02:00 ET is still inside.
        assert is_opg_window_open(_et(2026, 5, 28, 2, 0)) is True
        # 09:27 ET is the last accepted minute.
        assert is_opg_window_open(_et(2026, 5, 28, 9, 27)) is True

    def test_closed_at_09_28_et_through_18_59(self):
        # 09:28 ET — Alpaca's dead-zone starts here (matches the rejection text).
        assert is_opg_window_open(_et(2026, 5, 28, 9, 28)) is False
        assert is_opg_window_open(_et(2026, 5, 28, 12, 0)) is False
        assert is_opg_window_open(_et(2026, 5, 28, 16, 0)) is False
        # 18:59 ET — still in the dead zone, one minute before reopen.
        assert is_opg_window_open(_et(2026, 5, 28, 18, 59)) is False

    def test_default_argument_uses_now(self):
        # Smoke test: no argument means use system clock; must not raise.
        result = is_opg_window_open()
        assert isinstance(result, bool)


class TestNextOpgWindowOpen:
    def test_returns_now_when_window_already_open(self):
        # 21:00 ET on Wed — window is open, no deferral needed.
        t = _et(2026, 5, 27, 21, 0)
        assert next_opg_window_open(t) == t

    def test_returns_19_00_et_same_day_when_in_dead_zone(self):
        # 14:00 ET on Wed → next open is 19:00 ET same Wed.
        t = _et(2026, 5, 27, 14, 0)
        expected = _et(2026, 5, 27, 19, 0)
        assert next_opg_window_open(t) == expected

    def test_returns_19_00_et_just_after_09_28_cutoff(self):
        # 09:28 ET — first minute of the dead zone → defer to 19:00 ET same day.
        t = _et(2026, 5, 28, 9, 28)
        expected = _et(2026, 5, 28, 19, 0)
        assert next_opg_window_open(t) == expected

    def test_returns_18_59_resolves_to_19_00_same_day(self):
        # 18:59 ET — defer just one minute to 19:00 ET same day.
        t = _et(2026, 5, 28, 18, 59)
        expected = _et(2026, 5, 28, 19, 0)
        result = next_opg_window_open(t)
        assert result == expected
        assert (result - t).total_seconds() == 60
