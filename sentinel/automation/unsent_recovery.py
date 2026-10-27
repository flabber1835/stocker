"""Explicit scheduling recovery; no broker contact or failed-cycle mutation."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Literal

from pydantic import Field, field_validator

from sentinel.automation.model import AutomationRefused, ControlBinding, CycleState
from sentinel.feed import calendar
from sentinel.feed.rolling_contract import Contract, Digest, digest

ACTION = 'KILL_ENGAGED'
KIND = 'LOCAL_CONTENTION_MISCLASSIFIED'
PREFLIGHT_KIND = 'PREFLIGHT_IDENTITY_BEYOND_FRONTIER'
SOURCE_FRONTIER_KIND = 'ROLLING_SOURCE_FRONTIER_MISCLASSIFIED'
PUBLICATION_CHANGED_KIND = 'ROLLING_PUBLICATION_ADVANCE_MISCLASSIFIED'
PUBLICATION_CHANGED_FAILURE = ('certified shadow status is invalid: shadow status refused: '
    'Refused: ROLLING_RUNTIME_PUBLICATION_CHANGED')
SOURCE_FRONTIER_FAILURE = ('certified shadow status is invalid: shadow status refused: '
    'RollingSourceFrontierPending: ROLLING_INPUTS_NOT_READY: rolling source-final frontier')
PREFLIGHT_FAILURE = ('unreviewed callback exception '
    'sentinel.execution.feed_inputs.ExecutionInputsRefused: '
    'ROLLING_IDENTITY_BEYOND_NEXT_SESSION')


class Authorization(Contract):
    schema_id: Literal['sentinel.unsent-recovery/1'] = Field(
        default='sentinel.unsent-recovery/1', alias='schema')
    kind: Literal['LOCAL_CONTENTION_MISCLASSIFIED',
                  'PREFLIGHT_IDENTITY_BEYOND_FRONTIER',
                  'ROLLING_SOURCE_FRONTIER_MISCLASSIFIED',
                  'ROLLING_PUBLICATION_ADVANCE_MISCLASSIFIED'] = KIND
    binding: ControlBinding
    decision_session: date
    effective_session: date
    blocked_cycle_id: Digest
    predecessor_fingerprints: dict[Digest, Digest]

    @field_validator('predecessor_fingerprints')
    @classmethod
    def require_predecessors(cls, value):
        if not value:
            raise ValueError('recovery requires predecessors')
        return value


def eligible_kind(cycle):
    """Recognize typed historical adapter failures, never operator free text."""
    if cycle.state is not CycleState.BLOCKED or cycle.historical_state_only:
        return None
    if (cycle.failure_code == 'NonRetryableCallbackRefused'
            and cycle.diagnostic.get('control_poll_failure') == 'NONRETRYABLE'
            and any((cycle.failure_detail or '').startswith(
                'automation authority/integrity refusal: ' + name + ': ')
                for name in ('CorpusLockUnavailable', 'WriterLockUnavailable'))):
        return KIND
    if (cycle.plan_id is None and cycle.failure_code == 'SoftwareDefect'
            and cycle.failure_detail == PREFLIGHT_FAILURE
            and cycle.diagnostic.get('retry_phase') == 'PREFLIGHT_RECOVER'
            and cycle.diagnostic.get('callback_failure') == 'SOFTWARE_DEFECT'
            and cycle.diagnostic.get('terminal_reason') == 'SOFTWARE_DEFECT'
            and cycle.diagnostic.get('exception_type')
                == 'sentinel.automation.model.SoftwareDefect'):
        return PREFLIGHT_KIND
    if (cycle.plan_id is None and cycle.failure_code == 'NonRetryableCallbackRefused'
            and cycle.failure_detail == SOURCE_FRONTIER_FAILURE
            and cycle.diagnostic.get('retry_phase') == 'REFRESH'
            and cycle.diagnostic.get('callback_failure') == 'PERMANENT_OPERATIONAL_REFUSAL'
            and cycle.diagnostic.get('terminal_reason') == 'PERMANENT_OPERATIONAL_REFUSAL'
            and cycle.diagnostic.get('exception_type')
                == 'sentinel.automation.model.NonRetryableCallbackRefused'):
        return SOURCE_FRONTIER_KIND
    if (cycle.plan_id is None and cycle.failure_code == 'NonRetryableCallbackRefused'
            and cycle.failure_detail == PUBLICATION_CHANGED_FAILURE
            and cycle.diagnostic.get('retry_phase') == 'REFRESH'
            and cycle.diagnostic.get('callback_failure') == 'PERMANENT_OPERATIONAL_REFUSAL'
            and cycle.diagnostic.get('terminal_reason') == 'PERMANENT_OPERATIONAL_REFUSAL'
            and cycle.diagnostic.get('exception_type')
                == 'sentinel.automation.model.NonRetryableCallbackRefused'):
        return PUBLICATION_CHANGED_KIND
    return None


def eligible_block(cycle) -> bool:
    return eligible_kind(cycle) is not None


def fingerprints(cycles):
    result = {}
    for cycle in sorted(cycles, key=lambda c: c.cycle_id):
        record = cycle.model_dump(mode='json')
        for name in type(cycle).model_fields:
            value = getattr(cycle, name)
            if isinstance(value, datetime):
                record[name] = value.astimezone(timezone.utc).isoformat()
        result[cycle.cycle_id] = digest(record)
    return result


def require_unsent(conn, cycles, *, binding, effective_session):
    """Negative transport proof for the entire scoped obligation and journal."""
    ids = [c.cycle_id for c in cycles]
    plans = [c.plan_id for c in cycles if c.plan_id is not None]
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_automation_cycle_events "
                    "WHERE cycle_id=ANY(%s::text[]) AND (from_state IN ('EXECUTING','RECONCILING') "
                    "OR to_state IN ('EXECUTING','RECONCILING')))", (ids,))
        if cur.fetchone()[0]:
            raise AutomationRefused('recovery predecessor reached transport/reconciliation')
        cur.execute("SELECT EXISTS(SELECT 1 FROM sentinel_commands c "
                    "LEFT JOIN sentinel_execution_plans p USING(plan_id) "
                    "WHERE c.plan_id=ANY(%s::text[]) OR (c.deployment_id=%s "
                    "AND c.broker=%s AND c.broker_account_id=%s AND c.takeover_epoch=%s "
                    "AND (p.plan_id IS NULL OR p.effective_session=%s "
                    "OR c.state NOT IN ('FILLED','CANCELLED','REJECTED','SUPERSEDED'))))",
                    (plans, binding.deployment_id, binding.broker,
                     binding.broker_account_id, binding.takeover_epoch,
                     effective_session))
        if cur.fetchone()[0]:
            raise AutomationRefused('recovery has durable commands or unresolved outcomes')


def require_predecessors(conn, cycles, *, generation):
    from sentinel.automation.integrity import validate_cycle_lineage
    if not cycles or not any(eligible_block(c) for c in cycles):
        raise AutomationRefused('recovery has no eligible reviewed unsent block')
    for cycle in cycles:
        validate_cycle_lineage(conn, cycle)
        superseded = (cycle.state is CycleState.SUPERSEDED
                      and cycle.failure_code == 'CONTROL_GENERATION_SUPERSEDED')
        if (cycle.control_generation >= generation or cycle.historical_state_only
                or not (eligible_block(cycle) or superseded)):
            raise AutomationRefused('recovery has an ineligible predecessor')


def load_authorization(conn, generation):
    with conn.cursor() as cur:
        cur.execute('SELECT action,detail,at FROM sentinel_automation_events '
                    'WHERE generation=%s', (generation,))
        rows = cur.fetchall()
    if len(rows) != 1 or rows[0][0] != ACTION:
        raise AutomationRefused('recovery authorization is missing or ambiguous')
    try:
        detail = rows[0][1]
        if isinstance(detail, str):
            detail = json.loads(detail)
        return decode_authorization(detail), rows[0][2]
    except (ValueError, TypeError) as exc:
        raise AutomationRefused('recovery authorization is malformed') from exc


def is_authorization(conn, generation):
    with conn.cursor() as cur:
        cur.execute('SELECT action,detail FROM sentinel_automation_events WHERE generation=%s',
                    (generation,))
        rows = cur.fetchall()
    return (len(rows) == 1 and rows[0][0] == ACTION and isinstance(rows[0][1], dict)
            and rows[0][1].get('schema') == 'sentinel.unsent-recovery/1')


def decode_authorization(detail):
    if not isinstance(detail, dict) or set(detail) != {
            'schema', 'kind', 'binding', 'decision_session', 'effective_session',
            'blocked_cycle_id', 'predecessor_fingerprints'}:
        raise AutomationRefused('recovery authorization shape changed')
    return Authorization.model_validate(detail)


def authorization_generation(conn, spec):
    """Only an immediately subsequent exact-binding kill release may consume."""
    from sentinel.automation import store
    generation = spec.control_generation - 1
    if store.control_generation_action(conn, generation=generation) != ACTION:
        raise AutomationRefused('current activation has no recovery authorization')
    return generation


def validate_authorization(conn, *, spec, cycles, generation):
    from sentinel.automation import store
    auth, authorized_at = load_authorization(conn, generation)
    binding = ControlBinding.model_validate({
        key: getattr(spec, key) for key in ControlBinding.model_fields})
    if (generation + 1 != spec.control_generation
            or store.control_generation_action(conn, generation=spec.control_generation)
            != 'KILL_RELEASED'
            or auth.binding != binding or auth.decision_session != spec.decision_session
            or auth.effective_session != spec.effective_session
            or auth.predecessor_fingerprints != fingerprints(cycles)
            or auth.blocked_cycle_id not in {c.cycle_id for c in cycles if eligible_block(c)}
            or auth.kind != next((eligible_kind(c) for c in cycles
                                   if c.cycle_id == auth.blocked_cycle_id), None)
            or authorized_at >= spec.execution_open_at):
        raise AutomationRefused('recovery authorization does not match this exact obligation')
    return auth


def require_fresh_plan(conn, cycle, plan_id):
    """A recovered cycle must never acquire a predecessor's immutable plan."""
    with conn.cursor() as cur:
        cur.execute('SELECT detail FROM sentinel_automation_cycle_events '
                    'WHERE cycle_id=%s AND from_state IS NULL', (cycle.cycle_id,))
        row = cur.fetchone()
    detail = row[0] if row else {}
    if isinstance(detail, str):
        detail = json.loads(detail)
    generation = detail.get('recovery_authorization_generation')
    if generation is None:
        return
    auth, _ = load_authorization(conn, generation)
    with conn.cursor() as cur:
        cur.execute('SELECT EXISTS(SELECT 1 FROM sentinel_automation_cycles '
                    'WHERE cycle_id=ANY(%s::text[]) AND plan_id=%s)',
                    (list(auth.predecessor_fingerprints), plan_id))
        if cur.fetchone()[0]:
            raise AutomationRefused('recovery requires a fresh plan under renewed authority')


