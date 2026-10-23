"""The actual coordinator nests queued turns around unchanged mutation guards.

Provider and database responses are deterministic local fixtures. The real
PostgreSQL queue/fairness tests live in test_corpus_writer_scheduling.py; these
tests retain the actual turn, store guards, and coordinator exception ordering.
"""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import shadow_dependency_notifications as notices
from sentinel.feed import operational_snapshot, retention, rolling_publisher as publisher
from sentinel.feed import writer_schedule
from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusLockUnavailable
from sentinel.feed.rolling_contract import digest


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None
        self.uncertain = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=()):
        connection = self.connection
        assert not connection.closed, 'SQL attempted on disposed connection'
        phase = connection.phase
        if statement.startswith("SELECT current_setting('lock_timeout')"):
            self.row = ('0', Decimal('0'))
        elif statement.startswith("SELECT set_config('lock_timeout'"):
            self.row = (params[0],)
        elif statement == 'SELECT pg_advisory_lock(%s)':
            assert params == (CORPUS_LOCK_KEY,)
            assert connection.depth == 0
            connection.depth += 1
            connection.events.append(('turn', phase, 'enter'))
            self.row = (None,)
            self.uncertain = phase == connection.unknown_phase
        elif statement == 'SELECT pg_try_advisory_lock(%s)':
            assert params == (CORPUS_LOCK_KEY,)
            assert connection.depth == 1, 'original guard entered without queued turn'
            connection.depth += 1
            connection.events.append(('original', phase, 'enter'))
            self.row = (True,)
        elif statement == 'SELECT pg_advisory_unlock(%s)':
            assert params == (CORPUS_LOCK_KEY,)
            assert connection.depth in (1, 2)
            kind = 'original' if connection.depth == 2 else 'turn'
            connection.events.append((kind, phase, 'exit'))
            connection.depth -= 1
            if not connection.depth:
                connection.completed_turns += 1
            self.row = (True,)
        else:
            raise AssertionError('Unexpected database operation: '+statement)

    def fetchone(self):
        if self.uncertain:
            self.uncertain = False
            raise self.connection.unknown_response
        return self.row


class _Connection:
    def __init__(self, *, ready=False, unknown_phase=None, failed_close=False):
        self.events = []
        self.closed = False
        self.depth = 0
        self.completed_turns = 0
        self.phases = ['freeze', 'publication'] if ready else ['freeze', 'build', 'publication']
        self.unknown_phase = unknown_phase
        self.unknown_response = psycopg.OperationalError('lost acquisition response')
        self.failed_close = failed_close
        self.close_calls = 0
        self.database_calls_after_close_attempt = 0

    @property
    def phase(self):
        return self.phases[min(self.completed_turns, len(self.phases)-1)]

    def _usable(self):
        if self.close_calls:
            self.database_calls_after_close_attempt += 1
        assert not self.closed, 'transaction attempted on disposed connection'

    def cursor(self):
        self._usable()
        return _Cursor(self)

    def commit(self):
        self._usable()

    def rollback(self):
        self._usable()

    def close(self):
        self.close_calls += 1
        if self.failed_close:
            raise RuntimeError('independent close failure')
        self.closed = True
        self.depth = 0


