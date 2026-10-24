"""The actual PostgreSQL queue gives finite readers and publishers a turn."""
from contextlib import contextmanager
from datetime import timedelta
import threading
import time
import uuid

import psycopg
import pytest

from sentinel.feed import publication, rolling_jobs as jobs, store, writer_schedule
from tests.sentinel.test_corpus_publication import pg  # noqa: F401

KEY = publication.CORPUS_LOCK_KEY
SECRET = 'private-cleanup-detail-must-not-leak'


@pytest.fixture
def conn(pg, monkeypatch):
    monkeypatch.delenv(writer_schedule.shadow_budget.DEADLINE_ENV, raising=False)
    monkeypatch.setattr(writer_schedule.acquisition_work, 'remaining', lambda: None)
    value = psycopg.connect(pg.sync_dsn)
    value.execute('DROP TABLE IF EXISTS sentinel_snapshot_jobs CASCADE')
    value.execute('CREATE TABLE sentinel_snapshot_jobs ('
                  'job_id uuid PRIMARY KEY,state text,resume_state text,'
                  'deadline timestamptz,lease_until timestamptz,owner uuid,'
                  'fence bigint,candidate_id uuid,request jsonb,rows_done bigint,bytes_done bigint)')
    value.execute('DROP TABLE IF EXISTS corpus_schedule_marker')
    value.execute('CREATE TABLE corpus_schedule_marker (value integer)')
    value.execute('INSERT INTO corpus_schedule_marker VALUES (1)')
    value.commit()
    try:
        yield value
    finally:
        value.close()


def lease(conn, *, seconds=30):
    value = jobs.Lease(str(uuid.uuid4()), str(uuid.uuid4()), 1)
    conn.execute("INSERT INTO sentinel_snapshot_jobs VALUES (%s,'READY','READY',"
                 "clock_timestamp()+%s*interval '1 second',"
                 "clock_timestamp()+%s*interval '1 second',%s,1,NULL,'{}',0,0)",
                 (value.job_id, seconds, seconds, value.owner))
    conn.commit()
    return value


def _spawn(operation):
    outcome = {}
    def run():
        try:
            operation()
        except BaseException as exc:
            outcome['error'] = exc
        finally:
            outcome['done'] = True
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def _queued(conn, pid, outcome, *, seconds=8):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        row = conn.execute("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory'"
                           " AND pid=%s AND NOT granted AND mode='ExclusiveLock'"
                           " AND ((classid::bigint<<32)|objid::bigint)=%s)", (pid, KEY)).fetchone()
        conn.rollback()
        if row[0]:
            return
        if outcome.get('done'):
            break
        time.sleep(.01)
    raise AssertionError('writer never entered the PostgreSQL lock queue')


def _available(pg):
    with psycopg.connect(pg.sync_dsn) as other:
        assert other.execute('SELECT pg_try_advisory_lock(%s)', (KEY,)).fetchone()[0]


def _no_waiter(conn):
    assert conn.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory'"
                        " AND NOT granted AND ((classid::bigint<<32)|objid::bigint)=%s",
                        (KEY,)).fetchone()[0] == 0
    conn.rollback()


