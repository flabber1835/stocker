"""Paper-specific readiness, authority, plan, and grant validation."""

from __future__ import annotations

import hashlib

import json

from datetime import date, datetime, timedelta

from decimal import Decimal, InvalidOperation

from typing import Mapping, Optional

from zoneinfo import ZoneInfo

from sentinel import (
    binding as binding_mod,
    dual_plan_authority,
    identity as system_identity,
    informational_paper_mirror,
    schema,
    trial,
    trial_close,
    trial_fills,
)

from sentinel.authority import (
    AuthorityRefused,
    PAPER_OBSERVATION_ONLY,
    RolloutMode,
    load_rollout_state,
    require_observation_safety_authority,
)

from sentinel.controller.concordance import is_concordance_identity

from sentinel.core import catchup

from sentinel.core.decision import (
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)

from sentinel.core.production import (
    CONCORDANCE_WITNESS_PROSPECTIVE,
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution.authority_gate import (
    build_fresh_execution_guard,
    require_current_authority,
)

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
)

from sentinel.execution.plan import ExecutionPlan

from sentinel.feed import calendar, publication, readiness, store as feed_store

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
)

def _assert_concordance_witness_authority(
        state: SessionState, authorization_mode: str) -> None:
    """Prevent a prospective witness from inheriting historical authority."""
    if (is_concordance_identity(state.strategy_identity)
            and state.concordance_witness_origin
            == CONCORDANCE_WITNESS_PROSPECTIVE
            and authorization_mode != PAPER_OBSERVATION_ONLY):
        raise PaperActivationRefused(
            "prospectively formed Concordance witness state is authorized only "
            "for PAPER_OBSERVATION_ONLY; rebuild from a complete causal "
            "metadata timeline before using historically certified authority")

def _hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()

def _readiness_or_refuse(conn, *, now_et=None):
    """Recompute readiness for the named operational session.

    The exchange-local clock, not ``--through``, decides what data is owed.
    Supplying a future decision date must not make a future-dated corpus look
    current. ``now_et`` exists only as a deterministic test seam.
    """
    if now_et is None:
        now_et = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
    report = readiness.check_readiness(conn, today=now_et.isoformat())
    if report.ready:
        return report
    detail = "; ".join(f"{c.name}: {c.detail}" for c in report.failures)
    raise PaperRetryableRefused(f"corpus readiness failed: {detail}")

def _execution_window_or_refuse(session: date, now_et: datetime) -> None:
    """Require the actual instant to lie inside the named XNYS session."""
    opened, closed = calendar.session_window(session)
    if not (opened <= now_et < closed):
        raise PaperRetryableRefused(
            f"paper execution time {now_et.isoformat()} is outside the "
            f"certified XNYS execution window for {session}: "
            f"[{opened.isoformat()}, {closed.isoformat()}). The gateway will "
            "not queue a DAY order before the open or after the close.")

def _missed_sessions(cursor: Optional[date], through: date) -> list[str]:
    if cursor is None:
        return [through.isoformat()]
    if cursor > through:
        raise PaperActivationRefused(
            f"durable cursor {cursor} is ahead of requested session {through}")
    start = cursor + timedelta(days=1)
    return calendar.sessions_in_range(start, through) if start <= through else []

def _assert_deterministic_plan_id(plan: ExecutionPlan) -> None:
    """Prove the durable handle still names the economics stored beside it."""
    expected = f"sentinel-{plan.fingerprint()}"
    if plan.plan_id != expected:
        raise PaperActivationRefused(
            f"durable plan id {plan.plan_id!r} does not match its deterministic "
            f"economic identity {expected!r}; the stored plan is corrupt")

def _fresh_connection_factory(conn):
    """Reuse the credential-preserving, target-pinned fresh DB connection path."""
    from sentinel.guarded_administration import fresh_connection_factory

    try:
        return fresh_connection_factory(conn)
    except AuthorityRefused as exc:
        raise PaperActivationRefused(
            "paper broker authority could not construct a fresh PostgreSQL "
            "connection from the active target") from exc

