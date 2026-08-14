"""SELECT-only durable health projection for supervisors and the panel."""
from __future__ import annotations

from datetime import datetime

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
    last_clean_reconciliation_id: str | None = None
    pending_alerts: int = 0
    dead_letter_alerts: int = 0
    unacknowledged_alerts: int = 0
    last_instance_id: str | None = None
    last_instance_heartbeat_at: datetime | None = None
    reason: str | None = None


def read_health(conn) -> AutomationHealth:
    """Read policy and service state without constructing any broker client.

    Correctly disabled or killed is supervisor-healthy but not operationally
    ready.  A missing singleton is both uninstalled and unhealthy.
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
            "  AND expires_at > clock_timestamp())"
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
            " last_clean_reconciliation_id"
            " FROM sentinel_automation_cycles"
            " ORDER BY decision_session DESC,created_at DESC LIMIT 1")
        cycle = cur.fetchone()
        cur.execute(
            "SELECT"
            " COUNT(*) FILTER (WHERE state IN ('PENDING','DELIVERING')),"
            " COUNT(*) FILTER (WHERE state='DEAD_LETTER'),"
            " COUNT(*) FILTER (WHERE ack_state='UNACKNOWLEDGED')"
            " FROM sentinel_alert_outbox")
        pending, dead, unacknowledged = cur.fetchone()
        cur.execute(
            "SELECT instance_id,heartbeat_at FROM"
            " sentinel_automation_service_instances"
            " ORDER BY heartbeat_at DESC LIMIT 1")
        instance = cur.fetchone()
        cur.execute(
            "SELECT a.active_certificate_sha256,"
            " (a.active_certificate_sha256=%s"
            "  AND l.status='ACTIVE'"
            "  AND c.expires_at > clock_timestamp()"
            "  AND cr.certificate_sha256 IS NULL"
            "  AND kr.key_id IS NULL)"
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

    holder, token, heartbeat, expires, active = lease
    authority_current = bool(
        authority_row is not None and authority_row[0] is not None
        and authority_row[1])
    if not control.enabled:
        policy = "DISABLED"
    elif control.kill_switch_engaged:
        policy = "KILLED"
    elif control.authority_verdict == "FAIL":
        policy = "AUTHORITY_FAILED"
    elif control.authority_verdict != "PASS":
        policy = "AUTHORITY_UNVERIFIED"
    elif not authority_current:
        policy = "AUTHORITY_INVALID"
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
            and bool(active)),
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
        pending_alerts=pending,
        dead_letter_alerts=dead,
        unacknowledged_alerts=unacknowledged,
        last_instance_id=instance[0] if instance else None,
        last_instance_heartbeat_at=instance[1] if instance else None,
    )


__all__ = ["AutomationHealth", "read_health"]
