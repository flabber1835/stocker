"""Real competing sessions must defer work without poisoning the supervisor."""
from contextlib import contextmanager
from decimal import Decimal

import pytest

from sentinel import automation_runtime, shadow_worker, shadow_service, shadow_recovery, shadow_runtime
from sentinel.automation.model import TransientInfrastructureFailure
from sentinel.execution import journal
from sentinel.feed import publication, rolling_store, store
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401


@contextmanager
def _contended(conn, boundary):
    """Hold the opposite advisory mode on a second real PostgreSQL session."""
    import psycopg
    key = journal.WRITER_LOCK_KEY if boundary == 'behavioral_writer' else publication.CORPUS_LOCK_KEY
    mode = '_shared' if boundary == 'corpus_writer' else ''
    conn.rollback()
    with psycopg.connect(conn.info.dsn) as other:
        other.execute(f'SELECT pg_advisory_lock{mode}(%s)', (key,))
        yield


def _attempt(conn, boundary):
    if boundary == 'snapshot_reader':
        rolling_store._pin_reader(conn)
    elif boundary == 'corpus_reader':
        with publication._core.pinned(conn, commit=False):
            pass
    elif boundary == 'atomic_publisher':
        publication._publish_atomic(conn)
    else:
        lock = journal.writer_lock if boundary == 'behavioral_writer' else store.corpus_write_lock
        with lock(conn):
            pass


@pytest.mark.parametrize('boundary', [
    'corpus_reader', 'snapshot_reader', 'corpus_writer', 'atomic_publisher', 'behavioral_writer'])
def test_actual_lock_contention_is_availability_at_both_worker_boundaries(conn, monkeypatch, boundary):
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: object())
    def attempt(_):
        try:
            _attempt(conn, boundary)
        finally:
            conn.rollback()
    monkeypatch.setattr(shadow_worker, 'advance_once', attempt)
    with _contended(conn, boundary):
        with pytest.raises(RuntimeError) as caught:
            _attempt(conn, boundary)
        conn.rollback()
        assert isinstance(automation_runtime.classify_dependency_failure(caught.value),
                          TransientInfrastructureFailure)
        assert shadow_worker.main() == shadow_worker.EXIT_AVAILABILITY
    # Lock release, not a changed authority or reset, restores ordinary access.
    with journal.writer_lock(conn), store.corpus_write_lock(conn):
        assert conn.execute('SELECT 42').fetchone()[0] == 42


def test_missing_writer_ownership_is_not_transient(conn):
    with pytest.raises(publication.CorpusBusy) as caught:
        store._assert_corpus_locked(conn)
    conn.rollback()
    assert not shadow_worker._availability_failure(caught.value)
    assert not isinstance(automation_runtime.classify_dependency_failure(caught.value),
                          TransientInfrastructureFailure)


def test_real_database_timeout_resumes_same_acquisition_job(conn, operational_source, monkeypatch):
    import psycopg
    from sentinel.feed import operational_snapshot as op, rolling_jobs as jobs
    from sentinel.feed.rolling_source import SharadarSource
    from tests.sentinel.test_operational_snapshot import enqueue
    job = enqueue(conn)
    deadline = jobs.status(conn, job)['deadline']
    original = SharadarSource.preflight
    def timed_out(self):
        conn.execute("SET LOCAL statement_timeout='20ms'")
        conn.execute('SELECT pg_sleep(1)')
    monkeypatch.setattr(SharadarSource, 'preflight', timed_out)
    with pytest.raises(psycopg.errors.QueryCanceled):
        op.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state['state'] == 'RETRY_WAIT' and state['owner'] is None
    assert state['reason'] == 'DATABASE_UNAVAILABLE'
    assert state['deadline'] == deadline
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0
    conn.execute('UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s', (job,))
    conn.commit()
    monkeypatch.setattr(SharadarSource, 'preflight', original)
    result = op.prepare(conn, job)
    assert result['job_id'] == job
    assert jobs.status(conn, job)['deadline'] == deadline
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 1


def test_missing_lock_during_acquisition_is_terminal(conn, operational_source, monkeypatch):
    from sentinel.feed import operational_snapshot as op, rolling_jobs as jobs
    from sentinel.feed.rolling_source import SharadarSource
    from tests.sentinel.test_operational_snapshot import enqueue
    monkeypatch.setattr(SharadarSource, 'preflight', lambda _: store._assert_corpus_locked(conn))
    job = enqueue(conn)
    with pytest.raises(publication.CorpusBusy):
        op.prepare(conn, job)
    assert jobs.status(conn, job)['state'] == 'REFUSED'
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0


@pytest.mark.parametrize('boundary', ['corpus_reader', 'behavioral_writer'])
def test_real_rolling_worker_recovers_without_reset_or_duplicate_state(
        conn, published, monkeypatch, boundary):
    from sentinel import rolling_authority
    from tests.sentinel.test_rolling_initialization import OBS, NOW
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, 'connect', lambda _: Borrowed())
    config = shadow_service.ShadowServiceConfig('fixture', OBS, Decimal('100000'),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: config)
    monkeypatch.setattr(shadow_worker, 'advance_once',
                        lambda cfg: shadow_recovery.advance_once(cfg, now=NOW))
    before = conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name,session').fetchall()
    with _contended(conn, boundary):
        assert shadow_worker.main() == shadow_worker.EXIT_AVAILABILITY
        assert conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name,session').fetchall() == before
        conn.rollback()
    assert shadow_worker.main() == 0
    first = rolling_authority.latest(conn, OBS)
    conn.rollback()
    assert len(first) == 1
    assert shadow_worker.main() == 0
    assert rolling_authority.latest(conn, OBS) == first
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    for table in ('sentinel_commands', 'sentinel_fills', 'sentinel_execution_plans'):
        assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


@pytest.mark.parametrize('entry', ['advance_ready_shadow', 'verified_shadow_status', 'classify_shadow_lineage'])
@pytest.mark.parametrize('kind', ['database', 'integrity'])
def test_public_shadow_wrappers_preserve_dependency_type_without_unwrapping_integrity(
        conn, monkeypatch, entry, kind):
    import psycopg
    from sentinel import rolling_runtime
    def select(_):
        try:
            conn.execute("SET LOCAL statement_timeout='20ms'")
            conn.execute('SELECT pg_sleep(1)')
        except psycopg.errors.QueryCanceled as exc:
            if kind == 'integrity':
                raise shadow_runtime.ShadowRuntimeRefused('retained state changed') from exc
            raise
    monkeypatch.setattr(rolling_runtime, 'selected', select)
    kwargs = {'observation_id': 'fixture', 'starting_cash': 50000}
    if entry == 'advance_ready_shadow':
        kwargs['through'] = '2026-09-14'
    expected = psycopg.errors.QueryCanceled if kind == 'database' else shadow_runtime.ShadowRuntimeRefused
    with pytest.raises(expected) as caught:
        getattr(shadow_runtime, entry)(conn, **kwargs)
    conn.rollback()
    assert shadow_worker._availability_failure(caught.value) == (kind == 'database')
