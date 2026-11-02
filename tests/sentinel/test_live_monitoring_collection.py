"""Private PostgreSQL + mock native GETs -> exact LIVE display/alert receipts."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from sentinel import binding
from sentinel.automation import outbox
from sentinel.execution import account_status, fill_notifications, journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, OrderTerms, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S
from sentinel.execution.trading_readonly import MonitoringReadRefused
from sentinel.authority import repository
from sentinel.authority.model import AuthorityRefused
from sentinel.feed import store
from tests.sentinel.test_live_monitoring import monitoring, reader
from tests.sentinel.test_notification_recovery import db, historical_db
from tests.sentinel.test_operator_monitoring import issue369_pg

ORDER = '22222222-2222-4222-8222-222222222222'
ASSET = '33333333-3333-4333-8333-333333333333'


def bound(db, f):
    binding.bind(db, deployment_id=f.owner.deployment_id, broker='alpaca-live',
                 broker_account_id=f.subject.account_id)


def test_live_account_receipt_is_native_bound_and_retains_actual_namespace(db, tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    bound(db, f)
    assert asyncio.run(account_status.collect(db, config=f.config, reader=reader(f)))
    rows = db.execute('SELECT broker,broker_account_id,cash,flags FROM sentinel_broker_account_evidence').fetchall()
    assert len(rows) == 1 and rows[0][:3] == ('alpaca-live', f.subject.account_id, D('1000'))
    assert account_status.RESERVATION_FLAG not in rows[0][3]
    assert db.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    assert [path for _, path, _ in f.calls] == ['/v2/account', '/v2/account']


def test_real_public_loader_rechecks_actual_private_database_before_each_get(db, tmp_path, monkeypatch):
    actual_require, actual_rollout = binding.require, repository.load_rollout_state
    f = monitoring(tmp_path, monkeypatch)
    # Retain real signature/public-file validation and actual DB-backed context
    # providers. Only runtime identities and native HTTP are offline fixtures.
    monkeypatch.setattr(binding, 'require', actual_require)
    monkeypatch.setattr(repository, 'load_rollout_state', actual_rollout)
    f.config = replace(f.config, database_url=db.info.dsn)
    bound(db, f)
    def connect(*args, **kwargs):
        conn = store.connect(*args, **kwargs)
        f.connections.append(conn)
        return conn
    f.factory = connect
    r = reader(f)
    assert asyncio.run(account_status.collect(db, config=f.config, reader=r))
    assert all(conn.closed for conn in f.connections)
    assert len(f.calls) == 2
    db.execute('UPDATE sentinel_account_binding SET takeover_epoch=2 WHERE id=1')
    db.commit()
    with pytest.raises(AuthorityRefused):
        asyncio.run(r.identify_account())
    assert len(f.calls) == 2


def test_live_account_cannot_use_plain_reader_or_paper_binding(db, tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    bound(db, f)
    with pytest.raises(MonitoringReadRefused, match='authenticated GET-only'):
        asyncio.run(account_status.collect(db, config=f.config, reader=SimpleNamespace()))
    db.execute("UPDATE sentinel_account_binding SET broker='alpaca' WHERE id=1")
    db.commit()
    with pytest.raises(MonitoringReadRefused, match='alpaca-live binding'):
        asyncio.run(account_status.collect(db, config=f.config, reader=reader(f)))
    assert not f.calls
    assert db.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone()[0] == 0


def fill_fixture(db, tmp_path, monkeypatch):
    f = monitoring(tmp_path, monkeypatch)
    bound(db, f)
    submitted, filled = f.now - timedelta(minutes=20), f.now - timedelta(minutes=19)
    monkeypatch.setenv(fill_notifications.SINCE_ENV, (f.now - timedelta(hours=1)).isoformat())
    db.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s', (f.now-timedelta(days=1),))
    command = Command(CommandIdentity(f.owner.identity, 'plan', 'SEC-BIL'),
        BrokerInstrument('SEC-BIL', 'BIL', ASSET), Side.BUY, D('2'), order_terms=OrderTerms('limit', 'day', D('101')))
    journal.save_command(db, command)
    pending = command.transition(S.SEND_PENDING)
    journal.save_command(db, pending, previous=S.PLANNED)
    ack = pending.transition(S.ACKNOWLEDGED, broker_order_id=ORDER)
    journal.save_command(db, ack, previous=S.SEND_PENDING)
    journal.save_command(db, replace(ack, state=S.FILLED, filled_quantity=D('2'),
        filled_average_price=D('100')), previous=S.ACKNOWLEDGED)
    db.execute('UPDATE sentinel_commands SET created_at=%s', (submitted,))
    db.commit()
    f.order = dict(id=ORDER, client_order_id=command.client_key, asset_id=ASSET, symbol='BIL',
        side='buy', qty='2', filled_qty='2', filled_avg_price='100', type='limit', time_in_force='day',
        limit_price='101', order_class='simple', extended_hours=False, status='filled',
        submitted_at=submitted.isoformat(), filled_at=filled.isoformat())
    f.activities = [dict(id='20261022094100000::1', activity_type='FILL', order_id=ORDER,
        transaction_time=filled.isoformat(), type='fill', price='100', qty='2', side='buy', symbol='BIL')]
    def handle(request):
        assert request.method == 'GET'
        assert all(conn.closed for conn in f.connections)
        f.calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == '/v2/account':
            data = f.account
        elif request.url.path == '/v2/orders/' + ORDER:
            data = f.order
        elif request.url.path == '/v2/account/activities/FILL':
            assert request.url.params['order_id'] == ORDER
            data = f.activities
        else:
            raise AssertionError(request.url)
        return httpx.Response(200, json=deepcopy(data))
    f.provider = SimpleNamespace(AsyncClient=lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handle), **kwargs))
    return f


def test_live_native_fill_has_truthful_scope_and_preserves_paper_history(db, tmp_path, monkeypatch):
    f = fill_fixture(db, tmp_path, monkeypatch)
    outbox.enqueue(db, idempotency_key='retained-paper', event_type='BROKER_FILL', severity='TRADE',
                   payload={'scope': 'original-paper'})
    r = reader(f)
    assert asyncio.run(fill_notifications.collect(db, config=f.config, reader=r, now=f.now)) == 1
    rows = db.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL' ORDER BY created_at").fetchall()
    assert rows[0][0] == {'scope': 'original-paper'}
    payload = rows[1][0]
    assert (payload['environment'], payload['base_url'], payload['broker']) == (
        'ALPACA_LIVE', f.subject.base_url, 'alpaca-live')
    assert payload['native_account_id'] == f.subject.account_id
    assert payload['notification_only'] is True
    assert [path for _, path, _ in f.calls] == [
        '/v2/account', '/v2/orders/'+ORDER, '/v2/account/activities/FILL', '/v2/account']
    assert db.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 0
    assert asyncio.run(fill_notifications.collect(db, config=f.config, reader=r, now=f.now)) == 0


def test_live_average_order_without_native_activities_never_invents_a_fill(db, tmp_path, monkeypatch):
    f = fill_fixture(db, tmp_path, monkeypatch)
    f.activities = []
    assert asyncio.run(fill_notifications.collect(db, config=f.config, reader=reader(f), now=f.now)) == 0
    assert db.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0] == 0
