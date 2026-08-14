"""Typed durable state for Sentinel's broker-independent automation core.

These models deliberately contain orchestration identity and lifecycle only.
Plan economics remain in the canonical execution plan and command journal.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AutomationRefused(RuntimeError):
    """Automation cannot safely perform the requested operation."""


class MissingAutomationState(AutomationRefused):
    """A required singleton row is absent from an existing schema."""


class StaleLeaderRefused(AutomationRefused):
    """The caller no longer owns the current live fencing token."""


class NonRetryableCallbackRefused(AutomationRefused):
    """An injected authority or integrity boundary requires an operator."""


class InvalidCycleTransition(AutomationRefused):
    """A cycle transition is not part of the durable state machine."""


class ImmutableCycleChanged(AutomationRefused):
    """One deterministic cycle id was presented with different identity."""


class ImmutableAlertChanged(AutomationRefused):
    """One alert idempotency key was presented with different content."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AutomationConfig(_FrozenModel):
    """Versioned scheduling and retry policy included in activation identity."""

    schema_version: int = Field(default=1, ge=1)
    publication_delay_seconds: int = Field(default=900, ge=0)
    execution_delay_seconds: int = Field(default=60, ge=0)
    lease_seconds: int = Field(default=45, ge=3)
    heartbeat_seconds: int = Field(default=10, ge=1)
    control_poll_seconds: int = Field(default=10, ge=1)
    retry_base_seconds: int = Field(default=30, ge=1)
    retry_max_seconds: int = Field(default=900, ge=1)
    alert_claim_seconds: int = Field(default=60, ge=3)
    alert_max_attempts: int = Field(default=8, ge=1)

    @model_validator(mode="after")
    def _coherent_intervals(self) -> "AutomationConfig":
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat_seconds must be less than lease_seconds")
        if self.retry_base_seconds > self.retry_max_seconds:
            raise ValueError(
                "retry_base_seconds must not exceed retry_max_seconds")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hashlib.sha256(payload).hexdigest()


class ControlBinding(_FrozenModel):
    deployment_id: str = Field(min_length=1)
    broker: str = Field(min_length=1)
    broker_account_id: str = Field(min_length=1)
    takeover_epoch: int = Field(ge=1)
    certificate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollout_mode: str = Field(min_length=1)
    rollout_version: int = Field(ge=1)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AutomationControl(_FrozenModel):
    enabled: bool
    generation: int = Field(ge=1)
    kill_switch_engaged: bool
    deployment_id: str | None = None
    broker: str | None = None
    broker_account_id: str | None = None
    takeover_epoch: int | None = None
    certificate_sha256: str | None = None
    rollout_mode: str | None = None
    rollout_version: int | None = None
    config_sha256: str | None = None
    authority_verdict: str | None = Field(
        default=None, pattern=r"^(PASS|FAIL)$")
    authority_detail: str | None = None
    authority_checked_at: datetime | None = None
    enabled_at: datetime | None = None
    disabled_at: datetime | None = None
    updated_at: datetime

    @property
    def binding(self) -> ControlBinding | None:
        values = {
            "deployment_id": self.deployment_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "takeover_epoch": self.takeover_epoch,
            "certificate_sha256": self.certificate_sha256,
            "rollout_mode": self.rollout_mode,
            "rollout_version": self.rollout_version,
            "config_sha256": self.config_sha256,
        }
        if any(value is None for value in values.values()):
            return None
        return ControlBinding.model_validate(values)


class LeaderPermit(_FrozenModel):
    holder_id: str = Field(min_length=1)
    fence_token: int = Field(ge=1)
    control_generation: int = Field(ge=1)
    acquired_at: datetime
    expires_at: datetime


class SessionSchedule(_FrozenModel):
    decision_session: date
    effective_session: date
    decision_close_at: datetime
    prepare_at: datetime
    execution_open_at: datetime
    execute_at: datetime
    execution_close_at: datetime

    @model_validator(mode="after")
    def _ordered(self) -> "SessionSchedule":
        instants = (
            self.decision_close_at, self.prepare_at,
            self.execution_open_at, self.execute_at,
            self.execution_close_at,
        )
        if any(value.tzinfo is None for value in instants):
            raise ValueError("schedule instants must be timezone-aware")
        if self.prepare_at < self.decision_close_at:
            raise ValueError("prepare_at precedes the decision close")
        if self.prepare_at >= self.execution_open_at:
            raise ValueError(
                "prepare_at must precede the effective-session open")
        if self.execute_at < self.execution_open_at:
            raise ValueError("execute_at precedes the effective-session open")
        if self.execute_at >= self.execution_close_at:
            raise ValueError("execute_at is not inside the execution session")
        return self


class CycleState(str, Enum):
    DISCOVERED = "DISCOVERED"
    REFRESHING_DATA = "REFRESHING_DATA"
    PREPARING = "PREPARING"
    PLAN_READY = "PLAN_READY"
    WAITING_OPEN = "WAITING_OPEN"
    EXECUTING = "EXECUTING"
    RECONCILING = "RECONCILING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    MISSED_STATE_ONLY = "MISSED_STATE_ONLY"
    SUPERSEDED = "SUPERSEDED"
    BLOCKED = "BLOCKED"

    @property
    def terminal(self) -> bool:
        return self in {
            CycleState.SUCCEEDED,
            CycleState.MISSED_STATE_ONLY,
            CycleState.SUPERSEDED,
            CycleState.BLOCKED,
        }


