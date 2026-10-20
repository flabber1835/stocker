"""Production report-only consumers must not retain the strategy warmup."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone

import psycopg
import pytest

from sentinel import schema
from sentinel.core import rolling_inputs as adapter
from sentinel.execution import feed_inputs
from sentinel.feed import publication, readers, rolling_go_inputs as inputs, rolling_store
from tests.sentinel.test_rolling_runtime import advance
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source

__all__ = ['conn', 'pg', 'source', 'operational_source', 'issuer_source', 'published', 'ready']
REAL_CLOSED_SESSION = inputs.calendar.latest_closed_session
NOW = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)


def forbid_materialization(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('report-only caller retained the complete strategy warmup')
    monkeypatch.setattr(inputs, 'cold_start_inputs', forbidden)
    monkeypatch.setattr(adapter, 'cold_start_inputs', forbidden)


def report(conn, consumer, instant=NOW):
    if consumer == 'assessment':
        return readers.readiness(conn, today=instant.isoformat())
    if consumer == 'readiness':
        return inputs.readiness(conn, now=instant)
    with feed_inputs.pinned(conn, commit=False):
        return feed_inputs.readiness(conn, today=instant.isoformat())


@pytest.mark.parametrize('consumer', ['assessment', 'readiness', 'execution', 'prepare', 'runtime_retry'])
def test_report_only_entrypoints_never_materialize(conn, published, monkeypatch, consumer):
    before = advance(conn) if consumer == 'runtime_retry' else None
    conn.rollback()
    forbid_materialization(monkeypatch)
    if consumer == 'runtime_retry':
        after = advance(conn)
        assert after.state.state_hash == before.state.state_hash
        assert after.strategy_nav == before.strategy_nav
        assert after.runtime_authority_sha256 == before.runtime_authority_sha256
        assert not after.appended
        assert conn.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 0
    elif consumer == 'prepare':
        result = inputs.prepare(conn, target_session='2026-09-14')
        assert result['status'] == 'ALREADY_CURRENT'
        assert result['snapshot_id'] == published['snapshot_id']
    else:
        inputs.require_schemas(conn)
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        assert report(conn, consumer).ready
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'


def test_first_acquisition_verification_never_materializes(conn, issuer_source, monkeypatch):
    schema.ensure_schema(conn)
    forbid_materialization(monkeypatch)
    result = inputs.prepare(conn, target_session='2026-09-14')
    assert result['status'] == 'PUBLISHED'
    assert conn.execute('SELECT COUNT(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions').fetchone()[0] == 0


@pytest.mark.parametrize('consumer', ['assessment', 'readiness', 'execution'])
def test_report_consumers_preserve_stale_frontier_semantics(conn, published, monkeypatch, consumer):
    monkeypatch.setattr(inputs.calendar, 'latest_closed_session', REAL_CLOSED_SESSION)
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    later = datetime(2026, 9, 17, 4, tzinfo=timezone.utc)
    if consumer == 'assessment':
        result = report(conn, consumer, later)
        assert not result.ready
        assert any(check.name == 'rolling source-final frontier' for check in result.failures)
    else:
        with pytest.raises(inputs.RollingGoRefused, match='source-final'):
            report(conn, consumer, later)


@pytest.mark.parametrize('consumer', ['assessment', 'readiness', 'execution'])
def test_report_consumers_refuse_late_corruption(conn, published, consumer):
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=close_unadjusted+1'
                 ' WHERE candidate_id=%s AND session=%s AND security_id=%s',
                 (published['candidate_id'], '2026-09-14', '25'))
    conn.commit()
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    with pytest.raises(rolling_store.SnapshotStorageRefused, match='manifest'):
        report(conn, consumer)


class TrackedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.rollbacks = self.commits = 0

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def rollback(self):
        self.rollbacks += 1
        return self.connection.rollback()

    def commit(self):
        self.commits += 1
        return self.connection.commit()


def _transaction_identity(conn):
    return conn.execute(
        "SELECT pg_backend_pid(),transaction_timestamp(),"
        "current_setting('transaction_read_only'),current_setting('transaction_isolation')"
    ).fetchone()


def _assert_healthy_read_only_pin_preserved(conn):
    inputs.require_schemas(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    before = _transaction_identity(conn)
    assert before[2:] == ('on', 'repeatable read')
    tracked = TrackedConnection(conn)
    try:
        with readers.pinned(tracked, commit=False) as pub:
            assert readers.is_rolling(pub)
            assert tracked.rollbacks == tracked.commits == 0, 'reader ended caller transaction'
            assert _transaction_identity(tracked) == before
            _assert_pin_availability(tracked, expected=False)
        assert tracked.rollbacks == tracked.commits == 0, 'reader ended caller transaction'
        assert _transaction_identity(conn) == before
        # Snapshot storage also owns a transaction-level shared pin. Keeping
        # this caller transaction open must keep excluding its writer.
        _assert_pin_availability(conn, expected=False)
    finally:
        conn.rollback()
    _assert_pin_availability(conn, expected=True)


def test_versioned_pin_preserves_healthy_read_only_transaction(conn, published):
    _assert_healthy_read_only_pin_preserved(conn)


def _assert_pin_availability(conn, *, expected):
    database = conn.execute('SELECT current_database()').fetchone()[0]
    with psycopg.connect(conn.info.dsn) as other:
        actual_database, available = other.execute(
            'SELECT current_database(),pg_try_advisory_lock(%s)',
            (publication.CORPUS_LOCK_KEY,)).fetchone()
        assert actual_database == database == conn.info.dbname
        assert available is expected


def _assert_failed_reader_body_rolled_back(conn, kind):
    inputs.require_schemas(conn)
    conn.execute('CREATE TEMP TABLE reader_pin_failure_marker (value integer)')
    conn.commit()
    primary = publication.CorpusIncoherent('reader body integrity refusal')
    expected = publication.CorpusIncoherent
    if kind == 'timeout':
        expected = psycopg.errors.QueryCanceled
    try:
        with pytest.raises(expected) as caught:
            with readers.pinned(conn, commit=False):
                _assert_pin_availability(conn, expected=False)
                conn.execute('INSERT INTO reader_pin_failure_marker VALUES (1)')
                if kind == 'timeout':
                    conn.execute("SET LOCAL statement_timeout='20ms'")
                    try:
                        conn.execute('SELECT pg_sleep(1)')
                    except psycopg.errors.QueryCanceled as exc:
                        primary = exc
                        raise
                    pytest.fail('actual PostgreSQL timeout did not fire')
                raise primary
        assert caught.value is primary
        if kind == 'timeout':
            assert caught.value.sqlstate == '57014'
        assert conn.execute('SELECT count(*) FROM reader_pin_failure_marker').fetchone()[0] == 0, \
            'failed reader body was not rolled back'
        _assert_pin_availability(conn, expected=True)
    finally:
        conn.rollback()


@pytest.mark.parametrize('kind', ['timeout', 'integrity'])
def test_versioned_pin_preserves_real_body_failure_and_rolls_back(conn, published, kind):
    _assert_failed_reader_body_rolled_back(conn, kind)


@contextmanager
def _former_exception_dispatch(conn, *, commit=True):
    with ExitStack() as stack:
        snapshot_reader = False
        try:
            pub = stack.enter_context(publication.pinned(conn, commit=commit))
        except publication.CorpusIncoherent as exc:
            if str(exc) != 'ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER':
                raise
            snapshot_reader = True
        if snapshot_reader:
            pub, _ = stack.enter_context(readers.snapshots.pinned(conn, commit=commit))
        from sentinel.feed import readiness_scope
        with readiness_scope.pinned(conn, pub):
            yield pub


def test_former_dispatch_falsifies_caller_transaction_preservation(conn, published, monkeypatch):
    monkeypatch.setattr(readers, 'pinned', _former_exception_dispatch)
    with pytest.raises(AssertionError, match='reader ended caller transaction'):
        _assert_healthy_read_only_pin_preserved(conn)


def test_removed_failed_body_rollback_is_detected(conn, published, monkeypatch):
    monkeypatch.setattr(publication._core, '_release_failed_pin',
                        lambda connection, _primary: publication._core._unlock_pin(connection))
    with pytest.raises(AssertionError, match='failed reader body was not rolled back'):
        _assert_failed_reader_body_rolled_back(conn, 'integrity')
    _assert_pin_availability(conn, expected=True)
