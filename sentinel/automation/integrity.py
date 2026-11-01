"""Fail-closed integrity and clock helpers for Stage-4 automation.

The helpers in this module are deliberately read-only. Durable disagreement is
corruption evidence: nothing here repairs cycle rows or event history.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sentinel.automation.model import (
    AutomationRefused,
    CycleRecord,
    CycleSpec,
    CycleState,
)


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
        CycleState.RECONCILING, CycleState.SUPERSEDED,
        CycleState.BLOCKED,
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
        CycleState.RETRY_WAIT, CycleState.SUPERSEDED,
        CycleState.BLOCKED,
    },
    CycleState.RETRY_WAIT: {
        CycleState.REFRESHING_DATA, CycleState.PREPARING,
        CycleState.EXECUTING, CycleState.RECONCILING,
        CycleState.MISSED_STATE_ONLY, CycleState.SUPERSEDED,
        CycleState.BLOCKED,
    },
}

_MUTABLE_EVENT_FIELDS = (
    "plan_id",
    "data_version",
    "publication_fingerprint",
    "state_fingerprint",
    "plan_fingerprint",
    "last_clean_reconciliation_id",
    "next_wake_at",
    "failure_code",
    "failure_detail",
    "diagnostic",
)

# adopt_cycle currently persists these row changes but its immutable event does
# not serialize their values. After an adoption we therefore stop claiming
# value-level proof for them until a later ordinary transition explicitly
# carries the field again. State/fence/edge/attempt/completion proof remains
# mandatory, and no row is ever repaired from event data.
_ADOPTION_UNCARRIED_FIELDS = {
    "last_clean_reconciliation_id",
    "next_wake_at",
    "failure_code",
    "failure_detail",
}


def database_now(conn) -> datetime:
    """Return PostgreSQL wall time without leaving a read transaction open."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT clock_timestamp()")
            row = cur.fetchone()
        if row is None or row[0] is None:
            raise AutomationRefused("PostgreSQL clock_timestamp() returned no value")
        value = row[0]
        conn.rollback()
        return value
    except BaseException:
        conn.rollback()
        raise


def _as_detail(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value or {})


def _event_datetime(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _recovered_preflight_observation(conn, cycle: CycleRecord) -> bool:
    """Authenticate the retained native recovery proof, without broker contact."""
    diagnostic = cycle.diagnostic
    sequence = diagnostic.get("transport_reconciliation_id")
    if (not isinstance(sequence, str) or not sequence.isdecimal()
            or int(sequence) < 1
            or type(diagnostic.get("observation_id")) is not int
            or diagnostic.get("observation_id") != int(sequence)
            or str(diagnostic["observation_id"]) != sequence
            or diagnostic.get("runtime_state") != "RUNNING"
            or any(diagnostic.get(key) != [] for key in (
                "unresolved", "foreign_orders", "foreign_positions"))):
        return False
    from sentinel.execution.journal import load_observation_payload
    payload = load_observation_payload(conn, int(sequence))
    if (payload["completeness"] != "COMPLETE"
            or payload["broker"] != cycle.broker
            or payload["account_id"] != cycle.broker_account_id):
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT runtime_state FROM sentinel_observations WHERE seq=%s",
                    (int(sequence),))
        return cur.fetchone() == ("RUNNING",)


def predecessors_reached_transport(conn, cycles: list[CycleRecord]) -> bool:
    """Classify validated event histories, not the overloaded state name alone.

    Callers validate complete predecessor lineage first. A RECONCILING edge is
    harmless only when its carried snapshot proves planless preflight. Legacy
    adoption events preserve diagnostics but omit some other mutable fields.
    """
    for cycle in cycles:
        preflight = cycle.failure_code == "STALE_PREFLIGHT_RECOVERED"
        if preflight and not _recovered_preflight_observation(conn, cycle):
            return True
        with conn.cursor() as cur:
            cur.execute("SELECT from_state,to_state,control_generation,detail "
                        "FROM sentinel_automation_cycle_events "
                        "WHERE cycle_id=%s ORDER BY seq", (cycle.cycle_id,))
            events = cur.fetchall()
        diagnostic, plan_id, plan_fingerprint = {}, None, None
        if preflight:
            source, target, generation, raw_final = events[-1]
            final = _as_detail(raw_final)
            if (source not in {"RETRY_WAIT", "RECONCILING"}
                    or target != "SUPERSEDED" or generation <= cycle.control_generation
                    or final.get("adoption") is not True
                    or final.get("identity_matches_current_authority") is not True
                    or final.get("diagnostic") != cycle.diagnostic):
                return True
        for source, target, _generation, raw_detail in events:
            detail = _as_detail(raw_detail)
            if source == "EXECUTING" or target == "EXECUTING":
                return True
            if source == "RECONCILING" and (
                    not preflight or plan_id is not None or plan_fingerprint is not None
                    or diagnostic.get("retry_phase") != "PREFLIGHT_RECOVER"):
                return True
            if preflight and target == "SUPERSEDED" and (
                    diagnostic.get("retry_phase") != "PREFLIGHT_RECOVER"):
                return True
            diagnostic = detail.get("diagnostic", diagnostic)
            plan_id = detail.get("plan_id", plan_id)
            plan_fingerprint = detail.get("plan_fingerprint", plan_fingerprint)
            if preflight and (plan_id is not None or plan_fingerprint is not None):
                return True
            if diagnostic.get("retry_phase") in {"EXECUTE", "RECOVER"}:
                return True
            if target == "RECONCILING" and (
                    not preflight or plan_id is not None or plan_fingerprint is not None
                    or diagnostic.get("retry_phase") != "PREFLIGHT_RECOVER"):
                return True
    return False


