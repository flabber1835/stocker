"""Structural restore consumes the authenticated rolling book and current tape."""
import json
import psycopg
import pytest

from sentinel import restore_validation, rolling_checkpoint
from sentinel.feed import rolling_store
from tests.sentinel.test_rolling_initialization import ready, start
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source


@pytest.mark.parametrize('damage', ['checkpoint', 'snapshot'])
def test_restore_refuses_corrupt_current_rolling_dependencies(conn, ready, damage, monkeypatch):
    from sentinel.feed import runtime_schema
    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema', runtime_schema.require_feed_schema)
    start(conn)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restored:
        report = restore_validation.validate_restored_database(restored)
        assert report['restart_state_present'] and report['transaction_read_only']
    if damage == 'checkpoint':
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',%s::jsonb) WHERE cursor_name=%s",
                     (json.dumps('f'*64), rolling_checkpoint.CURSOR))
        error, reason = rolling_checkpoint.RollingColdStartRefused, 'AUTHENTICATION_FAILED'
    else:
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=1 WHERE candidate_id=%s AND session=%s',
                     (ready['candidate_id'], '2026-09-14'))
        error, reason = rolling_store.SnapshotStorageRefused, 'manifest'
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restored:
        with pytest.raises(error, match=reason):
            restore_validation.validate_restored_database(restored)

__all__ = ['conn', 'operational_source', 'pg', 'ready', 'source']
