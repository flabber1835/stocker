"""Unattended automation retry policy for recoverable infrastructure loss.

Financial integrity and authority failures remain terminal. A dependency that
has already been classified as transient may remain unavailable for hours or
days; elapsed outage duration alone is not evidence of corruption. Keep the
same durable retry state and capped backoff until the dependency heals.

Refresh, preparation and read-only reconciliation are restart-convergent around
existing durable transaction/checkpoint boundaries. Their supervised runtime
limit is therefore a liveness boundary: crossing it kills the child and retries
from durable state. New order execution is excluded because an execution-timeout
can straddle broker transport and must follow the stricter ambiguous-outcome
reconciliation path.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from sentinel.automation.model import (
    CallbackDeadlineExceeded,
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


__all__ = ["RecoveryAutomationService"]
