"""Isolated generic cash-contract probes; no deployed adapter capability promotion."""
from __future__ import annotations
import asyncio
import os
import signal
import traceback
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import psycopg
import pytest

from sentinel import binding, schema
from sentinel.core import cashflow
from sentinel.execution import broker_cash as cash, journal
from sentinel.execution.contract import Completeness
from sentinel.execution.plan import ExecutionPlan
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401

DAY = date(2026, 9, 14)
UPPER = datetime(2026, 9, 14, 20, tzinfo=timezone.utc)
ACCOUNT = 'PA-AUDIT-CASH'
EVENTS = tuple(cash.BrokerCashActivity(f'cash-{i}', kind, DAY, D(amount), {})
    for i, (kind, amount) in enumerate([
        ('CSD', '100'), ('CSW', '-40'), ('DIV', '12'),
        ('FEE', '-2'), ('INT', '0.5'), ('SPLIT', '0')], 1))

class TypedSource:
    # Exercises the generic accepted-input branch. The deployed Alpaca class
    # remains unchanged and advertises this capability as false.
    financial_activity_sse = True
    def __init__(self, events=EVENTS, complete=Completeness.COMPLETE, event_id='000006'):
        self.events, self.complete, self.event_id = events, complete, event_id
    async def account_cash_activities(self, *, after, through, since_event_id=None):
        return cash.BrokerCashActivityBatch(self.events, through, self.complete,
            self.events[-1].activity_id if self.events else None, self.event_id)

@pytest.fixture
def cash_conn(conn):
    schema.ensure_schema(conn)
    binding.bind(conn, deployment_id='cash-commit-audit', broker='alpaca', broker_account_id=ACCOUNT)
    conn.execute('UPDATE sentinel_account_binding SET established_at=%s',
                 (UPPER - timedelta(days=1),))
    conn.commit()
    return conn


def ingest(conn, source=None, upper=UPPER):
    return asyncio.run(cash.ingest_account_cash(conn, broker_adapter=source or TypedSource(),
        broker='alpaca', account_id=ACCOUNT, through=upper))


def kill_here():
    os.kill(os.getpid(), signal.SIGKILL)
    raise AssertionError('SIGKILL returned')


def fork_kill(conn, work):
    dsn = conn.info.dsn
    conn.commit()
    pid = os.fork()
    if pid == 0:
        try:
            with psycopg.connect(dsn) as fresh:
                work(fresh)
        except BaseException:
            traceback.print_exc()
            os._exit(41)
        os._exit(42)
    child, status = os.waitpid(pid, 0)
    assert child == pid and os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL


def assert_cash_oracle(conn):
    rows = cashflow.flows_between(conn, DAY, DAY)
    assert len(rows) == 5  # A zero-valued SPLIT has no cash entitlement.
    assert sum((row.amount for row in rows), D(0)) == D('70.5')
    assert cashflow.net_external(conn, DAY, DAY) == D('60')
    assert cashflow.strategy_pl(conn, start=DAY, end=DAY,
        opening_nav=D(1000), closing_nav=D('1070.5')) == D('10.5')
    state = cash.load_activity_state(conn, broker='alpaca', account_id=ACCOUNT)
    assert state.balance_total == D('70.5')
    assert state.last_activity_id == 'cash-5'
    assert state.last_event_id == '000006'
    return state


@pytest.mark.parametrize('boundary', ['first_row', 'last_row', 'cursor', 'commit'])
def test_activity_rows_and_cursor_converge_after_actual_sigkill(cash_conn, boundary):
    def work(c):
        original = cash._insert_activity
        def insert(*args, **kwargs):
            result = original(*args, **kwargs)
            native_id = kwargs['activity'].activity_id
            if ((boundary == 'first_row' and native_id == 'cash-1') or
                    (boundary == 'last_row' and native_id == 'cash-6')):
                kill_here()
            return result
        cash._insert_activity = insert
        with journal.writer_lock(c):
            ingest(c)
            if boundary == 'cursor':
                kill_here()
            c.commit()
            kill_here()
    fork_kill(cash_conn, work)
    with psycopg.connect(cash_conn.info.dsn) as c:
        if boundary == 'commit':
            assert_cash_oracle(c)
        else:
            assert cash.load_activity_state(c, broker='alpaca', account_id=ACCOUNT) is None
            assert not cashflow.flows_between(c, DAY, DAY)
        # Replayed complete native evidence converges through three intervals.
        for offset in (1, 2, 3):
            with journal.writer_lock(c):
                ingest(c, upper=UPPER + timedelta(seconds=offset))
            assert_cash_oracle(c)


