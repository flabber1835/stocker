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
from sentinel.execution.opening_prices import OpeningPriceUnavailability
from sentinel.feed import calendar, publication, store as feed_store
from sentinel.paper import execution as paper_execution, recovery as paper_recovery, targets
from tests.v5.test_opening import case, base, prices
from tests.sentinel.test_production_decision import _observation
from tests.sentinel.test_automation_runtime import config, production, reconciliation
from tests.sentinel.test_preopen_paper_gate import _install_recovery_harness


def published_opening_identity(monkeypatch):
    from sentinel.feed import universe
    resolver = universe.IdentityResolver([universe.Listing('SEC-AAA', 'AAA')])
    monkeypatch.setattr(universe, 'load_resolver', lambda *a, **k: resolver)


def test_expired_opening_returns_no_buy_evidence_for_mixed_plan(monkeypatch):
    env, plan = case(cash=100., sale=True)
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: None)
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: ())
    opened, _ = calendar.session_window(plan.effective_session)
    evidence = paper_execution._opening_resolution_freshness_or_refuse(
        object(), plan=plan, deployment=object(),
        now_et=opened + timedelta(hours=2))
    assert isinstance(evidence, OpeningPriceUnavailability)
    projected = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    assert projected.target_basket == {'SEC-AAA': D(0), 'SEC-X': D(0)}
    assert projected.opening_sizing['mode'] == opening_sizing.UNAVAILABLE_MODE


@pytest.mark.parametrize('seconds', [60, 120])
def test_fresh_opening_still_requests_price_evidence(monkeypatch, seconds):
    _, plan = case()
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: None)
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: ())
    opened, _ = calendar.session_window(plan.effective_session)
    assert paper_execution._opening_resolution_freshness_or_refuse(
        object(), plan=plan, deployment=object(),
        now_et=opened + timedelta(seconds=seconds)) is None


def test_expired_unsent_projection_retains_original_economics(monkeypatch):
    env, plan = case(sale=True)
    stored = opening_sizing.resolve(env, plan, base(env, plan), prices(env, plan))
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: stored)
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: ())
    opened, _ = calendar.session_window(plan.effective_session)
    assert paper_execution._opening_resolution_freshness_or_refuse(
        object(), plan=plan, deployment=object(),
        now_et=opened + timedelta(hours=2)) is None
    assert stored.target_basket['SEC-AAA'] > 0


@pytest.mark.parametrize('seconds', [0, 30, 59])
def test_forming_opening_minute_retries_then_sizes_the_same_intent(monkeypatch, seconds):
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    from sentinel.execution.opening_prices import OpeningPrices
    published_opening_identity(monkeypatch)
    env, plan = case()
    before = env.to_dict()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    opened, _ = calendar.session_window(plan.effective_session)
    now = [opened + timedelta(seconds=seconds)]
    reads = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            reads.append(url)
            return httpx.Response(200, request=httpx.Request('GET', url), json={
                'bars': {'AAA': [{'t': opened.isoformat(), 'o': 100, 'v': 10}]},
                'next_page_token': None})
    broker = AlpacaExecutionBroker(api_key='test', secret_key='test',
        base_url='https://paper-api.alpaca.markets',
        http_provider=lambda: SimpleNamespace(AsyncClient=Client),
        clock_provider=lambda: now[0])
    async def resolve_instrument(*, security_id, symbol):
        return BrokerInstrument(security_id, symbol, 'asset-'+security_id)
    monkeypatch.setattr(broker, 'resolve_instrument', resolve_instrument)
    with pytest.raises(paper.PaperRetryableRefused, match='still forming'):
        asyncio.run(paper_execution._opening_prices_or_retry(
            object(), state=env, plan=plan, broker=broker))
    assert reads == []
    now[0] = opened + timedelta(seconds=60)
    evidence = asyncio.run(paper_execution._opening_prices_or_retry(
        object(), state=env, plan=plan, broker=broker))
    assert isinstance(evidence, OpeningPrices)
    assert len(reads) == 1
    projected = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    assert projected.target_basket['SEC-AAA'] == D(49)
    assert projected.opening_sizing['mode'] == opening_sizing.FINAL_MODE
    assert env.to_dict() == before


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
def test_opening_asset_lookup_transient_failure_becomes_no_buy(monkeypatch, status):
    published_opening_identity(monkeypatch)
    env, plan = case()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    class Broker:
        capabilities = SimpleNamespace(require=lambda *a: None)
        async def resolve_instrument(self, **kwargs):
            request = httpx.Request('GET', 'https://paper-api.alpaca.markets/v2/assets/AAA')
            response = httpx.Response(status, request=request)
            response.raise_for_status()
    evidence = asyncio.run(paper_execution._opening_prices_or_retry(
        object(), state=env, plan=plan, broker=Broker()))
    assert isinstance(evidence, OpeningPriceUnavailability)
    projected = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    assert projected.target_basket['SEC-AAA'] == 0
    assert projected.opening_sizing['mode'] == opening_sizing.UNAVAILABLE_MODE


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


