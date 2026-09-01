"""Unattended automation retry policy for recoverable infrastructure loss.

Financial integrity and authority failures remain terminal.  A dependency that
has already been classified as transient may remain unavailable for hours or
days; elapsed outage duration alone is not evidence of corruption.  Keep the
same durable retry state and capped backoff until the dependency heals.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from sentinel.automation.model import TransientInfrastructureFailure
from sentinel.automation.service import AutomationService


class RecoveryAutomationService(AutomationService):
    """Automation service whose typed transient failures do not expire.

    The base service's per-phase attempt limits are still retained in the signed
    configuration and diagnostics, but they are not converted into a permanent
    BLOCKED generation for an explicitly transient infrastructure failure.  The
    delay saturates at ``retry_max_seconds`` so arbitrarily long outages do not
    construct exponentially large integers.
    """

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
        if not isinstance(exc, TransientInfrastructureFailure):
            return terminal, diagnostic
        # A reviewed transient classification means the evidence can heal while
        # the durable cycle remains authoritative.  Preserve the attempt count
        # for observability, but never make outage duration an integrity event.
        value = dict(diagnostic)
        value["callback_failure"] = "TRANSIENT_INFRASTRUCTURE"
        value["terminal_reason"] = None
        value["availability_retry_unbounded"] = True
        return False, value


__all__ = ["RecoveryAutomationService"]