def _coordinator(monkeypatch, *, ready=False, failure_phase=None,
                 unknown_phase=None, failed_close=False):
    """Replace external observations while keeping coordinator and both locks."""
    connection = _Connection(ready=ready, unknown_phase=unknown_phase,
                             failed_close=failed_close)
    lease = SimpleNamespace(owner='private-fixture-owner', job_id='fixture-job')
    request = SimpleNamespace(window='fixture-window')
    source_payload = {'source_corrections': {'fixture': 1}}
    reference_payload = {'tickers': []}
    manifest = SimpleNamespace(source_evidence_sha256=digest(source_payload),
                               reference_sha256=digest(reference_payload))
    failure = CorpusLockUnavailable('original phase failure')
    recorded, cleared = [], []
    monkeypatch.delenv('SENTINEL_SHADOW_ADVANCE_DEADLINE_UTC', raising=False)
    # Use the named constant rather than assume a particular environment spelling.
    from sentinel import shadow_budget
    monkeypatch.delenv(shadow_budget.DEADLINE_ENV, raising=False)
    monkeypatch.setattr(notices.supervisor_io, 'report', lambda *_: None)
    monkeypatch.setattr(publisher.runtime_schema, 'require_feed_schema', lambda _: None)
    monkeypatch.setattr(operational_snapshot, 'registered', lambda *_: True)
    monkeypatch.setattr(operational_snapshot, 'published', lambda *_: None)
    monkeypatch.setattr(publisher.identity, 'require_feed_producer_identity', lambda: {})
    monkeypatch.setattr(publisher.jobs, 'claim', lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(publisher.jobs.PreparationRequest, 'model_validate', lambda _: request)
    monkeypatch.setattr(publisher.jobs, 'status', lambda *_: {
        'request': {}, 'state': 'READY' if ready else 'ACQUIRING',
        'candidate_id': 'candidate', 'remaining_seconds': 600})
    monkeypatch.setattr(publisher.jobs, 'heartbeat', lambda *_args, **_kwargs: None)

    def owned(_connection, actual_lease):
        assert actual_lease is lease and not connection.closed
        now = datetime.now(timezone.utc)
        row = [None]*11
        row[2] = now+timedelta(seconds=600)
        row[3] = now+timedelta(seconds=600)
        row[10] = now
        return row
    monkeypatch.setattr(publisher.jobs, '_owned', owned)

    def guard(_connection, *, operation):
        if operation == 'corpus writer mutation':
            assert connection.depth == 2
            connection.events.append(('guard', connection.phase, 'checked'))
        else:
            assert operation == 'operational publication preflight'
            assert connection.depth == 0
    monkeypatch.setattr(publisher.backup_runtime_authority, 'require_staging', guard)
    monkeypatch.setattr(publisher.backup_runtime_authority, 'require', guard)

    def body(phase):
        assert connection.depth == 2, 'mutation ran without both original and queued guards'
        connection.events.append(('body', phase, 'run'))
        if phase == failure_phase:
            raise failure

    monkeypatch.setattr(operational_snapshot, 'freeze', lambda *_: body('freeze'))
    monkeypatch.setattr(publisher.rolling_builder, 'build', lambda *_: body('build'))
    def publish(*_args, **_kwargs):
        body('publication')
        return {'publication': 'fixture-published'}
    monkeypatch.setattr(operational_snapshot, 'publish', publish)

    class Source:
        provider = 'ALPACA_OPENFIGI'
        parts = SimpleNamespace(unit=lambda: nullcontext())
        def preflight(self):
            assert connection.depth == 0
        def references(self, _checkpoint):
            assert connection.depth == 0
        def acquire_prices(self, _checkpoint, _pulse):
            assert connection.depth == 0
        def corroborate(self):
            assert connection.depth == 0
        def reference_payload(self):
            return reference_payload
        def source_payload(self):
            return source_payload
    source = Source()
    monkeypatch.setattr(publisher, '_operational_source', lambda *_args, **_kwargs: source)
    monkeypatch.setattr(publisher.rolling_store, 'manifest', lambda *_: manifest)
    monkeypatch.setattr(publisher.rolling_store, 'load_evidence',
                        lambda _, key: source_payload if key == manifest.source_evidence_sha256
                        else reference_payload)
    monkeypatch.setattr(operational_snapshot, 'validate', lambda *_: None)
    monkeypatch.setattr(publisher.acquisition_work, 'budget', lambda **_: nullcontext())
    monkeypatch.setattr(publisher.progress, 'phase', lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(publisher, '_record_failure',
                        lambda _connection, _lease, exc, **_: recorded.append(exc))
    monkeypatch.setattr(publisher.staging, 'clear',
                        lambda _connection, **_: cleared.append('scratch'))
    monkeypatch.setattr(retention, 'maintain', lambda _: cleared.append('maintenance'))
    return SimpleNamespace(connection=connection, lease=lease, failure=failure,
                           recorded=recorded, cleared=cleared)


def _assert_scopes(monkeypatch, *, ready=False):
    fixture = _coordinator(monkeypatch, ready=ready)
    assert publisher._prepare(fixture.connection, 'fixture-job', operational=True) == {
        'publication': 'fixture-published'}
    expected = []
    for phase in fixture.connection.phases:
        expected.extend([('turn', phase, 'enter'), ('original', phase, 'enter'),
                         ('guard', phase, 'checked'), ('body', phase, 'run'),
                         ('original', phase, 'exit'), ('turn', phase, 'exit')])
    assert fixture.connection.events == expected
    assert fixture.connection.depth == 0 and fixture.connection.close_calls == 0
    assert fixture.recorded == [] and fixture.cleared == ['scratch', 'maintenance']


@pytest.mark.parametrize('ready', [False, True], ids=['acquiring-three-scopes', 'ready-skips-build'])
def test_coordinator_queues_before_unchanged_guards(monkeypatch, ready):
    _assert_scopes(monkeypatch, ready=ready)


@pytest.mark.parametrize('phase,stage', [('freeze', 'ACQUISITION_LOCK'),
                                      ('build', 'CANDIDATE_BUILD'),
                                      ('publication', 'PUBLICATION')])
def test_phase_failure_balances_both_locks_and_retains_original_diagnostic(monkeypatch, phase, stage):
    fixture = _coordinator(monkeypatch, failure_phase=phase)
    with pytest.raises(CorpusLockUnavailable) as caught:
        publisher._prepare(fixture.connection, 'fixture-job', operational=True)
    assert caught.value is fixture.failure
    context = getattr(fixture.failure, '_sentinel_dependency_context')
    assert isinstance(context, notices.FailureContext) and context.stage == stage
    assert fixture.recorded == [fixture.failure]
    assert fixture.cleared == ['scratch', 'maintenance']
    assert fixture.connection.depth == 0 and not fixture.connection.closed
    assert fixture.connection.events[-2:] == [('original', phase, 'exit'), ('turn', phase, 'exit')]


@pytest.mark.parametrize('phase,stage', [('freeze', 'ACQUISITION_LOCK'),
                                      ('build', 'CANDIDATE_BUILD'),
                                      ('publication', 'PUBLICATION')])
def test_unknown_acquisition_response_disposes_and_skips_publisher_database_cleanup(monkeypatch, phase, stage):
    fixture = _coordinator(monkeypatch, unknown_phase=phase)
    with pytest.raises(psycopg.OperationalError) as caught:
        publisher._prepare(fixture.connection, 'fixture-job', operational=True)
    assert caught.value is fixture.connection.unknown_response
    assert writer_schedule.connection_discarded(caught.value)
    assert caught.value._sentinel_dependency_context.stage == stage
    assert fixture.connection.closed and fixture.connection.close_calls == 1
    assert fixture.connection.database_calls_after_close_attempt == 0
    assert fixture.recorded == [] and fixture.cleared == []
    assert ('original', phase, 'enter') not in fixture.connection.events
    assert ('body', phase, 'run') not in fixture.connection.events


def test_disposal_failure_still_preserves_original_error_and_skips_bookkeeping(monkeypatch):
    fixture = _coordinator(monkeypatch, unknown_phase='freeze', failed_close=True)
    with pytest.raises(psycopg.OperationalError) as caught:
        publisher._prepare(fixture.connection, 'fixture-job', operational=True)
    assert caught.value is fixture.connection.unknown_response
    assert writer_schedule.connection_discarded(caught.value)
    assert not fixture.connection.closed and fixture.connection.close_calls == 1
    assert fixture.connection.database_calls_after_close_attempt == 0
    assert fixture.recorded == [] and fixture.cleared == []
    assert any('session disposal failed: RuntimeError' in note for note in caught.value.__notes__)


def test_missing_turn_is_detected_by_coordinator_falsifier(monkeypatch):
    monkeypatch.setattr(writer_schedule, 'turn', lambda *_: nullcontext())
    with pytest.raises(AssertionError):
        _assert_scopes(monkeypatch)


def test_missing_original_guard_is_detected_by_coordinator_falsifier(monkeypatch):
    monkeypatch.setattr(publisher.store, 'acquisition_write_lock', lambda *_: nullcontext())
    with pytest.raises(AssertionError):
        _assert_scopes(monkeypatch)
