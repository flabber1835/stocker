"""PostgreSQL-backed control, leader fencing, and durable cycle state."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from sentinel.automation.model import (
    AutomationControl,
    AutomationRefused,
    ControlBinding,
    CycleRecord,
    CycleSpec,
    CycleState,
    ImmutableCycleChanged,
    InvalidCycleTransition,
    LeaderPermit,
    MissingAutomationState,
    StaleLeaderRefused,
)
from sentinel.execution.journal import writer_lock


_CONTROL_COLUMNS = (
    "enabled,generation,kill_switch_engaged,deployment_id,broker,"
    "broker_account_id,takeover_epoch,certificate_sha256,rollout_mode,"
    "rollout_version,config_sha256,authority_verdict,authority_detail,"
    "authority_checked_at,enabled_at,disabled_at,updated_at"
)
_CYCLE_COLUMNS = (
    "cycle_id,state,decision_session,effective_session,deployment_id,broker,"
    "broker_account_id,takeover_epoch,control_generation,certificate_sha256,"
    "rollout_mode,rollout_version,config_sha256,decision_close_at,prepare_at,"
    "execution_open_at,execute_at,execution_close_at,historical_state_only,"
    "plan_id,data_version,"
    "publication_fingerprint,state_fingerprint,plan_fingerprint,"
    "last_clean_reconciliation_id,attempt_count,next_wake_at,last_fence_token,"
    "failure_code,failure_detail,diagnostic,created_at,updated_at,completed_at"
)
_CYCLE_COLUMNS_ALIASED = ",".join(
    f"c.{column}" for column in _CYCLE_COLUMNS.split(","))


def _json(value: Mapping[str, Any] | None) -> str:
    return json.dumps(
        dict(value or {}), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, default=str)


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AutomationRefused(f"{label} must be non-empty")
    return value.strip()


def _control(row) -> AutomationControl:
    return AutomationControl.model_validate(dict(zip(
        (
            "enabled", "generation", "kill_switch_engaged",
            "deployment_id", "broker", "broker_account_id", "takeover_epoch",
            "certificate_sha256", "rollout_mode", "rollout_version",
            "config_sha256", "authority_verdict", "authority_detail",
            "authority_checked_at", "enabled_at", "disabled_at", "updated_at",
        ), row, strict=True)))


def _cycle(row) -> CycleRecord:
    names = _CYCLE_COLUMNS.split(",")
    return CycleRecord.model_validate(dict(zip(names, row, strict=True)))


def load_control(conn, *, for_update: bool = False) -> AutomationControl:
    suffix = " FOR UPDATE" if for_update else ""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CONTROL_COLUMNS} FROM sentinel_automation_control "
            f"WHERE id=1{suffix}")
        row = cur.fetchone()
    if row is None:
        raise MissingAutomationState(
            "durable automation control is missing; schema startup does not "
            "repair operational intent")
    return _control(row)


def control_generation_action(conn, *, generation: int) -> str | None:
    """Return the immutable action that created a control generation."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_automation_events"
            " WHERE generation=%s ORDER BY seq DESC LIMIT 1", (generation,))
        row = cur.fetchone()
    return str(row[0]) if row is not None else None


def _insert_control_event(
        cur, *, generation: int, action: str, actor: str, reason: str,
        detail: Mapping[str, Any] | None = None) -> None:
    cur.execute(
        "INSERT INTO sentinel_automation_events"
        " (generation,action,actor,reason,detail)"
        " VALUES (%s,%s,%s,%s,%s::jsonb)",
        (generation, action, actor, reason, _json(detail)))


def _invalidate_lease(cur) -> None:
    cur.execute(
        "UPDATE sentinel_automation_lease SET holder_id=NULL,"
        " control_generation=NULL,acquired_at=NULL,heartbeat_at=NULL,"
        " expires_at=NULL,updated_at=clock_timestamp() WHERE id=1")
    if cur.rowcount != 1:
        raise MissingAutomationState(
            "durable automation lease singleton is missing")


def activate(
        conn, *, binding: ControlBinding, actor: str,
        reason: str) -> AutomationControl:
    """Bind unattended authority; deliberately leave the kill engaged."""
    actor = _require_text(actor, "actor")
    reason = _require_text(reason, "reason")
    try:
        current = load_control(conn, for_update=True)
        if current.enabled:
            raise AutomationRefused(
                "automation is already enabled; deactivate before rebinding")
        generation = current.generation + 1
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_control SET enabled=TRUE,"
                " generation=%s,kill_switch_engaged=TRUE,deployment_id=%s,"
                " broker=%s,broker_account_id=%s,takeover_epoch=%s,"
                " certificate_sha256=%s,rollout_mode=%s,rollout_version=%s,"
                " config_sha256=%s,enabled_at=clock_timestamp(),"
                " disabled_at=NULL,authority_verdict=NULL,"
                " authority_detail=NULL,authority_checked_at=NULL,"
                " updated_at=clock_timestamp() WHERE id=1",
                (generation, binding.deployment_id, binding.broker,
                 binding.broker_account_id, binding.takeover_epoch,
                 binding.certificate_sha256, binding.rollout_mode,
                 binding.rollout_version, binding.config_sha256))
            _invalidate_lease(cur)
            _insert_control_event(
                cur, generation=generation, action="ACTIVATED", actor=actor,
                reason=reason, detail=binding.model_dump(mode="json"))
        conn.commit()
        return load_control(conn)
    except BaseException:
        conn.rollback()
        raise


