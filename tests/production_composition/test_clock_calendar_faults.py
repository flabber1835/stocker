from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from sentinel.feed import calendar
from sentinel import shadow_runtime

ET = ZoneInfo("America/New_York")


def test_weekend_transition_uses_next_exchange_session():
    assert calendar.next_session("2026-03-06") == "2026-03-09"


def test_memorial_day_transition_does_not_invent_monday_session():
    assert calendar.next_session("2026-05-22") == "2026-05-26"


def test_thanksgiving_transition_skips_closed_thursday():
    assert calendar.next_session("2026-11-25") == "2026-11-27"


def test_dst_changes_utc_offset_without_changing_wall_clock_open():
    winter_open, _ = calendar.session_window("2026-01-05")
    summer_open, _ = calendar.session_window("2026-07-06")
    assert (winter_open.hour, winter_open.minute) == (9, 30)
    assert (summer_open.hour, summer_open.minute) == (9, 30)
    assert winter_open.utcoffset() != summer_open.utcoffset()


def test_thanksgiving_friday_uses_exchange_half_day_close():
    _opened, closed = calendar.session_window("2026-11-27")
    assert (closed.hour, closed.minute) == (13, 0)


@pytest.mark.parametrize("day", ["2026-03-07", "2026-03-08", "2026-05-25", "2026-11-26"])
def test_non_session_dates_cannot_be_misused_as_execution_session(day):
    with pytest.raises(calendar.NonSessionDate):
        calendar.session_window(day)


def test_frontier_does_not_advance_until_actual_session_close():
    before = datetime(2026, 9, 10, 15, 59, 59, tzinfo=ET)
    after = datetime(2026, 9, 10, 16, 0, 1, tzinfo=ET)
    assert calendar.latest_closed_session(before) == "2026-09-09"
    assert calendar.latest_closed_session(after) == "2026-09-10"


def test_clock_moving_backward_across_close_never_creates_future_session():
    after_close = datetime(2026, 9, 10, 16, 5, tzinfo=ET)
    moved_back = datetime(2026, 9, 10, 15, 55, tzinfo=ET)
    assert calendar.latest_closed_session(after_close) == "2026-09-10"
    assert calendar.latest_closed_session(moved_back) == "2026-09-09"
    assert calendar.next_session(calendar.latest_closed_session(moved_back)) == "2026-09-10"


def test_clock_moving_forward_across_close_advances_only_to_observed_session():
    before = datetime(2026, 9, 10, 15, 55, tzinfo=ET)
    jumped = datetime(2026, 9, 10, 18, 30, tzinfo=ET)
    assert calendar.latest_closed_session(before) == "2026-09-09"
    assert calendar.latest_closed_session(jumped) == "2026-09-10"
    assert calendar.next_session(calendar.latest_closed_session(jumped)) == "2026-09-11"


def test_large_forward_clock_jump_never_skips_exchange_calendar_authority():
    before = datetime(2026, 9, 4, 15, 55, tzinfo=ET)
    jumped = datetime(2026, 9, 8, 16, 5, tzinfo=ET)
    assert calendar.latest_closed_session(before) == "2026-09-03"
    assert calendar.latest_closed_session(jumped) == "2026-09-08"
    assert calendar.next_session("2026-09-04") == "2026-09-08"


def test_sharadar_publication_final_boundary_is_exact_and_timezone_aware():
    session = "2026-09-10"
    eligible = shadow_runtime.publication_not_before(session)
    assert eligible.tzinfo == timezone.utc
    assert eligible == datetime(2026, 9, 11, 3, 45, tzinfo=timezone.utc)

    with pytest.raises(shadow_runtime.ShadowRuntimeRefused, match="not source-final"):
        shadow_runtime._require_publication_not_before(
            session, now=eligible - timedelta(microseconds=1))

    assert shadow_runtime._require_publication_not_before(
        session, now=eligible) == eligible
    assert shadow_runtime._require_publication_not_before(
        session, now=eligible + timedelta(hours=8)) == eligible


def test_sharadar_publication_final_boundary_tracks_dst_in_new_york():
    winter = shadow_runtime.publication_not_before("2026-01-05")
    summer = shadow_runtime.publication_not_before("2026-07-06")
    assert winter == datetime(2026, 1, 6, 4, 45, tzinfo=timezone.utc)
    assert summer == datetime(2026, 7, 7, 3, 45, tzinfo=timezone.utc)


def test_reboot_over_weekend_resolves_same_execution_session_deterministically():
    friday_decision = "2026-09-04"
    before_reboot = calendar.next_session(friday_decision)
    after_reboot = calendar.next_session(friday_decision)
    assert before_reboot == after_reboot == "2026-09-08"  # Labor Day is Sep 7.


def test_calendar_authority_is_versioned_and_bounded():
    version = calendar.calendar_version()
    assert version.startswith("XNYS/exchange_calendars ")
    assert calendar.CALENDAR_START == "1997-01-01"
    assert calendar.CALENDAR_END == "2100-12-31"
