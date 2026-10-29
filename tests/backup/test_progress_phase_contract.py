"""Join actual maintenance progress writes to the real PostgreSQL guard."""
import json
import time

import psycopg
import pytest
from psycopg.types.json import Jsonb

from sentinel import schema
from tests.support.postgres import _EphemeralPostgres
from tests.backup.test_recurring_maintenance import boundary, coordinator


@pytest.fixture
def database():
    server = _EphemeralPostgres()
    try:
        server.start()
        with psycopg.connect(server.sync_dsn) as conn:
            schema.ensure_schema(conn)
            yield conn
    finally:
        server.stop()


def test_native_renewal_progress_uses_real_guard(database, boundary):
    before = 'base-20260918T120000Z'
    after = boundary.name
    boundary.name, boundary.old = before, True
    def runner(argv, **kwargs):
        if argv[:2] == ['bash','scripts/sentinel-base-backup.sh']:
            boundary.name = after
        if 'psql' in argv and "SELECT 'MAINTENANCE_PROGRESS'" in argv[-1]:
            proof = database.execute(argv[-1]).fetchone()[0]
            database.commit()
            return proof
        return boundary(argv, **kwargs)
    assert coordinator.tick('/media',runner)['retention_ready'] is True
    rows = database.execute("SELECT proof FROM sentinel_backup_evidence WHERE kind='MAINTENANCE_PROGRESS' ORDER BY seq").fetchall()
    assert [r[0]['phase'] for r in rows] == ['BASE_BACKUP','VERIFY_CHAIN','COMPLETE']
    assert [r[0]['base_backup'] for r in rows] == [before,after,after]
    assert len({(r[0]['attempt'],r[0]['started_at'],r[0]['deadline']) for r in rows}) == 1
    assert not any(a[:2]==['bash','scripts/sentinel-restore-drill.sh'] for a in boundary.calls)


def test_failed_progress_publication_keeps_last_committed_base(database, boundary):
    before, after = 'base-20260918T120000Z', boundary.name
    boundary.name, boundary.old = before, True
    def runner(argv, **kwargs):
        if argv[:2] == ['bash','scripts/sentinel-base-backup.sh']:
            boundary.name = after
        if 'psql' in argv and "SELECT 'MAINTENANCE_PROGRESS'" in argv[-1]:
            if '"phase":"VERIFY_CHAIN"' in argv[-1]:
                raise coordinator.Refused('injected progress publication refused')
            proof=database.execute(argv[-1]).fetchone()[0]
            database.commit()
            return proof
        return boundary(argv, **kwargs)
    with pytest.raises(coordinator.Refused,match='injected progress publication'):
        coordinator.tick('/media',runner)
    rows=database.execute("SELECT proof FROM sentinel_backup_evidence WHERE kind='MAINTENANCE_PROGRESS' ORDER BY seq").fetchall()
    assert [r[0]['phase'] for r in rows] == ['BASE_BACKUP','FAILED']
    assert all(r[0]['base_backup']==before for r in rows)


