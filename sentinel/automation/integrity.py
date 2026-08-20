"""Fail-closed integrity and clock helpers for Stage-4 automation.

The helpers in this module are deliberately read-only.  Durable disagreement is
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
# not serialize their values.  After an adoption we therefore stop claiming
# value-level proof for them until a later ordinary transition explicitly
# carries the field again.  State/fence/edge/attempt/completion proof remains
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


def validate_cycle_lineage(conn, cycle: CycleRecord) -> CycleRecord:
    """Require the materialized cycle to be explained by immutable events.

    Validation includes deterministic identity, genesis, legal/continuous edges,
    final state/fence, attempt count, completion semantics, and mutable fields
    explicitly carried by transition events.  Adoption events are the only
    allowed exception to ordinary same-generation edges.
    """
    expected_id = CycleSpec(
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
    ).cycle_id
    if cycle.cycle_id != expected_id:
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

    for index, (_seq, raw_from, raw_to, _generation, fence, raw_detail) in enumerate(events):
        detail = _as_detail(raw_detail)
        from_state = CycleState(raw_from) if raw_from is not None else None
        to_state = CycleState(raw_to)

        if index == 0:
            if from_state is not None or to_state is not CycleState.DISCOVERED:
                raise AutomationRefused(
                    "automation cycle genesis is not NULL -> DISCOVERED")
        else:
            if from_state is not previous:
                raise AutomationRefused(
                    "automation cycle event lineage is discontinuous")
            if detail.get("adoption"):
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
            elif to_state not in _ALLOWED_TRANSITIONS.get(from_state, set()):
                raise AutomationRefused(
                    f"automation cycle contains illegal edge "
                    f"{from_state.value} -> {to_state.value}")

        if detail.get("increment_attempt") is True:
            attempts += 1
        for field in _MUTABLE_EVENT_FIELDS:
            if field in detail:
                reconstructed[field] = detail[field]
        previous = to_state
        final_fence = fence

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

    return cycle


__all__ = ["database_now", "validate_cycle_lineage"]
