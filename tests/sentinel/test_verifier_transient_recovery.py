"""Temporary SQL refusal cannot reset owner, retry, observer or proof clocks."""
from datetime import datetime, timedelta, timezone
import inspect
from threading import Lock
from types import SimpleNamespace
import time
import uuid

import psycopg
from psycopg.errors import LockNotAvailable, QueryCanceled
import pytest

from sentinel.panel import model, read_projection, verification_service as verifier
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)


class Connection:
    closed = False
    broken = False

    def __init__(self, outcomes=()):
        self.outcomes = iter(outcomes)
        self.executions = self.commits = self.rollbacks = 0
        self.isolation_statements = 0

    def execute(self, query, params=None):
        if params is None:
            assert query == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'
            self.isolation_statements += 1
            return SimpleNamespace()
        self.executions += 1
        answer = next(self.outcomes, (NOW+timedelta(seconds=610), NOW))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer()
        return SimpleNamespace(fetchone=lambda: answer)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def loop(monkeypatch):
    clock = [0.0]
    heartbeats, waits, refreshed = [], [], []
    class Stop:
        done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            waits.append(seconds)
            clock[0] += seconds
            assert clock[0] < 40, 'retry deadline was reset'
            if seconds == 15:
                self.done = True
            return self.done
    stopped = Stop()
    monkeypatch.setattr(verifier, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(verifier, 'HEARTBEAT', SimpleNamespace(
        write_text=lambda text, **kwargs: heartbeats.append(text)))
    monkeypatch.setattr(verifier, '_refresh_readers', lambda *args: refreshed.append(args))
    return SimpleNamespace(clock=clock, heartbeats=heartbeats, waits=waits,
                           refreshed=refreshed, stopped=stopped)


def run_loop(loop, connection, *, readers=None, previous=None, deadline=100):
    verifier._run_owned_loop(connection, readers or {}, 'private-fixture', 'owned',
        {} if previous is None else previous, loop.stopped, deadline)


def test_statement_and_lock_timeouts_rollback_on_same_owned_session(loop):
    connection = Connection([QueryCanceled('temporary statement timeout'),
                             LockNotAvailable('temporary lock timeout')])
    run_loop(loop, connection)
    assert connection.executions == 3 and connection.rollbacks == 2
    assert len(loop.refreshed) == len(loop.heartbeats) == 1
    assert loop.refreshed[0][0] is connection
    assert loop.waits == [.5, .5, 15]


def assert_retry_window_does_not_reset(loop, monkeypatch):
    def failed_publication(*args):
        raise QueryCanceled('temporary projection write timeout')
    monkeypatch.setattr(verifier, '_refresh_readers', failed_publication)
    connection = Connection()
    with pytest.raises((TimeoutError, QueryCanceled)):
        run_loop(loop, connection)
    assert loop.clock[0] == 20
    assert connection.commits > 1  # Successful renewals cannot move the retry bound.
    assert not loop.heartbeats


def test_repeated_timeout_and_successful_renewals_keep_first_retry_bound(loop, monkeypatch):
    assert_retry_window_does_not_reset(loop, monkeypatch)


def test_removed_first_failure_retry_anchor_is_detected(loop, monkeypatch):
    source = inspect.getsource(verifier._run_owned_loop)
    assert source.count('if retry_until is None:') == 1
    namespace = {}
    exec(compile(source.replace('if retry_until is None:', 'if True:'),
         '<reset-retry-clock>', 'exec'), verifier.__dict__, namespace)
    monkeypatch.setattr(verifier, '_run_owned_loop', namespace['_run_owned_loop'])
    with pytest.raises(AssertionError, match='retry deadline was reset'):
        assert_retry_window_does_not_reset(loop, monkeypatch)


def test_retry_is_capped_by_original_owner_expiry(loop):
    class AlwaysTimedOut(Connection):
        def execute(self, *args):
            self.executions += 1
            raise QueryCanceled('temporary timeout')
    with pytest.raises((TimeoutError, QueryCanceled)):
        run_loop(loop, AlwaysTimedOut(), deadline=1.2)
    assert loop.clock[0] == 1.2
    assert loop.waits[-1] == pytest.approx(.2)
    assert not loop.refreshed and not loop.heartbeats


@pytest.mark.parametrize('error', [psycopg.OperationalError('connection lost'),
    psycopg.errors.InsufficientPrivilege('not permitted'), ValueError('integrity failure')])
def test_connection_loss_and_semantic_failures_are_not_retried(loop, error):
    with pytest.raises(type(error)):
        run_loop(loop, Connection([error]))
    assert not loop.waits and not loop.refreshed and not loop.heartbeats


@pytest.mark.parametrize('flag', ['closed', 'broken'])
def test_timeout_cannot_reuse_a_lost_connection(loop, flag):
    connection = Connection([QueryCanceled('timeout then connection loss')])
    setattr(connection, flag, True)
    with pytest.raises(QueryCanceled):
        run_loop(loop, connection)
    assert connection.rollbacks == 1 and not loop.waits


def test_stop_during_retry_admits_no_new_reader_or_health(loop):
    loop.stopped.wait = lambda _: setattr(loop.stopped, 'done', True)
    connection = Connection([QueryCanceled('temporary timeout')])
    run_loop(loop, connection)
    assert connection.executions == 1
    assert not loop.refreshed and not loop.heartbeats


def test_foreign_owner_stops_before_reader_or_health(loop):
    with pytest.raises(ValueError, match='ownership lost'):
        run_loop(loop, Connection([None]))
    assert not loop.refreshed and not loop.heartbeats and not loop.waits


def test_known_expired_owner_is_not_renewed(loop):
    connection = Connection()
    with pytest.raises(ValueError, match='ownership expired'):
        verifier._renew_owner(connection, 'owned', 0)
    assert connection.executions == connection.commits == 0


def test_owner_deadline_counts_claim_roundtrip_time(loop):
    loop.clock[0] = 7
    assert verifier._owner_deadline(0, (NOW+timedelta(seconds=610), NOW)) == 610
    assert verifier._owner_deadline(0, (NOW+timedelta(seconds=700), NOW)) == 610


def test_completed_claim_cannot_revive_elapsed_ownership(loop):
    loop.clock[0] = 611
    with pytest.raises(ValueError, match='ownership expired'):
        verifier._owner_deadline(0, (NOW+timedelta(seconds=610), NOW))


def assert_late_renewal_is_not_committed(loop):
    def delayed_result():
        loop.clock[0] = 2
        return NOW+timedelta(seconds=610), NOW
    connection = Connection([delayed_result])
    with pytest.raises(ValueError):
        verifier._renew_owner(connection, 'owned', 1)
    assert connection.rollbacks == 1 and connection.commits == 0


def test_late_renewal_is_rolled_back_before_commit(loop):
    assert_late_renewal_is_not_committed(loop)


def test_removed_renewal_completion_deadline_is_detected(loop, monkeypatch):
    source = inspect.getsource(verifier._renew_owner)
    old = "    if not time.monotonic() < deadline:\n        conn.rollback()\n        raise ValueError('verifier ownership expired during renewal')\n"
    assert source.count(old) == 1
    namespace = {}
    exec(compile(source.replace(old, ''), '<late-owner-renewal>', 'exec'),
         verifier.__dict__, namespace)
    monkeypatch.setattr(verifier, '_renew_owner', namespace['_renew_owner'])
    with pytest.raises(AssertionError):
        assert_late_renewal_is_not_committed(loop)


def test_commit_that_outlives_known_ownership_admits_no_reader(loop):
    connection = Connection()
    def late_commit():
        loop.clock[0] = 101
    connection.commit = late_commit
    with pytest.raises(ValueError, match='expired during commit'):
        run_loop(loop, connection)
    assert not loop.refreshed and not loop.heartbeats


def test_retry_preserves_original_receipt_and_existing_reader(loop, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'isolated-qualification-key-'+'x'*32)
    observed = datetime.now(timezone.utc)
    rows = [model.Row(key, key, 'verified', model.OK, as_of=observed,
                     freshness=timedelta(seconds=600)) for key in sorted(read_projection.SHADOW_KEYS)]
    reader = SimpleNamespace(lock=Lock(), configuration='a'*64,
                             completed=(rows, [], observed), read=lambda *a, **k: None,
                             attempt_state=lambda: None)
    monkeypatch.setattr(verifier, '_refresh_readers', _ORIGINAL_REFRESH)
    monkeypatch.setattr(read_projection, 'subject', lambda *a: 'a'*64)
    published = []
    def publish(*args, **kwargs):
        published.append(kwargs['value'])
        if len(published) == 1:
            raise QueryCanceled('temporary projection write refusal')
    monkeypatch.setattr(read_projection, 'publish', publish)
    previous = {}
    connection = Connection()
    run_loop(loop, connection, readers={'SHADOW': reader}, previous=previous)
    assert connection.isolation_statements == 2
    assert len(published) == 2 and published[0] == published[1]
    assert published[1]['observed_at'] == observed.isoformat()
    assert published[1]['valid_until'] == (observed+timedelta(seconds=600)).isoformat()
    assert previous['SHADOW'][0] == published[1]
    assert len(loop.heartbeats) == 1


_ORIGINAL_REFRESH = verifier._refresh_readers


def owned_row(conn, *, expires="INTERVAL '610 seconds'", other=False):
    conn.execute(f'CREATE TABLE {verifier.schema.OWNER} '
        '(id INTEGER PRIMARY KEY,owner_id UUID NOT NULL,expires_at TIMESTAMPTZ NOT NULL)')
    owner = uuid.uuid4()
    row = conn.execute(f'INSERT INTO {verifier.schema.OWNER} '
        f'VALUES (1,%s,clock_timestamp()+{expires}) RETURNING expires_at,clock_timestamp()',
        (uuid.uuid4() if other else owner,)).fetchone()
    conn.commit()
    return owner, row


def test_real_statement_timeout_recovers_with_same_session_and_advisory_lock(conn, monkeypatch):
    started = time.monotonic()
    owner, row = owned_row(conn)
    assert conn.execute('SELECT pg_try_advisory_lock(%s,%s)', verifier.OWNER_LOCK).fetchone()[0]
    original_pid = conn.execute('SELECT pg_backend_pid()').fetchone()[0]
    conn.execute("SET statement_timeout='75ms'");conn.commit()
    locker = psycopg.connect(conn.info.dsn)
    contender = psycopg.connect(conn.info.dsn)
    seen, heartbeats = [], []
    monkeypatch.setattr(verifier, 'HEARTBEAT', SimpleNamespace(write_text=lambda *a, **k: heartbeats.append(True)))
    class Stop:
        done = False
        def is_set(self): return self.done
        def wait(self, seconds):
            if seconds < 1:
                assert not contender.execute('SELECT pg_try_advisory_lock(%s,%s)', verifier.OWNER_LOCK).fetchone()[0]
                locker.rollback()
            else:
                self.done = True
    def refresh(*args):
        assert args[0] is conn
        assert conn.execute('SELECT pg_backend_pid()').fetchone()[0] == original_pid
        assert not contender.execute('SELECT pg_try_advisory_lock(%s,%s)', verifier.OWNER_LOCK).fetchone()[0]
        seen.append(True)
    monkeypatch.setattr(verifier, '_refresh_readers', refresh)
    try:
        locker.execute(f'SELECT id FROM {verifier.schema.OWNER} FOR UPDATE')
        verifier._run_owned_loop(conn, {}, conn.info.dsn, owner, {}, Stop(),
                                  verifier._owner_deadline(started, row))
        assert seen == heartbeats == [True]
    finally:
        locker.rollback();locker.close();contender.close()


@pytest.mark.parametrize('other,expires', [(False, "INTERVAL '-1 second'"), (True, "INTERVAL '610 seconds'")])
def test_real_expired_or_foreign_owner_cannot_be_renewed(conn, other, expires):
    owner, _ = owned_row(conn, expires=expires, other=other)
    before = conn.execute(f'SELECT owner_id,expires_at FROM {verifier.schema.OWNER}').fetchone()
    with pytest.raises(ValueError, match='ownership lost'):
        verifier._renew_owner(conn, owner, time.monotonic()+100)
    conn.rollback()
    assert conn.execute(f'SELECT owner_id,expires_at FROM {verifier.schema.OWNER}').fetchone() == before
