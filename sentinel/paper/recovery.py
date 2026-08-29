"""Restart and unresolved paper-cycle recovery orchestration."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from decimal import Decimal, InvalidOperation

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

from sentinel.config import DEFAULT_BASE_URL, assert_paper_url

from sentinel.core import catchup

from sentinel.core.production import (
    CONCORDANCE_WITNESS_PROSPECTIVE,
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution import preopen_authority

from sentinel.execution import reconcile as reconciliation

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

from sentinel.execution.states import RuntimeState

from sentinel.feed import calendar, publication, readiness, store as feed_store

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
    PreOpenShareUnitAuthorityUnavailable,
)

from .inspection import (
    _require_certified_paper_broker,
    _account_evidence_is_quiescent,
    _recovery_account_identity_or_refuse,
)

from .validation import (
    _assert_deterministic_plan_id,
    _validate_automation_grant,
    _guard_broker,
)

from .cash import (
    _broker_cash_state_or_refuse,
    _cash_authority_or_refuse,
)

from .targets import (
    _action_lookup,
    _target_action_lookup,
    _post_projection_action_multipliers,
    _preopen_active_security_ids,
    _preopen_views_or_none,
    _revalidate_preopen_authority_or_refuse,
    _official_preopen_cutoff,
    _target_projection_or_refuse,
)

from .reconciliation import (
    _dual_mutation_observation_or_refuse,
    _settled_account_evidence_bracket,
)

from .preparation import _default_paper_strategy

async def recover_automated_paper_cycle(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: AutomationExecutionGrant,
        automation_config_sha256: str,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None):
    """Read-only reconciliation for restart/pre-publication automation recovery."""
    if grant.operation_scope != "RECOVER":
        raise PaperActivationRefused(
            "automation recovery requires a RECOVER-scoped grant")
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER recovery requires both reviewed shadow identity and "
            "starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    schema.require_runtime_schema(conn)
    with journal.writer_lock(conn):
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        rollout = load_rollout_state(conn)
        _controller_config, strategy = _default_paper_strategy()
        current = publication.require_current(conn)
        authority_kwargs = dict(
            runtime_identity=system_identity.rehearsal_identity(),
            strategy_identity=strategy, required_mode=rollout.mode,
            paper_base_url=base_url,
            current_publication_version=current.version,
            automation_config_sha256=automation_config_sha256)
        try:
            automated = require_current_authority(
                conn, required_operation="AUTOMATION", **authority_kwargs)
            readable = require_current_authority(
                conn, required_operation="EXECUTE_READ", **authority_kwargs)
            if automated.certificate_sha256 != readable.certificate_sha256:
                raise AuthorityRefused(
                    "automation and recovery authority differ")
        except AuthorityRefused:
            readable = require_observation_safety_authority(
                conn, required_operation="SAFETY_READ",
                required_mode=rollout.mode, paper_base_url=base_url)
        if grant.certificate_sha256 != readable.certificate_sha256:
            raise PaperActivationRefused(
                "automation recovery grant and signed safety authority differ")
        _control, cycle = _validate_automation_grant(conn, grant)
        clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
        broker = _guard_broker(
            conn=conn, broker=broker, grant=grant, base_url=base_url,
            now_provider=clock,
            strategy_provider=lambda: _default_paper_strategy()[1],
            automation_config_sha256=automation_config_sha256,
            dual_shadow_observation_id=dual_shadow_observation_id,
            dual_shadow_starting_cash=dual_shadow_starting_cash)
        account = await broker.account_snapshot()
        _recovery_account_identity_or_refuse(
            account, binding, grant.broker_account_id)
        activity_state = await _broker_cash_state_or_refuse(
            conn, broker=broker, binding=binding, through=clock())
        # A dual recovery never consults the separate PAPER catch-up lineage.
        # Its exact shadow state is loaded after the current-generation plan is
        # identified below.
        raw = None if dual_mode else catchup.resume_state(conn)
        state = SessionState.from_dict(raw) if raw is not None else None

        # An adopted old-generation obligation may be reconciled under the
        # current safety fence, but its stale plan economics must never be
        # loaded or interpreted under current authority.  Only the exact plan
        # already bound to this live generation can supply a target or a
        # plan-bound pre-open share-unit publication.
        plan = None
        if (cycle.control_generation == grant.control_generation
                and cycle.plan_id is not None):
            candidate = journal.load_plan(conn, cycle.plan_id)
            if (candidate is not None
                    and candidate.fingerprint() == cycle.plan_fingerprint
                    and candidate.decision_session == cycle.decision_session
                    and candidate.effective_session
                    == cycle.effective_session):
                _assert_deterministic_plan_id(candidate)
                plan = candidate

        dual_result = None
        if dual_mode and plan is not None:
            from sentinel import dual_reconciliation
            try:
                dual_result = dual_reconciliation.verified_shadow_intent(
                    conn, decision_session=plan.decision_session,
                    observation_id=str(dual_shadow_observation_id),
                    starting_cash=dual_shadow_starting_cash)
            except dual_reconciliation.DualReconciliationPending as exc:
                raise PaperRetryableRefused(str(exc)) from exc
            except dual_reconciliation.DualReconciliationRefused as exc:
                raise PaperActivationRefused(str(exc)) from exc
            state = SessionState.from_dict(dual_result.state.to_dict())
            try:
                dual_plan_authority.rederive_plan(
                    conn, plan=plan, binding=binding,
                    rollout_state=rollout,
                    expected_shadow_result=dual_result)
            except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual sizing authority refused recovery: {exc}") from exc
            try:
                # A cycle can remain RECONCILING across the next close.  Its
                # due post-close unit check must be earned here before the
                # transport fence is consulted; otherwise require_transport
                # reports PENDING forever and successor preparation (the other
                # caller of revalidate_all) is unreachable.
                with publication.pinned(conn, commit=False) as mirror_pin:
                    if mirror_pin.version != current.version:
                        raise PaperRetryableRefused(
                            "corpus publication advanced while dual recovery "
                            "authority was being established")
                    current_frontier = feed_store.latest_visible_session(conn)
                    from sentinel import shadow_runtime
                    if clock() < shadow_runtime.publication_not_before(
                            str(current_frontier)):
                        raise informational_paper_mirror.InformationalPaperMirrorPending(
                            "current publication has not reached the reviewed "
                            "23:45 New York source-final boundary")
                    informational_paper_mirror.revalidate_all(
                        conn, checked_through=current_frontier,
                        publication_version=mirror_pin.version, commit=True)
                    informational_paper_mirror.require_transport_permitted(
                        conn, current_frontier=current_frontier,
                        current_publication_version=mirror_pin.version)
            except informational_paper_mirror.InformationalPaperMirrorPending as exc:
                raise PaperRetryableRefused(
                    f"informational PAPER recovery is pending: {exc}") from exc
            except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
                raise PaperActivationRefused(
                    f"informational PAPER recovery is blocked: {exc}") from exc

        actions = (_action_lookup(conn, state, clock().date())
                   if state is not None else None)
        authority = None
        target_projection = None
        target_actions = None
        observation_target_actions = None
        if plan is not None:
            target_actions = _target_action_lookup(
                conn, plan, plan.effective_session)
            observation_target_actions = _target_action_lookup(
                conn, plan, clock().date())
            commands = journal.load_commands(conn, binding.identity)
            active_security_ids = _preopen_active_security_ids(
                plan=plan, commands=commands, actions=actions)
            if active_security_ids and not dual_mode:
                official_open = _official_preopen_cutoff(plan)
                authority, actions, target_actions = _preopen_views_or_none(
                    conn, plan=plan,
                    active_security_ids=active_security_ids,
                    required_cutoff_at=official_open,
                    evaluated_at=clock(), actions=actions,
                    target_actions=target_actions)
                if authority is None:
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open share-unit authority is absent for the "
                        "nonempty recovery book; Sentinel will not interpret "
                        "plan, command, or broker-position share units across "
                        "the effective-session open")
                observation_target_actions = (
                    preopen_authority.overlay_actions(
                        observation_target_actions, authority))
        result = await reconciliation.reconcile(
            broker=broker, conn=conn, binding=None,
            deployment=binding.identity, actions=actions)

        if plan is not None:
            current_commands = journal.load_commands(conn, binding.identity)
            current_security_ids = _preopen_active_security_ids(
                plan=plan, commands=current_commands, actions=actions)
            if (not dual_mode and authority is None
                    and current_security_ids):
                raise PreOpenShareUnitAuthorityUnavailable(
                    "pre-open share-unit authority is absent after recovery "
                    "adopted a nonempty share-unit identity; Sentinel will "
                    "not treat that command or broker position as current "
                    "plan economics")
            if authority is not None:
                _revalidate_preopen_authority_or_refuse(
                    authority=authority, plan=plan,
                    commands=current_commands, actions=actions,
                    required_cutoff_at=_official_preopen_cutoff(plan),
                    evaluated_at=clock())
                if state is None:
                    raise PaperActivationRefused(
                        "current-generation recovery cannot revalidate its "
                        "target projection without canonical strategy state")
                target_projection = _target_projection_or_refuse(
                    conn, state=state, plan=plan, binding=binding,
                    broker=broker, through=plan.effective_session,
                    actions=actions, target_actions=target_actions,
                    require_existing=True)

        if dual_mode:
            _dual_mutation_observation_or_refuse(result)

        if (plan is not None
                and result.runtime_state is RuntimeState.RUNNING
                and result.clean
                and result.observation is not None
                and result.observation.is_complete
                and result.observation_id is not None
                and target_projection is not None
                and _account_evidence_is_quiescent(
                    conn, deployment=binding.identity,
                    observation=result.observation)):
            (confirmed_result, account, activity_state,
             evidence_started_at, evidence_at) = (
                await _settled_account_evidence_bracket(
                    conn=conn, broker=broker, binding=binding,
                    expected_account=grant.broker_account_id,
                    deployment=binding.identity,
                    initial_result=result, actions=actions,
                    dual_mode=dual_mode, clock=clock))
            _cash_authority_or_refuse(
                conn, plan=plan, deployment=binding.identity,
                account=account,
                observation=confirmed_result.observation,
                activity_state=activity_state,
                # Recovery submits nothing. A recognized post-plan
                # dividend/interest/fee is legitimate realized economics;
                # it may be certified after the book is clean even though
                # it would refuse a stale plan's new BUY authorization.
                permit_new_activity=True,
                endpoint_lag_observed_at=evidence_at)
            trial.record_account_evidence(
                conn, session=plan.effective_session,
                observation_id=confirmed_result.observation_id,
                observation_started_at=evidence_started_at,
                observed_at=evidence_at, snapshot=account,
                deployment=binding.identity,
                reconciliation=confirmed_result,
                activity_state=activity_state,
                plan=plan,
                target_projection=target_projection,
                observation_post_projection_actions=(
                    _post_projection_action_multipliers(
                        target_projection, observation_target_actions)))
        return result