def deactivate(
        conn, *, actor: str, reason: str) -> AutomationControl:
    """Disable automation and fence every old worker without broker contact."""
    actor = _require_text(actor, "actor")
    reason = _require_text(reason, "reason")
    try:
        current = load_control(conn, for_update=True)
        if not current.enabled:
            raise AutomationRefused("automation is already disabled")
        generation = current.generation + 1
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_control SET enabled=FALSE,"
                " generation=%s,kill_switch_engaged=TRUE,"
                " disabled_at=clock_timestamp(),authority_verdict=NULL,"
                " authority_detail=NULL,authority_checked_at=NULL,"
                " updated_at=clock_timestamp()"
                " WHERE id=1", (generation,))
            _invalidate_lease(cur)
            _insert_control_event(
                cur, generation=generation, action="DEACTIVATED", actor=actor,
                reason=reason)
        conn.commit()
        return load_control(conn)
    except BaseException:
        conn.rollback()
        raise


def engage_kill(
        conn, *, actor: str, reason: str) -> AutomationControl:
    """Immediately fence workers.  This never cancels or liquidates anything."""
    actor = _require_text(actor, "actor")
    reason = _require_text(reason, "reason")
    try:
        current = load_control(conn, for_update=True)
        if current.kill_switch_engaged:
            raise AutomationRefused(
                "automation kill switch is already engaged")
        generation = current.generation + 1
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_control SET generation=%s,"
                " kill_switch_engaged=TRUE,authority_verdict=NULL,"
                " authority_detail=NULL,authority_checked_at=NULL,"
                " updated_at=clock_timestamp()"
                " WHERE id=1", (generation,))
            _invalidate_lease(cur)
            _insert_control_event(
                cur, generation=generation, action="KILL_ENGAGED", actor=actor,
                reason=reason)
        conn.commit()
        return load_control(conn)
    except BaseException:
        conn.rollback()
        raise


def engage_config_mismatch_kill(
        conn, *, expected_generation: int,
        expected_config_sha256: str, actual_config_sha256: str
        ) -> AutomationControl:
    """Atomically latch a changed service configuration behind the kill.

    This is a system fencing action, not an operator shortcut around activation.
    Its compare-and-set identity prevents a stale process from overwriting a
    concurrent operator generation change.
    """
    for value, label in (
            (expected_config_sha256, "expected config SHA-256"),
            (actual_config_sha256, "actual config SHA-256")):
        if (not isinstance(value, str) or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)):
            raise AutomationRefused(f"{label} is malformed")
    try:
        current = load_control(conn, for_update=True)
        if (not current.enabled or current.kill_switch_engaged
                or current.generation != expected_generation
                or current.config_sha256 != expected_config_sha256):
            raise StaleLeaderRefused(
                "automation control changed before configuration fencing")
        if expected_config_sha256 == actual_config_sha256:
            raise AutomationRefused(
                "automation configuration still matches durable activation")
        generation = current.generation + 1
        detail = {
            "activated_config_sha256": expected_config_sha256,
            "observed_config_sha256": actual_config_sha256,
            "originating_generation": expected_generation,
        }
        reason = (
            "automatic kill: runtime automation configuration differs from "
            "durable activation")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_control SET generation=%s,"
                " kill_switch_engaged=TRUE,authority_verdict=NULL,"
                " authority_detail=NULL,authority_checked_at=NULL,"
                " updated_at=clock_timestamp() WHERE id=1 AND generation=%s"
                " AND enabled AND NOT kill_switch_engaged"
                " AND config_sha256=%s",
                (generation, expected_generation, expected_config_sha256))
            if cur.rowcount != 1:
                raise StaleLeaderRefused(
                    "automation control raced configuration fencing")
            _invalidate_lease(cur)
            _insert_control_event(
                cur, generation=generation, action="KILL_ENGAGED",
                actor="sentinel-automation", reason=reason, detail=detail)
        conn.commit()
        return load_control(conn)
    except BaseException:
        conn.rollback()
        raise


def release_kill(
        conn, *, expected_binding: ControlBinding, actor: str,
        reason: str) -> AutomationControl:
    """Second explicit activation boundary, with exact identity confirmation."""
    actor = _require_text(actor, "actor")
    reason = _require_text(reason, "reason")
    try:
        current = load_control(conn, for_update=True)
        if not current.enabled:
            raise AutomationRefused(
                "automation is disabled; activate before releasing the kill")
        if not current.kill_switch_engaged:
            raise AutomationRefused(
                "automation kill switch is already released")
        if current.binding != expected_binding:
            raise AutomationRefused(
                "kill release identity does not match durable activation")
        generation = current.generation + 1
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_control SET generation=%s,"
                " kill_switch_engaged=FALSE,authority_verdict=NULL,"
                " authority_detail=NULL,authority_checked_at=NULL,"
                " updated_at=clock_timestamp()"
                " WHERE id=1", (generation,))
            _invalidate_lease(cur)
            _insert_control_event(
                cur, generation=generation, action="KILL_RELEASED", actor=actor,
                reason=reason, detail=expected_binding.model_dump(mode="json"))
        conn.commit()
        return load_control(conn)
    except BaseException:
        conn.rollback()
        raise


