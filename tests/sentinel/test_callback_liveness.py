"""Real SQL/process acceptance for bounded work spanning the lease window."""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import sys
import time
from types import SimpleNamespace

import pytest

from sentinel import automation_liveness, automation_supervisor as supervisor, schema
from sentinel.automation import store
from sentinel.automation.health import read_health
from sentinel.automation.model import (
    AutomationConfig, CallbackDeadlineExceeded, CancellationAuthority,
    StaleLeaderRefused,
)
from sentinel.automation.service import AutomationService
from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_store import conn, pg, cycle_spec, enable
from tests.sentinel.test_autonomous_deploy import deploy


def authority(conn, cfg):
    """Health-only test authority rows; no signature/transport admission claim."""
    control = enable(conn, cfg)
    permit = store.acquire_lease(conn, holder_id='callback-worker', lease_seconds=cfg.lease_seconds)
    digest = control.certificate_sha256
    conn.execute("INSERT INTO sentinel_signed_execution_certificates "
        "(certificate_sha256,certificate_id,key_id,envelope_bytes,envelope,claims,"
        "issuer_generation,not_before,expires_at) VALUES (%s,'health','test',%s,'{}','{}',"
        "1,NOW()-INTERVAL '1 day',NOW()+INTERVAL '1 day')", (digest, b'test-only'))
    conn.execute("INSERT INTO sentinel_execution_certificate_lifecycle "
        "(certificate_sha256,status,activated_at) VALUES (%s,'ACTIVE',NOW())", (digest,))
    conn.execute("INSERT INTO sentinel_execution_authority_state "
        "(id,generation,highest_issuer_generation,active_certificate_sha256) VALUES (1,1,1,%s)", (digest,))
    conn.commit()
    store.record_authority_verdict(conn, verdict='PASS', detail='health fixture only',
        holder_id=permit.holder_id, fence_token=permit.fence_token,
        control_generation=permit.control_generation)
    return control, permit


def instance(conn):
    row = conn.execute("SELECT heartbeat_at,callback_started_at,callback_deadline_at "
        "FROM sentinel_automation_service_instances WHERE instance_id='callback-worker'").fetchone()
    conn.rollback()
    return row


def test_atomic_callback_renewal_keeps_invocation_boundary_and_due_cycle_healthy(conn):
    cfg = AutomationConfig(lease_seconds=30, heartbeat_seconds=1, callback_deadline_seconds=120)
    control, permit = authority(conn, cfg)
    store.create_cycle(conn, permit=permit, spec=cycle_spec(control, cfg))
    store.register_instance(conn, instance_id=permit.holder_id, state='PREPARE_CALLBACK',
                            callback_deadline_seconds=120)
    # Represent real work older than the lease; advance no production clock.
    conn.execute("UPDATE sentinel_automation_service_instances SET "
        "heartbeat_at=clock_timestamp()-INTERVAL '90 seconds',"
        "callback_started_at=clock_timestamp()-INTERVAL '90 seconds'")
    conn.commit()
    before = instance(conn)
    assert not read_health(conn).operational_ready
    store.heartbeat_lease(conn, permit=permit, lease_seconds=30, callback=True)
    after = instance(conn)
    assert after[0] > before[0] and after[1:] == before[1:]
    health = read_health(conn)
    assert health.operational_ready and health.service_heartbeat_fresh
    assert health.policy_state == 'LEADER_ACTIVE' and not health.scheduler_overdue
    assert health.callback_started_at == before[1]
    snapshot = supervisor._read_snapshot(conn.info.dsn, permit.holder_id)
    assert snapshot.invocation == before[1] and snapshot.callback_age_seconds >= 90
    watch = supervisor.CallbackWatch()
    assert not supervisor._callback_deadline_expired(watch, state=snapshot.state,
        now_monotonic=100, deadline_seconds=120,
        state_age_seconds=snapshot.callback_age_seconds, invocation=snapshot.invocation)
    store.heartbeat_lease(conn, permit=permit, lease_seconds=30, callback=True)
    renewed = supervisor._read_snapshot(conn.info.dsn, permit.holder_id)
    assert renewed.invocation == snapshot.invocation
    assert supervisor._callback_deadline_expired(watch, state=renewed.state,
        now_monotonic=131, deadline_seconds=120, state_age_seconds=0,
        invocation=renewed.invocation)


