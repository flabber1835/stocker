"""Deterministic XNYS automation schedules.

There is intentionally no weekday, holiday, early-close, or fixed-offset logic
here.  The production feed calendar is the single session authority.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sentinel.automation.model import AutomationConfig, SessionSchedule
from sentinel.feed import calendar
from sentinel.shadow_runtime import publication_not_before


UTC = timezone.utc


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("automation clocks must be timezone-aware")
    return value.astimezone(UTC)


def for_decision_session(
        decision_session: date | str,
        config: AutomationConfig) -> SessionSchedule:
    """Return the close-to-next-open obligation for one XNYS session."""
    decision = date.fromisoformat(str(decision_session))
    effective = date.fromisoformat(calendar.next_session(decision))
    _decision_open, decision_close = calendar.session_window(decision)
    execution_open, execution_close = calendar.session_window(effective)
    close_utc = _aware_utc(decision_close)
    open_utc = _aware_utc(execution_open)
    end_utc = _aware_utc(execution_close)
    return SessionSchedule(
        decision_session=decision,
        effective_session=effective,
        decision_close_at=close_utc,
        # Sharadar SEP/SFP publish again at 23:30 ET. A close-relative delay
        # (the former default was close+15m) can freeze provisional data and is
        # especially wrong on half-days. PAPER transport and certified shadow
        # therefore share the reviewed fixed 23:45 America/New_York boundary.
        prepare_at=publication_not_before(decision.isoformat()),
        execution_open_at=open_utc,
        execute_at=(open_utc
                    + timedelta(seconds=config.execution_delay_seconds)),
        execution_close_at=end_utc,
    )


def for_clock(now: datetime, config: AutomationConfig) -> SessionSchedule:
    """Resolve the latest closed-session obligation at an exact instant."""
    now = _aware_utc(now)
    decision = calendar.latest_closed_session(now)
    return for_decision_session(decision, config)


def between(
        first_decision_session: date | str,
        last_decision_session: date | str,
        config: AutomationConfig) -> tuple[SessionSchedule, ...]:
    """Schedules for every XNYS decision session in the inclusive range."""
    return tuple(
        for_decision_session(session, config)
        for session in calendar.sessions_in_range(
            first_decision_session, last_decision_session)
    )


def next_wake(
        *, now: datetime, schedule: SessionSchedule,
        retry_at: datetime | None = None,
        heartbeat_at: datetime | None = None,
        control_poll_at: datetime | None = None,
        alert_at: datetime | None = None) -> datetime:
    """Earliest outstanding persisted or recomputed obligation, in UTC.

    Due instants remain due (the result equals ``now``) rather than being
    skipped.  This is what makes a restart after a missed wake converge.
    """
    current = _aware_utc(now)
    candidates = [
        schedule.prepare_at,
        schedule.execute_at,
        schedule.execution_close_at,
        retry_at,
        heartbeat_at,
        control_poll_at,
        alert_at,
    ]
    normalized = [
        _aware_utc(candidate) for candidate in candidates
        if candidate is not None
    ]
    future = [candidate for candidate in normalized if candidate > current]
    if len(future) != len(normalized):
        return current
    return min(future)


__all__ = ["UTC", "between", "for_clock", "for_decision_session", "next_wake"]
