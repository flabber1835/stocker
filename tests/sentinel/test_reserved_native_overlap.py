"""Exercise funded PAPER purchases across real PostgreSQL and a native-shaped private venue.

The opening strategy output, issuer and signed grant checks are fixtures. The
executor, durable reservation, current-book proof, command identity, adapter
and last header write check run normally. Exchange time and fill delay are
controlled. No external broker or production database is reachable here.
"""
import asyncio
import json
import multiprocessing
import os
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import psycopg
import pytest

from sentinel import binding, dual_plan_authority, schema
from sentinel.execution import broker_cash, executor, fractional_sizing, journal, reconcile, target_reprojection
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.fractional_progress import PostingFunds
from sentinel.execution.guarded import AutomationExecutionGrant, ExecutionBrokerGuard, GuardedExecutionBroker
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.states import CommandState
from sentinel.feed import calendar
from sentinel.paper import market_reservations, validation
from sentinel.paper.cash import _broker_cash_state_or_refuse, _cash_authority_or_refuse
from tests.sentinel.test_fractional_flow import fractional_environment
from tests.sentinel.test_fractional_native_settlement import FractionalVenue
from tests.sentinel.test_limit_day_sizing import references
from tests.sentinel.test_order_terms_schema import database, pg
from tests.support.current_workflow_clock import BusinessClock
from tests.support.current_workflow_transport import Response
from tests.v5.test_opening import base, case


class RestingVenue(FractionalVenue):
    delay = timedelta(seconds=120)

    def __init__(self, *, clock, evidence, fault, **kwargs):
        super().__init__(**kwargs)
        self.clock, self.evidence, self.fault = clock, evidence, fault
        self.wire_attempts, self.acceptances, self.due_events = [], [], {}
        self.asset_reads = []
        if evidence.exists():
            saved = json.loads(evidence.read_text())
            self.restore(saved['native'])
            self.wire_attempts = saved['wire_attempts']
            self.acceptances = saved['acceptances']
            self.due_events = saved['due_events']
        venue = self

        class Client(self.AsyncClient):
            def __init__(self, *, event_hooks=None, **kwargs):
                super().__init__(**kwargs)
                self.hooks = (event_hooks or {}).get('request', ())

            async def post(self, url, headers=None, json=None):
                request = httpx.Request('POST', url, headers=headers, json=json)
                for hook in self.hooks:
                    await hook(request)
                if venue.fault == 'cutoff' and len(venue.acceptances) == 1:
                    venue.clock.instant = venue.window()[0] + timedelta(minutes=10)
                await request.extensions['trace']('http11.send_request_headers.started',
                                                  {'request': SimpleNamespace(method=b'POST')})
                return venue.post(url, json)

        self.AsyncClient = Client

    def persist(self):
        draft = self.evidence.with_suffix('.tmp')
        draft.write_text(json.dumps(dict(native=self.state(), wire_attempts=self.wire_attempts,
                                         acceptances=self.acceptances,
                                         due_events=self.due_events)))
        draft.replace(self.evidence)

    def post(self, url, body):
        # This ledger has only the BUYs the simulated broker actually accepted.
        prior = [o['client_order_id'] for o in self.orders.values() if o['status'] == 'new']
        available = self.cash - sum((D(o['notional']) for o in self.orders.values()
                                     if o['status'] == 'new'), D(0))
        if self.fault == 'external_hold' and prior:
            available = D(0)
        self.wire_attempts.append(body['client_order_id'])
        self.persist()  # Retain unexpected POSTs even if the private venue refuses them.
        assert D(0) < D(body['notional']) <= available
        assert self.clock.now() < self.window()[0] + timedelta(minutes=10)
        # Reuse the fixture's native order and activity schemas. Until due,
        # only a working order and its buying-power hold are visible.
        cash, positions = self.cash, self.positions.copy()
        filled = super().post(url, body).payload
        event = self.unpublished.pop()
        self.cash, self.positions = cash, positions
        stamp = self.clock.now()
        due = stamp + self.delay
        key = body['client_order_id']
        self.acceptances.append(dict(key=key, at=stamp.isoformat(), prior=prior, available=str(available),
                                     asset_reads=self.asset_reads.copy()))
        order = dict(filled, status='new', filled_at=None, filled_avg_price=None, filled_qty='0',
                     created_at=stamp.isoformat(), updated_at=stamp.isoformat(), submitted_at=stamp.isoformat())
        self.orders[order['id']] = order
        self.due_events[order['id']] = dict(event, at=due.isoformat(), executed_at=due.isoformat())
        self.persist()
        if self.fault == 'worker_loss' and len(self.acceptances) == 2:
            os._exit(72)  # Broker accepted. There will be no HTTP response or journal acknowledgement.
        self.clock.instant += timedelta(seconds=1)
        return Response(order)

    def get(self, url, params):
        if self.path(url).startswith('/v2/assets/'):
            self.asset_reads.append(self.path(url).rsplit('/', 1)[1])
        for order_id, event in tuple(self.due_events.items()):
            if self.clock.now() < datetime.fromisoformat(event['executed_at']):
                continue
            order = self.orders[order_id]
            order.update(status='filled', filled_at=event['executed_at'], updated_at=event['executed_at'],
                         filled_qty=event['qty'], filled_avg_price=event['price'])
            asset = order['asset_id']
            self.positions[asset] = self.positions.get(asset, D(0)) + D(event['qty'])
            self.cash += D(event['net_amount'])
            self.events.append(event)
            del self.due_events[order_id]
            self.persist()
        response = super().get(url, params)
        if self.fault == 'external_hold' and self.acceptances and self.path(url) == '/v2/account':
            response.payload['buying_power'] = '0'
        return response