def acquire_lease(
        conn, *, holder_id: str, lease_seconds: int) -> LeaderPermit:
    """Acquire or renew leadership using only PostgreSQL's clock.

    The existing execution writer lock serializes takeover with manual command
    handling.  A live lease owned by another instance is never stealable.
    """
    holder_id = _require_text(holder_id, "holder_id")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    with writer_lock(conn):
        control = load_control(conn, for_update=True)
        if not control.enabled:
            raise AutomationRefused("automation is disabled")
        if control.kill_switch_engaged:
            raise AutomationRefused("automation kill switch is engaged")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT holder_id,fence_token,control_generation,acquired_at,"
                " expires_at,clock_timestamp()"
                " FROM sentinel_automation_lease WHERE id=1 FOR UPDATE")
            row = cur.fetchone()
            if row is None:
                raise MissingAutomationState(
                    "durable automation lease singleton is missing")
            (current_holder, current_token, current_generation,
             acquired_at, expires_at, database_now) = row
            live = (
                current_holder is not None
                and current_generation == control.generation
                and expires_at is not None
                and expires_at > database_now
            )
            if live and current_holder != holder_id:
                raise AutomationRefused(
                    f"automation leader lease is held by {current_holder!r}")
            if live:
                token = current_token
                acquired = acquired_at
            else:
                token = current_token + 1
                acquired = database_now
            cur.execute(
                "UPDATE sentinel_automation_lease SET holder_id=%s,"
                " fence_token=%s,control_generation=%s,acquired_at=%s,"
                " heartbeat_at=clock_timestamp(),"
                " expires_at=clock_timestamp()+(%s * INTERVAL '1 second'),"
                " updated_at=clock_timestamp() WHERE id=1"
                " RETURNING acquired_at,expires_at",
                (holder_id, token, control.generation, acquired,
                 lease_seconds))
            acquired, expires = cur.fetchone()
        return LeaderPermit(
            holder_id=holder_id, fence_token=token,
            control_generation=control.generation,
            acquired_at=acquired, expires_at=expires)


def heartbeat_lease(
        conn, *, permit: LeaderPermit,
        lease_seconds: int) -> LeaderPermit:
    """Renew only an unexpired, still-authorized lease; never resurrect one."""
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_lease AS l SET"
                " heartbeat_at=clock_timestamp(),"
                " expires_at=clock_timestamp()+(%s * INTERVAL '1 second'),"
                " updated_at=clock_timestamp()"
                " FROM sentinel_automation_control AS c"
                " WHERE l.id=1 AND c.id=1 AND c.enabled"
                " AND NOT c.kill_switch_engaged"
                " AND c.generation=%s AND l.control_generation=c.generation"
                " AND l.holder_id=%s AND l.fence_token=%s"
                " AND l.expires_at > clock_timestamp()"
                " RETURNING l.acquired_at,l.expires_at",
                (lease_seconds, permit.control_generation, permit.holder_id,
                 permit.fence_token))
            row = cur.fetchone()
        if row is None:
            raise StaleLeaderRefused(
                "automation lease expired, was fenced, or authority changed")
        conn.commit()
        return permit.model_copy(update={"expires_at": row[1]})
    except BaseException:
        conn.rollback()
        raise