def _assert_priority(conn, pg, *, transaction_pin=False):
    owned = lease(conn)
    reader = psycopg.connect(pg.sync_dsn)
    writer = psycopg.connect(pg.sync_dsn)
    newcomer = psycopg.connect(pg.sync_dsn)
    pid = writer.info.backend_pid
    writing = threading.Event()
    finish = threading.Event()
    function = 'pg_advisory_xact_lock_shared' if transaction_pin else 'pg_advisory_lock_shared'
    reader.execute(f'SELECT {function}(%s)', (KEY,))
    if not transaction_pin:
        reader.commit()
    def mutate():
        with writer_schedule.turn(writer, owned):
            writing.set()
            assert finish.wait(8)
            writer.execute('UPDATE corpus_schedule_marker SET value=2')
            writer.commit()
    thread, outcome = _spawn(mutate)
    try:
        _queued(conn, pid, outcome)
        # Continuous fresh attempts cannot keep joining the original reader.
        for _ in range(25):
            assert not newcomer.execute('SELECT pg_try_advisory_lock_shared(%s)',
                                        (KEY,)).fetchone()[0]
            newcomer.rollback()
            assert reader.execute('SELECT value FROM corpus_schedule_marker').fetchone()[0] == 1
        assert not writing.is_set()
        # Same-session reader reentrancy remains legal despite the waiter.
        assert reader.execute('SELECT pg_try_advisory_lock_shared(%s)', (KEY,)).fetchone()[0]
        reader.execute('SELECT pg_advisory_unlock_shared(%s)', (KEY,))
        if transaction_pin:
            reader.rollback()
        else:
            reader.execute('SELECT pg_advisory_unlock_shared(%s)', (KEY,))
            reader.commit()
        assert writing.wait(8)
        assert not newcomer.execute('SELECT pg_try_advisory_lock_shared(%s)', (KEY,)).fetchone()[0]
        newcomer.rollback()
    finally:
        finish.set()
        reader.close()
        thread.join(10)
        writer.close()
        newcomer.close()
    assert not thread.is_alive()
    assert 'error' not in outcome, outcome
    assert conn.execute('SELECT value FROM corpus_schedule_marker').fetchone()[0] == 2
    conn.rollback()
    _available(pg)
    _no_waiter(conn)


@pytest.mark.parametrize('transaction_pin', [False, True])
def test_real_queue_blocks_fresh_readers_and_preserves_old_snapshot(conn, pg, transaction_pin):
    _assert_priority(conn, pg, transaction_pin=transaction_pin)


def test_removed_queue_falsifies_reader_priority(conn, pg, monkeypatch):
    @contextmanager
    def missing_turn(_conn, _lease):
        yield
    monkeypatch.setattr(writer_schedule, 'turn', missing_turn)
    with pytest.raises(AssertionError, match='never entered'):
        _assert_priority(conn, pg)


def test_original_store_context_remains_nonblocking(conn, pg):
    with psycopg.connect(pg.sync_dsn) as reader:
        reader.execute('SELECT pg_advisory_lock_shared(%s)', (KEY,))
        started = time.monotonic()
        with pytest.raises(publication.CorpusLockUnavailable):
            with store.corpus_write_lock(conn):
                pytest.fail('default writer bypassed a reader')
        assert time.monotonic() - started < 2
    conn.rollback()


def test_nested_turn_and_original_writer_context_balance_only_owned_counts(conn, pg, monkeypatch):
    owned = lease(conn)
    guards = []
    monkeypatch.setattr(store.backup_runtime_authority, 'require',
                        lambda *_args, **_kwargs: guards.append(True))
    with writer_schedule.turn(conn, owned):
        with store.corpus_write_lock(conn):
            with writer_schedule.turn(conn, owned):
                store._assert_corpus_locked(conn)
        store._assert_corpus_locked(conn)
        with psycopg.connect(pg.sync_dsn) as reader:
            assert not reader.execute('SELECT pg_try_advisory_lock_shared(%s)', (KEY,)).fetchone()[0]
    assert guards == [True]
    _available(pg)