def plan_inputs(bound):
    shadow, raw = case(entries=2)
    plan = replace(raw, **bound.identity.to_dict(), account_nav=D(20000), account_cash=D(20000))
    plan = replace(plan, plan_id='sentinel-' + plan.fingerprint())
    initial = base(shadow, plan)
    projection = fractional_sizing.resolve(shadow, plan, initial, references(plan, initial),
        MarketBuyPolicy(True), baseline={'through_event_seq': 0, 'commands': [], 'holdings': {}}, retained_targets={})
    return plan, projection


async def dispatch(conn, evidence, fault, clock, monkeypatch, *, recover=False):
    bound = binding.require(conn)
    plan, projection = plan_inputs(bound)
    window = calendar.session_window(plan.effective_session)
    instruments = {sid: BrokerInstrument(sid, sid.removeprefix('SEC-'), 'asset-' + sid)
                   for sid in projection.opening_sizing['purchases']}
    assets = {i.symbol: dict(id=i.broker_id, symbol=i.symbol, price=D(100)) for i in instruments.values()}
    venue = RestingVenue(clock=clock, evidence=evidence, fault=fault, account=bound.broker_account_id,
                         cash='20000', assets=assets, window=lambda: window)
    inner = AssetIdAlpacaExecutionBroker(api_key='fixture', secret_key='fixture',
        base_url='https://paper-api.alpaca.markets', http_provider=lambda: venue,
        resolve_security_id=lambda symbol, *_: 'SEC-' + symbol)
    grant = AutomationExecutionGrant('EXECUTE', 'test-cycle', 1, 'private', 1, bound.broker_account_id,
                                    1, 'CONTROLLER', 2, 'a'*64)
    async def permit(*args, **kwargs):
        pass

    def issuer(**kwargs):
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(dual_plan_authority, 'require_current_buy_policy', lambda *a, **kw: None)
    settled = None
    activity = None
    fill_cash = market_reservations.VerifiedFillCash()
    terminal_receipts = {}

    async def funds(rec):
        nonlocal settled, activity
        account = await broker.account_snapshot()
        activity = await _broker_cash_state_or_refuse(conn, broker=broker, binding=bound, through=clock.now())
        _cash_authority_or_refuse(conn, plan=plan, deployment=bound.identity, account=account,
                                  observation=rec.observation, activity_state=activity)
        settled = rec.observation
        return PostingFunds(account.cash, account.buying_power, D(0), D(0))

    def reserve(commands, rec, posting):
        market_reservations.reserve(conn, commands, plan=plan, projection=projection, deployment=bound.identity,
                                    reconciliation=rec, funds=posting, activity=activity)

    async def check(*, account, **candidate):
        basis = market_reservations.load(conn, plan)
        key = candidate['client_key']
        observed = await market_reservations.current_book(conn, binding=bound, expected_account=bound.broker_account_id,
            clock=clock.now, account=account, broker=broker, sweep_due=lambda: False, settled_observation=settled,
            basis=basis, plan=plan, projection=projection, candidate_key=key, terminal_receipts=terminal_receipts,
            fill_cash=fill_cash)
        validation._market_buy_candidate_or_refuse(conn, plan=plan, projection=projection, deployment=bound.identity,
            observation=observed, cash_ceiling=D(basis['cash_limits'][key]), reservation=basis, **candidate)
        if fault == 'worker_loss' and len(venue.acceptances) == 1:
            # Model the second cash check taking longer than the native asset rule's lifetime.
            clock.instant += timedelta(seconds=31)

    broker = GuardedExecutionBroker(inner=inner, grant=grant, guard=ExecutionBrokerGuard(permit, permit, permit),
                                   issuer_admission_check=issuer, market_buy_funding=check)
    with journal.writer_lock(conn, recovery_only=True):
        if not recover:
            initial_cash = await _broker_cash_state_or_refuse(conn, broker=broker, binding=bound, through=clock.now())
            broker_cash.record_plan_baseline(conn, plan_id=plan.plan_id, decision_session=plan.decision_session,
                                            activity_state=initial_cash)
        else:
            result = await reconcile.reconcile(broker=broker, conn=conn, binding=None, deployment=bound.identity,
                                               informational_current_book=True)
            assert result.clean, result.to_dict()
        result = await executor._execute_session_locked(broker=broker, conn=conn, deployment=bound.identity,
            plan=plan, instruments=instruments, today=plan.effective_session, actions=None, target_projection=projection,
            min_increment=D('0.000000001'), informational_current_book=True, increase_reconciliation_authority=funds,
            buy_admission=issuer, reserve_market_buys=reserve,
            market_buy_window_open=lambda: clock.now() < window[0] + timedelta(minutes=10))
        return result, venue


