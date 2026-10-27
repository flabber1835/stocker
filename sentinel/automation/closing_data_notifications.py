"""Positive, calendar-bound notification eligibility for closing-frontier waits.

These facts affect notifications and presentation only. They grant no data, trading, retry or
recovery authority and never change an original deadline.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Mapping

from sentinel.feed import calendar

SCHEMA = 'sentinel.closing-data-wait/1'
EXCEPTION_TYPE = 'sentinel.automation.model.ClosingDataPending'
_CLOCKS = ('decision_close_at', 'prepare_at', 'execution_open_at', 'execute_at',
           'execution_close_at', 'observed_at', 'next_retry_at')
_FIELDS = frozenset(('schema', 'decision_session', 'effective_session',
                     'publisher_deadline_at', 'worker_deadline_at', *_CLOCKS))


def _instant(value):
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise ValueError('closing-data notification clock must be aware')
    return instant.astimezone(timezone.utc)


def _session(value):
    text = value.isoformat() if type(value) is date else value
    if not isinstance(text, str) or len(text) != 10 or date.fromisoformat(text).isoformat() != text:
        raise ValueError('closing-data notification session must be exact')
    return text


def _valid(value):
    if not isinstance(value, Mapping) or set(value) != _FIELDS or value['schema'] != SCHEMA:
        return False
    decision, effective = (_session(value[field])
        for field in ('decision_session', 'effective_session'))
    clocks = {field: _instant(value[field]) for field in _CLOCKS}
    closed = calendar.session_window(decision)[1].astimezone(timezone.utc)
    following = calendar.next_session(decision)
    opened, ended = (instant.astimezone(timezone.utc)
        for instant in calendar.session_window(following))
    publisher_deadline = value['publisher_deadline_at']
    quiet_until = min(opened, _instant(publisher_deadline)) if publisher_deadline is not None else opened
    worker_deadline = value['worker_deadline_at']
    if worker_deadline is not None:
        quiet_until = min(quiet_until, _instant(worker_deadline))
    return (effective == following and clocks['decision_close_at'] == closed
        and clocks['execution_open_at'] == opened and clocks['execution_close_at'] == ended
        and closed <= clocks['prepare_at'] < opened
        and opened <= clocks['execute_at'] < ended
        and closed <= clocks['observed_at'] < clocks['next_retry_at'] < quiet_until
        and calendar.latest_closed_session(clocks['observed_at']) == decision)


def marker(*, cycle, observed_at, next_retry_at, publisher_deadline_at=None,
           worker_deadline_at=None):
    """Return a positive observation only for a consistent current close wait."""
    try:
        value = {'schema': SCHEMA,
            'decision_session': _session(cycle.decision_session),
            'effective_session': _session(cycle.effective_session),
            'publisher_deadline_at': (_instant(publisher_deadline_at).isoformat()
                if publisher_deadline_at is not None else None),
            'worker_deadline_at': (_instant(worker_deadline_at).isoformat()
                if worker_deadline_at is not None else None),
            **{field: _instant(getattr(cycle, field)).isoformat() for field in _CLOCKS[:-2]},
            'observed_at': _instant(observed_at).isoformat(),
            'next_retry_at': _instant(next_retry_at).isoformat()}
        return value if _valid(value) else None
    except Exception:
        # Missing or unverifiable evidence retains ordinary warning behavior.
        return None


def quiet_event(detail, *, state):
    """One shared rule for immediate notification and durable reconstruction."""
    try:
        if state != 'RETRY_WAIT' or not isinstance(detail, Mapping):
            return False
        diagnostic = detail.get('diagnostic')
        if not isinstance(diagnostic, Mapping):
            return False
        value = diagnostic.get('closing_data_wait')
        return (detail.get('failure_code') == 'ClosingDataPending'
            and diagnostic.get('exception_type') == EXCEPTION_TYPE
            and diagnostic.get('retry_phase') == 'REFRESH'
            and diagnostic.get('callback_failure') == 'SOURCE_DATA_PENDING'
            and diagnostic.get('notifier_action') == 'RETRY_SCHEDULED'
            and _valid(value)
            and _instant(detail['next_wake_at']) == _instant(value['next_retry_at'])
            and _instant(diagnostic['next_retry_at']) == _instant(value['next_retry_at'])
            and _instant(diagnostic['latest_failure_at']) == _instant(value['observed_at']))
    except Exception:
        return False