def _validate_automation_grant(conn, grant: AutomationExecutionGrant):
    from sentinel.automation import store as automation_store
    from sentinel.automation.model import CycleState, LeaderPermit

    control = automation_store.load_control(conn)
    if not control.enabled or control.kill_switch_engaged:
        raise PaperActivationRefused(
            "automation is disabled or its kill switch is engaged")
    bound = control.binding
    if bound is None:
        raise PaperActivationRefused("automation control has no durable binding")
    expected = (
        grant.broker_account_id, grant.takeover_epoch,
        grant.rollout_mode, grant.rollout_version,
        grant.certificate_sha256, grant.control_generation,
    )
    actual = (
        bound.broker_account_id, bound.takeover_epoch,
        bound.rollout_mode, bound.rollout_version,
        bound.certificate_sha256, control.generation,
    )
    if actual != expected:
        raise PaperActivationRefused(
            "automation grant does not match durable control authority")
    placeholder = datetime.now(ZoneInfo("UTC"))
    permit = LeaderPermit(
        holder_id=grant.holder_id, fence_token=grant.fence_token,
        control_generation=grant.control_generation,
        acquired_at=placeholder, expires_at=placeholder)
    automation_store.require_leader(conn, permit)
    cycle = automation_store.load_cycle(conn, grant.cycle_id)
    current_generation = cycle.control_generation == grant.control_generation
    if current_generation:
        cycle_expected = (
            grant.control_generation, grant.broker_account_id,
            grant.takeover_epoch, grant.rollout_mode, grant.rollout_version,
            grant.certificate_sha256,
        )
        cycle_actual = (
            cycle.control_generation, cycle.broker_account_id,
            cycle.takeover_epoch, cycle.rollout_mode, cycle.rollout_version,
            cycle.certificate_sha256,
        )
        if cycle_actual != cycle_expected:
            raise PaperActivationRefused(
                "automation cycle does not match its live fencing grant")
    else:
        # Only read-only recovery may cross a generation boundary. The core's
        # sole adoption operation proves that this old obligation needs
        # read-only recovery for the same deployment/account/takeover identity
        # and stamps the current live fence without rewriting its historical
        # rollout/certificate identity. A planless preflight has not crossed a
        # transport boundary; stale plan economics are never compared with
        # current authority and can never execute.
        if (grant.operation_scope != "RECOVER"
                or cycle.control_generation >= grant.control_generation
                or not automation_store.cycle_recovery_capable(cycle)
                or not automation_store.adoption_identity_matches(
                    cycle, control)
                or cycle.last_fence_token != grant.fence_token):
            raise PaperActivationRefused(
                "old-generation automation cycle lacks current fenced "
                "read-only recovery adoption")
    if grant.operation_scope == "PREPARE":
        allowed = {CycleState.PREPARING}
    elif grant.operation_scope == "RECOVER":
        allowed = {
            CycleState.DISCOVERED, CycleState.REFRESHING_DATA,
            CycleState.EXECUTING, CycleState.RECONCILING,
            CycleState.RETRY_WAIT,
        }
    else:
        allowed = {CycleState.EXECUTING, CycleState.RECONCILING,
                   CycleState.RETRY_WAIT}
    if cycle.state not in allowed:
        raise PaperActivationRefused(
            f"automation cycle state {cycle.state.value} does not permit "
            f"{grant.operation_scope.lower()} broker access")
    return control, cycle

