"""Read refusal is not completed financial evidence; clocks and facts survive."""
from datetime import datetime, timezone
import inspect
from types import SimpleNamespace

from psycopg.errors import LockNotAvailable, QueryCanceled
import pytest

from sentinel import shadow_runtime
from sentinel.feed import store
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.panel import authority_reader as reader, model, sources
from sentinel.panel import read_projection, shadow_source_wait, verification_service as verifier
from tests.sentinel.test_corpus_publication import pg  # noqa: F401


NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)


class Clock:
    now = 0.0

    def __init__(self):
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= .5
        self.waits.append(seconds)
        assert len(self.waits) <= 40, 'retry window reset'
        self.now += seconds


@pytest.fixture
def projection(monkeypatch):
    connections = []

    class Connection:
        closed = False

        def execute(self, *args):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    def connect(*args, **kwargs):
        connection = Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(store, 'connect', connect)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *args: None)
    monkeypatch.setattr(read_projection, 'subject_for', lambda *args: 'exact-subject')
    monkeypatch.setattr(shadow_source_wait, 'observe_preparation', lambda *args: None)
    return connections


@pytest.mark.parametrize('error_type', [QueryCanceled, LockNotAvailable])
@pytest.mark.parametrize('stage', ['shadow', 'paper'])
def test_source_propagates_only_explicitly_requested_typed_sql_refusal(projection, monkeypatch, error_type, stage):
    def unavailable(*args, **kwargs):
        raise error_type('bounded SQL refusal')
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', unavailable)
    if stage == 'paper':
        monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', lambda *args, **kwargs: SimpleNamespace(
            shadow_verdict='SHADOW_GO', verification='VERIFIED', session='2031-01-01',
            sessions_lag=0, strategy_nav='50000', strategy_cumulative_return='0'))
        monkeypatch.setattr(sources, '_verified_shadow_book_rows', lambda *args, **kwargs: ([], []))
        monkeypatch.setattr(sources, '_dual_paper_row', unavailable)
    ordinary = sources._dual_authority_rows('dbname=fixture', now=NOW, include_paper=stage == 'paper')
    assert any(row.status == model.UNKNOWN for row in ordinary[0]) and ordinary[3]
    with pytest.raises(error_type):
        sources._dual_authority_rows('dbname=fixture', now=NOW, include_paper=stage == 'paper',
                                     propagate_read_unavailability=True)
    assert len(projection) == 2 and all(conn.closed for conn in projection)


@pytest.mark.parametrize('error_type', [QueryCanceled, LockNotAvailable])
def test_book_adapter_does_not_swallow_typed_read_failure(monkeypatch, error_type):
    result = SimpleNamespace(state=SimpleNamespace(to_dict=lambda: {}), session='2031-01-01')
    monkeypatch.setattr(sources, '_state_view', lambda *args, **kwargs: {})
    def unavailable(*args):
        raise error_type('bounded plan read refusal')
    monkeypatch.setattr(sources, '_current_plan', unavailable)
    ordinary = sources._verified_shadow_book_rows(None, result, verified=True, now=NOW)
    assert all(row.status == model.UNKNOWN for row in ordinary[0]) and ordinary[1]
    with pytest.raises(error_type):
        sources._verified_shadow_book_rows(None, result, verified=True, now=NOW,
                                           propagate_read_unavailability=True)


