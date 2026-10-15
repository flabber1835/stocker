"""Execute the actual restore launcher's gates against actual paused PITR."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import psycopg
import pytest

from sentinel import schema
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres, _find_pg_bin, _as_pg_user, _run

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))


@pytest.fixture(params=[False, True], ids=['pristine', 'initialized'])
def replayed(request):
    primary, restored = _EphemeralPostgres(), _EphemeralPostgres()
    base = Path(tempfile.mkdtemp(prefix='sentinel_pristine_base_', dir=Path(primary.datadir).parent))
    try:
        primary.start()
        primary.enable_archive()
        with psycopg.connect(primary.sync_dsn) as conn:
            if request.param:
                schema.ensure_schema(conn)
                store.migrate_schema(conn)
            conn.execute('CREATE TABLE sentinel_backup_recovery_markers (marker text primary key)')
            conn.commit()
        if os.geteuid() == 0:
            shutil.chown(base, user='postgres', group='postgres')
        result = _run(_as_pg_user([_find_pg_bin('pg_basebackup'), '-h', '127.0.0.1',
            '-p', str(primary.port), '-U', primary.user, '-D', str(base), '-Fp', '-Xs', '-c', 'fast']))
        assert result.returncode == 0, result.stderr
        with psycopg.connect(primary.sync_dsn, autocommit=True) as conn:
            conn.execute("INSERT INTO sentinel_backup_recovery_markers VALUES ('pristine-marker')")
            lsn, wal = conn.execute('SELECT pg_current_wal_lsn()::text,pg_walfile_name(pg_current_wal_lsn())').fetchone()
            conn.execute('SELECT pg_switch_wal()')
        archive = Path(primary.datadir) / 'worker-archive'
        deadline = time.monotonic() + 15
        while not (archive / wal).is_file():
            assert time.monotonic() < deadline
            time.sleep(.1)
        target = Path(restored.datadir)
        shutil.copytree(base, target, dirs_exist_ok=True)
        with (target / 'postgresql.auto.conf').open('a') as stream:
            stream.write("\nrestore_command='cp " + str(archive) + "/%f %p'\n")
            stream.write("recovery_target_lsn='" + lsn + "'\nrecovery_target_action='pause'\n")
        (target / 'recovery.signal').touch()
        if os.geteuid() == 0:
            for item in [target, *target.rglob('*')]:
                shutil.chown(item, user='postgres', group='postgres')
        result = _run(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', str(target),
            '-o', f'-p {restored.port} -h 127.0.0.1 -k {target}',
            '-l', str(target / 'restored.log'), '-w', '-t', '30', 'start']))
        assert result.returncode == 0, result.stderr
        restored._started = True
        with psycopg.connect(restored.sync_dsn, autocommit=True) as conn:
            deadline = time.monotonic() + 15
            while not conn.execute('SELECT pg_is_wal_replay_paused()').fetchone()[0]:
                assert time.monotonic() < deadline
                time.sleep(.1)
            assert conn.execute("SELECT marker FROM sentinel_backup_recovery_markers").fetchall() == [('pristine-marker',)]
            assert conn.execute('SELECT pg_is_in_recovery()').fetchone()[0]
        yield restored.sync_dsn, request.param
    finally:
        restored.stop()
        primary.stop()
        assert base.name.startswith('sentinel_pristine_base_') and base.parent == Path(primary.datadir).parent
        shutil.rmtree(base)


def _gates(dsn, *, physical_only):
    script = (ROOT / 'scripts/sentinel-restore-drill.sh').read_text()
    start = script.index('docker exec "$CONTAINER" psql -U sentinel -d sentinel -v ON_ERROR_STOP=1 -Atc')
    end = script.index('\nRUNTIME_IMAGE="${SENTINEL_RUNTIME_IMAGE_REF:-}"', start)
    # Run the production shell branches and actual SQL. Only Docker transport is
    # mapped to this test's actual local PostgreSQL; no policy query is mocked.
    adapter = '''docker() {
      [ "$1" = exec ] && [ "$2" = fixture ] && [ "$3" = psql ] || return 91
      "$TEST_PSQL" "$TEST_DSN" -v ON_ERROR_STOP=1 -Atc "${!#}"
    }
    '''
    env = dict(os.environ, TEST_PSQL=_find_pg_bin('psql'), TEST_DSN=dsn,
               CONTAINER='fixture', LATEST='fixture-base', PHYSICAL_ONLY=str(int(physical_only)))
    return subprocess.run(['bash', '-eu', '-c', adapter + script[start:end] + '\necho semantic_schema_gate_ready:true\n'],
                          env=env, capture_output=True, text=True, timeout=15)


def test_physical_replay_does_not_require_application_schema(replayed):
    dsn, _ = replayed
    result = _gates(dsn, physical_only=True)
    assert result.returncode == 0, result.stderr
    assert 'physical_wal_replay_ready:true' in result.stdout
    assert 'semantic_schema_gate_ready:true' not in result.stdout


def test_full_replay_still_requires_application_schema(replayed):
    dsn, initialized = replayed
    result = _gates(dsn, physical_only=False)
    assert (result.returncode == 0) is initialized, result.stderr
    if initialized:
        assert 'semantic_schema_gate_ready:true' in result.stdout
    else:
        assert 'canonical Sentinel tables are missing' in result.stderr
        assert 'semantic_schema_gate_ready:true' not in result.stdout


@pytest.mark.parametrize('physical_only', [True, False])
def test_primary_cannot_satisfy_recovery_gate(physical_only):
    primary = _EphemeralPostgres()
    try:
        primary.start()
        with psycopg.connect(primary.sync_dsn) as conn:
            schema.ensure_schema(conn)
            store.migrate_schema(conn)
        result = _gates(primary.sync_dsn, physical_only=physical_only)
        assert result.returncode != 0
        assert 'restore drill did not enter recovery' in result.stderr
        assert 'physical_wal_replay_ready:true' not in result.stdout
        assert 'semantic_schema_gate_ready:true' not in result.stdout
    finally:
        primary.stop()
