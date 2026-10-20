"""A failed corpus reader keeps its primary error and releases its session pin."""
from contextlib import contextmanager

import psycopg
import pytest

from sentinel import automation_runtime, rolling_runtime, shadow_runtime, shadow_worker
from sentinel.automation.model import TransientInfrastructureFailure
from sentinel.feed import publication
from sentinel.feed.schema import DDL as FEED_DDL
from sentinel.feed.universe_projection import DDL as PROJECTION_DDL
from tests.sentinel.test_corpus_publication import pg  # noqa: F401


SECRET = "cleanup-detail-must-not-be-retained"
MARKER = "test_corpus_pin_failure_marker"


@pytest.fixture
def conn(pg, monkeypatch):
    # Install real DDL explicitly in the ephemeral cluster. Runtime validators
    # remain read-only; this module does not opt into legacy validator shims.
    connection = psycopg.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(psycopg.sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                psycopg.sql.Identifier(table)))
        for statement in (*FEED_DDL, *PROJECTION_DDL):
            cur.execute(statement)
    connection.commit()
    monkeypatch.setenv(publication.RECEIPT_KEY_ENV, "corpus-pin-unit-key-" * 4)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def published(conn):
    publication.publish(conn)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {MARKER} (value integer)")
    conn.execute(f"TRUNCATE {MARKER}")
    conn.commit()
    return conn


def _mark(conn):
    conn.execute(f"INSERT INTO {MARKER} VALUES (1)")


def _marker_count(conn):
    return conn.execute(f"SELECT count(*) FROM {MARKER}").fetchone()[0]


def _exclusive_available(pg):
    with psycopg.connect(pg.sync_dsn) as other:
        assert other.execute("SELECT pg_try_advisory_lock(%s)",
                             (publication.CORPUS_LOCK_KEY,)).fetchone()[0]


def _timeout(conn, errors):
    conn.execute("SET LOCAL statement_timeout='20ms'")
    try:
        conn.execute("SELECT pg_sleep(1)")
    except psycopg.errors.QueryCanceled as exc:
        errors.append(exc)
        raise


def _assert_body_timeout(conn, pg, *, commit=True):
    errors = []
    try:
        with publication.pinned(conn, commit=commit):
            _mark(conn)
            _timeout(conn, errors)
    except BaseException as exc:
        assert isinstance(exc, psycopg.errors.QueryCanceled)
        assert exc is errors[0]
        assert exc.sqlstate == "57014"
    else:
        pytest.fail("the failed body was accepted")
    assert _marker_count(conn) == 0
    conn.rollback()
    _exclusive_available(pg)
    with publication.pinned(conn):
        assert conn.execute("SELECT 42").fetchone()[0] == 42


@pytest.mark.parametrize("commit", [True, False])
def test_real_body_timeout_preserves_primary_and_releases_pin(published, pg, commit):
    _assert_body_timeout(published, pg, commit=commit)


def test_lookup_timeout_after_acquisition_preserves_primary(published, pg, monkeypatch):
    errors = []
    original = publication._core.require_current

    def timed_lookup(conn):
        _mark(conn)
        _timeout(conn, errors)

    monkeypatch.setattr(publication._core, "require_current", timed_lookup)
    with pytest.raises(psycopg.errors.QueryCanceled) as caught:
        with publication.pinned(published):
            pytest.fail("lookup failure yielded publication authority")
    assert caught.value is errors[0]
    assert _marker_count(published) == 0
    published.rollback()
    _exclusive_available(pg)
    monkeypatch.setattr(publication._core, "require_current", original)
    with publication.pinned(published):
        pass


def _assert_integrity_cleanup(conn, pg):
    primary = publication.CorpusIncoherent("authenticated state differs")
    with pytest.raises(publication.CorpusIncoherent) as caught:
        with publication.pinned(conn):
            _mark(conn)
            raise primary
    assert caught.value is primary
    assert not isinstance(automation_runtime.classify_dependency_failure(primary),
                          TransientInfrastructureFailure)
    assert _marker_count(conn) == 0
    conn.rollback()
    _exclusive_available(pg)


def test_integrity_error_is_preserved_without_committing_body(published, pg):
    _assert_integrity_cleanup(published, pg)