def test_explicit_migration_preserves_rows_and_runtime_does_not_migrate(database):
    for statement in schema._BACKUP_PROGRESS_V1_DDL[2:]:
        database.execute(statement)
    database.execute("INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof) VALUES ('BASE_BACKUP',%s,%s)",('a'*64,Jsonb({'retained':'unchanged'})))
    database.commit()
    control=database.execute('SELECT * FROM sentinel_automation_control').fetchall()
    ledger=database.execute('SELECT * FROM sentinel_behavioral_schema_migrations ORDER BY version').fetchall()
    evidence=database.execute('SELECT * FROM sentinel_backup_evidence ORDER BY seq').fetchall()
    database.rollback()
    database.execute("UPDATE sentinel_automation_control SET enabled=true,kill_switch_engaged=false,"
        " deployment_id='diagnostic',broker='alpaca-paper',broker_account_id='diagnostic',"
        " takeover_epoch=1,certificate_sha256=%s,rollout_mode='PINNED_1_00',rollout_version=1,config_sha256=%s"
        " WHERE id=1",('f'*64,'c'*64))
    with pytest.raises(schema.SchemaMigrationRefused,match='requires fenced'):
        schema.ensure_schema(database)
    assert database.execute('SELECT * FROM sentinel_automation_control').fetchall()==control
    database.rollback()
    with pytest.raises(schema.SchemaMigrationRefused):
        schema.require_runtime_schema(database)
    schema.ensure_schema(database)
    schema.require_runtime_schema(database)
    assert database.execute('SELECT * FROM sentinel_automation_control').fetchall()==control
    assert database.execute('SELECT * FROM sentinel_behavioral_schema_migrations ORDER BY version').fetchall()==ledger
    assert database.execute('SELECT * FROM sentinel_backup_evidence ORDER BY seq').fetchall()==evidence


def test_progress_guard_retains_deadline_identity_and_terminal_falsifier(database):
    proof=dict(schema='sentinel.backup-maintenance-progress/1',attempt='a'*32,
        started_at=1,deadline=3601,image='sha256:'+'a'*64,system_identifier='123',
        predecessor_base='base-20261028T000000Z',base_backup='base-20261028T000000Z',phase='BASE_BACKUP')
    def append(value):
        database.execute("INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof) VALUES ('MAINTENANCE_PROGRESS',%s,%s)",('b'*64,Jsonb(value)))
    append(proof)
    database.commit()
    for field,value in [('deadline',3602),('started_at',2),('image','sha256:'+'c'*64),
            ('system_identifier','456'),('predecessor_base','foreign'),('phase','COMPLETE')]:
        bad=dict(proof,phase='VERIFY_CHAIN')
        bad[field]=value
        with pytest.raises(psycopg.errors.RaiseException):
            append(bad)
        database.rollback()
    successor=dict(proof,phase='VERIFY_CHAIN',base_backup='base-20261029T000000Z')
    append(successor)
    append(dict(successor,phase='COMPLETE'))
    database.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        append(dict(successor,phase='FAILED'))
    database.rollback()
    bad=dict(successor,deadline=3602)
    # Removing the real guard admits the very mutation the test rejects.
    database.execute('DROP TRIGGER sentinel_backup_progress_guard ON sentinel_backup_evidence')
    append(bad)
    database.rollback()


def test_archive_frontier_hint_reads_real_statistics_without_a_copy():
    import sentinel_activation_checkpoint as checkpoint
    import sentinel_backup_maintenance as maintenance
    server=_EphemeralPostgres()
    try:
        server.start()
        server.enable_archive()
        with psycopg.connect(server.sync_dsn,autocommit=True) as conn:
            conn.execute('CREATE TABLE sentinel_backup_recovery_markers(marker text primary key)')
            conn.execute('SELECT pg_switch_wal()')
            deadline=time.monotonic()+15
            while not conn.execute('SELECT last_archived_wal IS NOT NULL FROM pg_stat_archiver').fetchone()[0]:
                assert time.monotonic()<deadline
                time.sleep(.1)
            def runner(argv,**kwargs):
                row=conn.execute(argv[-1]).fetchone()
                return json.dumps(row[0]) if isinstance(row[0],dict) else str(row[0])
            observation=maintenance.observe_primary(runner)
            marker,barrier=checkpoint.commit_boundary(runner)
            assert not checkpoint.archive_reached(barrier,observation,runner)
            conn.execute('SELECT pg_switch_wal()')
            deadline=time.monotonic()+15
            while not checkpoint.archive_reached(barrier,observation,runner):
                assert time.monotonic()<deadline
                time.sleep(.1)
            assert conn.execute('SELECT marker FROM sentinel_backup_recovery_markers').fetchall()==[(marker,)]
    finally:
        server.stop()