@pytest.mark.parametrize('status', [401, 403])
def test_opening_asset_lookup_authentication_error_stays_terminal(monkeypatch, status):
    published_opening_identity(monkeypatch)
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


@pytest.mark.parametrize('status', [404, 422])
def test_opening_asset_lookup_non_authority_4xx_suppresses_buy(monkeypatch, status):
    published_opening_identity(monkeypatch)
    env, plan = case()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    class Broker:
        capabilities = SimpleNamespace(require=lambda *a: None)
        async def resolve_instrument(self, **kwargs):
            request = httpx.Request('GET', 'https://paper-api.alpaca.markets/v2/assets/AAA')
            httpx.Response(status, request=request).raise_for_status()
    evidence = asyncio.run(paper_execution._opening_prices_or_retry(
        object(), state=env, plan=plan, broker=Broker()))
    assert isinstance(evidence, OpeningPriceUnavailability)


def test_opening_asset_lookup_timeout_suppresses_buy_and_authority_refusal_propagates(monkeypatch):
    published_opening_identity(monkeypatch)
    from sentinel.execution.guarded import BrokerAuthorityRefused
    env, plan = case()
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    class Broker:
        capabilities = SimpleNamespace(require=lambda *a: None)
        async def resolve_instrument(self, **kwargs):
            raise failure
    failure = httpx.ReadTimeout('late')
    evidence = asyncio.run(paper_execution._opening_prices_or_retry(
        object(), state=env, plan=plan, broker=Broker()))
    assert isinstance(evidence, OpeningPriceUnavailability)
    for failure, expected in [(BrokerAuthorityRefused('revoked'), BrokerAuthorityRefused),
                              (ValueError('software defect'), ValueError)]:
        with pytest.raises(expected):
            asyncio.run(paper_execution._opening_prices_or_retry(
                object(), state=env, plan=plan, broker=Broker()))


def test_abv_adjacent_split_rows_cannot_rescale_published_signal():
    from stock_strategy_shared.wealth_core.feed import SecuritySeries, VendorBar
    series = SecuritySeries('258893123405622697', 'ABV', 'SID:258893123405622697',
                            split_factor=.2)
    # Exact immutable-PIT rows surrounding the first historical divergence.
    rows = [('2013-11-08', 37.2, 7.44, 1.),
            ('2013-11-11', 37.2, 7.44, 5.),
            ('2013-11-12', 7.38, 7.38, 5.)]
    for i, (session, raw, signal, split) in enumerate(rows):
        series.append(VendorBar(session, series.security_id, 'ABV', raw, raw,
                               1e6, split_ratio=split, signal_close=signal),
                      i, published_signal=True)
        assert series.signal_closes[-1] == signal
        assert series.raw_closes[-1] == raw
        assert series.vendor_basis_multiplier == 1.
    assert series.signal_closes == [7.44, 7.44, 7.38]


def test_previously_inferred_price_basis_cannot_survive_restart():
    import json
    from stock_strategy_shared.wealth_core.feed import SecuritySeries, VendorBar, FeedError
    series = SecuritySeries('A', 'A', 'SID:A', vendor_basis_multiplier=5.)
    restored = SecuritySeries(**json.loads(json.dumps(vars(series))))
    with pytest.raises(FeedError, match='inferred vendor basis'):
        restored.append(VendorBar('0001', 'A', 'A', 7.38, 7.38, 1e6,
                                  signal_close=7.38), 1, published_signal=True)
    assert vars(restored) == vars(series)