def authorize(conn, *, binding, decision_session, blocked_cycle_id,
              actor, reason, now: datetime, automation_config):
    """Called only after fresh signed authority by the authorized operator CLI."""
    from sentinel.automation import schedule, store
    from sentinel.execution import journal
    actor = store._require_text(actor, 'actor')
    reason = store._require_text(reason, 'reason')
    decision = date.fromisoformat(str(decision_session))
    if (now.tzinfo is None or now.utcoffset() is None
            or str(decision) != calendar.latest_closed_session(now)):
        raise AutomationRefused('recovery requires the actual latest closed decision')
    if automation_config.fingerprint != binding.config_sha256:
        raise AutomationRefused('recovery configuration differs from current authority')
    timing = schedule.for_decision_session(decision, automation_config)
    if now >= timing.execution_open_at:
        raise AutomationRefused('recovery execution session has already opened')
    try:
        with journal.writer_lock(conn):
            journal.require_observation_integrity(conn)
            current = store.load_control(conn)
            observed_generation = current.generation
            if (not current.enabled or not current.kill_switch_engaged
                    or current.binding != binding):
                raise AutomationRefused('recovery requires exact activated authority behind the kill fence')
            with conn.cursor() as cur:
                cur.execute('SELECT clock_timestamp(),EXISTS(SELECT 1 FROM sentinel_automation_lease '
                            'WHERE holder_id IS NOT NULL AND expires_at>clock_timestamp())')
                clock, live = cur.fetchone()
            if live or clock >= timing.execution_open_at:
                raise AutomationRefused('recovery leader is live or execution session has opened')
            spec = store.CycleSpec(**binding.model_dump(),
                control_generation=current.generation, **timing.model_dump())
            cycles = store._cycles_in_scope(conn, spec)
            require_predecessors(conn, cycles, generation=current.generation)
            if blocked_cycle_id not in {c.cycle_id for c in cycles if eligible_block(c)}:
                raise AutomationRefused('blocked-cycle confirmation does not match eligible scope')
            require_unsent(conn, cycles, binding=binding, effective_session=timing.effective_session)
            kind = next(eligible_kind(c) for c in cycles if c.cycle_id == blocked_cycle_id)
            auth = Authorization(kind=kind, binding=binding, decision_session=decision,
                effective_session=timing.effective_session, blocked_cycle_id=blocked_cycle_id,
                predecessor_fingerprints=fingerprints(cycles))
            conn.rollback()
            current = store.load_control(conn, for_update=True)
            if (not current.enabled or not current.kill_switch_engaged or current.binding != binding
                    or current.generation != observed_generation):
                raise AutomationRefused('recovery authority changed before authorization')
            if is_authorization(conn, current.generation):
                existing, _ = load_authorization(conn, current.generation)
                if existing != auth:
                    raise AutomationRefused('repeated recovery request changed its exact scope')
                conn.rollback()
                return current.generation, auth
            generation = current.generation + 1
            with conn.cursor() as cur:
                cur.execute('UPDATE sentinel_automation_control SET generation=%s,'
                            'authority_verdict=NULL,authority_detail=NULL,authority_checked_at=NULL,'
                            'updated_at=clock_timestamp() WHERE id=1 AND generation=%s '
                            'AND enabled AND kill_switch_engaged AND clock_timestamp()<%s',
                            (generation, current.generation, timing.execution_open_at))
                if cur.rowcount != 1:
                    raise AutomationRefused('recovery authorization boundary changed')
                store._invalidate_lease(cur)
                store._insert_control_event(cur, generation=generation, action=ACTION,
                    actor=actor, reason=reason, detail=auth.model_dump(mode='json', by_alias=True))
            conn.commit()
            store.load_control(conn)
            return generation, auth
    except BaseException:
        conn.rollback()
        raise
