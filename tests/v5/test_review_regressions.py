"""Regressions for opening sizing, convergence, recovery and finalization."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from sentinel import automation_runtime, informational_paper_mirror, paper
from sentinel.core import catchup
from sentinel.core.production import SessionState
from sentinel.execution import journal, opening_sizing, preopen_authority
from sentinel.execution import target_reprojection as projections
from sentinel.execution.contract import BrokerCapabilities, BrokerInstrument, BrokerPosition
from sentinel.feed import calendar, publication, store as feed_store
from sentinel.paper import execution as paper_execution, recovery as paper_recovery, targets
from tests.v5.test_opening import case, base, prices
from tests.sentinel.test_production_decision import _observation
from tests.sentinel.test_automation_runtime import config, production, reconciliation
from tests.sentinel.test_preopen_paper_gate import _install_recovery_harness


@pytest.mark.parametrize('dual', [False, True])
def test_filled_open_sized_entry_converges(monkeypatch, dual):
    env, plan = case()
    projected = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan, price='50'))
    assert projected.target_basket == {'SEC-AAA': D(99)}
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: projected)
    runtime = production(config())
    runtime._dual_run_enabled = dual
    monkeypatch.setattr(runtime, '_require_dual_plan_shadow_match', lambda *a, **k: {
        'sizing_authority_sha256': 'sizing', 'shadow_record_sha256': 'shadow'})
    monkeypatch.setattr(publication, 'require_current', lambda *a: SimpleNamespace(version=7))
    monkeypatch.setattr(feed_store, 'latest_visible_session', lambda *a: plan.decision_session.isoformat())
    monkeypatch.setattr(informational_paper_mirror, 'require_transport_permitted', lambda *a, **k: None)
    monkeypatch.setattr(informational_paper_mirror, 'require_pending_for_plan', lambda *a, **k: None)
    observed = _observation(positions=(BrokerPosition(BrokerInstrument('SEC-AAA', 'AAA'), D(99)),))
    deltas = runtime._actionable_current_plan_deltas(
        object(), plan=plan, effective_session=plan.effective_session,
        observation=observed, minimum_quantity_increment=D(1))
    assert deltas == (), f'Filled opening target produced spurious deltas: {deltas}'


def test_finalization_preserves_split_authority_for_opening_entry():
    env, plan = case()
    projected = opening_sizing.resolve(env, plan,
        base(env, plan, multipliers={'SEC-AAA': D(2)}), prices(env, plan, price='50'))
    current_actions = targets._target_action_multipliers(plan, lambda sid: D(2))
    assert current_actions == dict(projected.action_multipliers)


@pytest.mark.parametrize('status', [429, 503])
def test_opening_asset_lookup_transient_failure_is_retryable(monkeypatch, status):
    env, plan = case()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    class Broker:
        capabilities = SimpleNamespace(require=lambda *a: None)
        async def resolve_instrument(self, **kwargs):
            request = httpx.Request('GET', 'https://paper-api.alpaca.markets/v2/assets/AAA')
            response = httpx.Response(status, request=request)
            response.raise_for_status()
    with pytest.raises(paper.PaperRetryableRefused):
        asyncio.run(paper_execution._opening_prices_or_retry(
            object(), state=env, plan=plan, broker=Broker()))


def test_restart_before_projection_can_reconcile_a_proven_unsent_plan(monkeypatch):
    env, plan = case()
    opened, _ = calendar.session_window(plan.effective_session)
    authority = preopen_authority.PreOpenShareUnitAuthority(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        effective_session=plan.effective_session, provider='test', publication_id='test',
        as_of=opened, cutoff_at=opened, complete=True,
        coverage=tuple(preopen_authority.ShareUnitCoverage.no_event(sid) for sid in plan.target_basket))
    async def reconcile(**kwargs):
        return reconciliation(_observation())
    grant, broker, recorded = _install_recovery_harness(
        monkeypatch, plan=plan, authority=authority, commands=[], reconcile=reconcile)
    monkeypatch.setattr(journal, 'require_observation_integrity', lambda *a: None)
    monkeypatch.setattr(paper_recovery, 'SessionState', SessionState)
    monkeypatch.setattr(catchup, 'resume_state', lambda *a: env.to_dict())
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: None)
    broker.capabilities = SimpleNamespace(minimum_quantity_increment=D(1), require=lambda *a: None)
    opening_reads = []
    async def opening_prices(**kwargs):
        opening_reads.append(kwargs)
        return prices(env, plan)
    async def resolve_instrument(**kwargs):
        return BrokerInstrument(kwargs['security_id'], kwargs['symbol'])
    broker.opening_prices = opening_prices
    broker.resolve_instrument = resolve_instrument
    class Clock:
        @staticmethod
        def now(tz):
            return (opened + timedelta(minutes=2)).astimezone(tz)
    monkeypatch.setattr(paper_recovery, 'datetime', Clock)
    result = asyncio.run(paper_recovery.recover_automated_paper_cycle(
        conn=object(), broker=broker, base_url='https://paper-api.alpaca.markets',
        grant=grant, automation_config_sha256='a'*64))
    assert result.clean
    assert recorded == []
    assert opening_reads == []


@pytest.mark.parametrize('dual', [False, True])
def test_unsized_empty_basket_cannot_certify_convergence(monkeypatch, dual):
    _, plan = case()
    runtime = production(config())
    runtime._dual_run_enabled = dual
    monkeypatch.setattr(runtime, '_require_dual_plan_shadow_match', lambda *a, **k: {})
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: None)
    with pytest.raises(projections.TargetProjectionRefused, match='absent'):
        runtime._actionable_current_plan_deltas(
            object(), plan=plan, effective_session=plan.effective_session,
            observation=_observation(), minimum_quantity_increment=D(1))


@pytest.mark.parametrize('state_name', ['UNKNOWN', 'ACKNOWLEDGED', 'FILLED', 'CANCELLED', 'REJECTED'])
def test_lost_opening_projection_with_any_plan_command_refuses(monkeypatch, state_name):
    from tests.sentinel.test_automation_runtime import command
    from sentinel.execution.states import CommandState
    _, plan = case()
    recorded = command(plan.plan_id, state=CommandState[state_name])
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: None)
    def commands(conn, deployment, *, plan_id):
        assert plan_id == plan.plan_id
        return (recorded,)
    monkeypatch.setattr(journal, 'load_commands', commands)
    with pytest.raises(projections.TargetProjectionRefused, match='durable commands'):
        opening_sizing.requires_initial_projection(object(), plan=plan, deployment=object())


@pytest.mark.parametrize('closed', [False, True])
def test_unsent_opening_recovery_returns_to_sizing_or_supersedes(monkeypatch, closed):
    from tests.sentinel.test_automation_runtime import (
        context, FakeConnection, install_runtime_seams)
    from sentinel.automation.model import CycleState, ExecuteDisposition
    from sentinel.execution.simulator import SimulatedBroker
    _, plan = case()
    cfg = config()
    ctx = context(cfg, state=CycleState.RECONCILING, plan=plan)
    conn, broker = FakeConnection(), SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    monkeypatch.setattr(automation_runtime.schema, 'require_runtime_schema', lambda *a: None)
    monkeypatch.setattr(automation_runtime, 'require_observation_integrity', lambda *a: None)
    async def clean(**kwargs):
        return reconciliation(await kwargs['broker'].observe())
    monkeypatch.setattr(paper, 'recover_automated_paper_cycle', clean)
    monkeypatch.setattr(journal, 'in_flight_commands', lambda *a: ())
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: ())
    monkeypatch.setattr(journal, 'latest_plan', lambda *a: plan)
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: None)
    # The cycle fixture carries its own certified execution-close instant.
    close = ctx.cycle.execution_close_at
    monkeypatch.setattr(automation_runtime, '_now_utc',
                        lambda: close if closed else close-timedelta(minutes=1))
    result = asyncio.run(runtime.recover(ctx))
    assert result.disposition is (ExecuteDisposition.SUPERSEDED if closed
                                  else ExecuteDisposition.READY_TO_EXECUTE)
    assert result.failure_code == ('EXECUTION_WINDOW_CLOSED' if closed
                                   else 'OPENING_SIZING_REQUIRED')


@pytest.mark.parametrize('status', [401, 403, 404, 422])
def test_opening_asset_lookup_permanent_error_stays_terminal(monkeypatch, status):
    env, plan = case()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    class Broker:
        capabilities = SimpleNamespace(require=lambda *a: None)
        async def resolve_instrument(self, **kwargs):
            request = httpx.Request('GET', 'https://paper-api.alpaca.markets/v2/assets/AAA')
            httpx.Response(status, request=request).raise_for_status()
    with pytest.raises(paper.PaperActivationRefused) as caught:
        asyncio.run(paper_execution._opening_prices_or_retry(
            object(), state=env, plan=plan, broker=Broker()))
    assert not isinstance(caught.value, paper.PaperRetryableRefused)


def test_opening_asset_lookup_timeout_retries_and_authority_refusal_propagates(monkeypatch):
    from sentinel.execution.guarded import BrokerAuthorityRefused
    env, plan = case()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    class Broker:
        capabilities = SimpleNamespace(require=lambda *a: None)
        async def resolve_instrument(self, **kwargs):
            raise failure
    for failure, expected in [(httpx.ReadTimeout('late'), paper.PaperRetryableRefused),
                              (BrokerAuthorityRefused('revoked'), BrokerAuthorityRefused),
                              (ValueError('software defect'), ValueError)]:
        with pytest.raises(expected):
            asyncio.run(paper_execution._opening_prices_or_retry(
                object(), state=env, plan=plan, broker=Broker()))