def _validate_broker_grant(
        conn, grant, _operation: BrokerOperation, result, *, now_provider,
        strategy_provider, dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None) -> None:
    """Fresh database-only grant proof run before and after every broker read."""
    from sentinel.handover import assert_no_legacy_path

    binding = assert_no_legacy_path(conn)
    reported = (result.identity if isinstance(result, BrokerAccountSnapshot)
                else result if isinstance(result, BrokerAccountIdentity)
                else None)
    if reported is not None and not binding.identity.matches_account(reported):
        raise PaperActivationRefused(
            "broker result identity does not match the durable binding")
    rollout = load_rollout_state(conn)
    now_et = now_provider()
    if now_et.tzinfo is None:
        raise PaperActivationRefused("broker authority clock is timezone-naive")
    current = publication.require_current(conn)
    frontier = feed_store.latest_visible_session(conn)
    runtime_strategy = dict(strategy_provider())

    if isinstance(grant, AutomationExecutionGrant):
        _control, cycle = _validate_automation_grant(conn, grant)
        if (binding.broker_account_id != grant.broker_account_id
                or binding.takeover_epoch != grant.takeover_epoch):
            raise PaperActivationRefused(
                "automation grant account/takeover identity is stale")
        decision_session = cycle.decision_session
        if grant.operation_scope == "EXECUTE":
            dual_mode = (
                dual_shadow_observation_id is not None
                and dual_shadow_starting_cash is not None)
            if dual_mode:
                plan = journal.latest_plan(conn)
                if plan is None:
                    raise PaperActivationRefused(
                        "dual broker guard has no current PAPER plan")
                from sentinel import dual_reconciliation
                try:
                    shadow = dual_reconciliation.verified_shadow_intent(
                        conn, decision_session=plan.decision_session,
                        observation_id=str(dual_shadow_observation_id),
                        starting_cash=dual_shadow_starting_cash)
                except (
                        dual_reconciliation.DualReconciliationPending,
                        dual_reconciliation.DualReconciliationRefused) as exc:
                    raise PaperActivationRefused(
                        f"dual broker guard shadow authority refused: {exc}") from exc
                state = SessionState.from_dict(shadow.state.to_dict())
                try:
                    dual_plan_authority.rederive_plan(
                        conn, plan=plan, binding=binding,
                        rollout_state=rollout,
                        expected_shadow_result=shadow)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual broker guard sizing authority refused: {exc}") from exc
            else:
                state, plan, _cursor = _state_and_plan_or_refuse(conn)
            if (cycle.plan_id != plan.plan_id
                    or cycle.plan_fingerprint != plan.fingerprint()):
                raise PaperActivationRefused(
                    "automation cycle does not name the durable current plan")
            _readiness_or_refuse(conn, now_et=now_et)
            _execution_window_or_refuse(plan.effective_session, now_et)
            _assert_plan_authorities(
                conn, state=state, plan=plan, binding=binding,
                pinned=current, frontier=str(frontier), today=now_et.date(),
                runtime_identity=runtime_strategy, rollout=rollout)
            return
        if grant.operation_scope == "RECOVER":
            return
    elif isinstance(grant, PaperPreparationGrant):
        if binding.broker_account_id != grant.expected_account:
            raise PaperActivationRefused(
                "paper preparation grant account is stale")
        decision_session = grant.decision_session
    elif isinstance(grant, ManualExecutionGrant):
        state, plan, _cursor = _state_and_plan_or_refuse(conn)
        if (grant.confirm_paper_account != binding.broker_account_id
                or grant.confirm_plan_id != plan.plan_id
                or grant.confirm_effective_session != plan.effective_session):
            raise PaperActivationRefused(
                "manual execution grant no longer names current authority")
        _readiness_or_refuse(conn, now_et=now_et)
        _execution_window_or_refuse(plan.effective_session, now_et)
        _assert_plan_authorities(
            conn, state=state, plan=plan, binding=binding, pinned=current,
            frontier=str(frontier), today=now_et.date(),
            runtime_identity=runtime_strategy, rollout=rollout)
        return
    else:                                                       # pragma: no cover
        raise PaperActivationRefused("unknown guarded broker grant")

    # Full readiness was computed once by prepare_paper_plan while the
    # originating connection holds publication.pinned()'s session-level shared
    # advisory lock.  That lock excludes ingest/publication writers for the
    # whole preparation. Fresh guard connections still recheck the cheap
    # publication/frontier/calendar identity before every broker read, but must
    # not rescan the corpus just to prove a fact the retained pin cannot change.
    latest_closed = calendar.latest_closed_session(now_et)
    if (decision_session.isoformat() != latest_closed
            or str(frontier) != decision_session.isoformat()):
        raise PaperActivationRefused(
            "preparation grant no longer names the latest closed published "
            "XNYS session")

