"""Warm alert observations retain fresh real schema and health predicates."""
from pathlib import Path
import sys
import time

import pytest

from sentinel import alert_health, alert_liveness
from sentinel.automation import outbox
from sentinel.supervisor_health import WarmHealthReader, probe
from tests.sentinel.test_automation_outbox import conn, pg  # noqa: F401


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux supervisor ownership')
@pytest.mark.parametrize('damage', ['heartbeat', 'dead-letter', 'schema'])
def test_warm_reader_rechecks_database_and_schema_without_mutation(conn, monkeypatch, tmp_path, damage):
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    monkeypatch.delenv('SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID', raising=False)
    alert_health.register(conn, dispatcher_id='primary')
    alert_health.record_success(conn, dispatcher_id='primary')
    conn.rollback()
    reader = WarmHealthReader(alert_liveness.observe, path=tmp_path/'alert-health.sock',
                              max_pulse_age=10)
    try:
        reader.tick()
        deadline = time.monotonic()+5
        while not reader.path.exists() and time.monotonic()<deadline:
            time.sleep(.01)
        assert probe(reader.path) == 0
        pid = reader.process.pid
        if damage == 'heartbeat':
            conn.execute("UPDATE sentinel_alert_dispatcher_health SET heartbeat_at=clock_timestamp()-interval '31 seconds'")
        elif damage == 'dead-letter':
            outbox.enqueue(conn, idempotency_key='private-dead-letter',event_type='PRIVATE_FAILURE',
                           severity='CRITICAL',payload={'reason':'private'})
            conn.execute("UPDATE sentinel_alert_outbox SET state='DEAD_LETTER'")
        else:
            conn.execute('ALTER TABLE sentinel_alert_dispatcher_health ADD COLUMN unreviewed_health text')
        conn.commit()
        before = conn.execute('SELECT to_jsonb(h) FROM sentinel_alert_dispatcher_health h').fetchall()
        conn.rollback()
        reader.tick()
        assert probe(reader.path) == 1
        assert reader.process.pid == pid
        assert conn.execute('SELECT to_jsonb(h) FROM sentinel_alert_dispatcher_health h').fetchall() == before
        conn.rollback()
    finally:
        reader.close()
    assert not reader.path.exists()
