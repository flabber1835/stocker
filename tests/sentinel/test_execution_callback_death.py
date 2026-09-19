"""Audit #399 F5 adjacency: abrupt callback death after durable broker acceptance.
Actual fork, SIGKILL, SQL command journal and deployed RecoveryAutomationService.
The external broker's acceptance survives in a separate audit-only SQL table.
No live broker or production source modification is used.
"""
import os
import signal
from decimal import Decimal
import pytest
from sentinel.automation import store, schedule
from sentinel.automation.model import AutomationConfig, ControlBinding, CycleState, TickAction
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.execution import journal, executor
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, CommandOutcome, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_service import conn, pg

@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['accepted_before_ack_commit', 'ack_committed_before_result'])
async def test_abrupt_child_death_retains_durable_recovery_wake(conn, pg, boundary):
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
    assert result.action is TickAction.RETRY_SCHEDULED
    assert result.cycle.state is CycleState.RECONCILING
    pending=journal.load_commands(conn,deployment)[0]
    expected=CommandState.SEND_PENDING if boundary=='accepted_before_ack_commit' else CommandState.ACKNOWLEDGED
    assert pending.state is expected
    assert result.cycle.next_wake_at is not None
    assert conn.execute('SELECT count(*) FROM audit_external_broker').fetchone()[0] == 1
    assert calls == []
__all__ = ['conn', 'pg']
