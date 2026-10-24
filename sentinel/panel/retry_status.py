"""Display-only recovery for durably classified source/infrastructure waits."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

from sentinel.automation.model import ProtectedDayWait
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
            and cycle.get('availability_retry_unbounded') is True):
        return RecoveryEvidence(
            phase=f"AUTOMATION_{str(cycle.get('retry_phase') or 'UNKNOWN').upper()}_AVAILABILITY_REFUSED",
            automatic=False, operator_required=True)
    return None


def protected_day_wait(value, effective_session=None, plan_id=None):
    """Parse original positive evidence without granting a new lifetime."""
    try:
        wait = ProtectedDayWait.model_validate(value)
        return wait if (effective_session is None or str(wait.effective_session) == str(effective_session)) and (plan_id is None or wait.plan_id == plan_id) else None
    except (ValueError, TypeError, ArithmeticError):
        return None


def clean_execution_deadline(cycle):
    """Read the producer's original cutoff; a market close cannot extend it."""
    try:
        def aware(value):
            result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if not _aware(result):
                raise ValueError("execution timing must be timezone aware")
            return result
        deadline = aware(cycle.get("original_execution_deadline_at"))
        opened = aware(cycle.get("execution_open_at"))
        execute = aware(cycle.get("execute_at"))
        closed = aware(cycle.get("execution_close_at"))
        return deadline if opened <= execute <= deadline <= min(closed, opened + timedelta(seconds=600)) else None
    except (ValueError, TypeError, ArithmeticError):
        return None


@dataclass(frozen=True)
class CycleRecovery:
    """One display interpretation of durable retry facts, never authority."""

    evidence: RecoveryEvidence | None = None
    availability: RecoveryEvidence | None = None
    availability_refused: bool = False
    protected_wait: ProtectedDayWait | None = None
    protected_recovery: RecoveryEvidence | None = None
    clean_execution_wait: bool = False


def project_cycle_recovery(
        cycle: Mapping | None, *, phases: tuple[str, ...] | None = None,
        failure_domains: tuple[str, ...] | None = None,
        allow_legacy_attempt: bool = False) -> CycleRecovery:
    """Apply typed refusal before any fallback, retaining caller read scopes.

    A source reader may narrow phase/domain and requires a phase attempt count.
    The historical summary/step views explicitly permit their old total-count
    fallback. Neither policy can renew a producer deadline.
    """
    if not isinstance(cycle, Mapping):
        return CycleRecovery()
    diagnostic = cycle.get('diagnostic')
    diagnostic = diagnostic if isinstance(diagnostic, Mapping) else {}
    phase = str(cycle.get('retry_phase') or diagnostic.get('retry_phase') or '').upper()
    if ((phases is not None and phase not in phases)
            or (failure_domains is not None
                and str(cycle.get('failure_domain') or '').upper() not in failure_domains)):
        return CycleRecovery()
    failed = bool(cycle.get('failure_code') or cycle.get('failure_detail'))
    wait = (protected_day_wait(cycle.get('protected_day_wait'),
                              cycle.get('effective_session'), cycle.get('plan_id'))
            if failure_domains is None and not failed else None)
    if wait is not None and (wait.plan_id != cycle.get('plan_id')
                             or str(wait.effective_session) != str(cycle.get('effective_session'))):
        wait = None
    wait_recovery = (RecoveryEvidence(
        phase='PROTECTED_DAY_ORDER_OBSERVATION', automatic=True,
        next_attempt_at=cycle.get('next_wake_at'),
        deadline=min(wait.deadline, wait.observed_at + timedelta(minutes=10)))
        if wait is not None else None)
    if str(cycle.get('state') or '').upper() != 'RETRY_WAIT':
        return CycleRecovery(protected_wait=wait, protected_recovery=wait_recovery)
    availability = availability_recovery(cycle)
    refused = availability_refusal(cycle, availability)
    if refused is not None:
        return CycleRecovery(evidence=refused, availability_refused=True)
    if availability is not None:
        return CycleRecovery(evidence=availability, availability=availability)
    if wait is not None:
        return CycleRecovery(evidence=wait_recovery, protected_wait=wait,
                             protected_recovery=wait_recovery)
    clean = (failure_domains is None and phase == 'EXECUTE' and not failed
             and cycle.get('phase_max_attempts') is None)
    if clean:
        return CycleRecovery(evidence=RecoveryEvidence(
            phase='CLEAN_RECOVERY_EXECUTION_WAKE', automatic=True,
            next_attempt_at=cycle.get('next_wake_at'),
            deadline=clean_execution_deadline(cycle)), clean_execution_wait=True)
    attempt = cycle.get('phase_attempt_count')
    if attempt is None and allow_legacy_attempt:
        attempt = cycle.get('attempt_count')
    return CycleRecovery(evidence=RecoveryEvidence(
        phase=f'AUTOMATION_{phase or "RECOVERY"}', automatic=True,
        attempt=attempt, maximum_attempts=cycle.get('phase_max_attempts'),
        next_attempt_at=cycle.get('next_wake_at'),
        operator_required=bool(cycle.get('terminal_reason'))))