def validate_cycle_lineage(conn, cycle: CycleRecord, *, _validated=None) -> CycleRecord:
    """Require the materialized cycle to be explained by immutable events.

    Validation includes deterministic identity, genesis, legal/continuous edges,
    control-generation/fence lineage, attempt count, completion semantics, and
    mutable fields explicitly carried by transition events. Adoption events are
    the only allowed exception to ordinary same-generation edges.
    """
    validated = {} if _validated is None else _validated
    if validated.get(cycle.cycle_id) == cycle:
        return cycle
    spec = CycleSpec(
        decision_session=cycle.decision_session,
        effective_session=cycle.effective_session,
        deployment_id=cycle.deployment_id,
        broker=cycle.broker,
        broker_account_id=cycle.broker_account_id,
        takeover_epoch=cycle.takeover_epoch,
        control_generation=cycle.control_generation,
        certificate_sha256=cycle.certificate_sha256,
        rollout_mode=cycle.rollout_mode,
        rollout_version=cycle.rollout_version,
        config_sha256=cycle.config_sha256,
        decision_close_at=cycle.decision_close_at,
        prepare_at=cycle.prepare_at,
        execution_open_at=cycle.execution_open_at,
        execute_at=cycle.execute_at,
        execution_close_at=cycle.execution_close_at,
        historical_state_only=cycle.historical_state_only,
    )
    replacement = cycle.cycle_id == spec.generation_cycle_id
    if cycle.cycle_id not in {spec.cycle_id, spec.generation_cycle_id}:
        raise AutomationRefused(
            "automation cycle identity does not match its immutable schedule")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seq,from_state,to_state,control_generation,fence_token,"
                " detail FROM sentinel_automation_cycle_events"
                " WHERE cycle_id=%s ORDER BY seq",
                (cycle.cycle_id,),
            )
            events = cur.fetchall()
        conn.rollback()
    except BaseException:
        conn.rollback()
        raise

    if not events:
        raise AutomationRefused("automation cycle has no genesis event")

    reconstructed: dict[str, Any] = {
        "plan_id": None,
        "data_version": None,
        "publication_fingerprint": None,
        "state_fingerprint": None,
        "plan_fingerprint": None,
        "last_clean_reconciliation_id": None,
        "next_wake_at": cycle.prepare_at,
        "failure_code": None,
        "failure_detail": None,
        "diagnostic": {},
    }
    previous: CycleState | None = None
    attempts = 0
    final_fence = None

    for index, (_seq, raw_from, raw_to, raw_generation, fence,
                raw_detail) in enumerate(events):
        detail = _as_detail(raw_detail)
        from_state = CycleState(raw_from) if raw_from is not None else None
        to_state = CycleState(raw_to)
        generation = int(raw_generation)

        if fence is None or int(fence) < 1:
            raise AutomationRefused(
                "automation cycle event contains an invalid fencing token")

        if index == 0:
            if from_state is not None or to_state is not CycleState.DISCOVERED:
                raise AutomationRefused(
                    "automation cycle genesis is not NULL -> DISCOVERED")
            if generation != cycle.control_generation:
                raise AutomationRefused(
                    "automation cycle genesis generation disagrees with row identity")
            if replacement:
                predecessors = detail.get("prospective_predecessors")
                recovered = 'recovery_authorization_generation' in detail
                fields = {'prospective_predecessors'}
                continuation = 'owner_paper_continuation' in detail
                if continuation:
                    from sentinel import local_paper
                    if detail['owner_paper_continuation'] != local_paper.MODE:
                        raise AutomationRefused('unknown owner PAPER continuation')
                    fields.add('owner_paper_continuation')
                debug = 'paper_debug_configuration' in detail
                if debug:
                    fields.add('paper_debug_configuration')
                    from sentinel.automation.model import AutomationConfig
                    try:
                        debug_config = AutomationConfig.model_validate(detail['paper_debug_configuration'])
                    except (ValueError, TypeError) as exc:
                        raise AutomationRefused('debug genesis configuration is malformed') from exc
                    if (debug_config.debug_window_for(spec) is None
                            or detail['paper_debug_configuration'] != debug_config.model_dump(mode="json", exclude_none=True)):
                        raise AutomationRefused('debug genesis configuration is not the signed cycle subject')
                if recovered:
                    fields.add('recovery_authorization_generation')
                if (set(detail) != fields
                        or not isinstance(predecessors, list) or not predecessors
                        or any(not isinstance(item, str) or len(item) != 64
                               or any(char not in '0123456789abcdef' for char in item)
                               or item == cycle.cycle_id for item in predecessors)
                        or predecessors != sorted(set(predecessors))):
                    raise AutomationRefused("prospective cycle genesis has invalid predecessors")
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT cycle_id,state,failure_code,historical_state_only "
                        "FROM sentinel_automation_cycles WHERE "
                        "deployment_id=%s AND broker=%s AND broker_account_id=%s "
                        "AND takeover_epoch=%s AND decision_session=%s AND control_generation<%s "
                        "ORDER BY cycle_id",
                        (cycle.deployment_id,cycle.broker,cycle.broker_account_id,
                         cycle.takeover_epoch,cycle.decision_session,cycle.control_generation))
                    rows = cur.fetchall()
                    known = [str(row[0]) for row in rows]
                    if continuation:
                        if not debug or recovered:
                            raise AutomationRefused('local PAPER continuation requires its explicit window')
                        from sentinel.automation import store, local_paper_continuation
                        prior = [store.load_cycle(conn, cycle_id) for cycle_id in known]
                        local_paper_continuation.require(conn, spec=spec, cycles=prior, config=debug_config)
                    elif not recovered:
                        from sentinel.automation import store
                        prior = [store.load_cycle(conn, cycle_id) for cycle_id in known]
                        for predecessor in prior:
                            validate_cycle_lineage(conn, predecessor, _validated=validated)
                        eligible = all(store._unsent_retirement(
                            cycle, spec, debug=debug, recovered_preflight=True) for cycle in prior)
                        if not eligible:
                            raise AutomationRefused('prospective cycle predecessor is not an unsent retirement')
                    from sentinel.automation import store
                    prior = [store.load_cycle(conn, cycle_id) for cycle_id in known]
                    if not continuation and predecessors_reached_transport(conn, prior):
                        raise AutomationRefused('prospective cycle predecessor reached transport')
                conn.rollback()
                if known != predecessors:
                    raise AutomationRefused("prospective cycle predecessor identity changed")
                if recovered:
                    from sentinel.automation import store, unsent_recovery as recovery
                    generation = detail['recovery_authorization_generation']
                    if type(generation) is not int or generation < 1:
                        raise AutomationRefused('recovery genesis generation is malformed')
                    prior = store._cycles_in_scope(conn, spec)
                    prior = [c for c in prior if c.control_generation < spec.control_generation]
                    recovery.require_predecessors(conn, prior, generation=spec.control_generation)
                    recovery.validate_authorization(conn, spec=spec, cycles=prior, generation=generation)
        else:
            if from_state is not previous:
                raise AutomationRefused(
                    "automation cycle event lineage is discontinuous")
            if detail.get("adoption"):
                if generation < cycle.control_generation:
                    raise AutomationRefused(
                        "automation adoption event predates originating generation")
                if detail.get("originating_control_generation") != cycle.control_generation:
                    raise AutomationRefused(
                        "automation adoption event has wrong originating generation")
                if detail.get("previous_fence_token") != final_fence:
                    raise AutomationRefused(
                        "automation adoption event has wrong predecessor fence")
                allowed = {
                    from_state,
                    CycleState.SUCCEEDED,
                    CycleState.RETRY_WAIT,
                    CycleState.SUPERSEDED,
                    CycleState.BLOCKED,
                }
                if to_state not in allowed:
                    raise AutomationRefused(
                        "automation cycle contains an illegal adoption edge")
                for field in _ADOPTION_UNCARRIED_FIELDS:
                    reconstructed.pop(field, None)
            else:
                if generation != cycle.control_generation:
                    raise AutomationRefused(
                        "ordinary cycle event escaped its originating generation")
                if to_state not in _ALLOWED_TRANSITIONS.get(from_state, set()):
                    raise AutomationRefused(
                        f"automation cycle contains illegal edge "
                        f"{from_state.value} -> {to_state.value}")

        if detail.get("increment_attempt") is True:
            attempts += 1
        for field in _MUTABLE_EVENT_FIELDS:
            if field in detail:
                reconstructed[field] = detail[field]
        previous = to_state
        final_fence = int(fence)

    if previous is not cycle.state:
        raise AutomationRefused(
            "automation cycle row state disagrees with its final event")
    if final_fence != cycle.last_fence_token:
        raise AutomationRefused(
            "automation cycle row fence disagrees with its final event")
    if attempts != cycle.attempt_count:
        raise AutomationRefused(
            "automation cycle attempt count disagrees with event history")
    if cycle.state.terminal != (cycle.completed_at is not None):
        raise AutomationRefused(
            "automation cycle completion marker disagrees with terminal state")

    for field, expected in reconstructed.items():
        actual = getattr(cycle, field)
        if field == "next_wake_at":
            expected = _event_datetime(expected)
        elif field == "diagnostic":
            expected = dict(expected or {})
            actual = dict(actual or {})
        if actual != expected:
            raise AutomationRefused(
                f"automation cycle field {field} disagrees with event history")

    validated[cycle.cycle_id] = cycle
    return cycle


__all__ = ["database_now", "validate_cycle_lineage"]
