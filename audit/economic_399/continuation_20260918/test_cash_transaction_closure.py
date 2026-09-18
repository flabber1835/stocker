"""Audit-only generic cash ledger transaction probes on unchanged aff4461d.
The accepted-SSE provider is a hypothetical controlled interface fixture. The
production adapter's F6/C1 capability restriction remains in force.
"""
from __future__ import annotations
import asyncio
import multiprocessing as mp
import os
import signal
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import psycopg
import pytest
from sentinel import binding, schema
from sentinel.core import cashflow
from sentinel.execution import broker_cash as C
from sentinel.execution.contract import Completeness
from tests.support.postgres import _EphemeralPostgres, drop_public_tables

ACCOUNT='audit-cash-account'
NOW=datetime(2026,9,17,20,tzinfo=timezone.utc)
EVENTS=tuple(C.BrokerCashActivity(f'native-{i}',kind,NOW.date(),D(amount),{})
    for i,(kind,amount) in enumerate((('CSD','1000'),('CSW','-250'),
        ('DIV','12.34'),('INT','0.67'),('FEE','-1.01'),('MA','2.00'))))

class AcceptedInterfaceFixture:
    financial_activity_sse=True
    def __init__(self,events=EVENTS):self.events=events
    async def account_cash_activities(self,*,after,through,since_event_id=None):
        return C.BrokerCashActivityBatch(self.events,through,Completeness.COMPLETE,
            self.events[-1].activity_id if self.events else None,'event-0001')

@pytest.fixture(scope='module')
def pg():
    server=_EphemeralPostgres();server.start()
    try:yield server
    finally:server.stop()

@pytest.fixture
def conn(pg):
    with psycopg.connect(pg.sync_dsn) as conn:
        drop_public_tables(conn);schema.ensure_schema(conn)
        binding.bind(conn,deployment_id='audit-cash-deployment',broker='alpaca',broker_account_id=ACCOUNT)
        conn.execute('UPDATE sentinel_account_binding SET established_at=%s WHERE id=1',(NOW-timedelta(days=1),));conn.commit()
        yield conn

def ingest(conn,events=EVENTS,through=NOW):
    return asyncio.run(C.ingest_account_cash(conn,broker_adapter=AcceptedInterfaceFixture(events),
        broker='alpaca',account_id=ACCOUNT,through=through))

def killed_publish(dsn,cut,with_baseline):
    conn=psycopg.connect(dsn)
    state=ingest(conn)
    if with_baseline:
        C.record_plan_baseline(conn,plan_id='audit-plan',decision_session=NOW.date(),activity_state=state)
    if cut=='before':os.kill(os.getpid(),signal.SIGKILL)
    conn.commit()
    os.kill(os.getpid(),signal.SIGKILL)

@pytest.mark.parametrize('cut',('before','after'))
@pytest.mark.parametrize('with_baseline',(False,True))
def test_cash_ledger_cursor_baseline_commit_is_atomic(conn,pg,cut,with_baseline):
    proc=mp.get_context('fork').Process(target=killed_publish,args=(pg.sync_dsn,cut,with_baseline))
    proc.start();proc.join(10)
    if proc.is_alive():proc.kill();proc.join();pytest.fail('audit child failed to finish')
    assert proc.exitcode==-signal.SIGKILL
    with psycopg.connect(pg.sync_dsn) as resumed:
        state=C.load_activity_state(resumed,broker='alpaca',account_id=ACCOUNT)
        baseline=C.load_plan_baseline(resumed,plan_id='audit-plan')
        rows=cashflow.flows_between(resumed,NOW.date(),NOW.date())
        if cut=='before':
            assert state is None and baseline is None and not rows
        else:
            assert len(rows)==6
            assert state.balance_total==D('764.00')
            assert state.last_activity_id=='native-5'
            assert (baseline is not None)==with_baseline
            if baseline:assert baseline.balance_total==state.balance_total
        # Replaying all native events and reconnecting cannot count money twice.
        replay=ingest(resumed,through=NOW+timedelta(seconds=1));resumed.commit()
        assert replay.balance_total==D('764.00')
        assert cashflow.net_external(resumed,NOW.date(),NOW.date())==D('750')
        assert cashflow.strategy_pl(resumed,start=NOW.date(),end=NOW.date(),opening_nav=D('10000'),closing_nav=D('10764'))==D('14')
        assert resumed.execute('SELECT count(*) FROM sentinel_cash_flows').fetchone()[0]==6


def test_changed_positive_activity_rolls_back_partial_new_batch(conn):
    prior=ingest(conn);conn.commit()
    new=C.BrokerCashActivity('new-native','DIV',NOW.date(),D('3'),{})
    corrupt=C.BrokerCashActivity('native-0','CSD',NOW.date(),D('1001'),{})
    with pytest.raises(C.BrokerCashAuthorityRefused,match='changed economics'):
        ingest(conn,(new,corrupt),NOW+timedelta(seconds=1))
    conn.rollback()
    assert C.load_activity_state(conn,broker='alpaca',account_id=ACCOUNT)==prior
    assert conn.execute('SELECT count(*) FROM sentinel_cash_flows').fetchone()[0]==6


def test_zero_replay_correction_is_ignored_by_generic_helper(conn):
    # Latent generic-only behavior: no accepted producer is deployed (C1/F6).
    prior=ingest(conn);conn.commit()
    zero=C.BrokerCashActivity('native-0','CSD',NOW.date(),D('0'),{})
    changed=ingest(conn,(zero,),NOW+timedelta(seconds=1));conn.commit()
    assert changed.balance_total==prior.balance_total==D('764')
    assert conn.execute('SELECT amount FROM sentinel_cash_flows WHERE flow_id=%s',
        (C.broker_flow_id(broker='alpaca',account_id=ACCOUNT,activity_id='native-0'),)).fetchone()[0]==D('1000')
    assert changed.processed_through>prior.processed_through
