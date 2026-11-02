"""Exercise the actual PostgreSQL OS/file boundary in an owned private PG16."""
from unittest.mock import patch

import psycopg
import pytest

from sentinel import backup_continuity as continuity, backup_runtime_authority as runtime, local_paper
from sentinel.backup_guard import BackupUnavailable
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope='module')
def pg():
    server=_EphemeralPostgres();server.start()
    try:yield server
    finally:server.stop()


@pytest.fixture
def conn(pg, monkeypatch):
    monkeypatch.setenv(continuity.KEY_ENV,'private-SQL-fixture-key-only-'*3)
    with psycopg.connect(pg.sync_dsn) as connection:
        yield connection


def test_atomic_primary_record_roundtrip_through_real_copy_program(conn):
    expected=dict(private_fixture=True,observed_at=123)
    with conn.cursor() as cur:
        cur.execute(continuity.publication_sql(continuity.CAPACITY,continuity.seal('CAPACITY',expected)))
    assert continuity._read(conn,continuity.CAPACITY,'CAPACITY')==expected
    with conn.cursor() as cur:
        cur.execute('SELECT (pg_stat_file(%s)).isdir',(continuity.CAPACITY,))
        assert cur.fetchone()==(False,)


def test_real_primary_filesystem_reserve_cannot_use_virtual_capacity_receipt(conn):
    observation=continuity.primary(conn)
    proof=dict(system_identifier=observation['system_identifier'],
        postmaster_start_us=observation['postmaster_start_us'],observed_at=observation['now'],
        physical_free_bytes=continuity.RESERVE_BYTES+1,engine_id='private-sql-fixture')
    with conn.cursor() as cur:
        cur.execute(continuity.publication_sql(continuity.CAPACITY,continuity.seal('CAPACITY',proof)))
    # This owned qualifier's database is on bounded 512 MiB tmpfs, below the
    # production 10 GiB reserve, regardless of the fixture's Windows receipt.
    with pytest.raises(BackupUnavailable,match='filesystem reserve'):
        with conn.transaction():continuity._capacity(conn,observation)
    # Executed threshold control, confined to this test process: the very same
    # server-side stat program succeeds with a 1 MiB private-fixture threshold.
    with patch.object(continuity,'RESERVE_BYTES',1024**2):
        assert continuity._capacity(conn,observation)['engine_id']=='private-sql-fixture'


def test_failed_media_read_rolls_back_only_guard_savepoint(conn,monkeypatch):
    with conn.cursor() as cur:
        cur.execute('CREATE TEMP TABLE continuity_preserved_fixture(n int)')
        cur.execute('INSERT INTO continuity_preserved_fixture VALUES (1)')
    def absent(connection,**kwargs):
        with connection.cursor() as cur:
            cur.execute("SELECT pg_read_file('private-fixture-does-not-exist')")
    def degraded(connection,**kwargs):
        with connection.cursor() as cur:
            cur.execute('SELECT count(*) FROM continuity_preserved_fixture')
            assert cur.fetchone()==(1,)
        return dict(enabled=True,backup_state='DEGRADED')
    monkeypatch.setattr(local_paper,'backups_suspended_for_account',lambda c:False)
    monkeypatch.setattr(continuity,'selected',lambda:True)
    monkeypatch.setattr(runtime,'_require',absent)
    monkeypatch.setattr(continuity,'degraded',degraded)
    assert runtime.require(conn,operation='private savepoint fixture',allow_continuity=True)['backup_state']=='DEGRADED'


def test_missing_transport_cannot_be_misclassified_as_absent_verified_media(conn):
    # The ordinary private SQL fixture has no configured transport. An absent
    # directory is not proof of the reviewed read-only tmpfs fallback parent.
    with pytest.raises(BackupUnavailable,match='absence is not proven'):
        with conn.transaction():continuity.require_absent_media(conn)


def test_failed_degraded_guard_preserves_earlier_transaction(conn,monkeypatch):
    conn.execute('CREATE TEMP TABLE preserved_refusal_fixture(n int)')
    conn.execute('INSERT INTO preserved_refusal_fixture VALUES (1)')
    monkeypatch.setattr(local_paper,'backups_suspended_for_account',lambda c:False)
    monkeypatch.setattr(continuity,'selected',lambda:True)
    def absent(connection,**kwargs):raise runtime.BackupRuntimeUnavailable('private absent fixture')
    def no_transport(connection,**kwargs):
        continuity.require_absent_media(connection)
    monkeypatch.setattr(runtime,'_require',absent)
    monkeypatch.setattr(continuity,'degraded',no_transport)
    with pytest.raises(runtime.BackupRuntimeUnavailable,match='absence is not proven'):
        runtime.require(conn,operation='private refusal fixture',allow_continuity=True)
    assert conn.execute('SELECT count(*) FROM preserved_refusal_fixture').fetchone()==(1,)
