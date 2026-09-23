"""Logical PostgreSQL restore of a formed origin; no transport authority claim."""
import subprocess

from sentinel import formation_bootstrap, rolling_initialization as init
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres, _find_pg_bin
from tests.sentinel.test_rolling_initialization import ready, start, OBS  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


def test_logical_restore_preserves_authenticated_formed_origin_and_never_reforms(
        conn, pg, ready, tmp_path, monkeypatch):
    before = start(conn, starting_cash=50_000)
    origin = init.checkpoints.read(conn)
    progress = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
        ('formation-progress:v1:' + OBS,)).fetchone()[0]
    conn.commit()
    dump = tmp_path / 'formed.dump'
    subprocess.run([_find_pg_bin('pg_dump'), '--format=custom', '--file', str(dump), conn.info.dsn],
                   check=True, capture_output=True, text=True, timeout=60)
    assert dump.stat().st_size > 0
    restored = _EphemeralPostgres()
    restored.start()
    try:
        subprocess.run([_find_pg_bin('pg_restore'), '--exit-on-error', '--no-owner', '--no-privileges',
                        '--dbname', restored.sync_dsn, str(dump)],
                       check=True, capture_output=True, text=True, timeout=60)
        def no_reformation(*args, **kwargs):
            raise AssertionError('restore must not re-form the book')
        monkeypatch.setattr(formation_bootstrap, 'prepare', no_reformation)
        with store.connect(restored.sync_dsn) as connection:
            after = init.resume(connection, observation_id=OBS, starting_cash=50_000)
            assert after.state.state_hash == before.state.state_hash
            assert after.record_sha256 == before.record_sha256
            assert after.strategy_nav == before.strategy_nav == '50000'
            assert init.checkpoints.read(connection) == origin
            assert connection.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                ('formation-progress:v1:' + OBS,)).fetchone()[0] == progress
            for table in ('sentinel_commands', 'sentinel_fills', 'sentinel_execution_plans'):
                assert connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
    finally:
        restored.stop()
