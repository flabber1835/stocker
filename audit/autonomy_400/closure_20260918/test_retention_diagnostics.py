"""Audit-only real-SQL witness: diagnostic contention after cleanup commit.

Copy into the pinned test lens's /work/tests/sentinel/ for its existing fixture
configuration, then run this module. Production source is unchanged. Both cases
assert the observed defect; a passing witness is not passing acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time

import psycopg
import pytest

from sentinel import rolling_runtime as runtime
from sentinel.feed import retention
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS


@pytest.mark.parametrize('cleanup_failure', [False, True])
def test_diagnostic_lock_outlives_cleanup_deadlines_and_release_recovers(
        conn, published, monkeypatch, cleanup_failure):
    first = runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    conn.commit()
    dsn = conn.info.dsn
    seen = {}
    entered = threading.Event()
    done = threading.Event()

    if cleanup_failure:
        def failed_pass(_conn, **_kwargs):
            raise OSError('audit-controlled cleanup failure')
        monkeypatch.setattr(retention, '_pass', failed_pass)

    class ObserveConnection:
        def __init__(self, native):
            self.native = native
        def __getattr__(self, name):
            return getattr(self.native, name)
        def execute(self, query, *args, **kwargs):
            if isinstance(query, str) and query.startswith('INSERT INTO sentinel_snapshot_maintenance'):
                seen['timeouts'] = self.native.execute(
                    "SELECT current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone()
                seen['backend_pid'] = self.native.info.backend_pid
                entered.set()
            return self.native.execute(query, *args, **kwargs)

    def worker():
        try:
            with psycopg.connect(dsn, application_name='audit400-retention-diagnostic') as native:
                start = time.monotonic()
                result = runtime.service_advance(ObserveConnection(native), through='2026-09-14',
                                                observation_id=OBS, starting_cash=100000)
                seen['elapsed_seconds'] = time.monotonic() - start
                seen['result_verification'] = result.verification
                seen['state_hash'] = result.state.state_hash
                return result
        finally:
            done.set()

    with psycopg.connect(dsn) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        row = blocker.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance WHERE id FOR UPDATE').fetchone()
        assert row is not None
        blocking_pid = blocker.info.backend_pid
        future = pool.submit(worker)
        try:
            assert entered.wait(15), 'service did not reach its native diagnostic write'
            assert seen['timeouts'] == ('0', '0')
            deadline = time.monotonic() + 5
            with psycopg.connect(dsn, autocommit=True) as observer:
                while True:
                    waiting = observer.execute(
                        'SELECT wait_event_type,query,pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s',
                        (seen['backend_pid'],)).fetchone()
                    if waiting and waiting[0] == 'Lock' and blocking_pid in waiting[2]:
                        break
                    assert time.monotonic() < deadline, waiting
                    time.sleep(.02)
            seen['wait'] = {'type': waiting[0], 'query': waiting[1], 'blocker_confirmed': blocking_pid in waiting[2]}
            assert not done.wait(5.3), 'witness requires waiting beyond both configured local SQL deadlines'
            assert not future.done()
        finally:
            blocker.rollback()
        result = future.result(timeout=10)
        assert result.verification == 'VERIFIED'
        assert result.state.state_hash == first.state.state_hash
        assert seen['elapsed_seconds'] >= 5.3
    conn.rollback()
    status = conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance WHERE id').fetchone()[0]['status']
    assert status == ('RETRY' if cleanup_failure else 'COMPLETE')
    conn.commit()
    start = time.monotonic()
    again = runtime.service_advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    assert again.state.state_hash == first.state.state_hash
    seen['uncontended_seconds'] = time.monotonic() - start
    seen['cleanup_status'] = status
    out = Path('/audit400/evidence/retention-diagnostics')
    out.mkdir(parents=True, exist_ok=True)
    (out / f'cleanup-failure-{cleanup_failure}.json').write_text(json.dumps(seen, indent=2))
