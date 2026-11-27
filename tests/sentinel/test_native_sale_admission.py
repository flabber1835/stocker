"""Only a guarded PAPER sale may publish its original pending row at native POST."""
import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import schema
from sentinel.execution import executor, guarded, journal, submission_group
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import Side
from sentinel.execution.guarded import ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant, PreTransportAuthorityRefused
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT, Response, full_order
from tests.sentinel.test_limit_day_transport import broker_for
from tests.sentinel.test_order_terms_schema import database, pg  # noqa: F401


@pytest.fixture
def native_sale(database, monkeypatch):
    schema.ensure_schema(database)
    monkeypatch.delenv('SENTINEL_PAPER_BUY_POLICY', raising=False)
    identity = DeploymentIdentity('private', 'alpaca', 'private-paper', 1)
    command = Command(CommandIdentity(identity, 'exit', INSTRUMENT.security_id), INSTRUMENT, Side.SELL, Decimal(2))
    raw, http = broker_for(AssetIdAlpacaExecutionBroker, routes={'/v2/assets/AAPL': {
        'id': INSTRUMENT.broker_id, 'symbol': INSTRUMENT.symbol, 'status': 'active',
        'tradable': True, 'fractionable': True}})
    states, writes = [], []
    with psycopg.connect(database.info.dsn, autocommit=True) as witness:
        def state():
            row = witness.execute("SELECT state FROM sentinel_commands WHERE client_key=%s", (command.client_key,)).fetchone()
            return row and row[0]
        async def read(*_):
            pass
        async def approve(*_):
            states.append(state())
        async def post(_client, _url, *, headers, json):
            writes.append((state(), json))
            return Response(full_order(client_order_id=command.client_key, side='sell'))
        monkeypatch.setattr(http.AsyncClient, 'post', post)
        wrapped = GuardedExecutionBroker(inner=raw,
            grant=ManualExecutionGrant(identity.broker_account_id, 'exit', date(2026, 11, 27), True),
            guard=ExecutionBrokerGuard(read, read, approve))
        def run():
            return asyncio.run(executor._dispatch_independent(database, wrapped,
                [(command, False, None, False)], reserved=False))
        yield SimpleNamespace(raw=raw, http=http, broker=wrapped, writes=writes, states=states,
                              command=command, run=run, state=state)


def test_approval_sees_planned_and_venue_sees_only_committed_send_pending(native_sale):
    case = native_sale
    outcome, = case.run()
    assert case.states == ['PLANNED']
    assert [(state, body['client_order_id']) for state, body in case.writes] == [('SEND_PENDING', case.command.client_key)]
    assert outcome.state is S.ACKNOWLEDGED and case.state() == 'ACKNOWLEDGED'


def test_failed_local_commit_never_reaches_post_and_preserves_plan(database, native_sale):
    database.execute("""
        CREATE FUNCTION refuse_send_commit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.to_state='SEND_PENDING' THEN RAISE EXCEPTION 'private commit failure'; END IF; RETURN NULL; END $$""")
    database.execute("""CREATE CONSTRAINT TRIGGER refuse_send_commit AFTER INSERT ON sentinel_command_events
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION refuse_send_commit()""")
    database.commit()
    with pytest.raises(PreTransportAuthorityRefused, match='could not be committed'):
        native_sale.run()
    assert native_sale.states == ['PLANNED'] and not native_sale.writes and native_sale.state() == 'PLANNED'


def test_direct_adapter_and_removed_native_handoff_never_reach_post(native_sale, monkeypatch):
    case = native_sale
    with submission_group.independent_dispatch_scope((case.command,), paper_seller=case.broker):
        with pytest.raises(PreTransportAuthorityRefused, match='original guarded writer'):
            asyncio.run(case.raw.submit(client_key=case.command.client_key, instrument=INSTRUMENT,
                                         side=Side.SELL, quantity=Decimal(2)))
    async def omit_handoff(*_args, **_kwargs):
        pass
    monkeypatch.setattr(guarded, 'admit_planned_paper_sale', omit_handoff)
    with pytest.raises(PreTransportAuthorityRefused, match='committed send checkpoint'):
        case.run()
    assert not case.writes and not case.states and case.state() == 'PLANNED'


def test_sale_cannot_change_economics_or_reuse_a_siblings_checkpoint(native_sale, monkeypatch):
    case = native_sale
    actual = guarded.admit_planned_paper_sale
    async def substitute(adapter, **terms):
        await actual(adapter, **{**terms, 'quantity': terms['quantity'] * 2})
    monkeypatch.setattr(guarded, 'admit_planned_paper_sale', substitute)
    with pytest.raises(PreTransportAuthorityRefused, match='original guarded writer and command'):
        case.run()
    assert not case.states and not case.writes and case.state() == 'PLANNED'


def test_regular_session_can_expire_during_native_sale_approval(native_sale, monkeypatch):
    from datetime import timedelta
    from sentinel.execution.market_buy_policy import FRACTIONAL_MODE
    from sentinel.feed import calendar
    from tests.sentinel.test_market_buy_policy import MARKET_ENV

    case = native_sale
    for key, value in {**MARKET_ENV, 'SENTINEL_PAPER_BUY_POLICY': FRACTIONAL_MODE}.items():
        monkeypatch.setenv(key, value)
    _opened, close = calendar.session_window(date(2026, 11, 27))
    clock = [close - timedelta(seconds=1)]
    case.raw._clock_provider = lambda: clock[0]
    case.http.routes['/v2/clock'] = dict(timestamp=clock[0].isoformat(), is_open=True,
        next_open=(close + timedelta(days=3)).isoformat(), next_close=close.isoformat())
    case.http.routes['/v2/assets/' + INSTRUMENT.broker_id] = case.http.routes['/v2/assets/AAPL']
    prior = case.broker._guard
    async def close_during_approval(*args):
        await prior.before_mutation(*args)
        clock[0] = close
    monkeypatch.setattr(case.broker, '_guard', ExecutionBrokerGuard(prior.before_read, prior.after_read, close_during_approval))
    outcome, = case.run()
    assert outcome.state is S.PLANNED and 'outside the plan' in outcome.detail
    assert case.states == ['PLANNED'] and not case.writes and case.state() == 'PLANNED'


@pytest.mark.parametrize('scope', ['live', 'reserved-purchase'])
def test_other_funding_modes_keep_original_pending_checkpoint(database, native_sale, monkeypatch, scope):
    case = native_sale
    command = case.command
    if scope == 'live':
        live_deployment = replace(command.identity.deployment, broker='alpaca-live')
        command = replace(command, identity=replace(command.identity, deployment=live_deployment))
    else:
        command = replace(command, side=Side.BUY, quantity=None, notional=Decimal(10))
    async def check(_broker, pending):
        assert submission_group.sale_group() is None
        stored, = journal.load_commands(database, pending.identity.deployment)
        assert stored.state is S.SEND_PENDING and stored.client_key == command.client_key
        return pending.transition(S.ACKNOWLEDGED, broker_order_id='original-test-receipt')
    monkeypatch.setattr(executor.recovery, 'dispatch', check)
    if scope == 'reserved-purchase':
        journal.save_command(database, command)
    outcome, = asyncio.run(executor._dispatch_independent(database, case.broker,
        [(command, False, None, False)], reserved=scope == 'reserved-purchase'))
    assert outcome.state is S.ACKNOWLEDGED and not case.writes
