"""Final paper execution gate and canonical executor orchestration."""

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

from sentinel.core.production import (
    CONCORDANCE_WITNESS_PROSPECTIVE,
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution import commands as execution_commands

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
    ExecutionResult,
)

from .inspection import (
    _require_certified_paper_broker,
    _account_evidence_is_quiescent,
    _account_or_refuse,
)

from .validation import (
    _readiness_or_refuse,
    _execution_window_or_refuse,
    _assert_deterministic_plan_id,
    _validate_automation_grant,
    _guard_broker,
    _state_and_plan_or_refuse,
    _assert_plan_authorities,
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
    _informational_active_symbols,
    _plan_deltas,
    _provably_clean_empty_noop,
    _preopen_views_or_none,
    _revalidate_preopen_authority_or_refuse,
    _official_preopen_cutoff,
    _target_projection_or_refuse,
    _instrument_map,
)

from .reconciliation_evidence import (
    _clean_or_refuse,
    _dual_mutation_observation_or_refuse,
    _settled_account_evidence_bracket,
)

from .preparation import _default_paper_strategy

def _execution_observation_time(value: date | datetime | None) -> datetime:
    """Resolve the real clock, while preserving the date-only test seam.

    Production never supplies ``value`` and therefore always uses the actual ET
    instant. Existing deterministic tests pass a date; resolve that date to its
    certified XNYS open rather than treating midnight as executable. A datetime
    is the exact-time seam used by open/close and half-day falsifiers.
    """
    tz = ZoneInfo(calendar.EXCHANGE_TZ)
    if value is None:
        return datetime.now(tz)
    if isinstance(value, datetime):
        return (value.replace(tzinfo=tz) if value.tzinfo is None
                else value.astimezone(tz))
    opened, _closed = calendar.session_window(value)
    return opened

