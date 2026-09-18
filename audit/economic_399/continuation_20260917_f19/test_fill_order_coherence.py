"""Audit #399, pinned aff4461d: broker fill/order economic consistency.

Actual production AssetId adapter, HTTP parsing, observation, PostgreSQL journal,
strict recovery completion and outbox reconstruction. HTTP responses are local
fixtures. Real accounts and production source are never changed.
"""
from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
from sentinel import binding, schema
from sentinel.execution import journal, reconcile as R
from sentinel.execution.alpaca import strict_checkpoint
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.automation import outbox
from tests.conftest import isolated_image_backup_policy, isolated_source_cache
from tests.sentinel.test_alpaca_boundary_overlay import (
    Httpx, Response, account_payload, full_order, activity_event, sse,
    ACCOUNT_NUMBER, INSTRUMENT, PAPER,
)
from tests.sentinel.test_rolling_snapshot_publisher import pg, conn

UTC=timezone.utc
START=datetime(2026,8,19,16,tzinfo=UTC)
SUBMIT=datetime(2026,8,19,17,tzinfo=UTC)
FILL=datetime(2026,8,19,17,1,tzinfo=UTC)


def fixture(conn, *, native_quantities, fill_time=FILL):
    schema.ensure_schema(conn)
    owner=binding.bind(conn,deployment_id='audit399-fill-order-coherence',
                       broker='alpaca',broker_account_id=ACCOUNT_NUMBER)
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s WHERE id=1',(START,))
    command=Command(identity=CommandIdentity(owner.identity,'audited-ten-share-plan',INSTRUMENT.security_id),
                    instrument=INSTRUMENT, side=Side.BUY, quantity=Decimal(10))
    journal.save_command(conn,command)
    pending=command.transition(S.SEND_PENDING)
    journal.save_command(conn,pending,previous=S.PLANNED)
    ack=pending.transition(S.ACKNOWLEDGED,broker_order_id='order-1')
    journal.save_command(conn,ack,previous=S.SEND_PENDING)
    conn.execute('UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s',(SUBMIT,command.client_key))
    conn.commit()
    order=full_order(client_order_id=command.client_key,status='filled',qty='10',
                     filled_qty='10',filled_avg_price='100',submitted_at=SUBMIT.isoformat())
    events=[activity_event(event_id=f'01J5R0000000000000000{i:06d}',
                  ref_id=f'22222222-2222-2222-2222-{i:012d}',
                  at=fill_time.isoformat(),executed_at=fill_time.isoformat(),
                  activity_type='TRD',qty=str(q),price='100',net_amount=str(-Decimal(q)*100),
                  details={'execution_type':'fill','order_id':'order-1','client_order_id':command.client_key})
            for i,q in enumerate(native_quantities,1)]
    http=Httpx(routes={
        '/v2/account':account_payload(),
        '/v2/orders':lambda p:[order] if p.get('status')=='closed' else [],
        '/v2/positions':[{'symbol':'AAPL','asset_id':'asset-aapl','qty':'10'}],
        '/v2/orders/order-1':order,
        '/v2beta1/events/activities':Response(text=sse(*events)),
    })
    broker=AssetIdAlpacaExecutionBroker(api_key='local-audit-k',secret_key='local-audit-s',
        base_url=PAPER,resolve_security_id=lambda symbol,_as_of=None:f'SEC-{symbol}',
        http_provider=lambda:http)
    return owner,command,broker,http,events


@pytest.mark.parametrize('native_quantities', [('10',),('20',),('6','6')])
def test_native_fill_quantity_can_disagree_with_completed_order(conn,native_quantities):
    owner,command,broker,http,events=fixture(conn,native_quantities=native_quantities)
    expected_native=sum(map(Decimal,native_quantities))
    for i in range(2):
        result=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
        assert result.runtime_state is RuntimeState.RUNNING, result.to_dict()
        assert result.clean and result.expected==result.observed=={'SEC-AAPL':Decimal(10)}
        assert strict_checkpoint(conn)>SUBMIT
    retained=conn.execute('SELECT SUM(quantity),SUM(quantity*price),COUNT(*) FROM sentinel_fills').fetchone()
    assert retained==(expected_native,expected_native*100,len(native_quantities))
    current=journal.load_commands(conn,owner.identity)[0]
    assert (current.state,current.filled_quantity,current.filled_average_price)==(S.FILLED,Decimal(10),Decimal(100))
    # The normal notification enrollment boundary is controlled as predating the
    # synthetic fill. The production reconstruction and durable outbox run.
    conn.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s WHERE id=1',(START,))
    conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    rows=conn.execute("SELECT event_type,payload FROM sentinel_alert_outbox ORDER BY idempotency_key").fetchall()
    fills=[p for kind,p in rows if kind=='BROKER_FILL']
    assert len(fills)==len(native_quantities),rows
    assert sum(Decimal(p['quantity']) for p in fills)==expected_native
    assert not [kind for kind,p in rows if kind=='FILL_NOTIFICATION_IDENTITY_INVALID']
    assert not [c for c in http.calls if c[0]!='GET']
    print(json.dumps({'native_total':str(expected_native),'order_total':'10','order_notional':'1000',
      'native_notional':str(retained[1]),'runtime':result.runtime_state.value,'alerts':fills},default=str))


def test_impossible_fill_timestamp_precedes_order_and_is_accepted(conn):
    impossible=datetime(2026,8,19,16,30,tzinfo=UTC)
    owner,command,broker,http,events=fixture(conn,native_quantities=('10',),fill_time=impossible)
    result=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
    assert result.clean and result.runtime_state is RuntimeState.RUNNING,result.to_dict()
    assert conn.execute('SELECT filled_at FROM sentinel_fills').fetchone()[0]==impossible
    assert strict_checkpoint(conn)>SUBMIT


def test_corrected_native_quantity_cannot_replace_previously_accepted_wrong_quantity(conn):
    owner,command,broker,http,events=fixture(conn,native_quantities=('20',))
    first=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
    assert first.clean and first.runtime_state is RuntimeState.RUNNING
    events[0].update(qty='10',net_amount='-1000')
    http.routes['/v2beta1/events/activities']=Response(text=sse(*events))
    import psycopg
    with psycopg.connect(conn.info.dsn) as restarted:
        with pytest.raises(journal.FillEconomicsChanged):
            asyncio.run(R.reconcile(broker=broker,conn=restarted,binding=None,deployment=owner.identity))
    assert conn.execute('SELECT quantity,price FROM sentinel_fills').fetchone()==(Decimal(20),Decimal(100))