@pytest.mark.parametrize('damage', [
    'missing', 'expired', 'future_start', 'missing_start', 'missing_deadline',
    'changed', 'generation', 'token', 'lease',
])
def test_failed_callback_renewal_rolls_back_lease_and_instance(conn, damage):
    cfg = AutomationConfig()
    _control, permit = authority(conn, cfg)
    store.register_instance(conn, instance_id=permit.holder_id, state='REFRESH_CALLBACK',
                            callback_deadline_seconds=900)
    if damage == 'missing':
        conn.execute("DELETE FROM sentinel_automation_service_instances")
    elif damage == 'expired':
        conn.execute("UPDATE sentinel_automation_service_instances SET callback_deadline_at=clock_timestamp()-INTERVAL '1 second'")
    elif damage == 'future_start':
        conn.execute("UPDATE sentinel_automation_service_instances SET callback_started_at=clock_timestamp()+INTERVAL '1 minute'")
    elif damage == 'missing_start':
        conn.execute("UPDATE sentinel_automation_service_instances SET callback_started_at=NULL")
    elif damage == 'missing_deadline':
        conn.execute("UPDATE sentinel_automation_service_instances SET callback_deadline_at=NULL")
    elif damage == 'changed':
        store.register_instance(conn, instance_id=permit.holder_id, state='WAITING')
    elif damage == 'generation':
        store.engage_kill(conn, actor='test', reason='change authority')
    elif damage == 'token':
        permit = permit.model_copy(update={'fence_token': permit.fence_token + 1})
    elif damage == 'lease':
        conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-INTERVAL '1 second'")
    conn.commit()
    before = instance(conn)
    lease = conn.execute("SELECT heartbeat_at,expires_at FROM sentinel_automation_lease").fetchone()
    conn.rollback()
    with pytest.raises(StaleLeaderRefused):
        store.heartbeat_lease(conn, permit=permit, lease_seconds=45, callback=True)
    assert instance(conn) == before
    assert conn.execute("SELECT heartbeat_at,expires_at FROM sentinel_automation_lease").fetchone() == lease
    conn.rollback()
    if damage in {'expired', 'future_start', 'missing_start', 'missing_deadline'}:
        assert not read_health(conn).operational_ready
        assert read_health(conn).scheduler_overdue


def test_new_same_phase_invocation_and_normal_sleep_have_distinct_bounds(conn):
    store.register_instance(conn, instance_id='callback-worker', state='REFRESH_CALLBACK',
                            callback_deadline_seconds=900)
    before = instance(conn)
    store.register_instance(conn, instance_id='callback-worker', state='REFRESH_CALLBACK',
                            callback_deadline_seconds=900)
    assert instance(conn)[1] > before[1]
    store.register_instance(conn, instance_id='callback-worker', state='WAITING')
    assert instance(conn)[1:] == (None, None)
    with pytest.raises(ValueError):
        store.register_instance(conn, instance_id='callback-worker', state='REFRESH_CALLBACK')
    with pytest.raises(ValueError):
        store.register_instance(conn, instance_id='callback-worker', state='WAITING',
                                callback_deadline_seconds=900)


class Context:
    def __init__(self):
        self.cancellation = CancellationAuthority()
    def require_active(self):
        self.cancellation.require_active()


