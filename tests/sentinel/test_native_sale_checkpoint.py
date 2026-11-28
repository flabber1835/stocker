"""Process death on either side of the native PAPER sale's durable checkpoint."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal
import json
import multiprocessing
import os
import signal
from types import SimpleNamespace

import httpx
import psycopg
import pytest

from sentinel import schema
from sentinel.execution import executor, guarded, journal
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import ALPACA_PAPER_BROKER, CommandIdentity, DeploymentIdentity
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from tests.sentinel.test_issue_183_alpaca_hardening import PAPER, full_order
from tests.sentinel.test_market_buy_policy import MARKET_ENV
from tests.sentinel.test_market_day_execution import wrapper
from tests.sentinel.test_order_terms_schema import database, pg  # noqa: F401


DEPLOYMENT = DeploymentIdentity('death-test', ALPACA_PAPER_BROKER, 'SIM-ACCOUNT', 1)
SALES = tuple(Command(CommandIdentity(DEPLOYMENT, 'exit', 'SEC-' + symbol),
    BrokerInstrument('SEC-' + symbol, symbol, 'asset-' + symbol), Side.SELL, Decimal('2.5'))
    for symbol in ('AAA', 'BBB'))


class PrivateVenue:
    """The venue's independent transaction survives a worker's SIGKILL."""

    def __init__(self, dsn, crash=None):
        self.dsn, self.crash = dsn, crash
        self.visible = False
        self.entered = set()
        self.both = asyncio.Event()
        self.lookups = []
        self.opened, self.closed = calendar.session_window(date(2026, 8, 18))
        self.now = self.opened + timedelta(minutes=2)

    def broker(self):
        transport = httpx.MockTransport(self.respond)
        venue = self

        async def before_transport(request):
            if venue.crash == 'pending' and request.method == 'POST':
                key = json.loads(request.content)['client_order_id']
                with psycopg.connect(venue.dsn) as audit:
                    assert audit.execute('SELECT state FROM sentinel_commands WHERE client_key=%s',
                                         (key,)).fetchone() == (S.SEND_PENDING.value,)
                os.kill(os.getpid(), signal.SIGKILL)

        class Client(httpx.AsyncClient):
            async def __aenter__(self):
                # The native adapter opens its POST client after guarded order preparation.
                if venue.crash and self.event_hooks['request']:
                    key = guarded._PAPER_SUBMIT_WINDOW.get().client_key
                    venue.entered.add(key)
                    if venue.entered == {sale.client_key for sale in SALES}:
                        venue.both.set()
                    await venue.both.wait()
                    if key == SALES[1].client_key:
                        await asyncio.Event().wait()  # This sibling never reaches the native checkpoint.
                    if venue.crash == 'before':
                        os.kill(os.getpid(), signal.SIGKILL)
                    self.event_hooks['request'].append(before_transport)
                return await super().__aenter__()

        http = SimpleNamespace(AsyncClient=lambda **options: Client(transport=transport, **options))
        raw = AssetIdAlpacaExecutionBroker(api_key='private', secret_key='private', base_url=PAPER,
            resolve_security_id=lambda symbol, _as_of=None: 'SEC-' + symbol, http_provider=lambda: http)
        raw.now = self.now
        raw._clock_provider = lambda: self.now
        return wrapper(raw)

    async def respond(self, request):
        path = request.url.path
        if path == '/v2/clock':
            return httpx.Response(200, json={'timestamp': self.now.isoformat(), 'is_open': True,
                'next_open': (self.opened + timedelta(days=1)).isoformat(), 'next_close': self.closed.isoformat()})
        if path.startswith('/v2/assets/'):
            asset = path.rsplit('/', 1)[1]
            return httpx.Response(200, json={'id': asset, 'symbol': asset.removeprefix('asset-'),
                'status': 'active', 'tradable': True, 'fractionable': True})
        if path == '/v2/orders' and request.method == 'POST':
            body = json.loads(request.content)
            with psycopg.connect(self.dsn) as audit:
                state, = audit.execute('SELECT state FROM sentinel_commands WHERE client_key=%s',
                                       (body['client_order_id'],)).fetchone()
                assert state == S.SEND_PENDING.value
                audit.execute('INSERT INTO private_venue_sales VALUES (%s,%s,%s,%s)',
                    (body['client_order_id'], body['symbol'], body['side'], body['qty']))
            if self.crash == 'accepted':
                os.kill(os.getpid(), signal.SIGKILL)
            return httpx.Response(201, json=self.order(body['client_order_id'], body['symbol'], body['qty']))
        if path == '/v2/orders:by_client_order_id':
            key = request.url.params['client_order_id']
            self.lookups.append(key)
            with psycopg.connect(self.dsn) as audit:
                row = audit.execute('SELECT asset, quantity FROM private_venue_sales WHERE client_key=%s', (key,)).fetchone()
            if self.visible and row:
                return httpx.Response(200, json=self.order(key, *row))
            return httpx.Response(404, json={'message': 'order not found'})
        if path == '/v2/account':
            return httpx.Response(200, json={'account_number': DEPLOYMENT.broker_account_id})
        if path in ('/v2/orders', '/v2/positions'):
            return httpx.Response(200, json=[])
        raise AssertionError(f'unexpected private venue request {request.method} {path}')

    def order(self, key, asset, qty):
        return full_order(id='venue-' + asset, client_order_id=key, symbol=asset.removeprefix('asset-'),
                          asset_id=asset, side='sell', quantity=str(qty), submitted_at=self.now.isoformat())


def dispatch(conn, broker, commands, *, planned):
    with journal.writer_lock(conn, recovery_only=True):
        return asyncio.run(executor._dispatch_independent(conn, broker,
            [(command, planned, None, False) for command in commands], reserved=False))


def crash_worker(dsn, boundary):
    with psycopg.connect(dsn) as conn:
        dispatch(conn, PrivateVenue(dsn, boundary).broker(), SALES, planned=False)


@pytest.mark.skipif(not hasattr(signal, 'SIGKILL'), reason='requires native uncatchable process death')
@pytest.mark.parametrize('boundary', ['before', 'pending', 'accepted'])
def test_restart_after_concurrent_native_sale_death(database, pg, boundary, monkeypatch):
    for name, value in {**MARKET_ENV, 'SENTINEL_PAPER_BUY_POLICY': FRACTIONAL_MODE}.items():
        monkeypatch.setenv(name, value)
    schema.ensure_schema(database)
    # Intentionally allow duplicate POSTs so the final count can detect them.
    database.execute('CREATE TABLE private_venue_sales (client_key text, asset text, side text, quantity numeric)')
    database.commit()
    worker = multiprocessing.get_context('spawn').Process(target=crash_worker, args=(pg.sync_dsn, boundary))
    worker.start()
    try:
        worker.join(35)
        assert worker.exitcode == -signal.SIGKILL
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join(5)

    # A killed process exits before PostgreSQL necessarily reaps its old session.
    with psycopg.connect(pg.sync_dsn) as barrier:
        barrier.execute("SET LOCAL lock_timeout='8s'")
        barrier.execute('SELECT pg_advisory_xact_lock(%s)', (journal.WRITER_LOCK_KEY,))

    def durable():
        return {command.client_key: command for command in journal.load_commands(database, DEPLOYMENT)}

    first, sibling = (command.client_key for command in SALES)
    interrupted = durable()
    assert interrupted[first].state is (S.PLANNED if boundary == 'before' else S.SEND_PENDING)
    assert interrupted[sibling].state is S.PLANNED
    prior = database.execute('SELECT client_key FROM private_venue_sales').fetchall()
    assert prior == ([(first,)] if boundary == 'accepted' else [])
    database.rollback()

    venue = PrivateVenue(pg.sync_dsn)
    broker = venue.broker()
    def restart():
        asyncio.run(executor.resolve_outstanding(broker=broker, conn=database, deployment=DEPLOYMENT))

    restart()
    if boundary != 'before':
        assert durable()[first].state is S.UNKNOWN and venue.lookups == [first]
        venue.visible = True
        restart()
        assert durable()[first].state is (S.UNKNOWN if boundary == 'pending' else S.ACKNOWLEDGED)
        assert venue.lookups == [first, first]
    if boundary == 'pending':
        assert durable()[sibling].state is S.PLANNED
        assert database.execute('SELECT count(*) FROM private_venue_sales').fetchone() == (0,)
        return
    planned = [command for command in durable().values() if command.state is S.PLANNED]
    assert {c.client_key for c in planned} == ({first, sibling} if boundary == 'before' else {sibling})
    assert all(c.state is S.ACKNOWLEDGED for c in dispatch(database, broker, planned, planned=True))
    restart()
    assert {key: c.state for key, c in durable().items()} == {first: S.ACKNOWLEDGED, sibling: S.ACKNOWLEDGED}
    assert sorted(database.execute('SELECT client_key, asset, side, quantity FROM private_venue_sales').fetchall()) == sorted(
        (c.client_key, c.instrument.broker_id, 'sell', c.quantity) for c in SALES)