async def _execute_current_paper_plan(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: ManualExecutionGrant | AutomationExecutionGrant,
        today: date | datetime | None = None,
        automation_config_sha256: str | None = None,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None
        ) -> ExecutionResult:
    """One durable-plan gateway shared by manual and automation grants."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    if (isinstance(grant, AutomationExecutionGrant)
            and grant.operation_scope != "EXECUTE"):
        raise PaperActivationRefused(
            "automation execution requires an EXECUTE-scoped grant")
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER execution requires both reviewed shadow identity and "
            "starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    if dual_mode and not isinstance(grant, AutomationExecutionGrant):
        raise PaperActivationRefused(
            "informational dual transport is automation-only")
    real_clock = today is None
    now_et = _execution_observation_time(today)
    today = now_et.date()
    schema.require_runtime_schema(conn)

    with journal.writer_lock(conn):
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        rollout = load_rollout_state(conn)
        _controller_config, strategy_identity = _default_paper_strategy()
        with publication.pinned(conn, commit=False) as pinned:
            _readiness_or_refuse(conn, now_et=now_et)
            frontier = feed_store.latest_visible_session(conn)
            dual_result = None
            if dual_mode:
                plan = journal.latest_plan(conn)
                if plan is None:
                    raise PaperActivationRefused(
                        "there is no durable current dual PAPER plan")
                _assert_deterministic_plan_id(plan)
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
                state = SessionState.from_dict(
                    dual_result.state.to_dict())
                _cursor = plan.decision_session
            else:
                state, plan, _cursor = _state_and_plan_or_refuse(conn)
            if isinstance(grant, ManualExecutionGrant):
                if grant.confirm_paper_account != binding.broker_account_id:
                    raise PaperActivationRefused(
                        "paper-account confirmation mismatch")
                if grant.confirm_plan_id != plan.plan_id:
                    raise PaperActivationRefused("plan-id confirmation mismatch")
                if grant.confirm_effective_session != plan.effective_session:
                    raise PaperActivationRefused(
                        "effective-session confirmation mismatch")
                confirmed_account = grant.confirm_paper_account
            else:
                _control, cycle = _validate_automation_grant(conn, grant)
                if (cycle.plan_id != plan.plan_id
                        or cycle.plan_fingerprint != plan.fingerprint()):
                    raise PaperActivationRefused(
                        "automation cycle does not name the current plan")
                confirmed_account = grant.broker_account_id
            _assert_plan_authorities(
                conn, state=state, plan=plan, binding=binding, pinned=pinned,
                frontier=str(frontier), today=today,
                runtime_identity=strategy_identity, rollout=rollout)
            dual_sizing_proof = None
            if dual_mode:
                try:
                    dual_sizing_proof = dual_plan_authority.rederive_plan(
                        conn, plan=plan, binding=binding,
                        rollout_state=rollout,
                        expected_shadow_result=dual_result)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual sizing authority refused execution: {exc}") from exc
                try:
                    informational_paper_mirror.require_transport_permitted(
                        conn, current_frontier=str(frontier),
                        current_publication_version=pinned.version)
                except informational_paper_mirror.InformationalPaperMirrorPending as exc:
                    raise PaperRetryableRefused(
                        f"informational PAPER transport is pending: {exc}") from exc
                except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
                    raise PaperActivationRefused(
                        f"informational PAPER transport is blocked: {exc}") from exc
            authority_kwargs = dict(
                runtime_identity=system_identity.rehearsal_identity(),
                strategy_identity=strategy_identity,
                required_mode=rollout.mode,
                paper_base_url=base_url,
                current_publication_version=pinned.version,
                automation_config_sha256=automation_config_sha256)
            if isinstance(grant, AutomationExecutionGrant):
                automation_certificate = require_current_authority(
                    conn, required_operation="AUTOMATION", **authority_kwargs)
            certificate = require_current_authority(
                conn, required_operation="EXECUTE_READ", **authority_kwargs)
            if (isinstance(grant, AutomationExecutionGrant)
                    and (automation_certificate.certificate_sha256
                         != certificate.certificate_sha256
                         or grant.certificate_sha256
                         != certificate.certificate_sha256)):
                raise PaperActivationRefused(
                    "automation grant and signed execution authority differ")
            if (rollout.mode is RolloutMode.CONTROLLER
                    and rollout.certificate_sha256
                    != certificate.certificate_sha256):
                raise PaperActivationRefused(
                    "controller rollout was authorized by a different system "
                    "certificate")
            maximum_exposure = getattr(
                certificate, "maximum_exposure", Decimal(1))
            if plan.target_exposure > maximum_exposure:
                raise PaperActivationRefused(
                    f"current plan exposure {plan.target_exposure} exceeds "
                    "signed maximum exposure "
                    f"{maximum_exposure}")
            # Strict activation executes only during the named exchange
            # session. This is before the first broker read and consults the
            # actual XNYS schedule, so a 13:00 half-day close is a hard stop.
            _execution_window_or_refuse(plan.effective_session, now_et)

            if real_clock:
                clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
            else:
                clock = lambda: now_et
            broker = _guard_broker(
                conn=conn, broker=broker, grant=grant, base_url=base_url,
                now_provider=clock,
                strategy_provider=lambda: _default_paper_strategy()[1],
                automation_config_sha256=automation_config_sha256,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)

            account = await broker.account_snapshot()
            _account_or_refuse(account, binding, confirmed_account)
            activity_state = await _broker_cash_state_or_refuse(
                conn, broker=broker, binding=binding, through=clock())
            try:
                actions = _action_lookup(conn, state, today)
                target_actions = _target_action_lookup(conn, plan, today)
            except ValueError as exc:
                raise PaperActivationRefused(
                    f"corporate-action authority is ambiguous or invalid: {exc}") from exc
            commands = journal.load_commands(conn, binding.identity)
            active_security_ids = _preopen_active_security_ids(
                plan=plan, commands=commands, actions=actions)
            official_open = _official_preopen_cutoff(plan)
            authority, actions, target_actions = _preopen_views_or_none(
                conn, plan=plan,
                active_security_ids=active_security_ids,
                required_cutoff_at=official_open,
                evaluated_at=clock(), actions=actions,
                target_actions=target_actions)
            target_projection = None
            if authority is not None:
                # Refuse unsupported/non-scalar corporate actions before the
                # broker book can be consulted.  Reconciliation may still
                # adopt a previously unknown command identity, so the exact
                # projection is re-derived and matched below after that read.
                target_projection = _target_projection_or_refuse(
                    conn, state=state, plan=plan, binding=binding,
                    broker=broker, through=today, actions=actions,
                    target_actions=target_actions,
                    persist_projection=False)
            preflight = await reconciliation.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=binding.identity, actions=actions)
            observation = (
                _dual_mutation_observation_or_refuse(preflight)
                if dual_mode else
                _clean_or_refuse(preflight, purpose="paper execution"))
            if _account_evidence_is_quiescent(
                    conn, deployment=binding.identity,
                    observation=observation):
                # The earlier account read established identity/availability,
                # but cannot be paired with a later reconciliation: a fill may
                # have landed between them. Re-read only after the observation
                # proves there is no working or durable in-flight command.
                account = await broker.account_snapshot()
                cash_evidence_at = clock()
                _account_or_refuse(account, binding, confirmed_account)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=cash_evidence_at)
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state,
                    endpoint_lag_observed_at=cash_evidence_at)
            current_commands = journal.load_commands(conn, binding.identity)
            _revalidate_preopen_authority_or_refuse(
                authority=authority, plan=plan, commands=current_commands,
                actions=actions, required_cutoff_at=official_open,
                evaluated_at=clock())
            minimum_increment = (
                broker.capabilities.minimum_quantity_increment)
            preopen_deltas = _plan_deltas(
                target_basket=plan.target_basket,
                observation=observation,
                minimum_quantity_increment=minimum_increment)
            if authority is None and dual_mode:
                # This is explicitly informational transport, not affirmative
                # pre-open unit authority. The exact close-unit basket remains
                # immutable and a post-close source-final check can only block
                # later mutations; it never rewrites these quantities.
                target_projection = None
                projected_deltas = preopen_deltas
                pending_ids = _preopen_active_security_ids(
                    plan=plan, commands=current_commands, actions=actions)
                pending_symbols = _informational_active_symbols(
                    active_security_ids=pending_ids,
                    commands=current_commands, observation=observation,
                    sizing_proof=dual_sizing_proof)
                informational_paper_mirror.record_pending(
                    conn, plan=plan, active_security_ids=pending_ids,
                    active_symbols=pending_symbols,
                    sizing_authority_sha256=(
                        dual_sizing_proof["authority_sha256"]),
                    shadow_record_sha256=(
                        dual_sizing_proof["shadow_record_sha256"]),
                    publication_version=pinned.version,
                    # Commit the PENDING stamp before the first possible
                    # broker call. A later outer rollback must not erase the
                    # fact that a crashed submit may have landed.
                    commit=True)
            elif authority is None:
                if not _provably_clean_empty_noop(
                        deltas=preopen_deltas, commands=current_commands,
                        observation=observation):
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open share-unit authority is absent and the "
                        "complete, clean broker book is not an empty no-op; "
                        "numerical equality of nonzero raw shares cannot prove "
                        "that no effective-session split occurred; "
                        "Sentinel will not project a target or create, cancel, "
                        "or submit a command")
                target_projection = None
                projected_deltas = preopen_deltas
            else:
                # Reconciliation can durably adopt a broker order that was not
                # present at the first projection boundary.  Re-run all
                # material-action checks over that expanded command set and
                # require the result to equal the immutable pre-read target.
                target_projection = _target_projection_or_refuse(
                    conn, state=state, plan=plan, binding=binding,
                    broker=broker, through=today, actions=actions,
                    target_actions=target_actions,
                    expected_projection=target_projection)
                projected_deltas = _plan_deltas(
                    target_basket=target_projection.target_basket,
                    observation=observation,
                    minimum_quantity_increment=minimum_increment)

            if all(delta.classification is execution_commands.DeltaClass.NONE
                   for delta in projected_deltas):
                session = executor.SessionResult(
                    runtime_state=RuntimeState.RUNNING,
                    reconciliation=preflight,
                    detail="complete clean empty no-op; no command transport")
            else:
                # The branch is unreachable without a validated authority:
                # dust is not a true no-op, even when no broker can fill it.
                if target_projection is None and not dual_mode:  # pragma: no cover
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open authority is required before command sizing")
                instruments = await _instrument_map(
                    conn, broker, state, plan, observation,
                    target_basket=(
                        plan.target_basket if target_projection is None
                        else target_projection.target_basket))

                async def authorize_increases(fresh_observation):
                    if not _account_evidence_is_quiescent(
                            conn, deployment=binding.identity,
                            observation=fresh_observation):
                        raise PaperRetryableRefused(
                            "account cash remains PENDING while an order or "
                            "durable command is in flight")
                    fresh_account = await broker.account_snapshot()
                    fresh_cash_at = clock()
                    _account_or_refuse(
                        fresh_account, binding, confirmed_account)
                    fresh_activity_state = await _broker_cash_state_or_refuse(
                        conn, broker=broker, binding=binding,
                        through=fresh_cash_at)
                    _cash_authority_or_refuse(
                        conn, plan=plan, deployment=binding.identity,
                        account=fresh_account,
                        observation=fresh_observation,
                        activity_state=fresh_activity_state,
                        endpoint_lag_observed_at=fresh_cash_at)

                async def authorize_dual_mutations(fresh_reconciliation):
                    _dual_mutation_observation_or_refuse(
                        fresh_reconciliation)

                session = await executor.execute_session(
                    broker=broker, conn=conn, deployment=binding.identity,
                    plan=plan, instruments=instruments, today=today,
                    actions=actions, target_projection=target_projection,
                    min_increment=minimum_increment,
                    increase_authority=authorize_increases,
                    mutation_authority=(
                        authorize_dual_mutations
                        if dual_mode else None))
            final_reconciliation = session.reconciliation
            if (final_reconciliation is not None
                    and final_reconciliation.runtime_state is RuntimeState.RUNNING
                    and final_reconciliation.clean
                    and final_reconciliation.observation is not None
                    and final_reconciliation.observation.is_complete
                    and final_reconciliation.observation_id is not None
                    and target_projection is not None
                    and _account_evidence_is_quiescent(
                        conn, deployment=binding.identity,
                        observation=final_reconciliation.observation)):
                (confirmed_reconciliation, evidence_account,
                 evidence_activity, evidence_started_at, evidence_at) = (
                    await _settled_account_evidence_bracket(
                        conn=conn, broker=broker, binding=binding,
                        expected_account=confirmed_account,
                        deployment=binding.identity,
                        initial_result=final_reconciliation,
                        actions=actions, dual_mode=dual_mode, clock=clock))
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=evidence_account,
                    observation=confirmed_reconciliation.observation,
                    activity_state=evidence_activity,
                    endpoint_lag_observed_at=evidence_at)
                trial.record_account_evidence(
                    conn, session=plan.effective_session,
                    observation_id=confirmed_reconciliation.observation_id,
                    observation_started_at=evidence_started_at,
                    observed_at=evidence_at, snapshot=evidence_account,
                    deployment=binding.identity,
                    reconciliation=confirmed_reconciliation,
                    activity_state=evidence_activity,
                    plan=plan,
                    target_projection=target_projection,
                    observation_post_projection_actions=(
                        _post_projection_action_multipliers(
                            target_projection, target_actions)))
            return ExecutionResult(plan=plan, preflight=preflight,
                                   session=session)

async def execute_paper_plan(*, conn, broker: ExecutionBroker, base_url: str,
                             confirm_account: str, confirm_plan_id: str,
                             confirm_effective_session: date | str,
                             confirm_submit: bool,
                             today: date | datetime | None = None
                             ) -> ExecutionResult:
    """Execute the current plan only with the exact manual confirmations."""
    if not confirm_submit:
        raise PaperActivationRefused("--confirm-submit-paper-orders is required")
    effective = (confirm_effective_session
                 if isinstance(confirm_effective_session, date)
                 else date.fromisoformat(str(confirm_effective_session)))
    grant = ManualExecutionGrant(
        confirm_paper_account=confirm_account,
        confirm_plan_id=confirm_plan_id,
        confirm_effective_session=effective,
        confirm_submit_paper_orders=True)
    return await _execute_current_paper_plan(
        conn=conn, broker=broker, base_url=base_url,
        grant=grant, today=today)

async def execute_automated_paper_plan(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: AutomationExecutionGrant,
        automation_config_sha256: str,
        today: date | datetime | None = None,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None
        ) -> ExecutionResult:
    """Execute the same current plan through a fenced automation grant."""
    return await _execute_current_paper_plan(
        conn=conn, broker=broker, base_url=base_url, grant=grant,
        today=today, automation_config_sha256=automation_config_sha256,
        dual_shadow_observation_id=dual_shadow_observation_id,
        dual_shadow_starting_cash=dual_shadow_starting_cash)
