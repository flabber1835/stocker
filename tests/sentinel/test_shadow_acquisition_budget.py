"""Exercise the real daily service with slow database-backed acquisition."""
from datetime import datetime, timedelta
from decimal import Decimal
import inspect

import psycopg
import pytest

from sentinel.feed import rolling_store, store, writer_schedule
from sentinel import shadow_budget, shadow_service, shadow_worker, shadow_recovery, shadow_runtime
from sentinel.feed import rolling_jobs as jobs
from tests.sentinel.test_rolling_runtime import (
    test_actual_shadow_service_initializes_and_acquires_next_snapshot as daily_route,
)
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS, NOW


@pytest.mark.parametrize("fault", [None, "deadline", "fence", "interrupt", "parent_deadline"])
def test_daily_service_uses_its_two_hour_budget(conn, published, operational_source, monkeypatch, fault):
    initial = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.commit()
    elapsed, sealing = [0.0], [False]
    monkeypatch.setattr(shadow_budget, "now", lambda: initial + timedelta(seconds=elapsed[0]))
    monkeypatch.delenv(shadow_budget.DEADLINE_ENV, raising=False)
    monkeypatch.setenv("SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "7200")
    if fault == "parent_deadline":
        monkeypatch.setenv(shadow_budget.DEADLINE_ENV, (initial + timedelta(seconds=3600)).isoformat())

    class ClockCursor(psycopg.Cursor):
        def execute(self, query, params=None, **kwargs):
            if isinstance(query, str) and not query.lstrip().startswith(("CREATE", "ALTER", "DROP")):
                stamp = (initial + timedelta(seconds=elapsed[0])).isoformat()
                query = query.replace("clock_timestamp()", "'%s'::timestamptz" % stamp)
            return super().execute(query, params, **kwargs)

    conn.cursor_factory = ClockCursor
    connect = store.connect
    disposed = []
    dispose = writer_schedule._dispose

    def record_disposal(connection, primary):
        backend = connection.info.backend_pid
        result = dispose(connection, primary)
        disposed.append((connection, backend, primary, connection.closed))
        return result

    def service_connection(_url):
        connection = connect(conn.info.dsn)
        connection.cursor_factory = ClockCursor
        return connection

    seal, fold = rolling_store.seal, rolling_store._fold

    def slow_seal(*a, **kw):
        sealing[0] = True
        try:
            return seal(*a, **kw)
        finally:
            sealing[0] = False

    def slow_fold(*a):
        if sealing[0]:
            if fault == "interrupt" and elapsed[0] == 0:
                elapsed[0] = 1
                raise KeyboardInterrupt("worker interrupted during actual sealing")
            if fault == "fence" and elapsed[0] == 0:
                changed = conn.execute("UPDATE sentinel_snapshot_jobs SET fence=fence+1 WHERE state='VALIDATING'")
                assert changed.rowcount == 1
            elapsed[0] += .6 if fault == "deadline" else .3
        return fold(*a)

    monkeypatch.setattr(rolling_store, "BATCH_SIZE", 100)
    monkeypatch.setattr(rolling_store, "seal", slow_seal)
    monkeypatch.setattr(rolling_store, "_fold", slow_fold)
    if fault == "interrupt":
        monkeypatch.setattr(writer_schedule, '_dispose', record_disposal)
        with pytest.raises(KeyboardInterrupt, match='worker interrupted during actual sealing') as caught:
            daily_route(conn, published, operational_source, monkeypatch,
                        connection_factory=service_connection)
        assert writer_schedule.connection_discarded(caught.value)
        assert len(disposed) == 1 and disposed[0][2] is caught.value
        connection, backend, _, closed_at_disposal = disposed[0]
        assert closed_at_disposal and connection.closed, 'actual interrupted worker backend must be closed'
        assert conn.execute('SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype=\'advisory\'',
                            (backend,)).fetchone()[0] == 0
        job = conn.execute("SELECT job_id FROM sentinel_snapshot_jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        before = jobs.status(conn, job)
        # Disposed sessions cannot safely record a new wait state. Recovery
        # observes the last committed stage and its still-owned original lease.
        assert before['state'] == 'ACQUIRING' and before['owner'] is not None
        assert before['lease_until'] is not None and before['retry_seconds'] > 2
        assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 1
        conn.rollback()
        with pytest.raises(jobs.JobWaiting):
            jobs.claim(conn, job, lease_seconds=600)
        conn.rollback()
        observed = jobs.status(conn, job)
        assert all(observed[field] == before[field] for field in
                   ('owner', 'fence', 'deadline', 'lease_until', 'state'))
        conn.rollback()
        downloads = [x for x in operational_source['calls'] if x[0] == 'download']
        elapsed[0] = (datetime.fromisoformat(before['lease_until']) - initial).total_seconds() + 1
        assert initial + timedelta(seconds=elapsed[0]) < datetime.fromisoformat(before['deadline'])
        config = shadow_service.ShadowServiceConfig("fixture", OBS, Decimal("100000"),
            shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
        result = shadow_recovery.advance_once(config, now=NOW + timedelta(days=1))
        assert result['verification'] == 'VERIFIED'
        after = jobs.status(conn, job)
        assert after['state'] == 'PUBLISHED' and after['deadline'] == before['deadline']
        assert after['fence'] > before['fence'] and after['owner'] is None
        assert [x for x in operational_source['calls'] if x[0] == 'download'] == downloads
        assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 2
    elif fault:
        expiry = fault in {"deadline", "parent_deadline"}
        expected = shadow_service.ShadowServiceRetry if expiry else shadow_service.ShadowServiceRefused
        with pytest.raises(expected) as caught:
            daily_route(conn, published, operational_source, monkeypatch)
        assert isinstance(caught.value.__cause__, jobs.JobRefused)
        assert shadow_worker._availability_failure(caught.value) is expiry
        assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 1
        assert (elapsed[0] >= (3600 if fault == "parent_deadline" else 7200)) is expiry
    else:
        daily_route(conn, published, operational_source, monkeypatch)
        assert 3600 < elapsed[0] < 7200
        deadline = conn.execute("SELECT deadline FROM sentinel_snapshot_jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        assert deadline == initial + timedelta(seconds=7200)


def test_interrupted_service_detects_missing_actual_disposal(
        conn, published, operational_source, monkeypatch):
    def no_disposal(connection, primary):
        setattr(primary, writer_schedule._DISCARDED, True)
    monkeypatch.setattr(writer_schedule, '_dispose', no_disposal)
    with pytest.raises(AssertionError, match='actual interrupted worker backend must be closed'):
        test_daily_service_uses_its_two_hour_budget(
            conn, published, operational_source, monkeypatch, 'interrupt')


def test_interrupted_service_detects_early_lease_takeover(
        conn, published, operational_source, monkeypatch):
    source = inspect.getsource(jobs.claim)
    guard = '"AND (owner IS NULL OR lease_until<=clock_timestamp()) "'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, '""'), 'unfenced early job takeover', 'exec'),
         jobs.__dict__, namespace)
    monkeypatch.setattr(jobs, 'claim', namespace['claim'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_daily_service_uses_its_two_hour_budget(
            conn, published, operational_source, monkeypatch, 'interrupt')
