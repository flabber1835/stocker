"""Current checkpoint pins, unattended retry, and database restore after GC."""
import subprocess
import uuid

from sentinel import rolling_runtime as runtime
from sentinel.feed import retention, rolling_store, runtime_schema
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh
from tests.support.postgres import _find_pg_bin

__all__ = ['conn', 'pg', 'source', 'operational_source', 'issuer_source', 'published', 'ready']


def test_checkpoint_handoff_releases_origin_prices_and_restore_keeps_current_closure(
        conn, published, operational_source, monkeypatch, tmp_path, pg):
    import psycopg
    from psycopg import sql
    first = runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    original = published['candidate_id']
    second_pub = refresh(conn, operational_source, monkeypatch)
    # Publication changed, but the old snapshot is still required for overlap.
    assert not rolling_store.retired(conn, original)
    assert conn.execute('SELECT sentinel_snapshot_pins(%s)', (original,)).fetchone()[0] == ['RESTART_CHECKPOINT']
    conn.commit()
    second = runtime.service_advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100000)
    assert second.state.state_hash != first.state.state_hash
    # Production-sized fixture exceeds one batch. Ordinary successful service
    # polls finish the cleanup without acquisition or another transition.
    for _ in range(3):
        again = runtime.service_advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100000)
        assert again.state.state_hash == second.state.state_hash
    assert rolling_store.retired(conn, original)
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s', (original,)).fetchone()[0] == 0
    assert not rolling_store.retired(conn, second_pub['candidate_id'])
    conn.commit()
    dump = tmp_path / 'after-cleanup.dump'
    subprocess.run([_find_pg_bin('pg_dump'), '--dbname', conn.info.dsn, '-Fc', '-f', str(dump)], check=True, capture_output=True)
    restored_name = 'restored_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_name)))
    restored_dsn = pg.sync_dsn.rsplit('/', 1)[0] + '/' + restored_name
    try:
        subprocess.run([_find_pg_bin('pg_restore'), '--dbname', restored_dsn, '--exit-on-error', str(dump)],
                       check=True, capture_output=True)
        with psycopg.connect(restored_dsn) as restored:
            runtime_schema.require_feed_schema(restored)
            restored.rollback()
            result = runtime.status(restored, observation_id=OBS, starting_cash=100000)
            assert result.state.state_hash == second.state.state_hash
            assert rolling_store.retired(restored, original)
    finally:
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(restored_name)))


def test_service_keeps_valid_trading_state_when_cleanup_fails(conn, published, monkeypatch):
    runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    def fail(*args, **kwargs):
        raise OSError('disposable cleanup failure')
    monkeypatch.setattr(retention, '_pass', fail)
    result = runtime.service_advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    assert result.verification == 'VERIFIED'
    assert conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance').fetchone()[0]['status'] == 'RETRY'
