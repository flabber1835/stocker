"""Real database contention at the known-cycle scheduler/health boundary."""
from datetime import timedelta

import psycopg
import pytest

from sentinel.automation import store, health
from sentinel.automation.model import CycleState, TickAction, StaleLeaderRefused
from sentinel.execution.journal import WRITER_LOCK_KEY
from tests.sentinel.test_automation_service import pg, conn, config, enable, service_for
from tests.sentinel.test_automation_generation import future_friday


@pytest.mark.asyncio
async def test_due_known_retry_progresses_under_financial_writer_and_falsifies_old_path(conn, pg, monkeypatch):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    timing, now = future_friday(conn, cfg)
    permit = store.acquire_lease(conn, holder_id=service.holder_id, lease_seconds=30)
    spec = service._spec(store.load_control(conn), timing)
    cycle = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                                   to_state=CycleState.REFRESHING_DATA)
    overdue = conn.execute('SELECT clock_timestamp()').fetchone()[0]-timedelta(minutes=1)
    conn.rollback()
    cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.RETRY_WAIT, next_wake_at=overdue, diagnostic={'retry_phase':'REFRESH'})
    store.register_instance(conn, instance_id=service.holder_id, state='WAITING', next_wake_at=overdue)
    owner = psycopg.connect(pg.sync_dsn)
    try:
        owner.execute('SELECT pg_advisory_lock(%s)', (WRITER_LOCK_KEY,));owner.commit()
        # Executed falsifier: the former creation-only path cannot service this
        # already-existing retry and health raises its overdue alarm.
        with monkeypatch.context() as broken:
            broken.setattr(store, '_existing_current_cycle', lambda *_a, **_kw: None)
            result = await service.tick(conn, now=now)
            assert result.action is TickAction.WAITING
            assert health.read_health(conn).scheduler_overdue
        result = await service.tick(conn, now=now)
        assert result.action is TickAction.REFRESHED
        assert result.cycle.cycle_id == cycle.cycle_id
        assert result.cycle.state is CycleState.PREPARING
        assert not health.read_health(conn).scheduler_overdue
        assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
        conn.rollback()
    finally:owner.close()


def test_known_cycle_read_still_refuses_a_revoked_leader(conn):
    cfg = config();enable(conn, cfg);service = service_for(cfg)
    timing, now = future_friday(conn, cfg)
    permit = store.acquire_lease(conn, holder_id=service.holder_id, lease_seconds=30)
    spec = service._spec(store.load_control(conn), timing)
    store.create_cycle(conn, permit=permit, spec=spec, now=now)
    store.engage_kill(conn, actor='qualification', reason='revoke the known reader')
    with pytest.raises(StaleLeaderRefused):
        store.create_cycle(conn, permit=permit, spec=spec, now=now)