def _guard_broker(*, conn, broker: ExecutionBroker, grant, base_url: str,
                  now_provider, strategy_provider,
                  automation_config_sha256: str | None = None,
                  dual_shadow_observation_id: str | None = None,
                  dual_shadow_starting_cash: Decimal | str | None = None
                  ) -> GuardedExecutionBroker:
    guard = build_fresh_execution_guard(
        connection_factory=_fresh_connection_factory(conn),
        paper_base_url=base_url,
        runtime_identity=system_identity.rehearsal_identity,
        strategy_identity=strategy_provider,
        validate_grant=lambda fresh, current_grant, operation, result: (
            _validate_broker_grant(
                fresh, current_grant, operation, result,
                now_provider=now_provider,
                strategy_provider=strategy_provider,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)),
        automation_config_sha256=automation_config_sha256,
        authority_check=require_current_authority)
    return GuardedExecutionBroker(inner=broker, grant=grant, guard=guard)

def _state_and_plan_or_refuse(conn) -> tuple[SessionState, ExecutionPlan, object]:
    plan = journal.latest_plan(conn)
    if plan is None:
        raise PaperActivationRefused("there is no durable current execution plan")
    _assert_deterministic_plan_id(plan)
    raw = catchup.resume_state(conn)
    cursor = catchup.last_processed_session(conn)
    if raw is None or cursor is None:
        raise PaperActivationRefused("the current plan has no canonical state/cursor")
    state = SessionState.from_dict(raw)
    if state.last_processed_session != cursor.isoformat():
        raise PaperActivationRefused("canonical state and cursor disagree")
    return state, plan, cursor

def _assert_plan_authorities(conn, *, state: SessionState, plan: ExecutionPlan,
                             binding, pinned, frontier: str, today: date,
                             runtime_identity: Mapping, rollout,
                             require_effective_today: bool = True) -> None:
    _assert_deterministic_plan_id(plan)
    if plan.decision_session.isoformat() != frontier:
        raise PaperActivationRefused("plan decision session is not the current frontier")
    if require_effective_today and plan.effective_session != today:
        raise PaperActivationRefused(
            f"plan is effective {plan.effective_session}, not today {today}")
    if plan.effective_session.isoformat() != calendar.next_session(
            plan.decision_session):
        raise PaperActivationRefused("plan effective session is not next XNYS session")
    if state.last_processed_session != plan.decision_session.isoformat():
        raise PaperActivationRefused("plan session is not the canonical state cursor")
    if state.state_hash != plan.shadow_snapshot_hash:
        raise PaperActivationRefused("plan state fingerprint is stale")
    if _hash(state.last_decision) != plan.sentinel_transition_hash:
        raise PaperActivationRefused("plan controller-transition fingerprint is stale")
    if _hash(state.strategy_identity) != plan.strategy_fingerprint:
        raise PaperActivationRefused("plan strategy fingerprint is stale")
    if state.strategy_identity != dict(runtime_identity):
        raise PaperActivationRefused(
            "durable strategy/config/source identity differs from runtime")
    if (plan.data_version != pinned.version
            or state.data_version != pinned.version
            or plan.publication_fingerprint != publication_fingerprint(pinned)):
        raise PaperActivationRefused("plan publication identity is stale")
    expected = binding.identity
    actual = (plan.deployment_id, plan.broker, plan.broker_account_id,
              plan.takeover_epoch)
    wanted = (expected.deployment_id, expected.broker,
              expected.broker_account_id, expected.takeover_epoch)
    if actual != wanted:
        raise PaperActivationRefused("plan account/deployment identity is stale")
    plan_rollout = (
        plan.rollout_mode, plan.rollout_version,
        plan.rollout_certificate_sha256)
    current_rollout = (
        rollout.mode.value, rollout.version, rollout.certificate_sha256)
    if plan_rollout != current_rollout:
        raise PaperActivationRefused(
            "plan rollout mode/version authority is stale")
    if (rollout.mode is RolloutMode.PINNED_1_00
            and plan.target_exposure != Decimal(1)):
        raise PaperActivationRefused(
            "pinned rollout plan target exposure is not exactly 1")
