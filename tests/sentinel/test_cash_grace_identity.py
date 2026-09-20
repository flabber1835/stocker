"""Audit-only SQL/crash and Decimal spelling witnesses for account-lag authority."""
import asyncio
import os
import signal
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import pytest
from sentinel.execution import alpaca, broker_cash, journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerObservation, BrokerInstrument, Side
from sentinel.execution.identity import DeploymentIdentity, CommandIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store
from sentinel.paper import cash
from sentinel.paper.model import PaperActivationRefused, PaperRetryableRefused

from tests.sentinel.test_journal_and_reconcile import conn, pg

T0 = datetime(2026,9,17,13,31,tzinfo=timezone.utc)
DEP = DeploymentIdentity('audit399','alpaca','audit-paper',1)
INST = BrokerInstrument('SEC-AAA','AAA','asset-AAA')
IDENTITY = BrokerAccountIdentity('alpaca','audit-paper')

def setup_plan(conn, *, side=Side.BUY, price=D(100)):
    p=ExecutionPlan('cash-audit-plan',date(2026,9,16),date(2026,9,17),D(1),
        target_basket={'SEC-AAA':D(1)},deployment_id=DEP.deployment_id,broker=DEP.broker,
        broker_account_id=DEP.broker_account_id,takeover_epoch=DEP.takeover_epoch,
        account_nav=D(1000),account_cash=D(1000))
    cmd=Command(CommandIdentity(DEP,p.plan_id,'SEC-AAA',0),INST,side,D(1),
        state=CommandState.FILLED,broker_order_id='accepted-1',filled_quantity=D(1),
        filled_average_price=price)
    journal.save_command(conn,cmd)
    return p

def observation(qty='1', when=T0):
    # Actual production position parser; only the HTTP fetch is a local fixture.
    broker=alpaca.FinancialGradeAlpacaExecutionBroker(api_key='audit',secret_key='audit',
        base_url='https://paper-api.alpaca.markets',resolve_security_id=lambda _: 'SEC-AAA')
    async def get(_): return [{'symbol':'AAA','asset_id':'asset-AAA','qty':qty}]
    broker._get=get
    positions=asyncio.run(broker._list_positions())
    return BrokerObservation(observed_at=when,orders=(),positions=tuple(positions),account_identity=IDENTITY)

def account(value='1000'):
    return BrokerAccountSnapshot(identity=IDENTITY,equity=D(1100),cash=D(value),
        buying_power=D(value),multiplier=D(1),status='ACTIVE')

def check(conn,p,when,qty='1',value='1000',**extra):
    return cash._cash_authority_or_refuse(conn,plan=p,deployment=DEP,account=account(value),
        observation=observation(qty,when),endpoint_lag_observed_at=when,**extra)

def count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'broker-account-lag:v1:%'")
        return cur.fetchone()[0]

def test_changed_cash_does_not_renew_durable_grace(conn,pg):
    p=setup_plan(conn)
    for seconds,value in [(0,'1000'),(119,'999')]:
        with pytest.raises(PaperRetryableRefused): check(conn,p,T0+timedelta(seconds=seconds),value=value)
        conn.rollback()
    c=feed_store.connect(pg.sync_dsn)
    try:
        with pytest.raises(PaperActivationRefused) as caught:
            check(c,p,T0+timedelta(seconds=121),value='998')
        assert not isinstance(caught.value,PaperRetryableRefused)
        assert count(c)==1
    finally: c.close()

