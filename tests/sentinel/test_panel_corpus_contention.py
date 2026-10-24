"""A refused source pin is retried inside one finite display observation."""
from datetime import datetime, timezone
import inspect
from threading import Event
from types import SimpleNamespace

import pytest

from sentinel import shadow_runtime
from sentinel.feed import _publication_impl as core, store
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.panel import authority_reader as reader, model, sources
from sentinel.panel import verification_monitor as monitor
from tests.sentinel.test_corpus_publication import pg
from tests.sentinel.test_panel_authority_reader import complete, result


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= reader.CORPUS_LOCK_POLL_SECONDS
        self.waits.append(seconds)
        self.now += seconds


def test_retry_budget_is_fixed_and_capped_by_original_work_deadline():
    for initial_cost, expected in ((0, reader.CORPUS_LOCK_RETRY_SECONDS),
                                   (reader.DEADLINE_SECONDS - 1, reader.DEADLINE_SECONDS)):
        clock = Clock()
        calls = []
        def busy():
            if not calls:
                clock.now += initial_cost
            calls.append(True)
            raise CorpusLockUnavailable('writer owns the corpus')
        with pytest.raises(CorpusLockUnavailable):
            reader.retry_corpus_lock(busy, clock=clock, sleep=clock.sleep)
        assert clock.now == expected
        assert len(clock.waits) <= reader.CORPUS_LOCK_RETRY_SECONDS / reader.CORPUS_LOCK_POLL_SECONDS


@pytest.mark.parametrize('error', [ValueError('changed evidence'), TimeoutError('stalled reader')])
def test_other_errors_are_not_retried(error):
    clock = Clock()
    calls = []
    def fail():
        calls.append(True)
        raise error
    with pytest.raises(type(error)):
        reader.retry_corpus_lock(fail, clock=clock, sleep=clock.sleep)
    assert len(calls) == 1 and clock.waits == []


def test_success_after_refused_pin_preserves_semantic_negative_result():
    clock = Clock()
    negative = object()
    calls = []
    def attempt():
        calls.append(True)
        if len(calls) < 3:
            raise CorpusLockUnavailable('busy')
        return negative
    assert reader.retry_corpus_lock(attempt, clock=clock, sleep=clock.sleep) is negative
    assert clock.now == 1 and len(calls) == 3


def test_source_propagates_only_typed_contention_and_closes_connection(monkeypatch):
    connections = []
    class Connection:
        closed = False
        def close(self):
            self.closed = True
    def connect(*_):
        connection = Connection()
        connections.append(connection)
        return connection
    monkeypatch.setattr(store, 'connect', connect)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    def busy(*_, **__):
        raise CorpusLockUnavailable('busy')
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', busy)
    arguments = dict(now=datetime.now(timezone.utc), include_paper=False)
    ordinary = sources._dual_authority_rows('fixture', **arguments)
    assert ordinary[0][0].status == model.UNKNOWN and ordinary[3]
    with pytest.raises(CorpusLockUnavailable):
        sources._dual_authority_rows('fixture', **arguments, propagate_corpus_lock=True)
    def corrupt(*_, **__):
        raise ValueError('invalid book')
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', corrupt)
    invalid = sources._dual_authority_rows('fixture', **arguments, propagate_corpus_lock=True)
    assert invalid[0][0].status == model.UNKNOWN and invalid[3]
    assert len(connections) == 3 and all(c.closed for c in connections)


def test_identity_change_during_retry_refuses_the_old_expected_key(monkeypatch):
    identity = ['before']
    clock = Clock()
    monkeypatch.setattr(monitor, 'shadow_evidence', lambda *_: identity[0])
    expected = reader._key('fixture', False, 'before')
    calls = []
    def busy(*_, **__):
        calls.append(True)
        raise CorpusLockUnavailable('busy')
    monkeypatch.setattr(sources, '_dual_authority_rows', busy)
    retry = reader.retry_corpus_lock
    def sleep(seconds):
        clock.sleep(seconds)
        identity[0] = 'after'
    monkeypatch.setattr(reader, 'retry_corpus_lock', lambda operation: retry(
        operation, clock=clock, sleep=sleep))
    with pytest.raises(ValueError, match='evidence changed before'):
        monitor.observe_shadow('fixture', False, expected)
    assert len(calls) == 1


