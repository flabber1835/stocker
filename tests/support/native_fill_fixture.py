"""Local provider responses for native fill/order economic acceptance.

Actual production AssetId adapter, HTTP parsing, observation, PostgreSQL journal,
strict recovery completion and outbox reconstruction. HTTP responses are local
fixtures. The fixture alone enables the candidate producer for validation;
production capability flags remain unchanged.
"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from sentinel import binding, schema
from sentinel.execution import journal
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_alpaca_boundary_overlay import (
    Httpx, Response, account_payload, full_order, activity_event, sse,
    ACCOUNT_NUMBER, INSTRUMENT, PAPER,
)

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
                  details={'execution_type':'fill','order_id':'order-1','client_order_id':command.client_key,'asset_id':'asset-aapl','side':'buy'})
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
    broker.capabilities = replace(broker.capabilities, recent_fill_history=True)
    return owner,command,broker,http,events