@pytest.mark.parametrize('bound', ['maximum', 'existing', 'lease', 'deadline', 'child', 'work'])
def test_known_timeout_is_reusable_restores_settings_and_removes_waiter(conn, pg, monkeypatch, bound):
    owned = lease(conn)
    conn.execute("SET lock_timeout='2s'")
    conn.execute("SET statement_timeout='3s'")
    conn.commit()
    if bound == 'maximum':
        monkeypatch.setattr(writer_schedule, 'MAX_DRAIN_SECONDS', .5)
    elif bound == 'existing':
        conn.execute("SET lock_timeout='500ms'"); conn.commit()
    elif bound in {'lease', 'deadline'}:
        column = 'lease_until' if bound == 'lease' else 'deadline'
        conn.execute(f"UPDATE sentinel_snapshot_jobs SET {column}=clock_timestamp()+interval '500ms'")
        conn.commit()
    elif bound == 'child':
        deadline = writer_schedule.shadow_budget.now() + timedelta(seconds=.5)
        monkeypatch.setenv(writer_schedule.shadow_budget.DEADLINE_ENV, deadline.isoformat())
    else:
        monkeypatch.setattr(writer_schedule.acquisition_work, 'remaining', lambda: .5)
    original = conn.execute('SHOW lock_timeout').fetchone()[0]
    conn.commit()
    with psycopg.connect(pg.sync_dsn) as reader:
        reader.execute('SELECT pg_advisory_lock_shared(%s)', (KEY,))
        started = time.monotonic()
        with pytest.raises(publication.CorpusLockUnavailable) as caught:
            with writer_schedule.turn(conn, owned):
                pytest.fail('timeout yielded writer authority')
        assert time.monotonic() - started < 2
        assert caught.value.__cause__.sqlstate == '55P03'
        assert not conn.closed and not writer_schedule.connection_discarded(caught.value)
        assert conn.execute('SHOW lock_timeout').fetchone()[0] == original
        assert conn.execute('SHOW statement_timeout').fetchone()[0] == '3s'
        conn.rollback()
        _no_waiter(conn)
    _available(pg)


@pytest.mark.parametrize('change', ['lease', 'deadline', 'fence'])
def test_waiting_never_renews_or_uses_revoked_job_authority(conn, pg, change):
    owned = lease(conn)
    writer = psycopg.connect(pg.sync_dsn)
    with psycopg.connect(pg.sync_dsn) as reader:
        reader.execute('SELECT pg_advisory_lock_shared(%s)', (KEY,))
        def mutate():
            with writer_schedule.turn(writer, owned):
                pytest.fail('revoked waiting writer entered mutation')
        thread, outcome = _spawn(mutate)
        try:
            _queued(conn, writer.info.backend_pid, outcome)
            if change == 'fence':
                conn.execute('UPDATE sentinel_snapshot_jobs SET fence=fence+1')
            else:
                column = 'lease_until' if change == 'lease' else 'deadline'
                conn.execute(f"UPDATE sentinel_snapshot_jobs SET {column}=clock_timestamp()-interval '1s'")
            conn.commit()  # Must not block on a row lock held by the queued writer.
            reader.execute('SELECT pg_advisory_unlock_shared(%s)', (KEY,)); reader.commit()
            thread.join(8)
        finally:
            reader.close(); thread.join(10); writer.close()
    assert not thread.is_alive()
    assert isinstance(outcome.get('error'), jobs.JobRefused), outcome
    assert not writer_schedule.connection_discarded(outcome['error'])
    _available(pg)


def test_two_queued_writers_run_serially(conn, pg):
    first_lease, second_lease = lease(conn), lease(conn)
    first, second = psycopg.connect(pg.sync_dsn), psycopg.connect(pg.sync_dsn)
    first_entered, second_entered, release_first = threading.Event(), threading.Event(), threading.Event()
    def write(connection, owned, entered, hold=False):
        with writer_schedule.turn(connection, owned):
            entered.set()
            if hold:
                assert release_first.wait(8)
    with psycopg.connect(pg.sync_dsn) as reader:
        reader.execute('SELECT pg_advisory_lock_shared(%s)', (KEY,))
        one, result_one = _spawn(lambda: write(first, first_lease, first_entered, True))
        two = None
        try:
            _queued(conn, first.info.backend_pid, result_one)
            two, result_two = _spawn(lambda: write(second, second_lease, second_entered))
            _queued(conn, second.info.backend_pid, result_two)
            reader.execute('SELECT pg_advisory_unlock_shared(%s)', (KEY,)); reader.commit()
            assert first_entered.wait(8) and not second_entered.is_set()
            release_first.set()
            one.join(8); two.join(8)
            assert second_entered.is_set()
            assert 'error' not in result_one and 'error' not in result_two
        finally:
            release_first.set(); reader.close(); one.join(10)
            if two is not None:
                two.join(10)
            first.close(); second.close()
    _available(pg)