def test_exhausted_contention_is_not_cached_for_five_minutes():
    clock = Clock()
    scheduler_clock = [0.0]
    healthy = [False]
    def attempt():
        if not healthy[0]:
            raise CorpusLockUnavailable('writer still owns the corpus')
        return result()
    value = reader.Reader(runner=lambda *a, **k: reader.retry_corpus_lock(
        attempt, clock=clock, sleep=clock.sleep),
        evidence_reader=lambda *_: 'unchanged', clock=lambda: scheduler_clock[0])
    value.read('fixture')
    complete(value)
    failed = value.read('fixture')
    assert failed[0][0].status == model.UNKNOWN
    assert value.completed is None and value.failure is not None
    healthy[0] = True
    scheduler_clock[0] = reader.RETRY_SECONDS + 1
    value.read('fixture')
    complete(value)
    recovered = value.read('fixture')
    assert recovered[0][0].status == model.OK and not recovered[3]


def test_real_exclusive_pin_collision_recovers_without_cached_red(pg, monkeypatch):
    """Actual PG locks + source exception + finite observer + Reader publication."""
    writer = store.connect(pg.sync_dsn)
    writer.execute('SELECT pg_advisory_lock(%s)', (core.CORPUS_LOCK_KEY,))
    writer.commit()
    collision = Event()
    attempts = []
    connections = []
    original_connect = store.connect
    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        connections.append(conn)
        return conn
    def verify(conn, **_):
        attempts.append(True)
        try:
            with core.pinned(conn):
                return SimpleNamespace(shadow_verdict='SHADOW_GO', verification='VERIFIED',
                    session='2026-10-21', sessions_lag=0, strategy_nav='50000',
                    strategy_cumulative_return='0')
        except CorpusLockUnavailable:
            collision.set()
            raise
    monkeypatch.setattr(store, 'connect', connect)
    monkeypatch.setattr(core, 'require_current', lambda _: object())
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', verify)
    monkeypatch.setattr(sources, '_verified_shadow_book_rows', lambda *a, **k: (
        [model.Row(key, key, 'verified', model.OK) for key in ('exposure', 'book', 'terminals')], []))
    monkeypatch.setattr(monitor, 'shadow_evidence', lambda *_: 'fixed-book-and-source')
    value = reader.Reader(runner=lambda operation, *args, **_: operation(*args),
        observer=monitor.observe_shadow, evidence_reader=monitor.shadow_evidence)
    try:
        value.read(pg.sync_dsn, include_paper=False)
        assert collision.wait(3), 'test did not exercise the native lock refusal'
        pending = value.read(pg.sync_dsn, include_paper=False)
        assert value.pending is not None and value.failure is None
        assert pending[0][0].status == model.WARN and not pending[3]
        writer.execute('SELECT pg_advisory_unlock(%s)', (core.CORPUS_LOCK_KEY,))
        writer.commit()
        complete(value)
        rows, _, _, errors = value.read(pg.sync_dsn, include_paper=False)
        assert rows[0].status == model.OK and not errors
        assert value.failure is None and len(attempts) >= 2
        assert all(connection.closed for connection in connections)
    finally:
        writer.close()
        complete(value)


def test_removing_retry_deadline_breaks_its_falsifier(monkeypatch):
    source = inspect.getsource(reader.retry_corpus_lock)
    source = source.replace('if remaining <= 0:', 'if False:')
    namespace = {}
    exec(compile(source, 'unbounded-lock-retry', 'exec'), vars(reader), namespace)
    monkeypatch.setattr(reader, 'retry_corpus_lock', namespace['retry_corpus_lock'])
    with pytest.raises(AssertionError):
        test_retry_budget_is_fixed_and_capped_by_original_work_deadline()


def test_retrying_all_errors_breaks_its_falsifier(monkeypatch):
    source = inspect.getsource(reader.retry_corpus_lock)
    source = source.replace('except CorpusLockUnavailable:', 'except Exception:')
    namespace = {}
    exec(compile(source, 'overbroad-lock-retry', 'exec'), vars(reader), namespace)
    monkeypatch.setattr(reader, 'retry_corpus_lock', namespace['retry_corpus_lock'])
    with pytest.raises(AssertionError):
        test_other_errors_are_not_retried(ValueError('invalid book'))


def test_swallowing_typed_contention_breaks_its_falsifier(monkeypatch):
    source = inspect.getsource(sources._dual_authority_rows)
    guard = 'if propagate_corpus_lock and isinstance(exc, CorpusLockUnavailable):'
    assert source.count(guard) == 2
    source = source.replace(guard, 'if False:')
    namespace = {}
    exec(compile(source, 'swallowed-lock-refusal', 'exec'), vars(sources), namespace)
    monkeypatch.setattr(sources, '_dual_authority_rows', namespace['_dual_authority_rows'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_source_propagates_only_typed_contention_and_closes_connection(monkeypatch)