def require_leader(conn, permit: LeaderPermit) -> LeaderPermit:
    """Fresh database-time fence check with no surviving read transaction.

    Callers use the returned permit only as a proof. Mutating store operations
    perform their own conditional SQL fence after this boundary, so this
    function deliberately owns and closes its read transaction instead of
    holding AccessShare locks across scheduler sleeps or broker work.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT l.acquired_at,l.expires_at"
                " FROM sentinel_automation_control AS c"
                " JOIN sentinel_automation_lease AS l ON l.id=1"
                " WHERE c.id=1 AND c.enabled AND NOT c.kill_switch_engaged"
                " AND c.generation=%s AND l.control_generation=c.generation"
                " AND l.holder_id=%s AND l.fence_token=%s"
                " AND l.expires_at > clock_timestamp()",
                (permit.control_generation, permit.holder_id, permit.fence_token))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM sentinel_automation_control"
                    " WHERE id=1),EXISTS(SELECT 1 FROM sentinel_automation_lease"
                    " WHERE id=1)")
                control_exists, lease_exists = cur.fetchone()
                if not control_exists or not lease_exists:
                    raise MissingAutomationState(
                        "automation control or lease singleton is missing")
                raise StaleLeaderRefused(
                    "caller does not hold the live automation fencing token")
        result = permit.model_copy(
            update={"acquired_at": row[0], "expires_at": row[1]})
        conn.rollback()
        return result
    except BaseException:
        conn.rollback()
        raise


def release_lease(conn, *, permit: LeaderPermit) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_lease SET holder_id=NULL,"
                " control_generation=NULL,acquired_at=NULL,heartbeat_at=NULL,"
                " expires_at=NULL,updated_at=clock_timestamp()"
                " WHERE id=1 AND holder_id=%s AND fence_token=%s"
                " AND control_generation=%s",
                (permit.holder_id, permit.fence_token,
                 permit.control_generation))
            if cur.rowcount != 1:
                raise StaleLeaderRefused(
                    "cannot release a lease owned by another fencing token")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def load_cycle(conn, cycle_id: str, *, for_update: bool = False) -> CycleRecord:
    suffix = " FOR UPDATE" if for_update else ""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CYCLE_COLUMNS} FROM sentinel_automation_cycles"
            f" WHERE cycle_id=%s{suffix}", (cycle_id,))
        row = cur.fetchone()
    if row is None:
        raise AutomationRefused(f"automation cycle {cycle_id!r} is missing")
    return _cycle(row)


def latest_cycle(conn, *, include_historical: bool = False) -> CycleRecord | None:
    predicate = "" if include_historical else " WHERE NOT historical_state_only"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CYCLE_COLUMNS} FROM sentinel_automation_cycles"
            + predicate
            + " ORDER BY decision_session DESC,created_at DESC LIMIT 1")
        row = cur.fetchone()
    return _cycle(row) if row is not None else None


def oldest_nonterminal_cycle(conn) -> CycleRecord | None:
    """Next live obligation, including a historical audit not yet finalized."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CYCLE_COLUMNS} FROM sentinel_automation_cycles"
            " WHERE state NOT IN ('SUCCEEDED','MISSED_STATE_ONLY',"
            " 'SUPERSEDED','BLOCKED')"
            " ORDER BY decision_session,created_at LIMIT 1")
        row = cur.fetchone()
    return _cycle(row) if row is not None else None


def oldest_unresolved_transport_cycle(
        conn, *, before_session) -> CycleRecord | None:
    """Oldest cycle whose durable command outcome can require re-observation."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CYCLE_COLUMNS} FROM sentinel_automation_cycles"
            " WHERE NOT historical_state_only"
            " AND state IN ('EXECUTING','RECONCILING','RETRY_WAIT')"
            " AND decision_session < %s"
            " ORDER BY decision_session LIMIT 1", (before_session,))
        row = cur.fetchone()
    return _cycle(row) if row is not None else None


def oldest_nonterminal_other_generation_cycle(
        conn, *, control_generation: int) -> CycleRecord | None:
    """Return the next durable obligation fenced by an older generation."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CYCLE_COLUMNS} FROM sentinel_automation_cycles"
            " WHERE control_generation<>%s"
            " AND state NOT IN ('SUCCEEDED','MISSED_STATE_ONLY',"
            " 'SUPERSEDED','BLOCKED')"
            " ORDER BY decision_session,created_at LIMIT 1",
            (control_generation,))
        row = cur.fetchone()
    return _cycle(row) if row is not None else None


