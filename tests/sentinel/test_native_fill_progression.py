"""Audit #399 F19 adjacent controls: legitimate partial-fill progression."""
from __future__ import annotations
import asyncio
from decimal import Decimal
import json
import psycopg
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
