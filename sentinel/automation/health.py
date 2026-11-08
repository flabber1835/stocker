"""SELECT-only durable health projection for supervisors and the panel."""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel.automation import store
from sentinel.automation.model import AutomationRefused, MissingAutomationState, ProtectedDayWait
from sentinel.execution import journal


class ObservationDiagnostic(BaseModel):
    """Closed attribution metadata; it never changes health or trading policy."""

    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_version: Literal['sentinel.observation-diagnostic/1'] = Field(
        default='sentinel.observation-diagnostic/1', alias='schema')
    stage: Literal['OBSERVATION_INTEGRITY'] = 'OBSERVATION_INTEGRITY'
    code: Literal['READ_UNAVAILABLE', 'EVIDENCE_INVALID', 'CHECK_FAILED']
    exception_type: str | None = Field(default=None, pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')
    errno: int | None = Field(default=None, ge=0, le=4095)
    sqlstate: str | None = Field(default=None, pattern=r'^[A-Z0-9]{5}$')


class SchedulerDiagnostic(BaseModel):
    """Closed facts from one scheduler decision; never financial authority."""

    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, allow_inf_nan=False)
    schema_version: Literal['sentinel.scheduler-diagnostic/1'] = Field(
        default='sentinel.scheduler-diagnostic/1', alias='schema')
    policy_state: Literal['SCHEDULER_STALLED', 'WAITING_FOR_LEADER']
    predicate: Literal['LEASE_HOLDER_MISSING', 'LEASE_GENERATION_MISMATCH',
        'LEASE_EXPIRY_MISSING', 'LEASE_EXPIRED', 'INSTANCE_MISSING',
        'INSTANCE_HOLDER_MISMATCH', 'INSTANCE_HEARTBEAT_MISSING',
        'INSTANCE_HEARTBEAT_FUTURE', 'INSTANCE_HEARTBEAT_STALE']
    sampled_at: datetime
    control_generation: int = Field(ge=1)
    fence: int = Field(ge=0)
    holder: str | None = Field(default=None, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')
    holder_present: bool
    holder_matches: bool
    leader_active: bool
    service_heartbeat_fresh: bool
    lease_heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    instance_state: str | None = Field(max_length=64, pattern=r'^[A-Z0-9_]+$')
    instance_heartbeat_at: datetime | None
    heartbeat_age_seconds: float | None
    heartbeat_window_seconds: float = Field(ge=1)
    callback_started_at: datetime | None
    callback_deadline_at: datetime | None
    callback_current: bool
    scheduler_overdue: bool
    read_elapsed_seconds: float | None = Field(ge=0)

    @field_validator('sampled_at', 'lease_heartbeat_at', 'lease_expires_at',
                     'instance_heartbeat_at', 'callback_started_at', 'callback_deadline_at')
    @classmethod
    def aware_clock(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError('scheduler diagnostic clock must be timezone aware')
        return value


def _observation_diagnostic(error: Exception | None = None) -> ObservationDiagnostic:
    if error is None:
        return ObservationDiagnostic(code='EVIDENCE_INVALID')
    from sentinel.dependency_availability import database_unavailable
    from sentinel.supervisor_io import error_diagnostic
    code = ('READ_UNAVAILABLE' if database_unavailable(error) else
            'EVIDENCE_INVALID' if isinstance(error, journal.ObservationEvidenceUncertifiable)
            else 'CHECK_FAILED')
    return ObservationDiagnostic(code=code, **error_diagnostic(error))


class AutomationHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    healthy: bool
    installed: bool
    operational_ready: bool
    policy_state: str
    enabled: bool | None = None
    kill_switch_engaged: bool | None = None
    control_generation: int | None = None
    deployment_id: str | None = None
    broker: str | None = None
    broker_account_id: str | None = None
    takeover_epoch: int | None = None
    certificate_sha256: str | None = None
    rollout_mode: str | None = None
    rollout_version: int | None = None
    config_sha256: str | None = None
    authority_verdict: str | None = None
    authority_detail: str | None = None
    authority_checked_at: datetime | None = None
    authority_lifecycle_current: bool | None = None
    authority_mode: str | None = None
    historical_causality: str | None = None
    authority_expires_at: datetime | None = None
    maximum_exposure: str | None = None
    leader_holder: str | None = None
    fencing_token: int | None = None
    leader_heartbeat_at: datetime | None = None
    leader_expires_at: datetime | None = None
    leader_active: bool = False
    latest_cycle_id: str | None = None
    latest_cycle_state: str | None = None
    next_wake_at: datetime | None = None
    latest_failure_code: str | None = None
    latest_failure_detail: str | None = None
    latest_attempt_count: int | None = None
    latest_phase_attempt_count: int | None = None
    first_failure_at: datetime | None = None
    latest_failure_at: datetime | None = None
    exception_fingerprint: str | None = None
    terminal_reason: str | None = None
    last_clean_reconciliation_id: str | None = None
    broker_outcome_unresolved: int = 0
    pending_alerts: int = 0
    dead_letter_alerts: int = 0
    unacknowledged_alerts: int = 0
    last_instance_id: str | None = None
    last_instance_heartbeat_at: datetime | None = None
    service_heartbeat_fresh: bool = False
    callback_started_at: datetime | None = None
    callback_deadline_at: datetime | None = None
    scheduler_overdue: bool = False
    database_now: datetime | None = None
    scheduler_diagnostic: SchedulerDiagnostic | None = None
    host_database_clock_skew_seconds: float | None = None
    reason: str | None = None
    observation_diagnostic: ObservationDiagnostic | None = None


def read_health(conn) -> AutomationHealth:
    """Read policy and service state without constructing any broker client.

    Correctly disabled or killed is supervisor-healthy but not operationally
    ready. A missing singleton is both uninstalled and unhealthy. Unresolved
    broker commands remain visible after kill/deactivation because revoking local
    authority cannot recall an already accepted broker request.
    """
    started = time.monotonic()
    from sentinel.notification_policy import CANCELLED_TEST_SQL
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('sentinel_automation_control'),"
            " to_regclass('sentinel_automation_lease')")
        control_table, lease_table = cur.fetchone()
    conn.rollback()
    if control_table is None or lease_table is None:
        return AutomationHealth(
            healthy=False, installed=False, operational_ready=False,
            policy_state="NOT_INSTALLED",
            reason="automation control or lease table is not installed")
    try:
        control = store.load_control(conn)
    except MissingAutomationState as exc:
        conn.rollback()
        return AutomationHealth(
            healthy=False, installed=True, operational_ready=False,
            policy_state="CORRUPT", reason=str(exc))

    try:
        observation_issues = journal.observation_integrity_issues(conn)
    except journal.ObservationIntegrityPending as exc:
        conn.rollback()
        return AutomationHealth(
            healthy=True,installed=True,operational_ready=False,
            policy_state="OBSERVATION_VERIFICATION_PENDING",
            enabled=control.enabled,kill_switch_engaged=control.kill_switch_engaged,
            control_generation=control.generation,reason=str(exc))
    except Exception as exc:                                  # noqa: BLE001
        conn.rollback()
        return AutomationHealth(
            healthy=False, installed=True, operational_ready=False,
            policy_state="UNCERTIFIABLE_OBSERVATIONS",
            enabled=control.enabled,
            kill_switch_engaged=control.kill_switch_engaged,
            control_generation=control.generation,
            observation_diagnostic=_observation_diagnostic(exc),
            reason=("broker observation integrity gate failed: "
                    f"{type(exc).__name__}: {exc}"))
    if observation_issues:
        conn.rollback()
        detail = "; ".join(
            f"{issue.observation_seq}:{','.join(issue.reasons)}"
            for issue in observation_issues)
        return AutomationHealth(
            healthy=False, installed=True, operational_ready=False,
            policy_state="UNCERTIFIABLE_OBSERVATIONS",
            enabled=control.enabled,
            kill_switch_engaged=control.kill_switch_engaged,
            control_generation=control.generation,
            observation_diagnostic=_observation_diagnostic(),
            reason=f"UNCERTIFIABLE broker observation evidence: {detail}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_commands WHERE state IN "
            "('SEND_PENDING','ACKNOWLEDGED','UNKNOWN','PARTIALLY_FILLED',"
            " 'CANCEL_PENDING')")
        broker_outcome_unresolved = int(cur.fetchone()[0])
        cur.execute(
            "SELECT"
            " COUNT(*) FILTER (WHERE state IN ('PENDING','DELIVERING')),"
            " COUNT(*) FILTER (WHERE state='DEAD_LETTER'),"
            " COUNT(*) FILTER (WHERE ack_state='UNACKNOWLEDGED')"
            f" FROM sentinel_alert_outbox a WHERE NOT {CANCELLED_TEST_SQL}")
        pending, dead, unacknowledged = cur.fetchone()
        # Slow integrity/history work precedes this one temporal observation.
        # The lease, its exact holder and their clock must share an MVCC snapshot.
        columns = ",".join("c." + name for name in store._CONTROL_COLUMNS.split(","))
        cur.execute(
            "WITH sampled AS MATERIALIZED (SELECT clock_timestamp() AS now) "
            f"SELECT {columns},l.holder_id,l.fence_token,l.heartbeat_at,l.expires_at,"
            " l.control_generation,i.instance_id,i.heartbeat_at,i.state,"
            " i.callback_started_at,i.callback_deadline_at,"
            " x.cycle_id,x.state,x.next_wake_at,x.failure_code,x.failure_detail,"
            " x.last_clean_reconciliation_id,x.attempt_count,x.diagnostic,"
            " a.active_certificate_sha256,"
            " (a.active_certificate_sha256=c.certificate_sha256"
            "  AND lifecycle.status='ACTIVE'"
            "  AND (certificate.expires_at > n.now"
            "       OR certificate.claims->>'authorization_mode'='PAPER_OBSERVATION_ONLY')"
            "  AND cr.certificate_sha256 IS NULL AND kr.key_id IS NULL),"
            " certificate.claims,certificate.expires_at,n.now"
            " FROM sampled n LEFT JOIN sentinel_automation_control c ON c.id=1"
            " LEFT JOIN sentinel_automation_lease l ON l.id=1"
            " LEFT JOIN sentinel_automation_service_instances i ON i.instance_id=l.holder_id"
            " LEFT JOIN LATERAL (SELECT cycle_id,state,next_wake_at,failure_code,"
            " failure_detail,last_clean_reconciliation_id,attempt_count,diagnostic"
            " FROM sentinel_automation_cycles cycle WHERE cycle.control_generation=c.generation"
            " OR EXISTS (SELECT 1 FROM sentinel_automation_cycle_events e"
            " WHERE e.cycle_id=cycle.cycle_id AND e.control_generation=c.generation)"
            " ORDER BY decision_session DESC,created_at DESC LIMIT 1) x ON TRUE"
            " LEFT JOIN sentinel_execution_authority_state a ON a.id=1"
            " LEFT JOIN sentinel_signed_execution_certificates certificate"
            " ON certificate.certificate_sha256=a.active_certificate_sha256"
            " LEFT JOIN sentinel_execution_certificate_lifecycle lifecycle"
            " ON lifecycle.certificate_sha256=a.active_certificate_sha256"
            " LEFT JOIN sentinel_execution_certificate_revocations cr"
            " ON cr.certificate_sha256=a.active_certificate_sha256"
            " LEFT JOIN sentinel_execution_key_revocations kr ON kr.key_id=certificate.key_id")
        temporal = cur.fetchone()
    conn.rollback()
    if temporal is None or temporal[0] is None or temporal[18] is None:
        return AutomationHealth(
            healthy=False, installed=True, operational_ready=False,
            policy_state="CORRUPT", enabled=control.enabled,
            kill_switch_engaged=control.kill_switch_engaged,
            control_generation=control.generation,
            reason="durable automation control or lease singleton is missing")
    late_control = store._control(temporal[:17])
    if ((late_control.generation, late_control.enabled, late_control.kill_switch_engaged,
         late_control.binding) !=
            (control.generation, control.enabled, control.kill_switch_engaged, control.binding)):
        raise AutomationRefused("automation control changed during health observation")
    control = late_control
    holder, token, heartbeat, expires, lease_generation = temporal[17:22]
    instance = temporal[22:27] if temporal[22] is not None else None
    cycle = temporal[27:35] if temporal[27] is not None else None
    authority_row = temporal[35:39]
    database_now = temporal[39]
    active = bool(holder is not None and lease_generation == control.generation
                  and expires is not None and expires > database_now)
    authority_current = bool(
        authority_row is not None and authority_row[0] is not None
        and authority_row[1])
    claims = (authority_row[2] if authority_row is not None else {})
    if not isinstance(claims, dict):
        try:
            claims = json.loads(claims or "{}")
        except (TypeError, json.JSONDecodeError):
            claims = {}
    cycle_diagnostic = cycle[7] if cycle is not None else {}
    if not isinstance(cycle_diagnostic, dict):
        try:
            cycle_diagnostic = json.loads(cycle_diagnostic or "{}")
        except (TypeError, json.JSONDecodeError):
            cycle_diagnostic = {}

    def diagnostic_time(name: str) -> datetime | None:
        raw = cycle_diagnostic.get(name)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None

    lease_window_seconds = (
        max(1.0, (expires - heartbeat).total_seconds())
        if heartbeat is not None and expires is not None else 1.0)
    service_heartbeat_fresh = bool(
        active and instance is not None and holder is not None
        and instance[0] == holder and instance[1] is not None
        and 0 <= (database_now - instance[1]).total_seconds()
        <= lease_window_seconds)
    terminal_states = {
        "SUCCEEDED", "MISSED_STATE_ONLY", "SUPERSEDED", "BLOCKED"}
    callback = bool(instance is not None and instance[2].endswith("_CALLBACK"))
    callback_current = bool(callback and instance[3] is not None
                            and instance[4] is not None
                            and instance[3] <= database_now < instance[4])
    scheduler_overdue = bool(
        callback and not callback_current
        or (not callback_current and cycle is not None
            and cycle[1] not in terminal_states and cycle[2] is not None
            and (database_now - cycle[2]).total_seconds() > lease_window_seconds))
    resting_wait_expired = False
    if cycle_diagnostic.get("protected_day_wait") is not None:
        try:
            wait = ProtectedDayWait.model_validate(cycle_diagnostic["protected_day_wait"])
            resting_wait_expired = (database_now < wait.observed_at or database_now >= min(
                wait.deadline, wait.observed_at + timedelta(minutes=10)))
        except (ValueError, TypeError, ArithmeticError):
            resting_wait_expired = True
    blocked = bool(cycle is not None and cycle[1] == "BLOCKED")
    host_database_clock_skew_seconds = abs(
        (datetime.now(timezone.utc) - database_now).total_seconds())

    if not control.enabled:
        policy = (
            "DISABLED_BROKER_OUTCOME_UNRESOLVED"
            if broker_outcome_unresolved else "DISABLED")
    elif control.kill_switch_engaged:
        policy = (
            "KILLED_BROKER_OUTCOME_UNRESOLVED"
            if broker_outcome_unresolved else "KILLED")
    elif control.authority_verdict == "FAIL":
        policy = "AUTHORITY_FAILED"
    elif control.authority_verdict != "PASS":
        policy = "AUTHORITY_UNVERIFIED"
    elif not authority_current:
        policy = "AUTHORITY_INVALID"
    elif blocked:
        policy = "BLOCKED"
    elif active and not service_heartbeat_fresh:
        policy = "SCHEDULER_STALLED"
    elif resting_wait_expired:
        policy = "PROTECTED_DAY_WAIT_EXPIRED"
    elif scheduler_overdue:
        policy = "SCHEDULER_OVERDUE"
    elif active:
        policy = "LEADER_ACTIVE"
    else:
        policy = "WAITING_FOR_LEADER"
    scheduler_diagnostic = None
    if policy in {'SCHEDULER_STALLED', 'WAITING_FOR_LEADER'}:
        age = ((database_now-instance[1]).total_seconds()
               if instance is not None and instance[1] is not None else None)
        if holder is None:
            predicate = 'LEASE_HOLDER_MISSING'
        elif lease_generation != control.generation:
            predicate = 'LEASE_GENERATION_MISMATCH'
        elif expires is None:
            predicate = 'LEASE_EXPIRY_MISSING'
        elif not active:
            predicate = 'LEASE_EXPIRED'
        elif instance is None:
            predicate = 'INSTANCE_MISSING'
        elif instance[0] != holder:
            predicate = 'INSTANCE_HOLDER_MISMATCH'
        elif age is None:
            predicate = 'INSTANCE_HEARTBEAT_MISSING'
        elif age < 0:
            predicate = 'INSTANCE_HEARTBEAT_FUTURE'
        else:
            predicate = 'INSTANCE_HEARTBEAT_STALE'
        elapsed = time.monotonic()-started
        safe_holder = (holder if isinstance(holder,str) and len(holder)<=128
                       and re.fullmatch(r'[A-Za-z0-9_.:-]+',holder) else None)
        state = instance[2] if instance is not None else None
        safe_state = (state if isinstance(state,str) and len(state)<=64
                      and re.fullmatch(r'[A-Z0-9_]+',state) else None)
        scheduler_diagnostic = SchedulerDiagnostic(
            policy_state=policy, predicate=predicate, sampled_at=database_now,
            control_generation=control.generation, fence=token, holder=safe_holder,
            holder_present=holder is not None,
            holder_matches=bool(instance is not None and instance[0]==holder),
            leader_active=active, service_heartbeat_fresh=service_heartbeat_fresh,
            lease_heartbeat_at=heartbeat, lease_expires_at=expires,
            instance_state=safe_state,
            instance_heartbeat_at=instance[1] if instance is not None else None,
            heartbeat_age_seconds=age, heartbeat_window_seconds=lease_window_seconds,
            callback_started_at=instance[3] if instance is not None else None,
            callback_deadline_at=instance[4] if instance is not None else None,
            callback_current=callback_current, scheduler_overdue=scheduler_overdue,
            read_elapsed_seconds=elapsed if math.isfinite(elapsed) and elapsed>=0 else None)
    return AutomationHealth(
        healthy=True,
        installed=True,
        operational_ready=(
            control.enabled and not control.kill_switch_engaged
            and control.authority_verdict == "PASS" and authority_current
            and bool(active) and service_heartbeat_fresh
            and not blocked and not scheduler_overdue and not resting_wait_expired),
        policy_state=policy,
        enabled=control.enabled,
        kill_switch_engaged=control.kill_switch_engaged,
        control_generation=control.generation,
        deployment_id=control.deployment_id,
        broker=control.broker,
        broker_account_id=control.broker_account_id,
        takeover_epoch=control.takeover_epoch,
        certificate_sha256=control.certificate_sha256,
        rollout_mode=control.rollout_mode,
        rollout_version=control.rollout_version,
        config_sha256=control.config_sha256,
        authority_verdict=control.authority_verdict,
        authority_detail=control.authority_detail,
        authority_checked_at=control.authority_checked_at,
        authority_lifecycle_current=authority_current,
        authority_mode=claims.get(
            "authorization_mode", "HISTORICALLY_CERTIFIED") if claims else None,
        historical_causality=claims.get(
            "historical_causality", "HISTORICALLY_CERTIFIED") if claims else None,
        authority_expires_at=(authority_row[3]
                              if authority_row is not None else None),
        maximum_exposure=(str(claims.get("maximum_exposure"))
                          if claims.get("maximum_exposure") is not None
                          else None),
        leader_holder=holder,
        fencing_token=token,
        leader_heartbeat_at=heartbeat,
        leader_expires_at=expires,
        leader_active=bool(active),
        latest_cycle_id=cycle[0] if cycle else None,
        latest_cycle_state=cycle[1] if cycle else None,
        next_wake_at=cycle[2] if cycle else None,
        latest_failure_code=cycle[3] if cycle else None,
        latest_failure_detail=cycle[4] if cycle else None,
        last_clean_reconciliation_id=cycle[5] if cycle else None,
        latest_attempt_count=int(cycle[6]) if cycle else None,
        latest_phase_attempt_count=(
            int(cycle_diagnostic["phase_attempt_count"])
            if cycle_diagnostic.get("phase_attempt_count") is not None
            else None),
        first_failure_at=diagnostic_time("first_failure_at"),
        latest_failure_at=diagnostic_time("latest_failure_at"),
        exception_fingerprint=cycle_diagnostic.get("exception_fingerprint"),
        terminal_reason=cycle_diagnostic.get("terminal_reason"),
        broker_outcome_unresolved=broker_outcome_unresolved,
        pending_alerts=pending,
        dead_letter_alerts=dead,
        unacknowledged_alerts=unacknowledged,
        last_instance_id=instance[0] if instance else None,
        last_instance_heartbeat_at=instance[1] if instance else None,
        service_heartbeat_fresh=service_heartbeat_fresh,
        callback_started_at=instance[3] if instance else None,
        callback_deadline_at=instance[4] if instance else None,
        scheduler_overdue=scheduler_overdue,
        database_now=database_now,
        scheduler_diagnostic=scheduler_diagnostic,
        host_database_clock_skew_seconds=host_database_clock_skew_seconds,
    )


__all__ = ["AutomationHealth", "read_health"]
