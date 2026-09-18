"""Audit #399 F5 adjacency: abrupt callback death after durable broker acceptance.
Actual fork, SIGKILL, SQL command journal and deployed RecoveryAutomationService.
The external broker's acceptance survives in a separate audit-only SQL table.
No live broker or production source modification is used.
"""
import os
import signal
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sentinel.automation import store, schedule
from sentinel.automation.model import AutomationConfig, ControlBinding, CycleState, TickAction, CycleContext
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.execution import journal, executor
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, CommandOutcome, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store

@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['accepted_before_ack_commit', 'ack_committed_before_result'])
async def test_abrupt_child_death_blocks_a_still_live_order(conn, pg, boundary):
    cfg = AutomationConfig(lease_seconds=30, heartbeat_seconds=5,
        callback_deadline_seconds=10, maximum_clock_skew_seconds=10_000_000)
    binding = ControlBinding(deployment_id='audit399', broker='alpaca-paper',
        broker_account_id='audit-paper', takeover_epoch=1, certificate_sha256='d'*64,
        rollout_mode='PINNED_1_00', rollout_version=1, config_sha256=cfg.fingerprint)
    store.activate(conn, binding=binding, actor='audit', reason='synthetic activation')
    control=store.release_kill(conn, expected_binding=binding, actor='audit', reason='fixture')
    permit=store.acquire_lease(conn, holder_id='audit-worker', lease_seconds=30)
    calls=[]
    async def unused(ctx):
        calls.append('unexpected_callback')
        raise AssertionError('blocked cycle should expose the lost recovery obligation')
    timing=schedule.for_decision_session('2026-09-16', cfg)
    with conn.cursor() as cur:
        cur.execute('CREATE TABLE audit_external_broker(client_key TEXT PRIMARY KEY, state TEXT, cash NUMERIC, shares NUMERIC)')
    conn.commit()
    deployment=DeploymentIdentity('audit399','alpaca-paper','audit-paper',1)
    command=Command(identity=CommandIdentity(deployment,'audit-plan','SEC-AAA',0),
        instrument=BrokerInstrument('SEC-AAA','AAA','asset-AAA'),side=Side.BUY,quantity=Decimal('1'))
    dsn=pg.sync_dsn
    async def callback(ctx):
        c=feed_store.connect(dsn)
        class ExternalBroker:
            async def submit(self, **kw):
                with c.cursor() as cur:
                    cur.execute('INSERT INTO audit_external_broker VALUES (%s,%s,%s,%s)',
                        (kw['client_key'],'ACKNOWLEDGED',Decimal('1000'),Decimal('0')))
                c.commit()
                if boundary=='accepted_before_ack_commit':
                    os.kill(os.getpid(),signal.SIGKILL)
                return CommandOutcome(CommandState.ACKNOWLEDGED, broker_order_id='external-1')
        with journal.writer_lock(c):
            await executor._persist_and_send(c,ExternalBroker(),command)
        os.kill(os.getpid(),signal.SIGKILL)
    svc=RecoveryAutomationService(config=cfg,holder_id='audit-worker',
        refresh=unused,prepare=unused,recover=unused,execute=callback)
    cycle=store.create_cycle(conn,permit=permit,spec=svc._spec(control,timing))
    for state in [CycleState.PREPARING, CycleState.PLAN_READY, CycleState.EXECUTING]:
        kwargs={'plan_id':'audit-plan','plan_fingerprint':'f'*64} if state is CycleState.PLAN_READY else {}
        cycle=store.transition_cycle(conn,permit=permit,cycle_id=cycle.cycle_id,to_state=state,**kwargs)
    result=await svc._run_execute(conn,now=timing.execute_at,cycle=cycle,permit=permit,
        heartbeat_conn_factory=lambda:feed_store.connect(dsn))
    assert result.action is TickAction.BLOCKED
    assert result.cycle.state is CycleState.BLOCKED
    pending=journal.load_commands(conn,deployment)[0]
    expected=CommandState.SEND_PENDING if boundary=='accepted_before_ack_commit' else CommandState.ACKNOWLEDGED
    assert pending.state is expected
    # External acceptance settles after the callback and after the cycle was blocked.
    with conn.cursor() as cur:
        cur.execute("UPDATE audit_external_broker SET state='FILLED',cash=900,shares=1")
    conn.commit()
    for elapsed in [1,5,30]:
        result=await svc.tick(conn,now=timing.execute_at+timedelta(days=elapsed))
        assert result.action is TickAction.BLOCKED
    assert calls==[]
    unchanged=journal.load_commands(conn,deployment)[0]
    assert unchanged.state is expected and unchanged.filled_quantity==0
    with conn.cursor() as cur:
        cur.execute('SELECT state,cash,shares FROM audit_external_broker')
        assert cur.fetchone()==('FILLED',Decimal('900'),Decimal('1'))
    print({'boundary':boundary,'cycle':result.cycle.state.value,'durable_command':unchanged.state.value,
           'durable_fill':str(unchanged.filled_quantity),'external_shares':'1','external_cash':'900',
           'later_recovery_calls':len(calls),'failure':result.cycle.failure_code})
