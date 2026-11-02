"""URL-selected gateway over the canonical plan, journal and execution engine.

PAPER retains its public implementation. LIVE reads the authenticated shadow
and requires a separately enrolled account admission at every broker boundary.
No operation here creates or advances strategy state.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sentinel import binding, dual_plan_authority, identity, paper, schema
from sentinel.authority import load_rollout_state
from sentinel.authority.live import require_live_adapter_admission
from sentinel.authority.live_runtime import load_live_adapter_admission
from sentinel.config import trading_endpoint
from sentinel.core.decision import build_execution_plan
from sentinel.execution import executor, feed_inputs, held_targets, journal
from sentinel.execution import reconcile
from sentinel.execution.authority_gate import build_fresh_execution_guard, build_fresh_execution_check
from sentinel.execution.certification import require_certified_adapter
from sentinel.execution.guarded import (
    AutomationExecutionGrant, BrokerOperation, GuardedExecutionBroker,
    LiveExecutionGrant,
)
from sentinel.execution.live_context import (
    load_live_order_context, load_owned_cancel_command,
)
from sentinel.execution.live_transport import LiveExecutionPolicy
from sentinel.execution.protected_limits import ProtectedLimitPolicy
from sentinel.feed import calendar
from sentinel.paper.inspection import _account_or_refuse
from sentinel.paper.model import ExecutionResult, PreparationResult
from sentinel.paper.preparation import _load_marks_and_tickers
from sentinel.paper.reconciliation_evidence import _transport_observation_or_refuse
from sentinel.paper.targets import (
    _action_lookup, _instrument_map, _official_preopen_cutoff,
    _preopen_active_security_ids, _preopen_views_or_none,
    _target_action_lookup, _target_projection_or_refuse,
)
from sentinel.paper.validation import (
    _assert_plan_authorities, _fresh_connection_factory,
    _readiness_or_refuse, _validate_automation_grant,
)
from sentinel.strategy import production_strategy
from sentinel.trading_environment import TradingEnvironment


class TradingGatewayRefused(paper.PaperActivationRefused):
    """The selected account has no current operational authority."""


class TradingExecutionResult(ExecutionResult):
    def to_dict(self) -> dict:
        result = super().to_dict()
        result.pop("paper_submission_authorized", None)
        return {"environment": TradingEnvironment.LIVE.value,
                "submission_authorized": not self.needs_attention, **result}


def _clock():
    return datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))


def _strategy():
    return production_strategy()[1]


def _bound(conn, expected_account=None):
    bound = binding.require(conn)
    if (not bound.is_owned or bound.broker != "alpaca-live"
            or expected_account is not None and bound.broker_account_id != expected_account):
        raise TradingGatewayRefused("LIVE requires its exact prebound alpaca-live account")
    return bound


def _shadow_config(observation_id, starting_cash):
    if observation_id is None or starting_cash is None:
        from sentinel.automation_runtime import shadow_config_from_env
        _worker_enabled, configured_id, configured_cash = shadow_config_from_env()
        observation_id = configured_id if observation_id is None else observation_id
        starting_cash = configured_cash if starting_cash is None else starting_cash
    return str(observation_id), starting_cash


def _shadow(conn, *, observation_id, starting_cash, session=None):
    from sentinel import shadow_runtime, shadow_segments
    if shadow_segments.active_segment(conn, observation_id).index != 0:
        raise TradingGatewayRefused("LIVE cannot inherit a PAPER post-gap shadow-origin approval")
    result = shadow_runtime.verified_shadow_status(
        conn, observation_id=observation_id, starting_cash=starting_cash)
    if (result is None or result.verification != "VERIFIED"
            or result.shadow_verdict != "SHADOW_GO"
            or not result.runtime_authority_sha256
            or session is not None and result.session != str(session)):
        raise TradingGatewayRefused("LIVE requires the exact current verified shadow session")
    return result


def _schema(conn):
    schema.require_runtime_schema(conn)
    journal.require_observation_integrity(conn)


def _admission(conn, base_url, automation_config_sha256):
    return load_live_adapter_admission(
        conn, base_url=base_url, runtime_identity=identity.rehearsal_identity(),
        strategy_identity=_strategy(), automation_config_sha256=automation_config_sha256)


def _manual_grant(conn, *, base_url, scope, expected_account=None,
                  plan=None, confirm_submit=False, automation_config_sha256=None):
    _bound(conn, expected_account)
    admission = _admission(conn, base_url, automation_config_sha256)
    subject = require_live_adapter_admission(admission, base_url=base_url).subject
    return LiveExecutionGrant(
        subject=subject, operation_scope=scope,
        plan_id=plan.plan_id if plan is not None else None,
        effective_session=plan.effective_session if plan is not None else None,
        confirm_submit_live_orders=confirm_submit)


def _validate_grant(conn, grant, operation, result, *, base_url,
                    observation_id, starting_cash, now):
    bound = _bound(conn)
    current = feed_inputs.require_current(conn)
    feed_inputs.coherent(conn)
    rollout = load_rollout_state(conn)
    if now.tzinfo is None:
        raise TradingGatewayRefused("LIVE authority clock must be timezone aware")
    scope = grant.operation_scope
    cycle = None
    if isinstance(grant, AutomationExecutionGrant):
        control, cycle = _validate_automation_grant(conn, grant)
        if (control.binding.broker != "alpaca-live" or cycle.broker != "alpaca-live"
                or cycle.deployment_id != bound.deployment_id
                or grant.broker_account_id != bound.broker_account_id
                or grant.takeover_epoch != bound.takeover_epoch):
            raise TradingGatewayRefused("LIVE automation binding or cycle is stale")
    elif isinstance(grant, LiveExecutionGrant):
        subject = grant.subject
        if (subject.deployment_id, subject.account_id, subject.takeover_epoch,
                subject.base_url) != (bound.deployment_id, bound.broker_account_id,
                                     bound.takeover_epoch, base_url):
            raise TradingGatewayRefused("LIVE manual subject does not match current binding")
        if operation in (BrokerOperation.SUBMIT, BrokerOperation.CANCEL):
            from sentinel.automation import store
            if store.load_control(conn).kill_switch_engaged:
                raise TradingGatewayRefused("LIVE emergency kill switch is engaged")
    else:
        raise TradingGatewayRefused("LIVE requires its typed manual or automation grant")
    if scope == "RECOVER":
        if operation in (BrokerOperation.SUBMIT, BrokerOperation.CANCEL):
            raise TradingGatewayRefused("LIVE recovery is read-only")
        return
    shadow = _shadow(conn, observation_id=observation_id, starting_cash=starting_cash)
    frontier = str(feed_inputs.frontier(conn))
    if shadow.session != frontier or shadow.state.data_version != current.version:
        raise TradingGatewayRefused("LIVE shadow is not current with the pinned publication")
    if scope == "PREPARE":
        if (frontier != calendar.latest_closed_session(now)
                or cycle is not None and str(cycle.decision_session) != frontier):
            raise TradingGatewayRefused("LIVE preparation does not name the latest closed session")
        return
    plan = journal.latest_plan(conn)
    if plan is None:
        raise TradingGatewayRefused("LIVE execution has no current durable plan")
    if isinstance(grant, LiveExecutionGrant):
        if (grant.plan_id != plan.plan_id or grant.effective_session != plan.effective_session
                or grant.confirm_submit_live_orders is not True):
            raise TradingGatewayRefused("LIVE execution confirmation does not name the current plan")
    elif (cycle.plan_id != plan.plan_id or cycle.plan_fingerprint != plan.fingerprint()):
        raise TradingGatewayRefused("LIVE cycle does not name the current immutable plan")
    _readiness_or_refuse(conn, now_et=now)
    opened, closed = calendar.session_window(plan.effective_session)
    if not opened <= now < closed:
        raise paper.PaperRetryableRefused("LIVE execution is outside its actual XNYS session")
    sizing = dual_plan_authority.rederive_plan(
        conn, plan=plan, binding=bound, rollout_state=rollout,
        expected_shadow_result=shadow)
    _assert_plan_authorities(
        conn, state=shadow.state, plan=plan, binding=bound,
        pinned=current, frontier=frontier, today=now.date(),
        runtime_identity=_strategy(), rollout=rollout,
        verified_state_sha256=sizing["state_sha256"], retained_shadow=True)


def _guard(conn, broker, *, base_url, grant, observation_id, starting_cash,
           automation_config_sha256=None, plan=None, actions=None, clock=_clock,
           issuer_admission_check=None):
    certified = require_certified_adapter(broker, expected="alpaca-live")
    if certified.wrapper_kind is not None:
        raise TradingGatewayRefused("LIVE gateway requires the certified raw adapter exactly once")
    bound = _bound(conn)
    def validate(fresh, current_grant, operation, result):
        _validate_grant(fresh, current_grant, operation, result, base_url=base_url,
                        observation_id=observation_id, starting_cash=starting_cash, now=clock())
    guard = build_fresh_execution_guard(
        connection_factory=_fresh_connection_factory(conn), paper_base_url=base_url,
        runtime_identity=identity.rehearsal_identity, strategy_identity=_strategy,
        validate_grant=validate, automation_config_sha256=automation_config_sha256)
    synchronous_check = build_fresh_execution_check(
        connection_factory=_fresh_connection_factory(conn), paper_base_url=base_url,
        runtime_identity=identity.rehearsal_identity, strategy_identity=_strategy,
        validate_grant=validate, automation_config_sha256=automation_config_sha256)
    def final_check(operation):
        if operation not in {"SUBMIT", "CANCEL"}:
            raise TradingGatewayRefused("unknown LIVE final transport operation")
        synchronous_check(grant, BrokerOperation.SUBMIT if operation == "SUBMIT" else BrokerOperation.CANCEL, None)
    async def submit_context(client_key):
        if plan is None:
            raise TradingGatewayRefused("LIVE read-only gateway has no execution plan")
        return await load_live_order_context(
            conn, broker=wrapped, plan=plan, binding=bound,
            client_key=client_key, actions=actions() if callable(actions) else actions, now=clock)
    async def cancel_context(broker_order_id):
        return load_owned_cancel_command(conn, binding=bound, broker_order_id=broker_order_id)
    policy = LiveExecutionPolicy(
        admission=lambda: _admission(conn, base_url, automation_config_sha256),
        load_submit=submit_context, load_cancel=cancel_context, now=clock,
        final_check=final_check)
    wrapped = GuardedExecutionBroker(inner=broker, grant=grant, guard=guard, live_policy=policy,
        issuer_admission_check=issuer_admission_check)
    require_certified_adapter(wrapped, expected="alpaca-live")
    return wrapped


async def prepare_trading_plan(*, conn, broker, base_url, through,
                               expected_account=None, automation_grant=None,
                               automation_config_sha256=None,
                               dual_shadow_observation_id=None,
                               dual_shadow_starting_cash=None, **paper_kwargs):
    endpoint = trading_endpoint(base_url)
    if endpoint.environment is TradingEnvironment.PAPER:
        return await paper.prepare_paper_plan(
            conn=conn, broker=broker, base_url=endpoint.base_url, through=through,
            expected_account=expected_account, automation_grant=automation_grant,
            automation_config_sha256=automation_config_sha256,
            dual_shadow_observation_id=dual_shadow_observation_id,
            dual_shadow_starting_cash=dual_shadow_starting_cash, **paper_kwargs)
    if paper_kwargs:
        raise TradingGatewayRefused("PAPER genesis or warmup options cannot authorize LIVE")
    _schema(conn)
    observation_id, starting_cash = _shadow_config(dual_shadow_observation_id, dual_shadow_starting_cash)
    through = date.fromisoformat(str(through))
    with journal.writer_lock(conn):
        with feed_inputs.pinned(conn, commit=False) as pinned:
            bound = _bound(conn, expected_account)
            _readiness_or_refuse(conn, now_et=_clock())
            shadow = _shadow(conn, observation_id=observation_id, starting_cash=starting_cash, session=through)
            if (str(feed_inputs.frontier(conn)) != str(through)
                    or shadow.state.data_version != pinned.version):
                raise TradingGatewayRefused("LIVE preparation shadow/publication frontier mismatch")
            rollout = load_rollout_state(conn)
            grant = automation_grant or _manual_grant(
                conn, base_url=endpoint.base_url, scope="PREPARE", expected_account=expected_account)
            guarded = _guard(conn, broker, base_url=endpoint.base_url, grant=grant,
                observation_id=observation_id, starting_cash=starting_cash,
                automation_config_sha256=automation_config_sha256)
            account = await guarded.account_snapshot()
            _account_or_refuse(account, bound, expected_account)
            actions = _action_lookup(conn, shadow.state, through)
            rec = await reconcile.reconcile(broker=guarded, conn=conn,
                binding=None, deployment=bound.identity, actions=actions)
            observation = _transport_observation_or_refuse(rec)
            previous = journal.latest_plan(conn)
            if previous is not None and previous.decision_session >= through:
                if previous.decision_session != through:
                    raise TradingGatewayRefused("LIVE cannot replace a newer durable plan")
                dual_plan_authority.rederive_plan(conn, plan=previous, binding=bound,
                    rollout_state=rollout, expected_shadow_result=shadow)
                plan, superseded = previous, 0
            else:
                marks, tickers = _load_marks_and_tickers(conn, shadow.state, str(through))
                share_basis = held_targets.build_basis(conn, previous=previous,
                    state=shadow.state, binding=bound, rollout=rollout)
                plan = build_execution_plan(state=shadow.state, binding=bound,
                    publication=pinned, account_snapshot=account, observation=observation,
                    marks=marks, tickers=tickers, decision_session=through,
                    effective_session=date.fromisoformat(calendar.next_session(through)),
                    rollout_state=rollout,
                    retained_targets={sid: Decimal(qty) for sid, qty in share_basis["targets"].items()}).plan
                authority = dual_plan_authority.build_authority(plan=plan,
                    shadow_result=shadow, publication=pinned, account_snapshot=account,
                    observation=observation, marks=marks, tickers=tickers,
                    held_share_targets=share_basis)
                await _instrument_map(conn, guarded, shadow.state, plan, observation, preparation=True)
                plan = journal.adopt_current_plan(conn, plan, commit=False)
                dual_plan_authority.record_authority(conn, authority, commit=False)
                dual_plan_authority.rederive_plan(conn, plan=plan, binding=bound,
                    rollout_state=rollout, expected_shadow_result=shadow)
                superseded = int(previous is not None)
                conn.commit()
            return PreparationResult(plan=plan, sessions_replayed=0, warmup_sessions=0,
                state_fingerprint=shadow.state.state_hash, publication_version=pinned.version,
                frontier=str(through), reconciliation=rec, superseded_plans=superseded)


def current_trading_plan(conn, *, base_url, dual_shadow_observation_id=None,
                         dual_shadow_starting_cash=None):
    endpoint = trading_endpoint(base_url)
    if endpoint.environment is TradingEnvironment.PAPER:
        return paper.current_paper_plan(conn, base_url=endpoint.base_url,
            dual_shadow_observation_id=dual_shadow_observation_id,
            dual_shadow_starting_cash=dual_shadow_starting_cash)
    _schema(conn)
    observation_id, starting_cash = _shadow_config(dual_shadow_observation_id, dual_shadow_starting_cash)
    bound = _bound(conn)
    plan = journal.latest_plan(conn)
    if plan is None:
        raise TradingGatewayRefused("LIVE has no durable current plan")
    with feed_inputs.pinned(conn, commit=False) as pinned:
        shadow = _shadow(conn, observation_id=observation_id, starting_cash=starting_cash, session=plan.decision_session)
        rollout = load_rollout_state(conn)
        proof = dual_plan_authority.rederive_plan(conn, plan=plan, binding=bound,
            rollout_state=rollout, expected_shadow_result=shadow)
        _assert_plan_authorities(conn, state=shadow.state, plan=plan, binding=bound,
            pinned=pinned, frontier=str(feed_inputs.frontier(conn)), today=_clock().date(),
            runtime_identity=_strategy(), rollout=rollout, require_effective_today=False,
            verified_state_sha256=proof["state_sha256"], retained_shadow=True)
        _admission(conn, endpoint.base_url, None)
    return {"environment": endpoint.environment.value, "broker_contacted": False,
            "broker_mutations_permitted": False, "execution_authorized": False,
            "database_authorities_match": True, "binding": bound.to_dict(),
            "plan": plan.to_dict(), "shadow": shadow.to_dict()}


async def recover_trading_account(*, conn, broker, base_url, expected_account=None,
                                  grant=None, automation_config_sha256=None,
                                  dual_shadow_observation_id=None, dual_shadow_starting_cash=None):
    endpoint = trading_endpoint(base_url)
    if endpoint.environment is TradingEnvironment.PAPER:
        if not isinstance(grant, AutomationExecutionGrant):
            raise TradingGatewayRefused("manual PAPER recovery uses the existing PAPER administrative workflow")
        return await paper.recover_automated_paper_cycle(conn=conn, broker=broker,
            base_url=endpoint.base_url, grant=grant, automation_config_sha256=automation_config_sha256,
            dual_shadow_observation_id=dual_shadow_observation_id,
            dual_shadow_starting_cash=dual_shadow_starting_cash)
    _schema(conn)
    observation_id, starting_cash = _shadow_config(dual_shadow_observation_id, dual_shadow_starting_cash)
    with journal.writer_lock(conn, recovery_only=True):
        with feed_inputs.pinned(conn, commit=False) as pinned:
            bound = _bound(conn, expected_account)
            grant = grant or _manual_grant(conn, base_url=endpoint.base_url,
                scope="RECOVER", expected_account=expected_account)
            if grant.operation_scope != "RECOVER":
                raise TradingGatewayRefused("recovery requires a read-only RECOVER grant")
            guarded = _guard(conn, broker, base_url=endpoint.base_url, grant=grant,
                observation_id=observation_id, starting_cash=starting_cash,
                automation_config_sha256=automation_config_sha256)
            account = await guarded.account_snapshot()
            if not bound.identity.matches_account(account.identity):
                raise TradingGatewayRefused("recovery account identity differs from binding")
            actions = _action_lookup(conn, None, _clock().date())
            return await reconcile.reconcile(broker=guarded, conn=conn,
                binding=None, deployment=bound.identity, actions=actions)


async def execute_trading_plan(*, conn, broker, base_url, confirm_account,
                               confirm_plan_id, confirm_effective_session,
                               confirm_submit, grant=None, automation_config_sha256=None,
                               dual_shadow_observation_id=None, dual_shadow_starting_cash=None):
    endpoint = trading_endpoint(base_url)
    if endpoint.environment is TradingEnvironment.PAPER:
        if grant is not None:
            return await paper.execute_automated_paper_plan(conn=conn, broker=broker,
                base_url=endpoint.base_url, grant=grant, automation_config_sha256=automation_config_sha256,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)
        return await paper.execute_paper_plan(conn=conn, broker=broker, base_url=endpoint.base_url,
            confirm_account=confirm_account, confirm_plan_id=confirm_plan_id,
            confirm_effective_session=confirm_effective_session, confirm_submit=confirm_submit)
    _schema(conn)
    observation_id, starting_cash = _shadow_config(dual_shadow_observation_id, dual_shadow_starting_cash)
    if ProtectedLimitPolicy.from_env() is None:
        raise TradingGatewayRefused("LIVE requires the selected protected-limit policy")
    with journal.writer_lock(conn):
        with feed_inputs.pinned(conn, commit=False) as pinned:
            bound = _bound(conn, confirm_account)
            plan = journal.latest_plan(conn)
            if (plan is None or plan.plan_id != confirm_plan_id
                    or str(plan.effective_session) != str(confirm_effective_session)
                    or confirm_submit is not True):
                raise TradingGatewayRefused("execution requires exact current account/plan/session confirmation")
            shadow = _shadow(conn, observation_id=observation_id, starting_cash=starting_cash, session=plan.decision_session)
            today = _clock().date()
            actions = _action_lookup(conn, shadow.state, today)
            target_actions = _target_action_lookup(conn, plan, today)
            action_context = {"value": actions}
            grant = grant or _manual_grant(conn, base_url=endpoint.base_url,
                scope="EXECUTE", expected_account=confirm_account, plan=plan, confirm_submit=True)
            if grant.operation_scope != "EXECUTE":
                raise TradingGatewayRefused("execution requires an EXECUTE grant")
            from sentinel.execution.issuer_runtime import PaperIssuerAdmission
            issuer = PaperIssuerAdmission(conn=conn, binding=bound.identity, clock=_clock)
            guarded = _guard(conn, broker, base_url=endpoint.base_url, grant=grant,
                observation_id=observation_id, starting_cash=starting_cash,
                automation_config_sha256=automation_config_sha256, plan=plan,
                actions=lambda: action_context["value"], issuer_admission_check=issuer.final_check)
            account = await guarded.account_snapshot()
            _account_or_refuse(account, bound, confirm_account)
            active_ids = _preopen_active_security_ids(plan=plan,
                commands=journal.load_commands(conn, bound.identity), actions=actions)
            _authority, actions, target_actions = _preopen_views_or_none(conn,
                plan=plan, active_security_ids=active_ids,
                required_cutoff_at=_official_preopen_cutoff(plan), evaluated_at=_clock(),
                actions=actions, target_actions=target_actions)
            action_context["value"] = actions
            projected = _target_projection_or_refuse(conn, state=shadow.state,
                plan=plan, binding=bound, broker=guarded, through=today,
                actions=actions, target_actions=target_actions, persist_projection=False,
                allow_restrictions=True)
            preflight = await reconcile.reconcile(broker=guarded, conn=conn,
                binding=None, deployment=bound.identity, actions=actions)
            observation = _transport_observation_or_refuse(preflight)
            projected = _target_projection_or_refuse(conn, state=shadow.state,
                plan=plan, binding=bound, broker=guarded, through=today,
                actions=actions, target_actions=target_actions, expected_projection=projected,
                allow_restrictions=True)
            instruments = await _instrument_map(conn, guarded, shadow.state, plan,
                observation, target_basket=projected.target_basket,
                restricted_security_ids=preflight.restricted_securities)
            issuer.prepare_for_transport(publication=pinned, state=shadow.state,
                plan=plan, projection=projected, reconciliation=preflight)
            async def mutation_authority(fresh_reconciliation):
                _transport_observation_or_refuse(fresh_reconciliation)
            session = await executor.execute_session(broker=guarded, conn=conn,
                deployment=bound.identity, plan=plan, instruments=instruments,
                today=today, actions=actions, target_projection=projected,
                min_increment=guarded.capabilities.minimum_quantity_increment,
                mutation_authority=mutation_authority,
                buy_admission=issuer.check_buy,
                security_restrictions=preflight.restricted_securities)
            return TradingExecutionResult(plan=plan, preflight=preflight, session=session)


async def execute_automated_trading_plan(*, conn, broker, base_url, grant,
                                        automation_config_sha256, **kwargs):
    plan = journal.latest_plan(conn)
    if plan is None:
        raise TradingGatewayRefused("automated execution has no current durable plan")
    return await execute_trading_plan(conn=conn, broker=broker, base_url=base_url,
        grant=grant, automation_config_sha256=automation_config_sha256,
        confirm_account=grant.broker_account_id, confirm_plan_id=plan.plan_id,
        confirm_effective_session=plan.effective_session, confirm_submit=True, **kwargs)


async def enroll_live_issuer_policy(*, conn, broker, base_url,
                                    confirm_account, confirm_deployment, confirm_real_money):
    endpoint = trading_endpoint(base_url)
    if endpoint.environment is not TradingEnvironment.LIVE or confirm_real_money is not True:
        raise TradingGatewayRefused("explicit LIVE issuer enrollment confirmation is required")
    from sentinel.automation import store
    from sentinel.execution import issuer_admission, issuer_runtime
    from sentinel.feed.issuer_reference import load_snapshot
    _schema(conn)
    observation_id, starting_cash = _shadow_config(None, None)
    with journal.writer_lock(conn):
        with feed_inputs.pinned(conn, commit=False) as pinned:
            bound = _bound(conn, confirm_account)
            if bound.deployment_id != confirm_deployment or not store.load_control(conn).kill_switch_engaged:
                raise TradingGatewayRefused("LIVE issuer enrollment requires exact deployment and engaged kill switch")
            shadow = _shadow(conn, observation_id=observation_id, starting_cash=starting_cash,
                session=feed_inputs.frontier(conn))
            grant = _manual_grant(conn, base_url=endpoint.base_url,
                scope="PREPARE", expected_account=confirm_account)
            guarded = _guard(conn, broker, base_url=endpoint.base_url, grant=grant,
                observation_id=observation_id, starting_cash=starting_cash)
            account = await guarded.account_snapshot()
            _account_or_refuse(account, bound, confirm_account)
            actions = _action_lookup(conn, shadow.state, _clock().date())
            rec = await reconcile.reconcile(broker=guarded, conn=conn,
                binding=None, deployment=bound.identity, actions=actions)
            _transport_observation_or_refuse(rec)
            result = issuer_admission.enroll(conn, binding=bound.identity,
                state=shadow.state, reconciliation=rec, snapshot=load_snapshot(),
                instruments=issuer_runtime.reference_instruments(conn, pinned), now=_clock())
            conn.commit()
            return {"environment": endpoint.environment.value, "broker_mutations_permitted": False,
                    "policy_sha256": result.policy_sha256, "enrollment_sha256": result.sha256}
