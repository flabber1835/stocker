"""Exercise the production backup callback and the persisted PREPARE retry."""
import psycopg
import pytest

from sentinel import backup_continuity, backup_integrity_reuse, backup_runtime_authority, local_paper
from sentinel.automation.model import CycleState, TickAction
from sentinel.automation_recovery import ProductionAutomation
from tests.sentinel.test_automation_service import (
    AFTER_WEDNESDAY_CLOSE, config, conn, enable, pg, service_for,
)


async def assert_durable_backup_refusal(conn, monkeypatch, *, enter_absence_probe=False):
    cfg = config()
    enable(conn, cfg)
    monkeypatch.setattr(local_paper, 'backups_suspended_for_account', lambda _conn: False)
    monkeypatch.setattr(backup_continuity, 'selected', lambda: True)
    monkeypatch.setattr(backup_integrity_reuse, 'selected', lambda: True)
    backup_connections = []

    def strict_proof(backup_conn, *, operation):
        backup_connections.append(backup_conn)
        try:
            with backup_integrity_reuse.owner(
                    backup_conn, system_id='1', base='base-20261110T000000Z',
                    start='000000010000000000000001', segment_size=16 * 1024**2):
                pytest.fail('the second session acquired the common owner')
        except backup_runtime_authority.BackupIntegrityBusy as exc:
            if enter_absence_probe:
                raise backup_runtime_authority.BackupRuntimeUnavailable(str(exc)) from exc
            raise

    monkeypatch.setattr(backup_runtime_authority, '_require', strict_proof)
    fallback_calls = []
    def unexpected_fallback(*args, **kwargs):
        fallback_calls.append(True)
        raise backup_continuity.MediaAbsenceUnproven('private mounted media')
    monkeypatch.setattr(backup_continuity, 'degraded', unexpected_fallback)
    runtime = object.__new__(ProductionAutomation)
    runtime.connect = lambda: psycopg.connect(conn.info.dsn)

    def prepare(_context):
        runtime._require_backup_for_new_mutation('prepare fixture')
        pytest.fail('a refused backup proof authorized preparation')

    service = service_for(cfg, prepare=prepare)
    assert (await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.RECOVERED
    assert (await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.REFRESHED
    with psycopg.connect(conn.info.dsn, autocommit=True) as owner:
        owner.execute('SELECT pg_advisory_lock(%s)', (backup_integrity_reuse.LOCK_KEY,))
        result = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
        assert owner.execute('SELECT pg_advisory_unlock(%s)', (
            backup_integrity_reuse.LOCK_KEY,)).fetchone() == (True,)

    assert result.action is TickAction.RETRY_SCHEDULED
    assert result.cycle.state is CycleState.RETRY_WAIT
    assert result.cycle.diagnostic['failure_domain'] == 'BACKUP'
    assert result.cycle.diagnostic['retry_phase'] == 'PREPARE'
    assert result.cycle.plan_id is None
    assert not fallback_calls, 'owner contention ran the media absence probe'
    assert len(backup_connections) == 1 and backup_connections[0].closed
    state, detail = conn.execute(
        'SELECT to_state,detail FROM sentinel_automation_cycle_events '
        'WHERE cycle_id=%s ORDER BY seq DESC LIMIT 1', (result.cycle.cycle_id,),
    ).fetchone()
    assert state == 'RETRY_WAIT'
    assert detail['failure_detail'] == result.cycle.failure_detail
    assert 'PROOF_OWNER_BUSY' in detail['failure_detail'], 'lost strict proof owner reason'
    assert 'MEDIA_ABSENCE_UNPROVEN' not in detail['failure_detail']


@pytest.mark.asyncio
async def test_prepare_persists_strict_backup_reason_without_absence_probe(conn, monkeypatch):
    await assert_durable_backup_refusal(conn, monkeypatch)


@pytest.mark.asyncio
async def test_ordinary_absence_fallback_fails_busy_oracle(conn, monkeypatch):
    with pytest.raises(AssertionError, match='owner contention ran the media absence probe'):
        await assert_durable_backup_refusal(conn, monkeypatch, enter_absence_probe=True)
