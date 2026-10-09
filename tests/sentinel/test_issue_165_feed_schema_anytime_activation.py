"""Real catalog proofs under a live reader; no-op activation cannot issue DDL."""
import inspect
from contextlib import redirect_stdout
import io
import json
import subprocess
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import schema
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from tests.sentinel.test_go_preparation_attempts import _probe
import sentinel_go_24x7_entry as source_final
import sentinel_go_backup_retry as retry


@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def installed(pg):
    conn = store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    store.migrate_schema(conn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_noop_installer_and_go_validation_do_not_contend_with_live_reader(installed, pg):
    reader = store.connect(pg.sync_dsn)
    try:
        # AccessShare remains owned throughout the installer/GO catalog proof.
        reader.execute('SELECT state FROM sentinel_processed_sessions LIMIT 0')
        schema.ensure_schema(installed)
        schema.require_runtime_schema(installed)
        store.require_feed_schema(installed)
        assert reader.execute('SELECT 1').fetchone()[0] == 1
    finally:
        reader.rollback()
        reader.close()


@pytest.mark.parametrize('table', ['sentinel_automation_control',
    'sentinel_automation_lease', 'sentinel_notification_policy', 'sentinel_alert_health_cursor'])
def test_noop_fast_path_does_not_reseed_missing_authority(installed, table):
    installed.execute('DELETE FROM '+table+' WHERE id=1')
    installed.commit()
    with pytest.raises(schema.SchemaMigrationRefused, match='singleton'):
        schema.ensure_schema(installed)
    assert installed.execute('SELECT count(*) FROM '+table+' WHERE id=1').fetchone()[0] == 0


def test_go_validation_refuses_instead_of_repairing_missing_schema(installed):
    installed.execute('ALTER TABLE sentinel_processed_sessions DROP COLUMN state')
    installed.commit()
    with pytest.raises(schema.SchemaMigrationRefused):
        schema.require_runtime_schema(installed)
    assert installed.execute("SELECT count(*) FROM information_schema.columns WHERE "
        "table_name='sentinel_processed_sessions' AND column_name='state'").fetchone()[0] == 0


def test_reintroduced_noop_ddl_is_detected_by_the_real_lock_failure(installed, pg, monkeypatch):
    source = textwrap.dedent(inspect.getsource(schema.ensure_schema))
    source = source.replace('if _semantic_catalog_sha256(', 'if False and _semantic_catalog_sha256(')
    namespace = {}
    exec(compile(source, 'no-noop-fast-path', 'exec'), schema.__dict__, namespace)
    monkeypatch.setattr(schema, 'ensure_schema', namespace['ensure_schema'])
    with pytest.raises(Exception, match='lock timeout'):
        test_noop_installer_and_go_validation_do_not_contend_with_live_reader(installed, pg)


@pytest.mark.parametrize('horizon', [False, True])
def test_real_preparation_catalog_to_json_and_resume_contract(installed, pg, monkeypatch, horizon):
    from sentinel import backup_guard, backup_runtime_authority, retained_go
    from sentinel.feed import publication, rolling_go_inputs

    connect = store.connect
    reader = connect(pg.sync_dsn)
    reader.execute('SELECT state FROM sentinel_processed_sessions LIMIT 0')
    monkeypatch.setattr(store, 'connect', lambda *a: connect(pg.sync_dsn))
    monkeypatch.setattr(backup_guard, 'require_writes_permitted', lambda *a, **k: None)
    # Installation already migrated the feed. GO must not repeat its DDL or
    # rebuild projections while a real reader owns an AccessShare lock.
    monkeypatch.setattr(store, 'migrate_schema', lambda *a: pytest.fail('GO repeated feed migration'))
    calls = []
    job = '00000000-0000-0000-0000-000000000001'

    def prepare(conn, **kwargs):
        calls.append(kwargs)
        assert kwargs['target_session'] == '2026-08-11'
        assert kwargs['resume_job_id'] is None
        if horizon:
            exc = backup_runtime_authority.BackupHorizonExceeded('fixture WAL horizon')
            exc.resume_job_id = job
            raise exc
        return {'status': 'ALREADY_CURRENT', 'schema': 'fixture-retained-inputs'}

    monkeypatch.setattr(retained_go, 'prepare', prepare)
    monkeypatch.setattr(rolling_go_inputs, 'current', lambda *a: SimpleNamespace(window_end='2026-08-11'))
    monkeypatch.setattr(publication, 'chain_gaps', lambda *a: [])
    monkeypatch.setenv('SENTINEL_DATABASE_URL', pg.sync_dsn)
    monkeypatch.setenv('SENTINEL_GO_PREPARATION_DEADLINE', '2026-08-12T16:46:00+00:00')
    monkeypatch.delenv('SENTINEL_GO_RESUME_JOB_ID', raising=False)
    code = source_final._PREPARATION_CODE.replace('now = datetime.now(timezone.utc)',
        'now = datetime(2026, 8, 12, 14, 46, tzinfo=timezone.utc)')
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            if horizon:
                with pytest.raises(backup_runtime_authority.BackupHorizonExceeded):
                    exec(code, {})
            else:
                exec(code, {})
        completed = subprocess.CompletedProcess([], 1 if horizon else 0, output.getvalue(), '')
        summary = _probe(monkeypatch, completed)
        assert summary.schema_migration_attempted and summary.bounded_sharadar_daily_attempted
        assert summary.broker_mutation_attempts == 0 and len(calls) == 1
        assert reader.execute('SELECT 1').fetchone()[0] == 1
        if horizon:
            assert not summary.complete and summary.status == source_final.go.FAIL
            assert retry.resumable_job(completed) == job
        else:
            assert summary.complete and summary.status == source_final.go.PASS
            serialized = json.loads(json.dumps(summary.to_dict()))
            assert serialized['completed_before_validation_boundary'] is True
            assert serialized['schema_migration_attempted'] is True
            assert serialized['database_mutation_scope'] == [
                'SCHEMA_MIGRATION', 'BOUNDED_SHARADAR_DAILY_INGEST']
            payload = json.loads(output.getvalue().split('SENTINEL_GO_PREPARATION=', 1)[1])
            assert payload['following_open_future'] is False
    finally:
        reader.rollback()
        reader.close()
