"""Pure recoverability classification shared by operator surfaces.

This module intentionally knows nothing about PostgreSQL, HTTP, brokers, or
rendering.  Callers supply durable facts; this code supplies one answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


OK = "ok"
WARN = "warn"
FAIL = "fail"
PENDING = "pending"
UNKNOWN = "unknown"

GREEN = "green"
AMBER = "amber"
RED = "red"


@dataclass(frozen=True)
class RecoveryEvidence:
    """Durable evidence that one bounded automatic recovery is still active."""

    phase: str
    automatic: bool
    attempt: Optional[int] = None
    maximum_attempts: Optional[int] = None
    next_attempt_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    operator_required: bool = False

    def active(self, now: datetime) -> bool:
        if not self.phase or not self.automatic or self.operator_required:
            return False
        if self.maximum_attempts is not None:
            if (self.maximum_attempts < 1 or self.attempt is None
                    or self.attempt < 0
                    or self.attempt >= self.maximum_attempts):
                return False
        if self.deadline is not None and now > self.deadline:
            return False
        # A scheduled retry alone says *when*, not whether recovery is bounded.
        # At least one exhaustion bound is required, plus a wake or deadline.
        bounded = self.maximum_attempts is not None or self.deadline is not None
        scheduled = self.next_attempt_at is not None or self.deadline is not None
        return bounded and scheduled

    def to_dict(self, now: datetime) -> dict:
        return {
            "phase": self.phase,
            "automatic": self.automatic,
            "attempt": self.attempt,
            "maximum_attempts": self.maximum_attempts,
            "next_attempt_at": (
                self.next_attempt_at.isoformat()
                if self.next_attempt_at is not None else None),
            "deadline": (
                self.deadline.isoformat() if self.deadline is not None else None),
            "operator_required": self.operator_required,
            "active": self.active(now),
        }


def effective_status(
        status: str, *, stale: bool, future: bool, required_current: bool,
        recovery: Optional[RecoveryEvidence], now: datetime) -> str:
    """Apply the central green/amber/red recoverability policy."""
    if status not in {OK, WARN, FAIL, PENDING, UNKNOWN}:
        raise ValueError(f"unknown operational status {status!r}")
    if future:
        return FAIL
    if status in {FAIL, UNKNOWN}:
        return status
    if status == PENDING:
        return FAIL if required_current else PENDING
    automatic = recovery is not None and recovery.active(now)
    if required_current and (stale or status == WARN):
        return WARN if automatic else FAIL
    if stale and status == OK:
        return WARN
    return status


def color(status: str) -> str:
    """Map projection vocabulary to the three operator colors."""
    if status == OK:
        return GREEN
    if status in {WARN, PENDING}:
        return AMBER
    if status in {FAIL, UNKNOWN}:
        return RED
    raise ValueError(f"unknown operational status {status!r}")


__all__ = [
    "AMBER", "FAIL", "GREEN", "OK", "PENDING", "RED", "UNKNOWN", "WARN",
    "RecoveryEvidence", "color", "effective_status",
]
