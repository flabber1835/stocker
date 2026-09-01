"""Unattended automation retry policy for recoverable infrastructure loss.

Financial integrity and authority failures remain terminal. A dependency that
has already been classified as transient may remain unavailable for hours or
days; elapsed outage duration alone is not evidence of corruption. Keep the
same durable retry state and capped backoff until the dependency heals.

Refresh, preparation and read-only reconciliation are restart-convergent around
existing durable transaction/checkpoint boundaries. Their supervised runtime
limit is therefore a liveness boundary: crossing it kills the child and retries
from durable state. An execution callback timeout is different because it may
straddle broker transport. It is never retried directly: the durable cycle is
moved to RECONCILING so a fresh complete broker observation must resolve the
journal before recovery may authorize any remaining fresh delta.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from sentinel.automation import store
from sentinel.automation.model import (
    CallbackDeadlineExceeded,
    CycleState,
    TickAction,
    TickResult,
    TransientInfrastructureFailure,
)
from sentinel.automation.service import AutomationService


_RESTARTABLE_DEADLINE_PHASES = frozenset({
    "REFRESH", "PREFLIGHT_RECOVER", "PREPARE", "RECOVER",
})


class RecoveryAutomationService(AutomationService):
    """Automation service whose recoverable failures do not expire."""

    def _retry_at(self, now: datetime, attempts: int) -> datetime:
        count = max(1, int(attempts))
        if count >= 63:
            delay = self.config.retry_max_seconds
        else:
            delay = min(
                self.config.retry_max_seconds,
                self.config.retry_base_seconds * (2 ** (count - 1)),
            )
        return now + timedelta(seconds=delay)

    def _failure_diagnostic(
            self, *, cycle, phase: str, exc: BaseException,
            now: datetime) -> tuple[bool, Mapping[str, Any]]:
        terminal, diagnostic = super()._failure_diagnostic(
            cycle=cycle, phase=phase, exc=exc, now=now)
        transient = isinstance(exc, TransientInfrastructureFailure)
        bounded_restart = (
            isinstance(exc, CallbackDeadlineExceeded)
            and phase in _RESTARTABLE_DEADLINE_PHASES)
        if not transient and not bounded_restart:
            return terminal, diagnostic

        value = dict(diagnostic)
        if bounded_restart:
            value["callback_failure"] = "BOUNDED_CALLBACK_RESTART"
            value["bounded_checkpoint_restart"] = True
        else:
            value["callback_failure"] = "TRANSIENT_INFRASTRUCTURE"
            value["availability_retry_unbounded"] = True
        value["terminal_reason"] = None
        return False, value

    def _handle_callback_failure(
            self, conn, *, now: datetime, cycle, permit,
            phase: str, exc: BaseException,
            recovery_transition: bool = False) -> TickResult:
        if phase == "EXECUTE" and isinstance(exc, CallbackDeadlineExceeded):
            # The supervisor killed the executor at a point where Alpaca may or
            # may not have accepted transport.  The command journal was durable
            # before every POST, so the only safe next action is read-only
            # reconciliation.  Do not consume another EXECUTE attempt here and
            # do not depend on the old callback's local outcome.
            diagnostic = {
                "callback_failure": "EXECUTE_TIMEOUT_REQUIRES_RECOVERY",
                "retry_phase": "RECOVER",
                "latest_failure_at": now.isoformat(),
                "exception_type": (
                    f"{type(exc).__module__}.{type(exc).__qualname__}"),
                "exception_fingerprint": self._exception_fingerprint(exc),
                "direct_execution_retry_permitted": False,
            }
            recovered = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RECONCILING,
                next_wake_at=now,
                failure_code=type(exc).__name__,
                failure_detail=str(exc)[:4000],
                diagnostic=diagnostic,
            )
            return TickResult(
                action=TickAction.RETRY_SCHEDULED,
                cycle=recovered,
                permit=permit,
                reason=(
                    "execution callback deadline exceeded; fresh broker "
                    "reconciliation is required before any further transport"),
            )
        return super()._handle_callback_failure(
            conn, now=now, cycle=cycle, permit=permit,
            phase=phase, exc=exc,
            recovery_transition=recovery_transition)


__all__ = ["RecoveryAutomationService"]