@pytest.mark.parametrize("commit", [True, False])
def test_success_keeps_the_requested_transaction_boundary(published, pg, commit):
    with publication.pinned(published, commit=commit):
        _mark(published)
    with psycopg.connect(pg.sync_dsn) as other:
        assert _marker_count(other) == int(commit)
    _exclusive_available(pg)
    published.rollback()
    assert _marker_count(published) == int(commit)


class FaultCursor:
    def __init__(self, owner, inner):
        self.owner, self.inner = owner, inner
        self.acquiring = False

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def execute(self, query, params=None):
        self.acquiring = "pg_try_advisory_lock_shared" in query
        if "pg_advisory_unlock_shared" in query and self.owner.fault == "unlock":
            raise self.owner.error
        result = self.inner.execute(query, params)
        if self.acquiring and self.owner.fault == "acquire_statement":
            # The real server owns the lock before the simulated response loss.
            raise self.owner.error
        return result

    def fetchone(self):
        result = self.inner.fetchone()
        if self.acquiring and self.owner.fault == "acquire_fetch":
            raise self.owner.error
        return result


class FaultConnection:
    """Fail one boundary while retaining real PostgreSQL transaction/lock state."""
    def __init__(self, inner, fault, *, close_error=False):
        self.inner, self.fault = inner, fault
        self.close_error = close_error
        self.error = psycopg.errors.QueryCanceled(SECRET)
        self.rollbacks = self.closes = self.commits = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def cursor(self, *args, **kwargs):
        return FaultCursor(self, self.inner.cursor(*args, **kwargs))

    def rollback(self):
        self.rollbacks += 1
        if ((self.fault == "rollback" and self.rollbacks == 1)
                or (self.fault == "final_rollback" and self.rollbacks == 2)):
            raise self.error
        return self.inner.rollback()

    def commit(self):
        self.commits += 1
        if self.fault == "commit":
            raise self.error
        result = self.inner.commit()
        if self.fault == "commit_after":
            raise self.error
        return result

    def close(self):
        self.closes += 1
        self.inner.close()
        if self.close_error:
            raise psycopg.OperationalError(SECRET)


@pytest.mark.parametrize("fault", ["rollback", "unlock", "final_rollback"])
@pytest.mark.parametrize("primary_kind", ["timeout", "integrity"])
def test_failed_cleanup_discards_real_session_and_preserves_primary(
        published, pg, fault, primary_kind):
    proxy = FaultConnection(published, fault)
    errors = []
    integrity = publication.CorpusIncoherent("retained state differs")
    expected = (psycopg.errors.QueryCanceled if primary_kind == "timeout"
                else publication.CorpusIncoherent)
    with pytest.raises(expected) as caught:
        with publication.pinned(proxy):
            _mark(proxy)
            if primary_kind == "timeout":
                _timeout(proxy, errors)
            raise integrity
    assert caught.value is (errors[0] if primary_kind == "timeout" else integrity)
    assert published.closed and proxy.closes == 1 and proxy.commits == 0
    notes = "\n".join(caught.value.__notes__)
    assert "QueryCanceled SQLSTATE=57014" in notes and SECRET not in notes
    _exclusive_available(pg)
    with psycopg.connect(pg.sync_dsn) as other:
        assert _marker_count(other) == 0


def test_disposal_error_is_retained_without_replacing_primary(published, pg):
    proxy = FaultConnection(published, "unlock", close_error=True)
    primary = publication.CorpusIncoherent("retained state differs")
    with pytest.raises(publication.CorpusIncoherent) as caught:
        with publication.pinned(proxy):
            raise primary
    assert caught.value is primary and proxy.closes == 1 and published.closed
    notes = "\n".join(primary.__notes__)
    assert "session disposal failed: OperationalError" in notes
    assert SECRET not in notes
    _exclusive_available(pg)


def test_successful_body_cannot_commit_after_unlock_failure(published, pg):
    proxy = FaultConnection(published, "unlock")
    with pytest.raises(psycopg.errors.QueryCanceled) as caught:
        with publication.pinned(proxy):
            _mark(proxy)
    assert caught.value is proxy.error
    assert proxy.commits == 0 and published.closed and proxy.closes == 1
    _exclusive_available(pg)
    with psycopg.connect(pg.sync_dsn) as other:
        assert _marker_count(other) == 0


