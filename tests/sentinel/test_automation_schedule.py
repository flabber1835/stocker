from __future__ import annotations

from datetime import date, datetime, timezone

from sentinel.automation.model import AutomationConfig
from sentinel.automation.schedule import (
    for_clock,
    for_decision_session,
    next_wake,
)


UTC = timezone.utc


def config(**changes) -> AutomationConfig:
    return AutomationConfig(
        publication_delay_seconds=changes.pop("publication_delay_seconds", 0),
        execution_delay_seconds=changes.pop("execution_delay_seconds", 0),
        **changes,
    )


def test_dst_is_derived_from_each_actual_session() -> None:
    schedule = for_decision_session("2026-03-06", config())

    assert schedule.decision_close_at == datetime(
        2026, 3, 6, 21, 0, tzinfo=UTC)
    assert schedule.effective_session == date(2026, 3, 9)
    # The weekend crosses into US daylight time. A fixed -05 offset fails here.
    assert schedule.execution_open_at == datetime(
        2026, 3, 9, 13, 30, tzinfo=UTC)
    assert schedule.execution_close_at == datetime(
        2026, 3, 9, 20, 0, tzinfo=UTC)


def test_holiday_is_not_weekday_arithmetic() -> None:
    schedule = for_decision_session("2026-09-04", config())

    assert schedule.effective_session == date(2026, 9, 8)
    assert schedule.execution_open_at == datetime(
        2026, 9, 8, 13, 30, tzinfo=UTC)


def test_early_close_is_the_final_execution_boundary() -> None:
    # Thanksgiving Thursday is skipped and the next session is the 13:00 ET
    # Friday half-day.
    schedule = for_decision_session("2026-11-25", config())

    assert schedule.effective_session == date(2026, 11, 27)
    assert schedule.execution_close_at == datetime(
        2026, 11, 27, 18, 0, tzinfo=UTC)


def test_clock_resolution_and_wake_are_restart_deterministic() -> None:
    cfg = config(publication_delay_seconds=600, execution_delay_seconds=90)
    now = datetime(2026, 8, 13, 20, 5, tzinfo=UTC)

    first = for_clock(now, cfg)
    restarted = for_clock(now, cfg)
    assert first == restarted
    assert first.decision_session == date(2026, 8, 13)
    assert next_wake(now=now, schedule=first) == first.prepare_at

    after_due = first.prepare_at.replace(microsecond=0)
    assert next_wake(now=after_due, schedule=first) == after_due


def test_schedule_rejects_an_execution_delay_past_the_close() -> None:
    cfg = config(execution_delay_seconds=7 * 60 * 60)

    try:
        for_decision_session("2026-11-25", cfg)
    except ValueError as exc:
        assert "inside the execution session" in str(exc)
    else:                                                        # pragma: no cover
        raise AssertionError("an after-close execution wake was accepted")
