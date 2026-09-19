"""Real PostgreSQL reads enforce the published selection contract."""
from pathlib import Path
import os
import subprocess
import uuid

import psycopg
import pytest

from sentinel import backup_runtime_authority as authority
from tests.sentinel.test_backup_bounded_reads import pg, archive

__all__ = ['pg', 'archive']
ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))


@pytest.fixture
def selection(pg, monkeypatch):
    root = Path(pg.datadir) / ('selection-' + uuid.uuid4().hex)
    root.mkdir()
    monkeypatch.setattr(authority, 'BASE_ROOT', str(root))
    path = root / '.sentinel-runtime-base-1-v1'
    with psycopg.connect(pg.sync_dsn, autocommit=True) as conn:
        yield conn, path


def test_real_sql_accepts_exact_record_then_missing_refuses(selection):
    conn, path = selection
    path.write_bytes(b'schema=sentinel.runtime-base/1\nsystem_identifier=1\nbase_backup=base-20260919T000000Z\n')
    assert authority._published_base(conn, system_id='1') == 'base-20260919T000000Z'
    path.unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable, match='selection'):
        authority._published_base(conn, system_id='1')


def test_actual_publisher_grants_only_selection_read_to_postgres(selection):
    conn, path = selection
    name = 'base-20260919T000000Z'
    base = path.parent / name
    base.mkdir()
    for field in ('backup_manifest', 'backup_label', 'sentinel-recovery-marker', 'sentinel-pitr-base-identity'):
        (base / field).write_bytes(b'preverified metadata fixture')
    private = base / 'private-payload'
    private.write_bytes(b'private')
    private.chmod(0o600)
    result = subprocess.run(['sh', str(ROOT / 'scripts/sentinel-backup-publish-selection.sh'),
                             str(path.parent), '1', name], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert authority._published_base(conn, system_id='1') == name
    assert path.stat().st_uid == 0 and path.stat().st_mode & 0o777 == 0o640
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute('SELECT pg_read_binary_file(%s)', (str(private),))
    assert subprocess.run(['runuser', '-u', 'postgres', '--', 'test', '-w', str(path)]).returncode == 1


def test_failed_atomic_rename_preserves_old_record_and_cleans_temporary(selection):
    _, path = selection
    name = 'base-20260919T000000Z'
    base = path.parent / name
    base.mkdir()
    for field in ('backup_manifest', 'backup_label', 'sentinel-recovery-marker', 'sentinel-pitr-base-identity'):
        (base / field).write_bytes(b'preverified metadata fixture')
    old = b'previous complete selection'
    path.write_bytes(old)
    binary = path.parent / 'bin'
    binary.mkdir()
    fail = binary / 'mv'
    fail.write_text('#!/bin/sh\nexit 73\n')
    fail.chmod(0o755)
    result = subprocess.run(['sh', str(ROOT / 'scripts/sentinel-backup-publish-selection.sh'),
                             str(path.parent), '1', name],
                            env={**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH']},
                            capture_output=True, text=True)
    assert result.returncode == 73
    assert path.read_bytes() == old
    assert not list(path.parent.glob('.sentinel-runtime-base-*.part-*'))


def test_large_non_ascii_record_is_bounded_before_decoding(selection):
    conn, path = selection
    with path.open('wb') as stream:
        stream.write(b'\xff')
        stream.truncate(32 * 1024 * 1024)
    received = []
    class Cursor:
        def __enter__(self):
            self.real = conn.cursor()
            return self
        def __exit__(self, *args):
            self.real.close()
        def execute(self, *args):
            return self.real.execute(*args)
        def fetchone(self):
            row = self.real.fetchone()
            received.append(len(row[0]))
            return row
    class Connection:
        def cursor(self):
            return Cursor()
    with pytest.raises(authority.BackupRuntimeRefused, match='byte bound'):
        authority._published_base(Connection(), system_id='1')
    # Measure the actual server response, independent of query spelling.
    assert received and max(received) <= 257


@pytest.mark.parametrize('alias', ['symlink', 'hardlink'])
def test_real_sql_refuses_selection_alias_during_archive_proof(archive, alias):
    conn, _, kwargs = archive
    path = Path(authority.BASE_ROOT) / '.sentinel-runtime-base-1-v1'
    other = Path(authority.BASE_ROOT) / 'unrelated-selection'
    other.write_bytes(b'not an authorized selection')
    if alias == 'symlink':
        path.symlink_to(other)
    else:
        path.hardlink_to(other)
    with pytest.raises(authority.BackupRuntimeRefused, match='alias'):
        authority._validate_archive_objects(conn, **kwargs)