class CycleSpec(_FrozenModel):
    """Immutable identity stamped on one deterministic daily obligation."""

    decision_session: date
    effective_session: date
    deployment_id: str = Field(min_length=1)
    broker: str = Field(min_length=1)
    broker_account_id: str = Field(min_length=1)
    takeover_epoch: int = Field(ge=1)
    control_generation: int = Field(ge=1)
    certificate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollout_mode: str = Field(min_length=1)
    rollout_version: int = Field(ge=1)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_close_at: datetime
    prepare_at: datetime
    execution_open_at: datetime
    execute_at: datetime
    execution_close_at: datetime
    historical_state_only: bool = False

    @model_validator(mode="after")
    def _ordered_identity(self) -> "CycleSpec":
        if self.effective_session <= self.decision_session:
            raise ValueError(
                "effective_session must follow decision_session")
        instants = (
            self.decision_close_at, self.prepare_at,
            self.execution_open_at, self.execute_at,
            self.execution_close_at,
        )
        if any(value.tzinfo is None for value in instants):
            raise ValueError("cycle schedule instants must be timezone-aware")
        if not (self.decision_close_at <= self.prepare_at
                < self.execution_open_at <= self.execute_at
                < self.execution_close_at):
            raise ValueError("cycle schedule instants are out of order")
        return self

    @property
    def cycle_id(self) -> str:
        identity = {
            "schema": "sentinel.automation_cycle/1",
            "deployment_id": self.deployment_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "takeover_epoch": self.takeover_epoch,
            "decision_session": self.decision_session.isoformat(),
        }
        encoded = json.dumps(
            identity, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class CycleRecord(_FrozenModel):
    cycle_id: str
    state: CycleState
    decision_session: date
    effective_session: date
    deployment_id: str
    broker: str
    broker_account_id: str
    takeover_epoch: int
    control_generation: int
    certificate_sha256: str
    rollout_mode: str
    rollout_version: int
    config_sha256: str
    decision_close_at: datetime
    prepare_at: datetime
    execution_open_at: datetime
    execute_at: datetime
    execution_close_at: datetime
    historical_state_only: bool
    plan_id: str | None = None
    data_version: str | None = None
    publication_fingerprint: str | None = None
    state_fingerprint: str | None = None
    plan_fingerprint: str | None = None
    last_clean_reconciliation_id: str | None = None
    attempt_count: int = Field(ge=0)
    next_wake_at: datetime | None = None
    last_fence_token: int | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    diagnostic: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class CycleContext(_FrozenModel):
    cycle: CycleRecord
    permit: LeaderPermit


class PrepareResult(_FrozenModel):
    plan_id: str = Field(min_length=1)
    data_version: str | None = None
    publication_fingerprint: str | None = None
    state_fingerprint: str | None = None
    plan_fingerprint: str | None = None
    missed_sessions: tuple[date, ...] = ()
    diagnostic: Mapping[str, Any] = Field(default_factory=dict)


class RefreshResult(_FrozenModel):
    """Identity of canonical publication refresh (or restart recognition)."""

    already_published: bool = False
    data_version: str | None = None
    publication_fingerprint: str | None = None
    diagnostic: Mapping[str, Any] = Field(default_factory=dict)


class ExecuteDisposition(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    RECONCILE = "RECONCILE"
    RETRY = "RETRY"
    SUPERSEDED = "SUPERSEDED"
    BLOCKED = "BLOCKED"


class ExecuteResult(_FrozenModel):
    disposition: ExecuteDisposition
    last_clean_reconciliation_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    diagnostic: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _conclusive_result_has_reconciliation(self) -> "ExecuteResult":
        if (
            self.disposition in {
                ExecuteDisposition.SUCCEEDED,
                ExecuteDisposition.READY_TO_EXECUTE,
                ExecuteDisposition.SUPERSEDED,
            }
            and not self.last_clean_reconciliation_id
        ):
            raise ValueError(
                f"{self.disposition.value} requires a clean reconciliation "
                "identity")
        return self


class AlertState(str, Enum):
    PENDING = "PENDING"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    DEAD_LETTER = "DEAD_LETTER"


class AckState(str, Enum):
    UNACKNOWLEDGED = "UNACKNOWLEDGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class AlertRecord(_FrozenModel):
    alert_id: str
    idempotency_key: str
    schema_version: int
    event_type: str
    severity: str
    payload: Mapping[str, Any]
    state: AlertState
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime
    delivery_holder: str | None = None
    delivery_expires_at: datetime | None = None
    last_error: str | None = None
    ack_state: AckState
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    acknowledgement: str | None = None
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None = None


class DispatchResult(_FrozenModel):
    alert: AlertRecord | None
    delivered: bool = False
    dead_lettered: bool = False
    error: str | None = None


class TickAction(str, Enum):
    INERT = "INERT"
    WAITING = "WAITING"
    RECOVERED = "RECOVERED"
    REFRESHED = "REFRESHED"
    PREPARED = "PREPARED"
    EXECUTED = "EXECUTED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"


class TickResult(_FrozenModel):
    action: TickAction
    cycle: CycleRecord | None = None
    permit: LeaderPermit | None = None
    reason: str | None = None


__all__ = [
    "AckState", "AlertRecord", "AlertState", "AutomationConfig",
    "AutomationControl", "AutomationRefused", "ControlBinding",
    "CycleContext", "CycleRecord", "CycleSpec", "CycleState",
    "DispatchResult", "ExecuteDisposition", "ExecuteResult",
    "ImmutableAlertChanged", "ImmutableCycleChanged",
    "InvalidCycleTransition", "LeaderPermit", "MissingAutomationState",
    "NonRetryableCallbackRefused", "PrepareResult", "RefreshResult", "SessionSchedule",
    "StaleLeaderRefused", "TickAction", "TickResult",
]