def blocked_cycle_for_generation(
        conn, *, control_generation: int) -> CycleRecord | None:
    """Find a block latched by this generation, including adopted cycles."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_CYCLE_COLUMNS_ALIASED}"
            " FROM sentinel_automation_cycles c"
            " WHERE c.state='BLOCKED' AND EXISTS ("
            " SELECT 1 FROM sentinel_automation_cycle_events e"
            " WHERE e.cycle_id=c.cycle_id AND e.to_state='BLOCKED'"
            " AND e.control_generation=%s)"
            " ORDER BY c.decision_session DESC,c.created_at DESC LIMIT 1",
            (control_generation,))
        row = cur.fetchone()
    return _cycle(row) if row is not None else None


def cycle_transport_capable(cycle: CycleRecord) -> bool:
    """Whether a cycle may have crossed a durable broker-send boundary."""
    if cycle.state in {CycleState.EXECUTING, CycleState.RECONCILING}:
        return True
    return (cycle.state is CycleState.RETRY_WAIT
            and str(cycle.diagnostic.get("retry_phase", "")) in {
                "EXECUTE", "RECOVER", "PREFLIGHT_RECOVER",
            })


def adoption_identity_matches(
        cycle: CycleRecord, control: AutomationControl) -> bool:
    """Recovery may use current authority only for the same paper account."""
    binding = control.binding
    if binding is None:
        return False
    return (
        cycle.deployment_id,
        cycle.broker,
        cycle.broker_account_id,
        cycle.takeover_epoch,
    ) == (
        binding.deployment_id,
        binding.broker,
        binding.broker_account_id,
        binding.takeover_epoch,
    )


def _immutable_cycle(record: CycleRecord) -> dict[str, Any]:
    return {
        key: getattr(record, key)
        for key in (
            "decision_session", "effective_session", "deployment_id", "broker",
            "broker_account_id", "takeover_epoch", "control_generation",
            "certificate_sha256", "rollout_mode", "rollout_version",
            "config_sha256", "decision_close_at", "prepare_at",
            "execution_open_at", "execute_at", "execution_close_at",
            "historical_state_only",
        )
    }


def create_cycle(
        conn, *, permit: LeaderPermit, spec: CycleSpec) -> CycleRecord:
    """Idempotently create one full-hash cycle under a live leader fence."""
    if spec.control_generation != permit.control_generation:
        raise StaleLeaderRefused(
            "cycle identity does not match the leader's control generation")
    expected = spec.model_dump()
    try:
        require_leader(conn, permit)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_automation_cycles"
                " (cycle_id,state,decision_session,effective_session,"
                " deployment_id,broker,broker_account_id,takeover_epoch,"
                " control_generation,certificate_sha256,rollout_mode,"
                " rollout_version,config_sha256,decision_close_at,prepare_at,"
                " execution_open_at,execute_at,execution_close_at,"
                " historical_state_only,next_wake_at,last_fence_token)"
                " SELECT %s,'DISCOVERED',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                " %s,%s,%s,%s,%s,%s,%s,%s"
                " WHERE EXISTS (SELECT 1 FROM sentinel_automation_control c"
                " JOIN sentinel_automation_lease l ON l.id=1"
                " WHERE c.id=1 AND c.enabled AND NOT c.kill_switch_engaged"
                " AND c.generation=%s AND l.control_generation=c.generation"
                " AND l.holder_id=%s AND l.fence_token=%s"
                " AND l.expires_at > clock_timestamp())"
                " ON CONFLICT (cycle_id) DO NOTHING RETURNING cycle_id",
                (spec.cycle_id, spec.decision_session, spec.effective_session,
                 spec.deployment_id, spec.broker, spec.broker_account_id,
                 spec.takeover_epoch, spec.control_generation,
                 spec.certificate_sha256, spec.rollout_mode,
                 spec.rollout_version, spec.config_sha256,
                 spec.decision_close_at, spec.prepare_at,
                 spec.execution_open_at, spec.execute_at,
                 spec.execution_close_at, spec.historical_state_only,
                 spec.prepare_at, permit.fence_token,
                 permit.control_generation, permit.holder_id,
                 permit.fence_token))
            inserted = cur.fetchone() is not None
            if inserted:
                cur.execute(
                    "INSERT INTO sentinel_automation_cycle_events"
                    " (cycle_id,from_state,to_state,control_generation,"
                    " fence_token,detail) VALUES (%s,NULL,'DISCOVERED',%s,%s,"
                    " '{}'::jsonb)",
                    (spec.cycle_id, permit.control_generation,
                     permit.fence_token))
        if not inserted:
            require_leader(conn, permit)
        conn.commit()
        stored = load_cycle(conn, spec.cycle_id)
        actual = _immutable_cycle(stored)
        if actual != expected:
            raise ImmutableCycleChanged(
                "deterministic automation cycle identity was reused with "
                "different immutable fields")
        return stored
    except BaseException:
        conn.rollback()
        raise


_ALLOWED_TRANSITIONS = {
    CycleState.DISCOVERED: {
        CycleState.REFRESHING_DATA, CycleState.PREPARING,
        CycleState.RETRY_WAIT, CycleState.MISSED_STATE_ONLY,
        CycleState.SUPERSEDED, CycleState.BLOCKED,
    },
    CycleState.REFRESHING_DATA: {
        CycleState.PREPARING, CycleState.RETRY_WAIT,
        CycleState.MISSED_STATE_ONLY, CycleState.SUPERSEDED,
        CycleState.BLOCKED,
    },
    CycleState.PREPARING: {
        CycleState.PLAN_READY, CycleState.RETRY_WAIT,
        CycleState.MISSED_STATE_ONLY, CycleState.SUPERSEDED,
        CycleState.BLOCKED,
    },
    CycleState.PLAN_READY: {
        CycleState.WAITING_OPEN, CycleState.EXECUTING,
        CycleState.RECONCILING, CycleState.SUPERSEDED, CycleState.BLOCKED,
    },
    CycleState.WAITING_OPEN: {
        CycleState.EXECUTING, CycleState.RECONCILING,
        CycleState.SUPERSEDED, CycleState.BLOCKED,
    },
    CycleState.EXECUTING: {
        CycleState.RECONCILING, CycleState.SUCCEEDED,
        CycleState.RETRY_WAIT, CycleState.BLOCKED,
    },
    CycleState.RECONCILING: {
        CycleState.EXECUTING, CycleState.SUCCEEDED,
        CycleState.RETRY_WAIT, CycleState.SUPERSEDED, CycleState.BLOCKED,
    },
    CycleState.RETRY_WAIT: {
        CycleState.REFRESHING_DATA, CycleState.PREPARING,
        CycleState.EXECUTING, CycleState.RECONCILING,
        CycleState.MISSED_STATE_ONLY, CycleState.SUPERSEDED,
        CycleState.BLOCKED,
    },
}

_UNSET = object()


def transition_cycle(
        conn, *, permit: LeaderPermit, cycle_id: str, to_state: CycleState,
        plan_id: str | None | object = _UNSET,
        data_version: str | None | object = _UNSET,
        publication_fingerprint: str | None | object = _UNSET,
        state_fingerprint: str | None | object = _UNSET,
        plan_fingerprint: str | None | object = _UNSET,
        last_clean_reconciliation_id: str | None | object = _UNSET,
        next_wake_at: datetime | None | object = _UNSET,
        failure_code: str | None | object = _UNSET,
        failure_detail: str | None | object = _UNSET,
        diagnostic: Mapping[str, Any] | object = _UNSET,
        increment_attempt: bool = False) -> CycleRecord:
    """Transition and event append in one fenced transaction."""
    if not isinstance(to_state, CycleState):
        to_state = CycleState(to_state)
    try:
        require_leader(conn, permit)
        current = load_cycle(conn, cycle_id, for_update=True)
        if (current.historical_state_only
                and to_state not in {
                    CycleState.MISSED_STATE_ONLY, CycleState.BLOCKED}):
            raise InvalidCycleTransition(
                "a historical state-only audit cycle can never become "
                "preparable or executable")
        allowed = _ALLOWED_TRANSITIONS.get(current.state, set())
        if to_state not in allowed:
            raise InvalidCycleTransition(
                f"automation cycle cannot move {current.state.value} -> "
                f"{to_state.value}")

        assignments = [
            "state=%s", "last_fence_token=%s",
            "updated_at=clock_timestamp()",
        ]
        params: list[Any] = [to_state.value, permit.fence_token]
        fields = {
            "plan_id": plan_id,
            "data_version": data_version,
            "publication_fingerprint": publication_fingerprint,
            "state_fingerprint": state_fingerprint,
            "plan_fingerprint": plan_fingerprint,
            "last_clean_reconciliation_id": last_clean_reconciliation_id,
            "next_wake_at": next_wake_at,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
        }
        detail: dict[str, Any] = {}
        for column, value in fields.items():
            if value is not _UNSET:
                assignments.append(f"{column}=%s")
                params.append(value)
                detail[column] = value
        if diagnostic is not _UNSET:
            assignments.append("diagnostic=%s::jsonb")
            params.append(_json(diagnostic))
            detail["diagnostic"] = diagnostic
        if increment_attempt:
            assignments.append("attempt_count=attempt_count+1")
            detail["increment_attempt"] = True
        if to_state.terminal:
            assignments.append("completed_at=clock_timestamp()")

        params.extend([
            cycle_id, current.state.value, permit.control_generation,
            permit.control_generation,
            permit.holder_id, permit.fence_token,
        ])
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_cycles SET "
                + ",".join(assignments)
                + " WHERE cycle_id=%s AND state=%s AND EXISTS ("
                  "SELECT 1 FROM sentinel_automation_control c"
                  " JOIN sentinel_automation_lease l ON l.id=1"
                  " WHERE c.id=1 AND sentinel_automation_cycles.control_generation=%s"
                  " AND c.enabled AND NOT c.kill_switch_engaged"
                  " AND c.generation=%s AND l.control_generation=c.generation"
                  " AND l.holder_id=%s AND l.fence_token=%s"
                  " AND l.expires_at > clock_timestamp())",
                tuple(params))
            if cur.rowcount != 1:
                raise StaleLeaderRefused(
                    "cycle transition lost its generation or fencing token")
            cur.execute(
                "INSERT INTO sentinel_automation_cycle_events"
                " (cycle_id,from_state,to_state,control_generation,"
                " fence_token,detail) VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                (cycle_id, current.state.value, to_state.value,
                 permit.control_generation, permit.fence_token, _json(detail)))
        conn.commit()
        return load_cycle(conn, cycle_id)
    except BaseException:
        conn.rollback()
        raise


def adopt_cycle(
        conn, *, permit: LeaderPermit, cycle_id: str,
        to_state: CycleState | None = None,
        last_clean_reconciliation_id: str | None = None,
        next_wake_at: datetime | None = None,
        failure_code: str | None = None,
        failure_detail: str | None = None,
        diagnostic: Mapping[str, Any] | None = None,
        increment_attempt: bool = False) -> CycleRecord:
    """Adopt a fenced cycle without rewriting its originating identity.

    This is the sole cross-generation transition.  A current live leader may
    stamp its fence before read-only recovery, or terminalize an old
    obligation.  It can never move an old cycle into an executable state.
    """
    if to_state is not None and not isinstance(to_state, CycleState):
        to_state = CycleState(to_state)
    try:
        require_leader(conn, permit)
        control = load_control(conn)
        current = load_cycle(conn, cycle_id, for_update=True)
        if current.state.terminal:
            raise InvalidCycleTransition(
                "a terminal automation cycle cannot be adopted")
        if current.control_generation == permit.control_generation:
            if current.last_fence_token == permit.fence_token:
                raise InvalidCycleTransition(
                    "the live fence already owns this cycle; adoption is not "
                    "a same-worker transition")
        elif current.control_generation > permit.control_generation:
            raise StaleLeaderRefused(
                "a leader cannot adopt a future-generation cycle")

        transport_capable = cycle_transport_capable(current)
        identity_matches = adoption_identity_matches(current, control)
        if to_state is None:
            if not transport_capable:
                raise InvalidCycleTransition(
                    "only a transport-capable cycle needs recovery adoption")
            if not identity_matches:
                raise AutomationRefused(
                    "ambiguous cycle paper-account identity differs from "
                    "current authority")
            target = current.state
        else:
            target = to_state
            allowed = ({CycleState.SUCCEEDED, CycleState.RETRY_WAIT,
                        CycleState.SUPERSEDED, CycleState.BLOCKED}
                       if transport_capable else
                       {CycleState.SUPERSEDED, CycleState.BLOCKED})
            if target not in allowed:
                raise InvalidCycleTransition(
                    f"adoption cannot move {current.state.value} -> "
                    f"{target.value}")
            if (transport_capable and target is not CycleState.BLOCKED
                    and not identity_matches):
                raise AutomationRefused(
                    "ambiguous cycle paper-account identity differs from "
                    "current authority")

        assignments = [
            "state=%s", "last_fence_token=%s",
            "updated_at=clock_timestamp()",
        ]
        params: list[Any] = [target.value, permit.fence_token]
        if to_state is not None or next_wake_at is not None:
            assignments.append("next_wake_at=%s")
            params.append(next_wake_at)
        for column, value in (
                ("last_clean_reconciliation_id",
                 last_clean_reconciliation_id),
                ("failure_code", failure_code),
                ("failure_detail", failure_detail)):
            assignments.append(f"{column}=%s")
            params.append(value)
        event_detail: dict[str, Any] = {
            "adoption": True,
            "originating_control_generation": current.control_generation,
            "previous_fence_token": current.last_fence_token,
            "identity_matches_current_authority": identity_matches,
        }
        if diagnostic is not None:
            assignments.append("diagnostic=%s::jsonb")
            params.append(_json(diagnostic))
            event_detail["diagnostic"] = dict(diagnostic)
        if increment_attempt:
            assignments.append("attempt_count=attempt_count+1")
            event_detail["increment_attempt"] = True
        if target.terminal:
            assignments.append("completed_at=clock_timestamp()")
        params.extend([
            cycle_id, current.state.value, permit.control_generation,
            permit.holder_id, permit.fence_token,
        ])
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_cycles SET "
                + ",".join(assignments)
                + " WHERE cycle_id=%s AND state=%s AND EXISTS ("
                  "SELECT 1 FROM sentinel_automation_control c"
                  " JOIN sentinel_automation_lease l ON l.id=1"
                  " WHERE c.id=1 AND c.enabled AND NOT c.kill_switch_engaged"
                  " AND c.generation=%s AND l.control_generation=c.generation"
                  " AND l.holder_id=%s AND l.fence_token=%s"
                  " AND l.expires_at > clock_timestamp())",
                tuple(params))
            if cur.rowcount != 1:
                raise StaleLeaderRefused(
                    "cycle adoption lost its current fencing token")
            cur.execute(
                "INSERT INTO sentinel_automation_cycle_events"
                " (cycle_id,from_state,to_state,control_generation,"
                " fence_token,detail) VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                (cycle_id, current.state.value, target.value,
                 permit.control_generation, permit.fence_token,
                 _json(event_detail)))
        conn.commit()
        return load_cycle(conn, cycle_id)
    except BaseException:
        conn.rollback()
        raise


def ensure_historical_cycles(
        conn, *, permit: LeaderPermit,
        specs) -> tuple[CycleRecord, ...]:
    """Create non-executable audit obligations before canonical catch-up.

    They remain DISCOVERED until the injected canonical preparation path has
    durably advanced state. A crash before that boundary therefore cannot
    falsely record a historical session as processed.
    """
    records = []
    for spec in sorted(specs, key=lambda value: value.decision_session):
        if not spec.historical_state_only:
            raise ValueError("historical cycle specs must be state-only")
        require_leader(conn, permit)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_CYCLE_COLUMNS} FROM sentinel_automation_cycles"
                " WHERE cycle_id=%s", (spec.cycle_id,))
            row = cur.fetchone()
        conn.rollback()
        if row is None:
            records.append(create_cycle(conn, permit=permit, spec=spec))
            continue

        existing = _cycle(row)
        if existing.historical_state_only:
            # Reuse create_cycle's full immutable comparison for an already
            # precreated historical obligation.
            records.append(create_cycle(conn, permit=permit, spec=spec))
            continue
        if existing.state not in {
                CycleState.SUPERSEDED, CycleState.BLOCKED}:
            raise ImmutableCycleChanged(
                "canonical catch-up found a non-historical daily cycle that "
                "is not safely terminal")
        if (existing.decision_session != spec.decision_session
                or existing.effective_session != spec.effective_session
                or existing.deployment_id != spec.deployment_id
                or existing.broker != spec.broker
                or existing.broker_account_id != spec.broker_account_id
                or existing.takeover_epoch != spec.takeover_epoch):
            raise ImmutableCycleChanged(
                "terminal daily cycle identity differs from the canonical "
                "catch-up obligation")
        # There is deliberately one row per account/session.  Its terminal
        # lifecycle plus the canonical processed-session cursor is the audit
        # evidence; manufacturing a second row would discard the original
        # authority and recovery history.
        require_leader(conn, permit)
        records.append(existing)
    return tuple(records)


def mark_historical_missed(
        conn, *, permit: LeaderPermit,
        before_session) -> tuple[CycleRecord, ...]:
    """Audit canonical catch-up only after its preparation callback succeeds."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cycle_id,state FROM sentinel_automation_cycles"
            " WHERE historical_state_only AND decision_session < %s"
            " AND state NOT IN ('MISSED_STATE_ONLY','SUPERSEDED','SUCCEEDED',"
            " 'BLOCKED') ORDER BY decision_session", (before_session,))
        pending = cur.fetchall()
    conn.rollback()  # end the read transaction before per-cycle fenced commits
    completed = []
    for cycle_id, state in pending:
        if CycleState(state) is not CycleState.DISCOVERED:
            raise InvalidCycleTransition(
                f"historical cycle {cycle_id} unexpectedly reached {state}")
        completed.append(transition_cycle(
            conn, permit=permit, cycle_id=cycle_id,
            to_state=CycleState.MISSED_STATE_ONLY,
            failure_code="HISTORICAL_STATE_ONLY",
            failure_detail=(
                "canonical catch-up advanced this missed session; no plan from "
                "it may be executed")))
    return tuple(completed)