@pytest.mark.parametrize('boundary',['before_commit','after_commit'])
def test_process_death_at_first_seen_commit(conn,pg,boundary):
    p=setup_plan(conn)
    pid=os.fork()
    if pid==0:
        c=feed_store.connect(pg.sync_dsn)
        class KillAtCommit:
            def __getattr__(self,name): return getattr(c,name)
            def commit(self):
                if boundary=='after_commit': c.commit()
                os.kill(os.getpid(),signal.SIGKILL)
        check(KillAtCommit(),p,T0)
        os._exit(100)
    _,status=os.waitpid(pid,0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
    c=feed_store.connect(pg.sync_dsn)
    try:
        assert count(c)==(1 if boundary=='after_commit' else 0)
        with pytest.raises(PaperActivationRefused) as caught:
            check(c,p,T0+timedelta(seconds=121))
        assert isinstance(caught.value,PaperRetryableRefused)==(boundary=='before_commit')
        assert count(c)==1
    finally: c.close()

def test_same_numeric_position_spelling_never_renews_grace(conn,pg):
    p = setup_plan(conn)
    with pytest.raises(PaperRetryableRefused):
        check(conn,p,T0,qty='1')
    conn.rollback()
    for seconds, spelling in [(121,'1.0'),(238,'1.00'),(357,'1.000')]:
        with feed_store.connect(pg.sync_dsn) as restarted:
            with pytest.raises(PaperActivationRefused) as caught:
                check(restarted,p,T0+timedelta(seconds=seconds),qty=spelling)
            assert not isinstance(caught.value, PaperRetryableRefused)
            assert count(restarted) == 1

def test_offsetting_new_activity_set_is_not_execution_permission(conn):
    p=setup_plan(conn)
    state=broker_cash.CashActivityState('alpaca','audit-paper',T0,'first',D(20),
        last_event_id='001',activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    broker_cash.record_plan_baseline(conn,plan_id=p.plan_id,decision_session=p.decision_session,activity_state=state)
    conn.commit()
    later=replace(state,last_activity_id='offsetting-second',last_event_id='003',processed_through=T0+timedelta(seconds=1))
    with pytest.raises(PaperActivationRefused,match='event set is durably explained'):
        check(conn,p,T0+timedelta(seconds=1),value='900',activity_state=later)
    assert count(conn)==0
    check(conn,p,T0+timedelta(seconds=1),value='900',activity_state=later,permit_new_activity=True)

__all__ = ['conn', 'pg']


@pytest.mark.parametrize('precision', [6, 28])
@pytest.mark.parametrize('side', [Side.BUY, Side.SELL])
@pytest.mark.parametrize('offset,accepted', [('0.999', True), ('1', True), ('1.001', False)])
def test_cash_tolerance_is_exact_after_restart(conn, pg, precision, side, offset, accepted):
    from decimal import localcontext

    # Both ordinary and sub-context prices are legal persisted broker values.
    price = D('100.00000000000000000000000001')
    p = setup_plan(conn, side=side, price=price)
    conn.commit()
    # Independent decimal oracle: inputs and expected balance are computed at
    # 100 digits before entering the deliberately restricted caller context.
    with localcontext() as context:
        context.prec = 100
        expected = D(1000) + (price if side is Side.SELL else -price)
        observed = expected + D(offset)
    snapshot = account(str(observed))
    book = observation()
    with feed_store.connect(pg.sync_dsn) as restarted, localcontext() as context:
        context.prec = precision
        if accepted:
            cash._cash_authority_or_refuse(restarted, plan=p, deployment=DEP,
                                          account=snapshot, observation=book)
        else:
            with pytest.raises(PaperActivationRefused, match='not explained'):
                cash._cash_authority_or_refuse(restarted, plan=p, deployment=DEP,
                                              account=snapshot, observation=book)


def test_default_precision_cannot_admit_cash_just_outside_tolerance(conn, pg):
    p = setup_plan(conn)
    command = journal.load_commands(conn, DEP, plan_id=p.plan_id)[0]
    journal.save_command(conn, replace(command,
        filled_average_price=D('100.000000000000000000000000000001')))
    conn.commit()
    # Integer-scaled oracle: expected=900-10^-30, so 901 differs by 1+10^-30.
    assert 901 * 10**30 - (900 * 10**30 - 1) > 10**30
    with feed_store.connect(pg.sync_dsn) as restarted:
        with pytest.raises(PaperActivationRefused, match='not explained'):
            cash._cash_authority_or_refuse(restarted, plan=p, deployment=DEP,
                                          account=account('901'), observation=observation())


def test_activity_delta_cannot_round_cash_into_tolerance(conn, pg):
    p = setup_plan(conn)
    state = broker_cash.CashActivityState('alpaca', 'audit-paper', T0, 'first', D(0),
        last_event_id='001', activity_identity_scheme=broker_cash.ACTIVITY_IDENTITY_SCHEME)
    broker_cash.record_plan_baseline(conn, plan_id=p.plan_id,
                                    decision_session=p.decision_session, activity_state=state)
    conn.commit()
    later = replace(state, balance_total=D('0.00000000000000000000000001'),
                    last_activity_id='second', last_event_id='002')
    # Cash must be 900+10^-26. Observed 899 is outside the unchanged $1 bound.
    with feed_store.connect(pg.sync_dsn) as restarted:
        with pytest.raises(PaperActivationRefused, match='not explained'):
            cash._cash_authority_or_refuse(restarted, plan=p, deployment=DEP,
                account=account('899'), observation=observation(), activity_state=later,
                permit_new_activity=True)


def test_changed_decimal_context_cannot_renew_cash_grace(conn, pg):
    from decimal import localcontext

    p = setup_plan(conn, price=D('100.0004'))
    with localcontext() as context:
        context.prec = 6
        with pytest.raises(PaperRetryableRefused):
            check(conn, p, T0)
    conn.rollback()
    with feed_store.connect(pg.sync_dsn) as restarted:
        with pytest.raises(PaperActivationRefused) as caught:
            check(restarted, p, T0 + timedelta(seconds=121))
        assert not isinstance(caught.value, PaperRetryableRefused)
        assert count(restarted) == 1
        retained = restarted.execute("SELECT state FROM sentinel_processed_sessions "
            "WHERE cursor_name LIKE 'broker-account-lag:v1:%'").fetchone()[0]
        assert retained['expected_cash'] == '899.9996'
