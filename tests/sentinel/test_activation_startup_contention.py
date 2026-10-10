"""Initial writer contention and retained diagnostics grant no trading authority."""
import asyncio
from datetime import datetime, timezone
import multiprocessing
from types import SimpleNamespace

import pytest

from sentinel.automation import store
from sentinel.automation.model import AutomationRefused, MissingAutomationState, TickAction
from sentinel.execution.journal import WRITER_LOCK_KEY, WriterLockUnavailable
from sentinel.automation.health import read_health
from sentinel.automation_runtime import ProductionAutomation
from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_service import (
    conn, pg, config, enable, service_for, binding, AFTER_WEDNESDAY_CLOSE)
from tests.sentinel.test_autonomous_deploy import deploy, _cfg, _health


def _hold_writer(dsn, channel, release):
    connection = feed_store.connect(dsn)
    try:
        assert connection.execute('SELECT pg_try_advisory_lock(%s)', (WRITER_LOCK_KEY,)).fetchone()[0]
        connection.commit()
        channel.send(True)
        assert release.wait(15), 'parent never released isolated writer'
    finally:
        connection.close()
        channel.close()


@pytest.fixture
def writer(pg):
    context = multiprocessing.get_context('fork')
    parent, child = context.Pipe(False)
    release = context.Event()
    process = context.Process(target=_hold_writer, args=(pg.sync_dsn, child, release))
    process.start()
    child.close()
    try:
        assert parent.poll(5) and parent.recv() is True
        yield release, process
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(2)
        parent.close()
        assert process.exitcode == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('release_before_next_tick', [False, True])
async def test_busy_writer_keeps_worker_and_waits_without_financial_work(
        conn, pg, writer, release_before_next_tick):
    cfg = config()
    now = datetime.now(timezone.utc)
    # Activation/control mutations are deliberately before the independent
    # writer, so this fixture does not bypass their strict refusal boundary.
    writer[0].set()
    writer[1].join(5)
    enable(conn, cfg)
    context = multiprocessing.get_context('fork')
    parent, child = context.Pipe(False)
    release = context.Event()
    owner = context.Process(target=_hold_writer, args=(pg.sync_dsn, child, release))
    owner.start()
    child.close()
    try:
        assert parent.poll(5) and parent.recv() is True
        service = service_for(cfg, holder='stable-startup-worker')
        first = await service.tick(conn, now=now)
        assert first.action is TickAction.WAITING
        assert first.permit is None and first.cycle is None
        assert 'writer lock is busy' in first.reason
        assert conn.info.transaction_status == 0
        assert store.latest_cycle(conn) is None
        assert conn.execute('SELECT holder_id,fence_token FROM sentinel_automation_lease').fetchone() == (None, 0)
        conn.rollback()

        async def sleep(_seconds):
            observed = conn.execute('SELECT state FROM sentinel_automation_service_instances WHERE instance_id=%s', (service.holder_id,)).fetchone()
            assert observed == ('WAITING',)
            assert store.latest_cycle(conn) is None
            conn.rollback()
            if release_before_next_tick:
                release.set()
                owner.join(5)
                assert owner.exitcode == 0

        await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
            clock=lambda: now, sleep=sleep, max_ticks=2)
        lease = conn.execute('SELECT holder_id,fence_token FROM sentinel_automation_lease').fetchone()
        if release_before_next_tick:
            assert lease == ('stable-startup-worker', 1)
            assert store.latest_cycle(conn) is not None
        else:
            assert lease == (None, 0)
            assert store.latest_cycle(conn) is None
        assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    finally:
        conn.rollback()
        release.set()
        owner.join(5)
        if owner.is_alive(): owner.kill(); owner.join(2)
        parent.close()
        assert owner.exitcode == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['missing_lease', 'foreign_live_leader', 'later_writer_failure'])
async def test_only_initial_writer_contention_is_a_wait(conn, monkeypatch, boundary):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    if boundary == 'missing_lease':
        conn.execute('DELETE FROM sentinel_automation_lease'); conn.commit()
        expected = MissingAutomationState
    elif boundary == 'foreign_live_leader':
        store.acquire_lease(conn, holder_id='foreign-live-leader', lease_seconds=cfg.lease_seconds)
        expected = AutomationRefused
    else:
        def refused(*args, **kwargs):
            raise WriterLockUnavailable('later financial boundary is never a startup wait')
        monkeypatch.setattr(store, 'create_cycle', refused)
        expected = WriterLockUnavailable
    with pytest.raises(expected):
        await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    conn.rollback()
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


@pytest.mark.parametrize('state,code', [
    ('SUPERSEDED', 'CONTROL_GENERATION_SUPERSEDED'),
    ('MISSED_STATE_ONLY', 'MISSED_EXECUTION_WINDOW'),
    ('RETRY_WAIT', 'SOURCE_DATA_PENDING'),
])
def test_retained_diagnostic_does_not_latch_readiness_or_heartbeat(
        tmp_path, monkeypatch, state, code):
    first = dict(_health(), latest_cycle_state=state, latest_failure_code=code)
    pending = dict(first, operational_ready=False, policy_state='AUTHORITY_UNVERIFIED')
    samples = iter([pending, first])
    clock = [0.0]
    obj = deploy.AutonomousDeploy(SimpleNamespace(health_timeout=30), SimpleNamespace(env={}), tmp_path)
    obj._automation_status = lambda **kwargs: next(samples)
    monkeypatch.setattr(deploy.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(deploy.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0]+delay))
    assert obj._wait_operational() == first
    second = dict(first, leader_heartbeat_at='2026-08-17T12:00:12+00:00')
    deploy.health_heartbeat_proof(first, second, cfg=_cfg(), certificate_sha256='c'*64)