def register_instance(
        conn, *, instance_id: str, state: str,
        next_wake_at: datetime | None = None,
        last_error: str | None = None) -> None:
    instance_id = _require_text(instance_id, "instance_id")
    state = _require_text(state, "state")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_automation_service_instances"
            " (instance_id,state,next_wake_at,last_error) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (instance_id) DO UPDATE SET"
            " heartbeat_at=clock_timestamp(),state=EXCLUDED.state,"
            " next_wake_at=EXCLUDED.next_wake_at,"
            " last_error=EXCLUDED.last_error,updated_at=clock_timestamp()",
            (instance_id, state, next_wake_at, last_error))
    conn.commit()


def record_authority_verdict(
        conn, *, verdict: str, detail: str,
        holder_id: str, fence_token: int, control_generation: int,
        instance_id: str | None = None) -> None:
    """Persist the service's actual signed-authority verdict for the panel."""
    verdict = str(verdict).strip().upper()
    detail = str(detail).strip()
    if verdict not in {"PASS", "FAIL"}:
        raise ValueError("authority verdict must be PASS or FAIL")
    if not detail:
        raise ValueError("authority verdict detail must be non-empty")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_automation_control SET authority_verdict=%s,"
                " authority_detail=%s,authority_checked_at=clock_timestamp(),"
                " updated_at=clock_timestamp() WHERE id=1"
                " AND enabled AND NOT kill_switch_engaged AND generation=%s"
                " AND EXISTS (SELECT 1 FROM sentinel_automation_lease l"
                " WHERE l.id=1 AND l.control_generation=%s"
                " AND l.holder_id=%s AND l.fence_token=%s"
                " AND l.expires_at > clock_timestamp())",
                (verdict, detail[:4000], control_generation,
                 control_generation, holder_id, fence_token))
            if cur.rowcount != 1:
                raise StaleLeaderRefused(
                    "authority verdict lost its live automation fence")
            if instance_id is not None:
                cur.execute(
                    "UPDATE sentinel_automation_service_instances"
                    " SET authority_verdict=%s,authority_detail=%s,"
                    " authority_checked_at=clock_timestamp(),"
                    " updated_at=clock_timestamp() WHERE instance_id=%s",
                    (verdict, detail[:4000], instance_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


# ``execution`` may have been imported by this module's journal dependency and
# observed us before ``engage_kill`` existed. Complete the emergency-authority
# serialization only after this module is fully defined.
from sentinel.execution.alpaca_remediation import (  # noqa: E402
    install_automation_serialization as _install_automation_serialization,
)
from sentinel.execution.alpaca_remediation_authority_semantics import (  # noqa: E402
    install as _install_immediate_authority_semantics,
)

_install_automation_serialization()
_install_immediate_authority_semantics()
del _install_automation_serialization
del _install_immediate_authority_semantics


__all__ = [
    "acquire_lease", "activate", "adopt_cycle",
    "adoption_identity_matches", "blocked_cycle_for_generation",
    "control_generation_action", "create_cycle",
    "cycle_transport_capable", "engage_config_mismatch_kill",
    "deactivate", "engage_kill",
    "ensure_historical_cycles", "heartbeat_lease", "latest_cycle",
    "load_control", "load_cycle", "mark_historical_missed",
    "oldest_nonterminal_other_generation_cycle",
    "oldest_nonterminal_cycle",
    "oldest_unresolved_transport_cycle", "record_authority_verdict",
    "register_instance", "release_kill",
    "release_lease", "require_leader", "transition_cycle",
]
