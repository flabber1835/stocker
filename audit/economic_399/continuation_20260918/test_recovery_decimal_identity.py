"""Audit-only production-parser/reconcile/SQL witnesses on pinned aff4461d."""
from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest
from sentinel import binding, schema
from sentinel.execution import alpaca, journal, reconcile as R
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerPosition, Completeness, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S, RuntimeState
from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from tests.sentinel.test_alpaca_boundary_overlay import (
    adapter, full_order, DEPLOYMENT, INSTRUMENT,
)

@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres(); server.start()
    try: yield server
    finally: server.stop()

@pytest.fixture
def setup(pg):
    conn = psycopg.connect(pg.sync_dsn)
    drop_public_tables(conn); schema.ensure_schema(conn)
    bound = binding.bind(conn, **{k:v for k,v in DEPLOYMENT.to_dict().items() if k != 'takeover_epoch'})
    now = datetime.now(timezone.utc) + timedelta(seconds=2)
    broker, http = adapter()
    command = Command(identity=CommandIdentity(DEPLOYMENT,'audit-plan',INSTRUMENT.security_id,0),
        instrument=INSTRUMENT, side=Side.BUY, quantity=Decimal('10'),
        state=S.ACKNOWLEDGED, broker_order_id='order-1')
    journal.save_command(conn,command)
    try: yield conn,bound,now,broker,http,command
    finally: conn.close()

async def observe(conn,bound,now,broker,command,*,quantity,filled='0',position='0'):
    payload=full_order(client_order_id=command.client_key,qty=quantity,
        filled_qty=filled,filled_avg_price='100' if Decimal(filled) else None,
        status='filled' if Decimal(filled)==Decimal(quantity) else 'new',
        submitted_at=(now-timedelta(seconds=1)).isoformat())
    order=broker._to_order(payload)
    identity=await broker.identify_account()
    observation=alpaca.AccountBoundObservation(
        observed_at=now,started_at=now-timedelta(milliseconds=10),
        terminal_recovery_through=now,completeness=Completeness.COMPLETE,
        account_identity=identity,orders=(order,),
        positions=(BrokerPosition(INSTRUMENT,Decimal(position)),) if Decimal(position) else ())
    async def fixture_observation(**kwargs):return observation
    # Replace network observation acquisition only. Actual final adapter type,
    # wire-order parser, reconciliation, command writes and strict witness run.
    broker.observe_with_terminal_recovery=fixture_observation
    return await R.reconcile(broker=broker,conn=conn,binding=bound,deployment=DEPLOYMENT)

@pytest.mark.parametrize('stored,observed',[('10','10.0'),('10.0','10'),('10','10.000000')])
@pytest.mark.parametrize('filled',['0','10'])
def test_equivalent_quantity_encoding_refuses_strict_completion(setup,stored,observed,filled):
    conn,bound,now,broker,http,command=setup
    # Exercise both directions using normal SQL persistence of the same value.
    command=replace(command,quantity=Decimal(stored))
    conn.execute('DELETE FROM sentinel_command_events');conn.execute('DELETE FROM sentinel_commands');conn.commit()
    journal.save_command(conn,command)
    with pytest.raises(RuntimeError,match='terminal recovery cannot advance'):
        asyncio.run(observe(conn,bound,now,broker,command,quantity=observed,
            filled=filled,position=filled))
    durable=journal.load_commands(conn,DEPLOYMENT)[0]
    assert durable.quantity==Decimal(observed)==Decimal(10)
    assert durable.filled_quantity==Decimal(filled)
    assert durable.state==(S.FILLED if Decimal(filled) else S.ACKNOWLEDGED)
    assert alpaca.completion_proof(conn,now) is None
    assert conn.execute('SELECT count(*) FROM sentinel_terminal_recovery_watermark').fetchone()[0]==0
    assert conn.execute('SELECT runtime_state FROM sentinel_observations ORDER BY seq DESC LIMIT 1').fetchone()[0]=='RECONCILING'
    assert all(call[0]!='POST' for call in http.calls)

@pytest.mark.parametrize('quantity',['10','10.0','10.000000'])
def test_matching_decimal_encodings_complete_normally(setup,quantity):
    conn,bound,now,broker,http,command=setup
    command=replace(command,quantity=Decimal(quantity))
    conn.execute('DELETE FROM sentinel_command_events');conn.execute('DELETE FROM sentinel_commands');conn.commit()
    journal.save_command(conn,command)
    result=asyncio.run(observe(conn,bound,now,broker,command,quantity=quantity,filled='10',position='10'))
    assert result.runtime_state is RuntimeState.RUNNING
    assert result.clean
    assert alpaca.strict_checkpoint(conn)==now


def test_equal_filled_quantity_lexical_variants_do_not_renew_position_lag(setup):
    conn,bound,now,broker,http,command=setup
    first=asyncio.run(observe(conn,bound,now,broker,command,quantity='10',filled='0',position='1'))
    assert first.runtime_state is RuntimeState.RECONCILING
    conn.rollback()
    later=asyncio.run(observe(conn,bound,now+timedelta(seconds=121),broker,command,
        quantity='10',filled='0.00',position='1.000'))
    assert later.runtime_state is RuntimeState.FOREIGN_ACTIVITY
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-position-lag:v2:%'").fetchone()[0]==1
