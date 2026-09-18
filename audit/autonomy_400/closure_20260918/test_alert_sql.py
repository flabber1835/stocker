"""Audit-only real dispatcher startup SQL contention composition."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time

import psycopg

from sentinel import alert_service, alert_health
from tests.sentinel.test_operator_monitoring import issue369_pg, db  # noqa: F401


def test_actual_dispatcher_sql_wait_delays_independent_transport_and_loop(db, monkeypatch):
    dispatcher_id = 'audit400-row-contention'
    dsn = db.info.dsn
    alert_health.register(db, dispatcher_id=dispatcher_id)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', dsn)
    monkeypatch.setenv('SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL', 'https://example.invalid/audit-only')
    monkeypatch.setenv('SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID', dispatcher_id)
    for name in ('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY', 'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY',
                 'SENTINEL_WEB_PUSH_VAPID_SUBJECT'):
        monkeypatch.delenv(name, raising=False)
    transport = []
    pulse = threading.Event()
    done = threading.Event()
    ready = threading.Event()
    seen = {}
    real_connect = alert_service.feed_store.connect

    def observed_connect(url):
        native = real_connect(url)
        seen['backend_pid'] = native.info.backend_pid
        seen['timeouts'] = native.execute(
            "SELECT current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone()
        native.rollback()
        ready.set()
        return native

    def delivered(_self, payload, key):
        transport.append({'event_type': payload['event_type'], 'key': key})

    async def stop_after_iteration(stop, seconds):
        stop.set()

    monkeypatch.setattr(alert_service.feed_store, 'connect', observed_connect)
    monkeypatch.setattr(alert_service.WebhookAlertAdapter, '_post', delivered)
    monkeypatch.setattr(alert_service, '_sleep_or_stop', stop_after_iteration)

    async def run_with_loop_probe():
        asyncio.get_running_loop().call_soon(pulse.set)
        return await alert_service.run()

    def worker():
        try:
            return asyncio.run(run_with_loop_probe())
        finally:
            done.set()

    with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute('SELECT dispatcher_id FROM sentinel_alert_dispatcher_health '
                        'WHERE dispatcher_id=%s FOR UPDATE', (dispatcher_id,)).fetchone()
        pid = blocker.info.backend_pid
        started = time.monotonic()
        future = pool.submit(worker)
        try:
            assert ready.wait(10)
            assert seen['timeouts'] == ('0', '0')
            with psycopg.connect(dsn, autocommit=True) as observer:
                deadline = time.monotonic() + 5
                while True:
                    row = observer.execute('SELECT wait_event_type,query,pg_blocking_pids(pid) '
                                           'FROM pg_stat_activity WHERE pid=%s',
                                           (seen['backend_pid'],)).fetchone()
                    if row and row[0] == 'Lock' and pid in row[2]:
                        break
                    assert time.monotonic() < deadline, row
                    time.sleep(.02)
            assert 'INSERT INTO sentinel_alert_dispatcher_health' in row[1]
            seen['query'] = row[1]
            assert not done.wait(2.2)
            assert not future.done()
            assert transport == []
            assert not pulse.is_set()
            seen['delayed_seconds'] = time.monotonic() - started
        finally:
            blocker.rollback()
        assert future.result(timeout=10) == 0
    assert pulse.is_set()
    assert [r['event_type'] for r in transport] == ['ALERT_DISPATCHER_REACHABILITY_PROBE']
    db.rollback()
    health = alert_health.load(db, dispatcher_id=dispatcher_id)
    assert health.state == 'HEALTHY'
    assert health.consecutive_failures == 0
    db.commit()
    seen['transport_after_release'] = transport
    seen['health_after_release'] = health.state
    out = Path('/audit400/evidence/alert-sql')
    out.mkdir(parents=True, exist_ok=True)
    (out/'measurements.json').write_text(json.dumps(seen, indent=2))