@pytest.mark.parametrize('paper', [False, True])
def test_verifier_retries_complete_observation_on_fresh_connection(projection, monkeypatch, paper):
    calls = []
    clock = Clock()
    retry = reader.retry_observation_read
    monkeypatch.setattr(reader, 'retry_observation_read', lambda operation: retry(
        operation, clock=clock, sleep=clock.sleep))
    def observe(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise QueryCanceled('statement timeout')
        if paper:
            return model.paper_reconciliation_row(state='CLEAN')
        return SimpleNamespace(shadow_verdict='SHADOW_GO', verification='VERIFIED',
            session='2031-01-01', sessions_lag=0, strategy_nav='50000',
            strategy_cumulative_return='0')
    monkeypatch.setattr(sources, '_dual_paper_row', observe)
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', observe)
    monkeypatch.setattr(sources, '_verified_shadow_book_rows', lambda *args, **kwargs: (
        [model.Row(key, key, 'verified', model.OK) for key in ('exposure', 'book', 'terminals')], []))
    result = verifier.observe('dbname=fixture', paper, 'exact-subject')
    assert result['errors'] == [] and all(row['status'] == model.OK for row in result['rows'])
    assert len(calls) == len(projection) == 2 and clock.waits == [.5]
    assert all(connection.closed for connection in projection)


@pytest.mark.parametrize('error', [ValueError('corrupt book'), RuntimeError('QueryCanceled'),
                                  TimeoutError('unclassified timeout')])
def test_untyped_errors_and_completed_negative_facts_are_not_retried(error):
    clock = Clock()
    calls = []
    def failed():
        calls.append(True)
        raise error
    with pytest.raises(type(error)):
        reader.retry_observation_read(failed, clock=clock, sleep=clock.sleep)
    negative = {'errors': ['integrity failure'], 'rows': []}
    assert reader.retry_observation_read(lambda: negative, clock=clock, sleep=clock.sleep) is negative
    assert len(calls) == 1 and not clock.waits


@pytest.mark.parametrize('cost,expected', [(0, 20), (299, 300)])
def test_mixed_typed_refusals_share_first_window_and_original_work_budget(cost, expected):
    clock = Clock()
    calls = []
    errors = (QueryCanceled, CorpusLockUnavailable, LockNotAvailable)
    def failed():
        if not calls:
            clock.now += cost
        assert clock.now < expected, 'attempt admitted after original boundary'
        calls.append(True)
        raise errors[len(calls) % 3]('bounded refusal')
    with pytest.raises((QueryCanceled, CorpusLockUnavailable, LockNotAvailable)):
        reader.retry_observation_read(failed, clock=clock, sleep=clock.sleep)
    assert clock.now == expected


def test_admitted_full_read_may_finish_after_retry_window_but_not_work_deadline():
    for cost in (91, 300):
        clock = Clock()
        calls = []
        answer = object()
        def attempt():
            calls.append(True)
            if len(calls) == 1:
                raise QueryCanceled('first bounded read refused')
            clock.now += cost
            return answer
        if cost == 91:
            assert reader.retry_observation_read(attempt, clock=clock, sleep=clock.sleep) is answer
        else:
            with pytest.raises(TimeoutError, match='work deadline'):
                reader.retry_observation_read(attempt, clock=clock, sleep=clock.sleep)
        assert len(calls) == 2


def test_subject_change_during_availability_retry_is_not_retried(projection, monkeypatch):
    subject = ['exact-subject']
    clock = Clock()
    calls = []
    monkeypatch.setattr(read_projection, 'subject_for', lambda *args: subject[0])
    def sleep(seconds):
        clock.sleep(seconds)
        subject[0] = 'changed-subject'
    retry = reader.retry_observation_read
    monkeypatch.setattr(reader, 'retry_observation_read', lambda operation: retry(
        operation, clock=clock, sleep=sleep))
    def unavailable(*args, **kwargs):
        calls.append(True)
        raise QueryCanceled('temporary read refusal')
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', unavailable)
    with pytest.raises(ValueError, match='subject changed before'):
        verifier.observe('dbname=fixture', False, 'exact-subject')
    assert len(calls) == len(projection) == 1


def test_removed_sql_propagation_guard_is_detected(projection, monkeypatch):
    source = inspect.getsource(sources._dual_authority_rows)
    guard = 'if propagate_read_unavailability and isinstance(exc, (QueryCanceled, LockNotAvailable)):'
    assert source.count(guard) == 2
    namespace = {}
    exec(compile(source.replace(guard, 'if False:'), '<swallowed-sql-refusal>', 'exec'),
         vars(sources), namespace)
    monkeypatch.setattr(sources, '_dual_authority_rows', namespace['_dual_authority_rows'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_source_propagates_only_explicitly_requested_typed_sql_refusal(projection, monkeypatch, QueryCanceled, 'shadow')


def test_removed_retry_admission_boundary_is_detected(monkeypatch):
    source = inspect.getsource(reader._retry_read)
    namespace = {}
    exec(compile(source.replace('if clock() >= retry_deadline:', 'if False:'),
                 '<late-read-attempt>', 'exec'), vars(reader), namespace)
    monkeypatch.setattr(reader, '_retry_read', namespace['_retry_read'])
    with pytest.raises(AssertionError, match='attempt admitted after original boundary'):
        test_mixed_typed_refusals_share_first_window_and_original_work_budget(0, 20)


def test_removed_book_read_propagation_is_detected(monkeypatch):
    source = inspect.getsource(sources._verified_shadow_book_rows)
    guard = 'if propagate_read_unavailability and isinstance(exc, (QueryCanceled, LockNotAvailable)):'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if False:'), '<swallowed-book-read>', 'exec'),
         vars(sources), namespace)
    monkeypatch.setattr(sources, '_verified_shadow_book_rows', namespace['_verified_shadow_book_rows'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_book_adapter_does_not_swallow_typed_read_failure(monkeypatch, QueryCanceled)


def test_removed_work_completion_deadline_is_detected(monkeypatch):
    source = inspect.getsource(reader._retry_read)
    namespace = {}
    exec(compile(source.replace('if clock() >= work_deadline:', 'if False:'),
                 '<late-completed-read>', 'exec'), vars(reader), namespace)
    monkeypatch.setattr(reader, '_retry_read', namespace['_retry_read'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_admitted_full_read_may_finish_after_retry_window_but_not_work_deadline()


def test_real_statement_timeout_reopens_transaction_and_recovers(pg, monkeypatch):
    """Real 57014 travels through the source adapter and finite verifier."""
    calls, connections = [], []
    connect = store.connect
    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(store, 'connect', tracked)
    monkeypatch.setattr(read_projection, 'subject_for', lambda *args: 'exact-subject')
    monkeypatch.setattr(shadow_source_wait, 'observe_preparation', lambda *args: None)
    def verify(connection, **kwargs):
        calls.append(True)
        connection.execute('BEGIN TRANSACTION READ ONLY')
        if len(calls) == 1:
            connection.execute("SET LOCAL statement_timeout = '50ms'")
            connection.execute('SELECT pg_sleep(0.2)')
            pytest.fail('fixture did not exercise real PostgreSQL cancellation')
        assert connection.execute('SELECT 1').fetchone() == (1,)
        return SimpleNamespace(shadow_verdict='SHADOW_GO', verification='VERIFIED',
            session='2031-01-01', sessions_lag=0, strategy_nav='50000',
            strategy_cumulative_return='0')
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', verify)
    monkeypatch.setattr(sources, '_verified_shadow_book_rows', lambda *args, **kwargs: (
        [model.Row(key, key, 'verified', model.OK) for key in ('exposure', 'book', 'terminals')], []))
    value = verifier.observe(pg.sync_dsn, False, 'exact-subject')
    assert len(calls) == len(connections) == 2 and all(conn.closed for conn in connections)
    assert not value['errors'] and all(row['status'] == model.OK for row in value['rows'])