def opening_worker(dsn, evidence, fault, at):
    clock = BusinessClock(at)
    with pytest.MonkeyPatch.context() as patch, psycopg.connect(dsn) as conn:
        clock.install(patch)
        result, _ = asyncio.run(dispatch(conn, evidence, fault, clock, patch))
        if fault == 'worker_loss':
            raise AssertionError(f'second native acceptance never reached: {result.to_dict()}')
        assert result.deferral_reasons, result.to_dict()


@pytest.mark.parametrize('fault', ['worker_loss', 'cutoff', 'external_hold'])
def test_native_parallel_funding_and_last_write(pg, database, monkeypatch, fractional_environment, tmp_path, fault):
    schema.ensure_schema(database)
    bound = binding.bind(database, deployment_id='parallel-native', broker='alpaca', broker_account_id='PA-private')
    database.execute("UPDATE sentinel_account_binding SET established_at='2026-02-12T00:00:00Z'")
    plan, projection = plan_inputs(bound)
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    database.commit()
    opened, _ = calendar.session_window(plan.effective_session)
    first_at = opened + timedelta(seconds=61)
    evidence = tmp_path / 'native.json'
    worker = multiprocessing.get_context('spawn').Process(target=opening_worker,
        args=(pg.sync_dsn, evidence, fault, first_at))
    worker.start()
    try:
        worker.join(120)
        assert worker.exitcode == (72 if fault == 'worker_loss' else 0)
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join()
    saved = json.loads(evidence.read_text())
    accepts = saved['acceptances']
    assert saved['wire_attempts'] == [r['key'] for r in accepts]
    commands = {c.client_key: c for c in journal.load_commands(database, bound.identity)}
    assert len(commands) == 2
    assert accepts[0]['prior'] == [] and D(accepts[0]['available']) == D(20000)
    if fault != 'worker_loss':
        assert len(accepts) == 1
        remaining, = set(commands) - {accepts[0]['key']}
        assert commands[remaining].state is CommandState.PLANNED
        return
    first, second = accepts
    assert second['prior'] == [first['key']] and D(second['available']) == D(19001)
    assert set(first['asset_reads']) == {c.instrument.broker_id for c in commands.values()}
    assert second['asset_reads'][len(first['asset_reads']):] == [commands[second['key']].instrument.broker_id]
    assert first_at <= datetime.fromisoformat(first['at']) < datetime.fromisoformat(second['at']) < first_at + RestingVenue.delay
    assert set(commands) == {r['key'] for r in accepts}
    assert commands[second['key']].state is CommandState.SEND_PENDING
    assert all(row['status'] == 'new' for row in saved['native']['orders'].values())
    assert saved['native']['cash'] == '20000' and not saved['native']['positions']
    clock = BusinessClock(datetime.fromisoformat(second['at']) + RestingVenue.delay + timedelta(seconds=1))
    clock.install(monkeypatch)
    result, venue = asyncio.run(dispatch(database, evidence, None, clock, monkeypatch, recover=True))
    assert not result.submitted and result.reconciliation.clean, result.to_dict()
    assert venue.acceptances == accepts and venue.wire_attempts == saved['wire_attempts']
    assert venue.requests['POST /v2/orders'] == 2
    assert venue.cash == D(18002) and venue.positions == {'asset-SEC-AAA': D('9.99'), 'asset-SEC-BBB': D('9.99')}
    commands = journal.load_commands(database, bound.identity)
    assert {c.client_key for c in commands} == {first['key'], second['key']}
    assert all(c.state is CommandState.FILLED and c.filled_quantity == D('9.99') for c in commands)
    assert database.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 2