@pytest.mark.parametrize('boundary', ['plan', 'baseline', 'commit'])
def test_plan_and_cash_baseline_share_one_commit(cash_conn, boundary):
    with journal.writer_lock(cash_conn):
        state = ingest(cash_conn)
    plan = ExecutionPlan(plan_id='cash-plan', decision_session=DAY,
        effective_session=DAY + timedelta(days=1), data_version=1,
        target_exposure=D(1), target_basket={'AAA': D(10)},
        account_nav=D('1070.5'), account_cash=D('1070.5'))
    def work(c):
        with journal.writer_lock(c):
            journal.save_plan(c, plan, commit=False)
            if boundary == 'plan':
                kill_here()
            cash.record_plan_baseline(c, plan_id=plan.plan_id,
                decision_session=DAY, activity_state=state)
            if boundary == 'baseline':
                kill_here()
            c.commit()
            kill_here()
    fork_kill(cash_conn, work)
    with psycopg.connect(cash_conn.info.dsn) as c:
        stored_plan = journal.load_plan(c, plan.plan_id)
        stored_baseline = cash.load_plan_baseline(c, plan_id=plan.plan_id)
        assert (stored_plan is not None) == (boundary == 'commit')
        assert (stored_baseline is not None) == (boundary == 'commit')
        with journal.writer_lock(c):
            journal.save_plan(c, plan, commit=False)
            baseline = cash.record_plan_baseline(c, plan_id=plan.plan_id,
                decision_session=DAY, activity_state=state)
        assert journal.load_plan(c, plan.plan_id).fingerprint() == plan.fingerprint()
        assert baseline.balance_total == D('70.5')
        assert baseline.activity_identity_authoritative
        assert not baseline.close_cash_finality_authoritative
        with pytest.raises(cash.BrokerCashAuthorityRefused, match='immutable'):
            with journal.writer_lock(c):
                cash.record_plan_baseline(c, plan_id=plan.plan_id,
                    decision_session=DAY, activity_state=replace(state, balance_total=D('71.5')))
        assert cash.load_plan_baseline(c, plan_id=plan.plan_id) == baseline
        assert_cash_oracle(c)


@pytest.mark.parametrize('fault', ['amount', 'classification', 'date', 'duplicate',
    'incomplete', 'event_regression', 'clock_regression', 'downgrade'])
def test_contradictory_or_incomplete_replay_rolls_back(cash_conn, fault):
    with journal.writer_lock(cash_conn):
        original = ingest(cash_conn)
    source = TypedSource()
    upper = UPPER + timedelta(seconds=1)
    if fault in ('amount', 'classification', 'date'):
        changes = {'amount': {'net_amount': D(101)},
                   'classification': {'activity_type': 'DIV'},
                   'date': {'activity_date': DAY - timedelta(days=1)}}[fault]
        source.events = (replace(EVENTS[0], **changes),) + EVENTS[1:]
    elif fault == 'duplicate':
        source.events = EVENTS + (EVENTS[0],)
    elif fault == 'incomplete':
        source.complete = Completeness.TRUNCATED
    elif fault == 'event_regression':
        source.event_id = '000001'
    elif fault == 'clock_regression':
        upper = UPPER - timedelta(seconds=1)
    elif fault == 'downgrade':
        source.financial_activity_sse = False
    with pytest.raises(cash.BrokerCashAuthorityRefused):
        with journal.writer_lock(cash_conn):
            ingest(cash_conn, source, upper)
    assert cash.load_activity_state(cash_conn, broker='alpaca', account_id=ACCOUNT) == original
    assert_cash_oracle(cash_conn)