class FaultCursor:
    def __init__(self, owner, inner):
        self.owner, self.inner, self.acquiring = owner, inner, False

    def __enter__(self):
        self.inner.__enter__(); return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def execute(self, query, params=None):
        self.acquiring = 'SELECT pg_advisory_lock(' in query
        if 'SELECT pg_advisory_unlock(' in query and self.owner.fault == 'unlock':
            raise self.owner.error
        result = self.inner.execute(query, params)
        if self.acquiring and self.owner.fault == 'acquire_statement':
            raise self.owner.error
        return result

    def fetchone(self):
        result = self.inner.fetchone()
        if self.acquiring and self.owner.fault == 'acquire_fetch':
            raise self.owner.error
        return result


class FaultConnection:
    def __init__(self, inner, fault, *, close_error=False, error=None):
        self.inner, self.fault, self.close_error = inner, fault, close_error
        self.error = error or psycopg.OperationalError(SECRET)
        self.commits = self.closes = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def cursor(self):
        return FaultCursor(self, self.inner.cursor())

    def commit(self):
        self.commits += 1
        if self.fault == f'commit_{self.commits}':
            raise self.error
        result = self.inner.commit()
        if self.fault == f'commit_after_{self.commits}':
            raise self.error
        return result

    def close(self):
        self.closes += 1
        self.inner.close()
        if self.close_error:
            raise psycopg.OperationalError(SECRET)


@pytest.mark.parametrize('fault', ['acquire_statement', 'acquire_fetch', 'commit_1',
                                  'commit_2', 'commit_after_2', 'commit_3', 'unlock'])
def test_unknown_acquisition_commit_or_unlock_discards_session(conn, pg, fault):
    owned = lease(conn)
    proxy = FaultConnection(conn, fault)
    with pytest.raises(psycopg.OperationalError) as caught:
        with writer_schedule.turn(proxy, owned):
            pass
    assert caught.value is proxy.error
    assert conn.closed and proxy.closes == 1
    assert writer_schedule.connection_discarded(caught.value)
    _available(pg)


@pytest.mark.parametrize('primary', [KeyboardInterrupt, SystemExit, psycopg.errors.QueryCanceled])
def test_interrupted_acquisition_preserves_primary_and_closes(conn, pg, primary):
    owned = lease(conn)
    original = primary(SECRET)
    proxy = FaultConnection(conn, 'acquire_fetch', error=original)
    with pytest.raises(primary) as caught:
        with writer_schedule.turn(proxy, owned):
            pytest.fail('uncertain acquisition entered body')
    assert caught.value is original and conn.closed
    assert writer_schedule.connection_discarded(original)
    _available(pg)


def test_real_cancel_removes_queued_session_without_hiding_primary(conn, pg):
    owned = lease(conn)
    writer = psycopg.connect(pg.sync_dsn)
    with psycopg.connect(pg.sync_dsn) as reader:
        reader.execute('SELECT pg_advisory_lock_shared(%s)', (KEY,))
        def mutate():
            with writer_schedule.turn(writer, owned):
                pytest.fail('cancelled acquisition entered body')
        thread, outcome = _spawn(mutate)
        try:
            _queued(conn, writer.info.backend_pid, outcome)
            writer.cancel()
            thread.join(8)
        finally:
            reader.close(); thread.join(10); writer.close()
    assert isinstance(outcome.get('error'), psycopg.errors.QueryCanceled), outcome
    assert writer_schedule.connection_discarded(outcome['error'])
    _available(pg); _no_waiter(conn)


@pytest.mark.parametrize('fault', ['none', 'unlock'])
def test_primary_integrity_failure_survives_cleanup(conn, pg, fault):
    owned = lease(conn)
    proxy = FaultConnection(conn, fault, close_error=fault == 'unlock')
    primary = publication.CorpusIncoherent('authenticated state changed')
    with pytest.raises(publication.CorpusIncoherent) as caught:
        with writer_schedule.turn(proxy, owned):
            raise primary
    assert caught.value is primary
    assert writer_schedule.connection_discarded(primary) == (fault == 'unlock')
    assert (not conn.closed) == (fault == 'none')
    if fault == 'unlock':
        notes = '\n'.join(primary.__notes__)
        assert 'OperationalError' in notes and SECRET not in notes
    _available(pg)
