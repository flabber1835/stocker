"""Display-only recovery for durably classified source/infrastructure waits."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
import re

from sentinel.operational_status import RecoveryEvidence


_EXCEPTION_TYPE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+')


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def availability_recovery(cycle: Mapping | None) -> RecoveryEvidence | None:
    """Keep this retry amber only until its original actual next-session open."""
    if not isinstance(cycle, Mapping) or cycle.get('state') != 'RETRY_WAIT':
        return None
    phase = cycle.get('retry_phase')
    if (phase not in ('REFRESH', 'PREPARE')
            or cycle.get('availability_retry_unbounded') is not True
            or cycle.get('callback_failure') not in (
                'SOURCE_DATA_PENDING', 'TRANSIENT_INFRASTRUCTURE')
            or cycle.get('terminal_reason') is not None):
        return None
    exception_type = cycle.get('exception_type')
    if (not isinstance(exception_type, str) or len(exception_type) > 512
            or _EXCEPTION_TYPE.fullmatch(exception_type) is None):
        return None
    attempt = cycle.get('phase_attempt_count')
    if type(attempt) is not int or attempt < 1:
        return None
    # The SQL reader normally normalizes naive legacy clocks. Its marker keeps
    # those values from acquiring this stricter availability-only allowance.
    if ('availability_retry_clocks_aware' in cycle
            and cycle['availability_retry_clocks_aware'] is not True):
        return None
    wake, saved_open = cycle.get('next_wake_at'), cycle.get('execution_open_at')
    if not _aware(wake) or not _aware(saved_open) or wake >= saved_open:
        return None
    try:
        from sentinel.feed import calendar

        decision, effective = cycle.get('decision_session'), cycle.get('effective_session')
        if (not isinstance(decision, str) or not isinstance(effective, str)
                or date.fromisoformat(decision).isoformat() != decision
                or date.fromisoformat(effective).isoformat() != effective
                or calendar.session_on_or_after(decision) != decision
                or calendar.next_session(decision) != effective):
            return None
        actual_open, _ = calendar.session_window(effective)
        if saved_open != actual_open:
            return None
    except (ValueError, TypeError, OverflowError, RuntimeError):
        return None
    return RecoveryEvidence(
        phase=f'AUTOMATION_{phase}_AVAILABILITY', automatic=True,
        attempt=attempt, next_attempt_at=wake,
        deadline=saved_open - timedelta(microseconds=1))


def availability_label(cycle: Mapping, recovery: RecoveryEvidence) -> str:
    state = ('WAITING FOR INPUTS' if cycle.get('callback_failure') == 'SOURCE_DATA_PENDING'
             else 'RETRYING AVAILABILITY')
    return f'{state} · ATTEMPT {recovery.attempt}'


def availability_refusal(
        cycle: Mapping, accepted: RecoveryEvidence | None) -> RecoveryEvidence | None:
    """A malformed explicit request cannot regain a generic retry allowance."""
    if (accepted is None and cycle.get('state') == 'RETRY_WAIT'
            and cycle.get('availability_retry_unbounded') is True
            and cycle.get('retry_phase') in ('REFRESH', 'PREPARE')):
        return RecoveryEvidence(
            phase=f"AUTOMATION_{cycle['retry_phase']}_AVAILABILITY_REFUSED",
            automatic=False, operator_required=True)
    return None
