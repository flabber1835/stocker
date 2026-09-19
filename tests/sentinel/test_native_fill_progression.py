"""Audit #399 F19 adjacent controls: legitimate partial-fill progression."""
from __future__ import annotations
import asyncio
from decimal import Decimal
import json
import psycopg
import pytest
from tests.support import native_fill_fixture as original
from sentinel.execution import journal, reconcile as R
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.automation import outbox
from tests.sentinel.test_rolling_snapshot_publisher import pg, conn


def test_six_then_four_shares_reconcile_and_notify_once_across_connections(conn):
    owner,command,broker,http,events=original.fixture(conn,native_quantities=('6','4'))
    order=http.routes['/v2/orders/order-1']
    order.update(status='partially_filled',filled_qty='6',filled_avg_price='100')
    http.routes['/v2/orders']=lambda p: [order] if p.get('status')=='open' else []
    http.routes['/v2/positions'][0]['qty']='6'
    http.routes['/v2beta1/events/activities']=original.Response(text=original.sse(events[0]))
    conn.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s WHERE id=1',(original.START,))
    conn.commit()
    for _ in range(2):
        result=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
        assert result.clean and result.runtime_state is RuntimeState.RUNNING,result.to_dict()
        assert result.expected==result.observed=={'SEC-AAPL':Decimal(6)}
        assert journal.load_commands(conn,owner.identity)[0].state is S.PARTIALLY_FILLED
        outbox._reconstruct_missing_transition_alerts(conn);conn.commit()
    assert conn.execute('SELECT SUM(quantity),COUNT(*) FROM sentinel_fills').fetchone()==(Decimal(6),1)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0]==1
    order.update(status='filled',filled_qty='10')
    http.routes['/v2/orders']=lambda p: [order] if p.get('status')=='closed' else []
    http.routes['/v2/positions'][0]['qty']='10'
    http.routes['/v2beta1/events/activities']=original.Response(text=original.sse(*events))
    for _ in range(2):
        with psycopg.connect(conn.info.dsn) as restarted:
            result=asyncio.run(R.reconcile(broker=broker,conn=restarted,binding=None,deployment=owner.identity))
            assert result.clean and result.runtime_state is RuntimeState.RUNNING,result.to_dict()
            assert result.expected==result.observed=={'SEC-AAPL':Decimal(10)}
            assert journal.load_commands(restarted,owner.identity)[0].state is S.FILLED
            outbox._reconstruct_missing_transition_alerts(restarted)
    assert conn.execute('SELECT SUM(quantity),SUM(quantity*price),COUNT(*) FROM sentinel_fills').fetchone()==(Decimal(10),Decimal(1000),2)
    alerts=conn.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchall()
    assert sorted(Decimal(p['quantity']) for (p,) in alerts)==[Decimal(4),Decimal(6)]
    assert not [call for call in http.calls if call[0]!='GET']
    print(json.dumps({'progression':[6,10],'native_total':10,'native_notional':1000,'retained_fill_rows':2,'ordinary_fill_alerts':2}))


__all__ = ['conn', 'pg']


@pytest.mark.parametrize('bad_price', ['200', '300'])
def test_partial_native_union_refuses_impossible_notional_and_recovers_after_restart(conn, monkeypatch, bad_price):
    from dataclasses import replace
    from fractions import Fraction

    owner, _, broker, http, events = original.fixture(conn, native_quantities=('3', '2', '5'))
    for event, price in zip(events, ('200', '100', '40'), strict=True):
        event.update(price=price, net_amount=str(-Decimal(event['qty']) * Decimal(price)))
    observe = broker._observe_snapshot
    complete = False

    async def history(**kwargs):
        return replace(await observe(**kwargs), fill_history_complete=complete)

    monkeypatch.setattr(broker, '_observe_snapshot', history)
    conn.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s WHERE id=1', (original.START,))
    conn.commit()
    http.routes['/v2beta1/events/activities'] = original.Response(text=original.sse(events[0]))
    first = asyncio.run(R.reconcile(broker=broker, conn=conn, binding=None, deployment=owner.identity))
    assert first.clean and first.runtime_state is RuntimeState.RUNNING
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    retained = conn.execute('SELECT fill_key,quantity,price FROM sentinel_fills').fetchall()
    count = conn.execute('SELECT count(*) FROM sentinel_observations').fetchone()[0]
    # Each response alone leaves positive residual gross. Together the first
    # five shares exhaust/exceed $1,000, leaving no positive price for the rest.
    assert 2 * Fraction(bad_price) < 1000
    assert (1000 - 3 * 200 - 2 * Fraction(bad_price)) / 5 <= 0
    bad = dict(events[1], price=bad_price, net_amount=str(-2 * Decimal(bad_price)))
    http.routes['/v2beta1/events/activities'] = original.Response(text=original.sse(bad))
    for _ in range(2):
        with psycopg.connect(conn.info.dsn) as restarted:
            result = asyncio.run(R.reconcile(broker=broker, conn=restarted, binding=None, deployment=owner.identity))
            assert result.runtime_state is RuntimeState.RECONCILING, result.to_dict()
            assert result.observation.terminal_recovery_through is None
            assert restarted.execute('SELECT fill_key,quantity,price FROM sentinel_fills').fetchall() == retained
            assert restarted.execute('SELECT count(*) FROM sentinel_observations').fetchone()[0] == count
            outbox._reconstruct_missing_transition_alerts(restarted)
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'native-fill-refusal:%'").fetchone()[0] >= 1
    conn.commit()
    complete = True
    http.routes['/v2beta1/events/activities'] = original.Response(text=original.sse(*events))
    for _ in range(2):
        with psycopg.connect(conn.info.dsn) as restarted:
            result = asyncio.run(R.reconcile(broker=broker, conn=restarted, binding=None, deployment=owner.identity))
            assert result.clean and result.runtime_state is RuntimeState.RUNNING, result.to_dict()
            outbox._reconstruct_missing_transition_alerts(restarted)
    assert conn.execute('SELECT SUM(quantity),SUM(quantity*price),COUNT(*) FROM sentinel_fills').fetchone() == (Decimal(10), Decimal(1000), 3)
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0] == 3
    assert all(method == 'GET' for method, *_ in http.calls)


@pytest.mark.parametrize('price,coherent', [
    ('499.9999999999999999999999999999', True),
    ('500', False),
    ('500.0000000000000000000000000001', False),
])
def test_partial_native_notional_comparison_is_exact_under_low_decimal_precision(price, coherent):
    from datetime import timedelta
    from decimal import localcontext
    from fractions import Fraction
    from sentinel.execution import fill_integrity
    from sentinel.execution.contract import BrokerFill, BrokerObservation, BrokerOrder, Side
    from sentinel.execution.identity import CommandIdentity, DeploymentIdentity

    instrument = original.INSTRUMENT
    key = CommandIdentity(DeploymentIdentity('partial', 'sim', 'account', 1), 'plan', instrument.security_id).client_key
    order = BrokerOrder('order', key, instrument, Side.BUY, S.FILLED,
                        Decimal(10), Decimal(10), Decimal(100), original.SUBMIT)
    fill = BrokerFill(key, 'order', Decimal(2), Decimal(price), original.FILL)
    observation = BrokerObservation(original.FILL + timedelta(seconds=1), orders=(order,), fills=(fill,))
    assert ((Fraction(1000) - 2 * Fraction(price)) / 8 > 0) is coherent
    with localcontext() as context:
        context.prec = 6
        if coherent:
            fill_integrity.validate(observation, {'order': order})
        else:
            with pytest.raises(ValueError, match='positive notional'):
                fill_integrity.validate(observation, {'order': order})