@pytest.mark.parametrize('phase', ['REFRESH', 'PREFLIGHT_RECOVER', 'PREPARE', 'RECOVER', 'EXECUTE'])
def test_real_callback_remains_healthy_beyond_lease_without_extending_deadline(
        conn, phase, monkeypatch, tmp_path):
    cfg = AutomationConfig(lease_seconds=3, heartbeat_seconds=1, callback_deadline_seconds=12)
    control, permit = authority(conn, cfg)
    # Isolated PostgreSQL, no broker/config/backup from the actual appliance.
    dsn = conn.info.dsn
    holder_file = tmp_path / 'holder'
    holder_file.write_text(permit.holder_id)
    monkeypatch.setattr(automation_liveness, 'HOLDER_FILE', holder_file)
    monkeypatch.setattr(automation_liveness.SentinelConfig, 'from_env',
        lambda: SimpleNamespace(database_url=dsn))
    monkeypatch.setattr(automation_liveness, 'config_from_env', lambda: cfg)
    process_context = multiprocessing.get_context('fork')
    release = process_context.Event()
    async def callback(_context):
        while not release.is_set():
            await asyncio.sleep(.02)
        return {'completed': phase}
    service = AutomationService(config=cfg, holder_id=permit.holder_id,
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    async def run():
        task = asyncio.create_task(service._invoke(callback, Context(), permit=permit,
            phase=phase, heartbeat_conn_factory=lambda: feed_store.connect(dsn)))
        try:
            deadline = time.monotonic() + 8
            while True:
                assert not task.done(), 'callback stopped before lease-spanning health evidence'
                snapshot = supervisor._read_snapshot(dsn, permit.holder_id)
                if snapshot.callback_age_seconds is not None and snapshot.callback_age_seconds > 4:
                    break
                assert time.monotonic() < deadline
                await asyncio.sleep(.05)
            assert snapshot.callback_remaining_seconds > 0
            health = read_health(conn)
            assert health.operational_ready and health.policy_state == 'LEADER_ACTIVE'
            assert health.service_heartbeat_fresh
            assert health.callback_started_at == snapshot.invocation
            assert automation_liveness.main() == 0
            first = health.model_dump(mode='json')
            await asyncio.sleep(1.2)
            second = read_health(conn).model_dump(mode='json')
            deploy.health_heartbeat_proof(first, second,
                cfg=SimpleNamespace(deployment_id=control.deployment_id,
                    account_id=control.broker_account_id),
                certificate_sha256=control.certificate_sha256)
        finally:
            release.set()
        assert await task == {'completed': phase}
    asyncio.run(run())
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()


def historical_callback_catalog(conn):
    conn.execute('ALTER TABLE sentinel_automation_service_instances DROP COLUMN callback_started_at')
    conn.execute('ALTER TABLE sentinel_automation_service_instances DROP COLUMN callback_deadline_at')
    conn.execute('ALTER TABLE sentinel_automation_cycles DROP CONSTRAINT sentinel_automation_cycles_generation_key')
    conn.execute('ALTER TABLE sentinel_automation_cycles ADD UNIQUE '
        '(deployment_id,broker,broker_account_id,takeover_epoch,decision_session)')
    conn.commit()
    # This is the independently pinned previous complete catalog, rather than
    # an invented partial schema combining old callbacks and the new cycle key.
    # No economic/authority columns are changed, and the historic pin stays fixed.
    with conn.cursor() as cur:
        catalog = schema._read_catalog(cur)
    assert schema._semantic_catalog_sha256(*catalog, schema._STAGE4_TABLES) == (
        '9d80e0801cf8c8e98b739e337eab3d883f3aac3495e47766b3214423ff90b7c1')
    conn.rollback()


def test_schema_upgrade_is_explicit_and_preserves_historical_instances(conn):
    store.register_instance(conn, instance_id='historical', state='STOPPED')
    before = conn.execute("SELECT instance_id,started_at,heartbeat_at,state FROM sentinel_automation_service_instances").fetchall()
    historical_callback_catalog(conn)
    with pytest.raises(Exception, match='callback'):
        schema.require_runtime_schema(conn)
    schema.ensure_schema(conn)
    assert conn.execute("SELECT instance_id,started_at,heartbeat_at,state FROM sentinel_automation_service_instances").fetchall() == before
    conn.rollback()
    schema.require_runtime_schema(conn)


@pytest.mark.parametrize('damage', ['active', 'live_leader', 'unknown_catalog', 'late_failure'])
def test_historical_callback_and_cycle_upgrade_refuses_and_rolls_back(conn, monkeypatch, damage):
    store.register_instance(conn, instance_id='historical', state='STOPPED')
    if damage == 'active':
        enable(conn, AutomationConfig())
    elif damage == 'live_leader':
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='live-historical',"
            "control_generation=(SELECT generation FROM sentinel_automation_control WHERE id=1),"
            "fence_token=1,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
            "expires_at=clock_timestamp()+interval '1 hour' WHERE id=1")
        conn.commit()
    historical_callback_catalog(conn)
    if damage == 'unknown_catalog':
        conn.execute('ALTER TABLE sentinel_automation_cycles ADD COLUMN unreviewed_authority text')
        conn.commit()
    elif damage == 'late_failure':
        monkeypatch.setattr(schema, '_STAGE4_CATALOG_SHA256', 'f'*64)
    with conn.cursor() as cur:
        before_catalog = schema._read_catalog(cur)
    tables = ('sentinel_automation_service_instances', 'sentinel_automation_control',
              'sentinel_automation_lease', 'sentinel_behavioral_schema_migrations')
    before_rows = {table: conn.execute('SELECT to_jsonb(t) FROM '+table+' t ORDER BY to_jsonb(t)::text').fetchall()
                   for table in tables}
    conn.rollback()
    with pytest.raises(schema.SchemaMigrationRefused):
        schema.ensure_schema(conn)
    with conn.cursor() as cur:
        assert schema._read_catalog(cur) == before_catalog
    assert {table: conn.execute('SELECT to_jsonb(t) FROM '+table+' t ORDER BY to_jsonb(t)::text').fetchall()
            for table in tables} == before_rows
    conn.rollback()


