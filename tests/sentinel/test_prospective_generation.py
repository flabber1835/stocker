"""Real PostgreSQL prospective upgrade obligations; no broker transport."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import pytest

from sentinel import schema
from sentinel.automation import integrity, schedule, store
from sentinel.automation.model import (
    AutomationRefused, CycleState,
    ProspectiveReplacementRefused, TickAction,
)
from sentinel.execution.journal import WRITER_LOCK_KEY, WriterLockUnavailable
from tests.sentinel.test_automation_service import (
    pg, conn, config, enable, service_for,
)


def future_friday(conn, cfg):
    today = conn.execute('SELECT clock_timestamp()').fetchone()[0].date()
    conn.rollback()
    friday = today + timedelta(days=7)
    while friday.weekday() != 4:
        friday += timedelta(days=1)
    timing = schedule.for_decision_session(friday, cfg)
    now = timing.decision_close_at + timedelta(hours=24)
    assert now < timing.execution_open_at
    return timing, now


def retained(conn, *, state=CycleState.PLAN_READY, historical=False, failure='CONTROL_GENERATION_SUPERSEDED'):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    timing, now = future_friday(conn, cfg)
    permit = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    old_spec = service._spec(store.load_control(conn), timing).model_copy(
        update={'historical_state_only': historical})
    cycle = store.create_cycle(conn, permit=permit, spec=old_spec)
    if state is not CycleState.DISCOVERED:
        for target in (CycleState.REFRESHING_DATA, CycleState.PREPARING, CycleState.PLAN_READY):
            cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=target, **({'plan_id': 'obsolete-plan'} if target is CycleState.PLAN_READY else {}))
        if state is CycleState.EXECUTING:
            cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=state)
    store.engage_kill(conn, actor='test', reason='reviewed upgrade')
    store.deactivate(conn, actor='test', reason='reviewed upgrade')
    enable(conn, cfg)
    current = store.load_control(conn)
    permit = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    retired_cycle = store.adopt_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.SUPERSEDED, failure_code=failure)
    spec = service._spec(current, timing)
    return service, retired_cycle, spec, permit, now


@pytest.mark.asyncio
async def test_upgrade_prepares_fresh_next_session_and_keeps_old_identity(conn):
    service, old, spec, permit, now = retained(conn)
    old_events = conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
        (old.cycle_id,)).fetchall()
    conn.rollback()
    fresh = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    assert fresh.cycle_id == spec.generation_cycle_id != old.cycle_id
    assert fresh.plan_id is None
    integrity.validate_cycle_lineage(conn, fresh)
    for _ in range(10):
        result = await service.tick(conn, now=now)
        assert result.action is not TickAction.EXECUTED
        if result.cycle and result.cycle.state is CycleState.WAITING_OPEN:
            break
    assert result.cycle.state is CycleState.WAITING_OPEN
    assert result.cycle.control_generation == spec.control_generation
    assert result.cycle.plan_id != 'obsolete-plan'
    assert result.cycle.effective_session.weekday() == 0
    restarted = service_for(config(), holder='worker-a')
    again = await restarted.tick(conn, now=now)
    assert again.cycle.cycle_id == fresh.cycle_id
    assert again.action is TickAction.WAITING
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
        (old.cycle_id,)).fetchall() == old_events


def test_repeated_upgrade_preserves_all_origins_and_uses_another_fresh_identity(conn):
    _, old, spec, permit, now = retained(conn)
    first = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    store.engage_kill(conn, actor='test', reason='another reviewed upgrade')
    store.deactivate(conn, actor='test', reason='another reviewed upgrade')
    cfg = config()
    enable(conn, cfg)
    permit = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    store.adopt_cycle(conn, permit=permit, cycle_id=first.cycle_id, to_state=CycleState.SUPERSEDED,
        failure_code='CONTROL_GENERATION_SUPERSEDED')
    spec = spec.model_copy(update={'control_generation': permit.control_generation})
    second = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    integrity.validate_cycle_lineage(conn, second)
    assert len({old.cycle_id, first.cycle_id, second.cycle_id}) == 3
    genesis = conn.execute('SELECT detail FROM sentinel_automation_cycle_events WHERE cycle_id=%s AND from_state IS NULL',
        (second.cycle_id,)).fetchone()[0]
    assert genesis['prospective_predecessors'] == sorted([old.cycle_id, first.cycle_id])
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()


def test_insert_rechecks_clock_even_when_preliminary_proof_was_eligible(conn, monkeypatch):
    _, old, spec, permit, now = retained(conn)
    clock = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    conn.rollback()
    delta = spec.execution_open_at-(clock-timedelta(seconds=1))
    late = spec.model_copy(update={name: getattr(spec,name)-delta for name in
        ('decision_close_at','prepare_at','execution_open_at','execute_at','execution_close_at')})
    monkeypatch.setattr(store, 'prospective_predecessors', lambda *a, **kw: [old.cycle_id])
    with pytest.raises(ProspectiveReplacementRefused, match='boundary changed'):
        store.create_cycle(conn, permit=permit, spec=late, now=now)
    assert conn.execute('SELECT count(*) FROM sentinel_automation_cycles').fetchone()[0] == 1
    conn.rollback()


def test_concurrent_creators_converge_and_database_enforces_one_per_generation(conn, pg):
    _, old, spec, permit, now = retained(conn)
    def create():
        other = psycopg.connect(pg.sync_dsn)
        try:
            try:
                return store.create_cycle(other, permit=permit, spec=spec, now=now).cycle_id
            except WriterLockUnavailable:
                return None
        finally:
            other.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda _: create(), range(2)))
    assert set(answers) <= {None, spec.generation_cycle_id}
    assert spec.generation_cycle_id in answers
    assert store.create_cycle(conn, permit=permit, spec=spec, now=now).cycle_id == spec.generation_cycle_id
    assert conn.execute('SELECT count(*) FROM sentinel_automation_cycles').fetchone()[0] == 2
    conn.rollback()
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO sentinel_automation_cycles SELECT 'other-id',state,decision_session,effective_session,"
            "deployment_id,broker,broker_account_id,takeover_epoch,control_generation,certificate_sha256,"
            "rollout_mode,rollout_version,config_sha256,decision_close_at,prepare_at,execution_open_at,execute_at,"
            "execution_close_at,historical_state_only,plan_id,data_version,publication_fingerprint,state_fingerprint,"
            "plan_fingerprint,last_clean_reconciliation_id,attempt_count,next_wake_at,last_fence_token,failure_code,"
            "failure_detail,diagnostic,created_at,updated_at,completed_at FROM sentinel_automation_cycles WHERE cycle_id=%s",
            (spec.generation_cycle_id,))
    conn.rollback()


@pytest.mark.parametrize('defect', ['scheduler_open', 'database_open', 'cutover_open', 'historical',
    'transport', 'other_terminal', 'command', 'wrong_certificate', 'wrong_account', 'wrong_epoch'])
def test_replacement_refuses_unsafe_or_late_obligations(conn, defect):
    _, old, spec, permit, now = retained(conn,
        state=(CycleState.EXECUTING if defect == 'transport' else
               CycleState.DISCOVERED if defect == 'historical' else CycleState.PLAN_READY),
        historical=defect == 'historical',
        failure='DISCOVERED_AFTER_SESSION_OPEN' if defect == 'other_terminal' else 'CONTROL_GENERATION_SUPERSEDED')
    if defect == 'scheduler_open':
        now = spec.execution_open_at
    elif defect == 'database_open':
        delta = spec.execution_open_at - (conn.execute('SELECT clock_timestamp()').fetchone()[0] - timedelta(seconds=1))
        spec = spec.model_copy(update={name: getattr(spec, name)-delta for name in
            ('decision_close_at','prepare_at','execution_open_at','execute_at','execution_close_at')})
        now = spec.execution_open_at-timedelta(seconds=1)
    elif defect == 'cutover_open':
        conn.execute('UPDATE sentinel_automation_control SET enabled_at=%s WHERE id=1', (spec.execution_open_at,))
        conn.commit()
    elif defect == 'command':
        conn.execute("INSERT INTO sentinel_commands (client_key,plan_id,security_id,deployment_id,broker,"
            "broker_account_id,takeover_epoch,symbol,side,quantity,state) VALUES ('old','obsolete-plan','sec',"
            "'sentinel-a','alpaca-paper','paper-account-1',1,'TEST','BUY',1,'UNKNOWN')")
        conn.commit()
    elif defect.startswith('wrong_'):
        key, value = {'wrong_certificate': ('certificate_sha256','e'*64),
            'wrong_account': ('broker_account_id','foreign'), 'wrong_epoch': ('takeover_epoch',2)}[defect]
        spec = spec.model_copy(update={key: value})
    with pytest.raises((ProspectiveReplacementRefused, AutomationRefused)):
        store.create_cycle(conn, permit=permit, spec=spec, now=now)
    assert conn.execute('SELECT count(*) FROM sentinel_automation_cycles').fetchone()[0] == 1
    conn.rollback()


def test_new_generation_and_genesis_cannot_hide_old_transport(conn):
    _, old, spec, permit, now = retained(conn)
    fresh = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    conn.execute("UPDATE sentinel_automation_cycle_events SET detail='{}'::jsonb WHERE cycle_id=%s AND from_state IS NULL",
        (fresh.cycle_id,))
    conn.commit()
    with pytest.raises(AutomationRefused, match='predecessors'):
        integrity.validate_cycle_lineage(conn, fresh)


def test_busy_canonical_writer_cannot_create_prospective_cycle(conn, pg):
    _, _, spec, permit, now = retained(conn)
    owner = psycopg.connect(pg.sync_dsn)
    try:
        owner.execute('SELECT pg_advisory_lock(%s)', (WRITER_LOCK_KEY,))
        owner.commit()
        with pytest.raises(WriterLockUnavailable):
            store.create_cycle(conn, permit=permit, spec=spec, now=now)
        assert conn.execute('SELECT count(*) FROM sentinel_automation_cycles').fetchone()[0] == 1
        conn.rollback()
    finally:
        owner.close()


def test_failure_after_scheduling_ownership_is_never_an_availability_wait(conn, monkeypatch):
    _, _, spec, permit, now = retained(conn)
    def later_failure(*a, **kw):
        raise WriterLockUnavailable('later financial owner failed')
    monkeypatch.setattr(store, '_create_cycle', later_failure)
    with pytest.raises(WriterLockUnavailable) as refused:
        store.create_cycle(conn, permit=permit, spec=spec, now=now)
    assert not isinstance(refused.value, store.CycleCreationBusy)


@pytest.mark.asyncio
async def test_actual_creation_entry_race_waits_then_resumes_without_a_financial_callback(conn, pg, monkeypatch):
    service, old, _, _, now = retained(conn)
    owner = psycopg.connect(pg.sync_dsn)
    acquire = store.acquire_lease
    held = False
    def race(*a, **kw):
        nonlocal held
        permit = acquire(*a, **kw)
        if not held:
            owner.execute('SELECT pg_advisory_lock(%s)', (WRITER_LOCK_KEY,))
            owner.commit()
            held = True
        return permit
    monkeypatch.setattr(store, 'acquire_lease', race)
    try:
        result = await service.tick(conn, now=now)
        assert result.action is TickAction.WAITING
        assert result.cycle is None
        assert 'before cycle creation' in result.reason
        assert conn.execute('SELECT count(*) FROM sentinel_automation_cycles').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
        conn.rollback()
    finally:
        owner.close()
    resumed = await service.tick(conn, now=now)
    assert resumed.cycle is not None and resumed.cycle.cycle_id != old.cycle_id


def old_catalog(conn):
    conn.execute('ALTER TABLE sentinel_automation_cycles DROP CONSTRAINT sentinel_automation_cycles_generation_key')
    conn.execute('ALTER TABLE sentinel_automation_cycles ADD UNIQUE '
        '(deployment_id,broker,broker_account_id,takeover_epoch,decision_session)')
    conn.commit()
    with conn.cursor() as cur:
        actual = schema._semantic_catalog_sha256(*schema._read_catalog(cur), schema._STAGE4_TABLES)
    conn.rollback()
    assert actual == schema._PRE_GENERATION_CATALOG_SHA256


def snapshot(conn):
    tables = ['sentinel_automation_control', 'sentinel_automation_lease', 'sentinel_automation_cycles',
        'sentinel_automation_cycle_events', 'sentinel_account_binding', 'sentinel_processed_sessions',
        'sentinel_commands','sentinel_command_events','sentinel_behavioral_schema_migrations']
    rows = {table: conn.execute('SELECT to_jsonb(t) FROM '+table+' t ORDER BY to_jsonb(t)::text').fetchall()
            for table in tables}
    conn.rollback()
    return rows


def test_exact_old_catalog_migrates_atomically_without_state_rewrites(conn):
    _, _, _, _, _ = retained(conn)
    store.engage_kill(conn, actor='test', reason='schema migration')
    old_catalog(conn)
    before = snapshot(conn)
    with pytest.raises(RuntimeError, match='fingerprint'):
        schema.require_runtime_schema(conn)
    schema.ensure_schema(conn)
    schema.require_runtime_schema(conn)
    assert snapshot(conn) == before
    schema.ensure_schema(conn)
    assert snapshot(conn) == before


@pytest.mark.parametrize('defect', ['active', 'live_fenced_leader', 'unknown_catalog', 'late_failure'])
def test_operational_migration_refuses_or_rolls_back_exactly(conn, monkeypatch, defect):
    cfg = config()
    enable(conn, cfg)
    if defect != 'active':
        store.engage_kill(conn, actor='test', reason='schema migration')
    if defect == 'live_fenced_leader':
        control = store.load_control(conn)
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='still-live',control_generation=%s,"
            "fence_token=1,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
            "expires_at=clock_timestamp()+interval '1 hour' WHERE id=1", (control.generation,))
        conn.commit()
    old_catalog(conn)
    if defect == 'unknown_catalog':
        conn.execute('ALTER TABLE sentinel_automation_cycles ADD COLUMN unknown_authority text')
        conn.commit()
    if defect == 'late_failure':
        monkeypatch.setattr(schema, '_STAGE4_CATALOG_SHA256', 'f'*64)
    before = snapshot(conn)
    with pytest.raises(RuntimeError):
        schema.ensure_schema(conn)
    assert snapshot(conn) == before
    with conn.cursor() as cur:
        catalog = schema._read_catalog(cur)
        unique = [item[0] for item in catalog[2]['sentinel_automation_cycles'] if item[1] == 'u']
    conn.rollback()
    assert unique != [schema._GENERATION_CYCLE_UNIQUE]
