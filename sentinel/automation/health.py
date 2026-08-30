"""SELECT-only durable health projection for supervisors and the panel."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from sentinel.automation import store
from sentinel.automation.model import MissingAutomationState


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
    scheduler_overdue: bool = False
    database_now: datetime | None = None
    host_database_clock_skew_seconds: float | None = None
    reason: str | None = None


def read_health(conn) -> AutomationHealth:
    """Read policy and service state without constructing any broker client.

    Correctly disabled or killed is supervisor-healthy but not operationally
    ready. A missing singleton is both uninstalled and unhealthy. Unresolved
    broker commands remain visible after kill/deactivation because revoking local
    authority cannot recall an already accepted broker request.
    """
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

    with conn.cursor() as cur:
        cur.execute(
            "SELECT holder_id,fence_token,heartbeat_at,expires_at,"
            " (holder_id IS NOT NULL"
            "  AND control_generation=%s"
            "  AND expires_at > clock_timestamp()),clock_timestamp()"
            " FROM sentinel_automation_lease WHERE id=1",
            (control.generation,))
        lease = cur.fetchone()
        if lease is None:
            conn.rollback()
            return AutomationHealth(
                healthy=False, installed=True, operational_ready=False,
                policy_state="CORRUPT", enabled=control.enabled,
                kill_switch_engaged=control.kill_switch_engaged,
                control_generation=control.generation,
                reason="durable automation lease singleton is missing")

        cur.execute(
            "SELECT cycle_id,state,next_wake_at,failure_code,failure_detail,"
            " last_clean_reconciliation_id,attempt_count,diagnostic"
            " FROM sentinel_automation_cycles c"
            " WHERE c.control_generation=%s OR EXISTS ("
            " SELECT 1 FROM sentinel_automation_cycle_events e"
            " WHERE e.cycle_id=c.cycle_id AND e.control_generation=%s)"
            " ORDER BY decision_session DESC,created_at DESC LIMIT 1",
            (control.generation, control.generation))
        cycle = cur.fetchone()
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
            " FROM sentinel_alert_outbox")
        pending, dead, unacknowledged = cur.fetchone()
        # Health belongs to the CURRENT LEASE HOLDER. A hot standby also emits
        # its own heartbeat; selecting the globally newest service row would let
        # that passive process either mask or falsely accuse the active leader.
        cur.execute(
            "SELECT i.instance_id,i.heartbeat_at FROM"
            " sentinel_automation_service_instances i"
            " JOIN sentinel_automation_lease l ON l.id=1"
            " WHERE i.instance_id=l.holder_id LIMIT 1")
        instance = cur.fetchone()
        cur.execute(
            "SELECT a.active_certificate_sha256,"
            " (a.active_certificate_sha256=%s"
            "  AND l.status='ACTIVE'"
            "  AND (c.expires_at > clock_timestamp()"
            "       OR c.claims->>'authorization_mode'='PAPER_OBSERVATION_ONLY')"
            "  AND cr.certificate_sha256 IS NULL"
            "  AND kr.key_id IS NULL),c.claims,c.expires_at"
            " FROM sentinel_execution_authority_state a"
            " LEFT JOIN sentinel_signed_execution_certificates c"
            "   ON c.certificate_sha256=a.active_certificate_sha256"
            " LEFT JOIN sentinel_execution_certificate_lifecycle l"
            "   ON l.certificate_sha256=a.active_certificate_sha256"
            " LEFT JOIN sentinel_execution_certificate_revocations cr"
            "   ON cr.certificate_sha256=a.active_certificate_sha256"
            " LEFT JOIN sentinel_execution_key_revocations kr"
            "   ON kr.key_id=c.key_id WHERE a.id=1",
            (control.certificate_sha256,))
        authority_row = cur.fetchone()
    conn.rollback()

    holder, token, heartbeat, expires, active, database_now = lease
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
    scheduler_overdue = bool(
        cycle is not None and cycle[1] not in terminal_states
        and cycle[2] is not None
        and (database_now - cycle[2]).total_seconds() > lease_window_seconds)
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
    elif scheduler_overdue:
        policy = "SCHEDULER_OVERDUE"
    elif active:
        policy = "LEADER_ACTIVE"
    else:
        policy = "WAITING_FOR_LEADER"
    return AutomationHealth(
        healthy=True,
        installed=True,
        operational_ready=(
            control.enabled and not control.kill_switch_engaged
            and control.authority_verdict == "PASS" and authority_current
            and bool(active) and service_heartbeat_fresh
            and not blocked and not scheduler_overdue),
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
        scheduler_overdue=scheduler_overdue,
        database_now=database_now,
        host_database_clock_skew_seconds=host_database_clock_skew_seconds,
    )


__all__ = ["AutomationHealth", "read_health"]