@pytest.mark.parametrize('failure', ['deadline', 'lost_instance'])
def test_real_callback_expiry_or_lost_liveness_terminates_and_reaps_child(conn, failure):
    cfg = AutomationConfig(lease_seconds=3, heartbeat_seconds=1, callback_deadline_seconds=5)
    _control, permit = authority(conn, cfg)
    dsn = conn.info.dsn
    child_pid = multiprocessing.get_context('fork').Value('i', 0)
    async def callback(_context):
        child_pid.value = os.getpid()
        time.sleep(30)  # Even an event-loop-blocking callback is disposable.
    service = AutomationService(config=cfg, holder_id=permit.holder_id,
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    context = Context()
    async def run():
        task = asyncio.create_task(service._invoke(callback, context, permit=permit,
            phase='PREPARE', heartbeat_conn_factory=lambda: feed_store.connect(dsn)))
        if failure == 'lost_instance':
            limit = time.monotonic() + 4
            while not child_pid.value:
                assert not task.done() and time.monotonic() < limit
                await asyncio.sleep(.02)
            conn.execute('DELETE FROM sentinel_automation_service_instances')
            conn.commit()
        with pytest.raises((CallbackDeadlineExceeded, StaleLeaderRefused)):
            await asyncio.wait_for(task, timeout=12)
    asyncio.run(run())
    assert context.cancellation.cancelled and child_pid.value > 0
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid.value, 0)
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()


def test_independent_supervisor_reaps_worker_despite_continuing_callback_heartbeats(
        conn, monkeypatch, tmp_path):
    cfg = AutomationConfig(lease_seconds=3, heartbeat_seconds=1, callback_deadline_seconds=5)
    authority(conn, cfg)
    # Release only this test's setup permit so the dedicated child may acquire
    # a lease under its actual supervised holder id.
    conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-INTERVAL '1 second'")
    conn.commit()
    dsn = conn.info.dsn
    code = '''import sys,time
from sentinel.automation import store
from sentinel.feed import store as feed
c=feed.connect(sys.argv[1]);p=store.acquire_lease(c,holder_id=sys.argv[2],lease_seconds=3)
store.register_instance(c,instance_id=p.holder_id,state='PREPARE_CALLBACK',callback_deadline_seconds=30)
while True:
 time.sleep(.5);p=store.heartbeat_lease(c,permit=p,lease_seconds=3,callback=True)
'''
    children = []
    actual_spawn = supervisor._spawn
    def spawn(holder):
        if children:
            raise StopIteration('one worker reaped before replacement')
        child = actual_spawn(holder, command=(sys.executable, '-c', code, dsn, holder))
        children.append(child)
        return child
    monkeypatch.setattr(supervisor, '_spawn', spawn)
    monkeypatch.setattr(supervisor, 'HOLDER_FILE', tmp_path / 'supervised-holder')
    monkeypatch.setattr(supervisor.SentinelConfig, 'from_env', lambda: SimpleNamespace(database_url=dsn))
    monkeypatch.setattr(supervisor, 'config_from_env', lambda: cfg)
    monkeypatch.setattr(supervisor.signal, 'signal', lambda *_: None)
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS', '.1')
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS', '2')
    actual_sleep = time.sleep
    start = time.monotonic()
    def bounded_sleep(seconds):
        assert time.monotonic() - start < 12, 'renewed heartbeat postponed the hard callback watchdog'
        actual_sleep(seconds)
    monkeypatch.setattr(supervisor.time, 'sleep', bounded_sleep)
    try:
        with pytest.raises(StopIteration, match='reaped before replacement'):
            supervisor.main()
        assert children[0].poll() is not None
        holder = (tmp_path / 'supervised-holder').read_text().strip()
        heartbeat, started = conn.execute("SELECT heartbeat_at,callback_started_at "
            "FROM sentinel_automation_service_instances WHERE instance_id=%s", (holder,)).fetchone()
        assert (heartbeat - started).total_seconds() > cfg.lease_seconds
        conn.rollback()
    finally:
        for child in children:
            if child.poll() is None:
                supervisor._terminate(child)


__all__ = ['conn', 'pg']