@pytest.mark.parametrize("fault", ["commit", "commit_after"])
def test_commit_failure_discards_session_and_preserves_uncertain_outcome(
        published, pg, fault):
    proxy = FaultConnection(published, fault)
    with pytest.raises(psycopg.errors.QueryCanceled) as caught:
        with publication.pinned(proxy):
            _mark(proxy)
    assert caught.value is proxy.error
    assert proxy.commits == 1 and published.closed and proxy.closes == 1
    _exclusive_available(pg)
    with psycopg.connect(pg.sync_dsn) as other:
        # Lost commit acknowledgement is not evidence that the body rolled back.
        assert _marker_count(other) == int(fault == "commit_after")


@pytest.mark.parametrize("fault", ["acquire_statement", "acquire_fetch"])
def test_unknown_acquisition_discards_possibly_pinned_session(published, pg, fault):
    proxy = FaultConnection(published, fault)
    with pytest.raises(psycopg.errors.QueryCanceled) as caught:
        with publication.pinned(proxy):
            pytest.fail("unknown acquisition yielded publication authority")
    assert caught.value is proxy.error
    assert published.closed and proxy.closes == 1 and proxy.commits == 0
    _exclusive_available(pg)


def test_known_false_acquisition_keeps_ordinary_contention(published, pg):
    proxy = FaultConnection(published, "none")
    with psycopg.connect(pg.sync_dsn) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (publication.CORPUS_LOCK_KEY,))
        with pytest.raises(publication.CorpusLockUnavailable):
            with publication.pinned(proxy):
                pytest.fail("contended corpus was readable")
        assert not published.closed and proxy.closes == 0
    published.rollback()
    assert published.execute("SELECT 42").fetchone()[0] == 42


@pytest.mark.parametrize("kind", ["timeout", "integrity"])
def test_public_shadow_wrapper_preserves_failure_from_inside_real_pin(
        published, pg, monkeypatch, kind):
    errors = []
    integrity = shadow_runtime.ShadowRuntimeRefused("authenticated state differs")

    def failed_status(conn, **_kwargs):
        with publication.pinned(conn):
            try:
                _timeout(conn, errors)
            except psycopg.errors.QueryCanceled as exc:
                if kind == "integrity":
                    raise integrity from exc
                raise

    monkeypatch.setattr(rolling_runtime, "selected", lambda _: True)
    monkeypatch.setattr(rolling_runtime, "status", failed_status)
    expected = (psycopg.errors.QueryCanceled if kind == "timeout"
                else shadow_runtime.ShadowRuntimeRefused)
    with pytest.raises(expected) as caught:
        shadow_runtime.verified_shadow_status(
            published, observation_id="fixture", starting_cash=50000)
    assert caught.value is (errors[0] if kind == "timeout" else integrity)
    assert shadow_worker._availability_failure(caught.value) == (kind == "timeout")
    classified = automation_runtime.classify_dependency_failure(caught.value)
    assert isinstance(classified, TransientInfrastructureFailure) == (kind == "timeout")
    _exclusive_available(pg)


def test_unexplained_aborted_transaction_does_not_become_retryable():
    failure = psycopg.errors.InFailedSqlTransaction("unknown failed transaction")
    assert automation_runtime.classify_dependency_failure(failure) is None
    assert not shadow_worker._availability_failure(failure)


@contextmanager
def _former_unconditional_cleanup(conn, *, commit=True):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock_shared(%s)",
                    (publication.CORPUS_LOCK_KEY,))
        assert cur.fetchone()[0]
    try:
        yield publication._core.require_current(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock_shared(%s)",
                        (publication.CORPUS_LOCK_KEY,))
        if commit:
            conn.commit()


def test_former_cleanup_fails_real_body_timeout_assertion(published, pg, monkeypatch):
    monkeypatch.setattr(publication._core, "pinned", _former_unconditional_cleanup)
    try:
        with pytest.raises(AssertionError):
            _assert_body_timeout(published, pg)
    finally:
        published.close()


def test_former_cleanup_fails_integrity_rollback_assertion(published, pg, monkeypatch):
    monkeypatch.setattr(publication._core, "pinned", _former_unconditional_cleanup)
    with pytest.raises(AssertionError):
        _assert_integrity_cleanup(published, pg)