def test_blocked_cycle_is_still_fatal_in_both_observers(tmp_path):
    blocked = dict(_health(), operational_ready=False, latest_cycle_state='BLOCKED',
        latest_failure_code='INTEGRITY_REFUSED')
    obj = deploy.AutonomousDeploy(SimpleNamespace(health_timeout=30), SimpleNamespace(env={}), tmp_path)
    obj._automation_status = lambda **kwargs: blocked
    with pytest.raises(deploy.DeployRefused, match='latched'):
        obj._wait_operational()
    blocked['operational_ready'] = True  # contradictory fixture cannot waive BLOCKED
    with pytest.raises(deploy.DeployRefused, match='latched'):
        obj._wait_operational()
    with pytest.raises(deploy.DeployRefused, match='latched'):
        deploy.health_heartbeat_proof(blocked, blocked, cfg=_cfg(), certificate_sha256='c'*64)


def test_historical_diagnostic_cannot_make_unready_worker_ready(tmp_path, monkeypatch):
    clock = [0.0]
    pending = dict(_health(), operational_ready=False, latest_cycle_state='SUPERSEDED',
        latest_failure_code='CONTROL_GENERATION_SUPERSEDED', policy_state='AUTHORITY_UNVERIFIED')
    obj = deploy.AutonomousDeploy(SimpleNamespace(health_timeout=9), SimpleNamespace(env={}), tmp_path)
    obj._automation_status = lambda **kwargs: pending
    monkeypatch.setattr(deploy.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(deploy.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0]+delay))
    with pytest.raises(deploy.ActivationPending, match='AUTHORITY_UNVERIFIED'):
        obj._wait_operational()
    assert clock[0] == 9


@pytest.mark.asyncio
async def test_retained_generation_first_tick_completes_actual_post_tick_hooks(conn, pg):
    """Real terminal/notifier/control loop; signed authority is a fixture seam.

    No certificate or broker is constructed. Terminal trial storage, outbox,
    cycle takeover, lease and service-instance rows use actual PostgreSQL.
    """
    cfg = config()
    now = datetime.now(timezone.utc)
    enable(conn, cfg)
    old = service_for(cfg)
    for _ in range(3):
        prepared = await old.tick(conn, now=now)
    prior = prepared.cycle
    store.engage_kill(conn, actor='fixture', reason='qualified software upgrade')
    store.deactivate(conn, actor='fixture', reason='preserve old cycle')
    enable(conn, cfg)
    runtime = object.__new__(ProductionAutomation)
    runtime.holder_id = 'new-generation-worker'
    runtime.automation_config = cfg

    def signed_fixture(connection, permit):
        store.require_leader(connection, permit)
        store.record_authority_verdict(connection, verdict='PASS',
            detail='explicit isolated signed-authority fixture boundary',
            holder_id=permit.holder_id, fence_token=permit.fence_token,
            control_generation=permit.control_generation, instance_id=runtime.holder_id)
        return store.load_control(connection), None

    runtime._assert_control_authority = signed_fixture
    service = service_for(cfg, holder=runtime.holder_id)
    service.terminal = runtime.certify_terminal_cycle
    service.notify = runtime.notify
    samples = []

    async def sleep(_seconds):
        observed = read_health(conn)
        assert observed.latest_failure_code == 'CONTROL_GENERATION_SUPERSEDED'
        assert observed.leader_holder == runtime.holder_id
        assert observed.service_heartbeat_fresh and observed.authority_verdict == 'PASS'
        samples.append(observed.model_dump(mode='json'))
        await asyncio.sleep(.01)

    assert await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
        clock=lambda: now, sleep=sleep, control_wake=runtime.control_wake, max_ticks=2) == 2
    samples.append(read_health(conn).model_dump(mode='json'))
    assert store.latest_cycle(conn).cycle_id == prior.cycle_id
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()
    # Isolate ONLY cryptographic lifecycle and externally enrolled identity.
    # Their own suites remain required; this test grants no real authority.
    expected = binding(cfg)
    host_config = SimpleNamespace(deployment_id=expected.deployment_id,
        account_id=expected.broker_account_id)
    for sample in samples:
        assert sample['policy_state'] == 'AUTHORITY_INVALID'
        assert sample['authority_lifecycle_current'] is False
        sample['authority_lifecycle_current'] = True
        sample['operational_ready'] = bool(sample['leader_active']
            and sample['service_heartbeat_fresh'] and not sample['scheduler_overdue'])
        assert sample['operational_ready'] is True
        sample['policy_state'] = 'LEADER_ACTIVE'
    deploy.health_heartbeat_proof(samples[0], samples[1], cfg=host_config,
        certificate_sha256=expected.certificate_sha256)


__all__ = ['conn', 'pg']
