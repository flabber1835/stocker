"""Enclosing source owners cannot reuse a disposed session or replace its error."""
from datetime import datetime, timezone
from decimal import Decimal
import inspect

import psycopg
import pytest

from sentinel import retained_go, rolling_recovery, rolling_runtime, shadow_budget, shadow_service, shadow_worker
from sentinel.feed import acquisition_parts, preparation_wait, rolling_go_inputs as inputs, writer_schedule
from sentinel.feed.publication import CorpusLockUnavailable


class Connection:
    def __init__(self, *, disposed, closed=False):
        self.disposed = disposed
        self.closed = closed
        self.calls = []

    def rollback(self):
        self.calls.append('rollback')
        assert not self.disposed, 'disposed session reused'

    def close(self):
        self.calls.append('close')
        assert not self.disposed, 'disposed session reused'
        self.closed = True


def primary(kind, *, disposed=True):
    value = {'interrupt': KeyboardInterrupt, 'exit': SystemExit,
             'database': psycopg.errors.QueryCanceled}[kind]('original source failure')
    if disposed:
        setattr(value, writer_schedule._DISCARDED, True)
    return value


def go_owner(monkeypatch, entry, error, connection):
    monkeypatch.setattr(inputs, 'require_schemas', lambda _: None)
    monkeypatch.setattr(inputs, 'require_first_deployment', lambda _: None)
    monkeypatch.setattr(inputs.snapshots, 'source_final_session', lambda: '2026-09-15')

    def failure(_):
        raise error
    monkeypatch.setattr(inputs, 'current', failure)
    with pytest.raises(type(error)) as caught:
        getattr(inputs, entry)(connection, target_session='2026-09-15')
    assert caught.value is error
    return caught.value


@pytest.mark.parametrize('entry', ['prepare', '_prepare'])
@pytest.mark.parametrize('kind', ['interrupt', 'exit', 'database'])
@pytest.mark.parametrize('closed', [False, True], ids=['close-failed', 'closed'])
def test_go_owner_preserves_disposed_primary_without_database_cleanup(
        monkeypatch, entry, kind, closed):
    connection = Connection(disposed=True, closed=closed)
    go_owner(monkeypatch, entry, primary(kind), connection)
    assert connection.calls == []


@pytest.mark.parametrize('entry', ['prepare', '_prepare'])
def test_removed_go_owner_disposal_guard_is_detected(monkeypatch, entry):
    source = inspect.getsource(getattr(inputs, entry))
    guard = 'if not writer_schedule.connection_discarded(exc):'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if True:'), 'unguarded disposed GO owner', 'exec'),
         inputs.__dict__, namespace)
    monkeypatch.setattr(inputs, entry, namespace[entry])
    with pytest.raises(AssertionError, match='disposed session reused'):
        test_go_owner_preserves_disposed_primary_without_database_cleanup(
            monkeypatch, entry, 'interrupt', False)


@pytest.mark.parametrize('entry,rollbacks', [('prepare', 2), ('_prepare', 1)])
def test_healthy_go_owner_keeps_original_rollback(monkeypatch, entry, rollbacks):
    connection = Connection(disposed=False)
    error = RuntimeError('ordinary source refusal')
    go_owner(monkeypatch, entry, error, connection)
    assert connection.calls == ['rollback'] * rollbacks


def service_owner(monkeypatch, error, connection):
    monkeypatch.setattr(shadow_budget, 'cutoff', lambda: datetime(2026, 9, 16, tzinfo=timezone.utc))
    monkeypatch.setattr(shadow_service, 'preflight', lambda *a, **k: {
        'input_contract': rolling_runtime.SCHEMA, 'status': 'ATTESTED_STRUCTURAL'})
    monkeypatch.setattr(shadow_service, '_causal_target', lambda **kwargs: '2026-09-15')
    monkeypatch.setattr(shadow_service.feed_store, 'connect', lambda _: connection)
    monkeypatch.setattr(shadow_worker, '_availability_failure', lambda _: False)

    def failure(*args, **kwargs):
        raise error
    monkeypatch.setattr(rolling_runtime, 'service_advance', failure)
    config = shadow_service.ShadowServiceConfig('private-fixture', 'fixture', Decimal('100000'),
        shadow_service.shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    return shadow_service.advance_once(config)


@pytest.mark.parametrize('kind', ['interrupt', 'exit', 'database'])
@pytest.mark.parametrize('closed', [False, True], ids=['close-failed', 'closed'])
def test_shadow_owner_preserves_disposed_primary_without_translation_or_cleanup(
        monkeypatch, kind, closed):
    connection = Connection(disposed=True, closed=closed)
    error = primary(kind)
    with pytest.raises(type(error)) as caught:
        service_owner(monkeypatch, error, connection)
    assert caught.value is error
    assert connection.calls == []


def test_removed_shadow_owner_disposal_guard_is_detected(monkeypatch):
    source = inspect.getsource(shadow_service.advance_once)
    guard = 'if not discard_connection:'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if True:'), 'unguarded disposed shadow owner', 'exec'),
         shadow_service.__dict__, namespace)
    monkeypatch.setattr(shadow_service, 'advance_once', namespace['advance_once'])
    with pytest.raises(AssertionError, match='disposed session reused'):
        test_shadow_owner_preserves_disposed_primary_without_translation_or_cleanup(
            monkeypatch, 'interrupt', False)


def test_healthy_shadow_owner_keeps_original_classification_and_cleanup(monkeypatch):
    connection = Connection(disposed=False)
    error = RuntimeError('ordinary source refusal')
    with pytest.raises(shadow_service.ShadowServiceRefused) as caught:
        service_owner(monkeypatch, error, connection)
    assert caught.value.__cause__ is error
    assert connection.calls == ['rollback', 'close']


def wait_failure(kind):
    if kind == 'revision':
        error = acquisition_parts.SourceRevision('TICKERS', 'a' * 64, 'b' * 64)
    else:
        error = {'busy': CorpusLockUnavailable, 'connection': ConnectionError}[kind]('original source failure')
    setattr(error, writer_schedule._DISCARDED, True)
    return error


@pytest.mark.parametrize('entry,kind', [('run', 'revision'), ('run', 'busy'),
    ('run', 'connection'), ('once', 'revision')])
@pytest.mark.parametrize('closed', [False, True], ids=['close-failed', 'closed'])
def test_preparation_wait_preserves_disposed_primary_without_retry_or_successor(
        monkeypatch, entry, kind, closed):
    connection = Connection(disposed=True, closed=closed)
    error = wait_failure(kind)
    stages = []

    def prepare(*args):
        stages.append('prepare')
        raise error
    monkeypatch.setattr(preparation_wait.jobs, 'status',
        lambda *a: pytest.fail('disposed worker read job status'))
    monkeypatch.setattr(acquisition_parts, 'successor',
        lambda *a: pytest.fail('disposed worker created a source successor'))
    kwargs = {'prepare': prepare, 'check_target': lambda: stages.append('target')}
    if entry == 'run':
        kwargs['sleep'] = lambda _: pytest.fail('disposed worker retried')
    with pytest.raises(type(error)) as caught:
        getattr(preparation_wait, entry)(connection, 'original-job', **kwargs)
    assert caught.value is error and connection.calls == []
    assert stages == ['target', 'prepare']


@pytest.mark.parametrize('entry,kind,index', [('run', 'revision', 0),
    ('run', 'busy', 1), ('once', 'revision', 0)])
def test_removed_preparation_wait_disposal_guard_is_detected(monkeypatch, entry, kind, index):
    source = inspect.getsource(getattr(preparation_wait, entry))
    guard = 'if writer_schedule.connection_discarded(exc):'
    assert source.count(guard) == (2 if entry == 'run' else 1)
    position = source.index(guard)
    if index:
        position = source.index(guard, position + len(guard))
    source = source[:position] + source[position:].replace(guard, 'if False:', 1)
    namespace = {}
    exec(compile(source, 'unguarded disposed preparation wait', 'exec'),
         preparation_wait.__dict__, namespace)
    monkeypatch.setattr(preparation_wait, entry, namespace[entry])
    with pytest.raises(AssertionError, match='disposed session reused'):
        test_preparation_wait_preserves_disposed_primary_without_retry_or_successor(
            monkeypatch, entry, kind, False)


@pytest.mark.parametrize('entry', ['run', 'once'])
def test_healthy_revision_keeps_its_bounded_successor_behavior(monkeypatch, entry):
    connection = Connection(disposed=False)
    error = acquisition_parts.SourceRevision('TICKERS', 'a' * 64, 'b' * 64)
    attempts, successors = [], []
    receipt = object()

    def prepare(_conn, job):
        attempts.append(job)
        if len(attempts) == 1:
            raise error
        return receipt

    def successor(conn, job, component):
        assert conn is connection
        successors.append((job, component))
        return 'successor-job'
    monkeypatch.setattr(acquisition_parts, 'successor', successor)
    kwargs = {'prepare': prepare, 'check_target': lambda: None}
    if entry == 'run':
        assert preparation_wait.run(connection, 'original-job', **kwargs) is receipt
        assert attempts == ['original-job', 'successor-job']
    else:
        with pytest.raises(preparation_wait.jobs.JobWaiting) as caught:
            preparation_wait.once(connection, 'original-job', **kwargs)
        assert caught.value.__cause__ is error and attempts == ['original-job']
    assert successors == [('original-job', 'TICKERS')]
    assert connection.calls == ['rollback']


def test_healthy_preparation_retry_keeps_transactions_closed_before_wait(monkeypatch):
    connection = Connection(disposed=False)
    attempts = []
    receipt = object()

    def prepare(*args):
        attempts.append(args[1])
        if len(attempts) == 1:
            raise ConnectionError('ordinary availability failure')
        return receipt
    monkeypatch.setattr(preparation_wait.jobs, 'status', lambda *a: {
        'state': 'RETRY_WAIT', 'remaining_seconds': 100, 'retry_seconds': 0,
        'owner': None, 'reason': 'SOURCE_RETRY'})
    assert preparation_wait.run(connection, 'original-job', prepare=prepare,
        check_target=lambda: None, sleep=lambda _: pytest.fail('zero-delay retry slept')) is receipt
    assert attempts == ['original-job', 'original-job']
    assert connection.calls == ['rollback'] * 3


def recovery_owner(monkeypatch, error, connection):
    monkeypatch.setattr(rolling_recovery.inputs, 'require_schemas', lambda _: None)
    monkeypatch.setattr(rolling_recovery.initial, '_context', lambda *a: {})

    def failure(*args, **kwargs):
        raise error
    monkeypatch.setattr(rolling_recovery, '_prepare_missing', failure)
    return rolling_recovery.advance_one(connection, through='2026-09-15',
        observation_id='fixture', starting_cash=Decimal('100000'))


@pytest.mark.parametrize('kind', ['interrupt', 'exit', 'database'])
@pytest.mark.parametrize('closed', [False, True], ids=['close-failed', 'closed'])
def test_recovery_owner_preserves_disposed_primary_without_cleanup(monkeypatch, kind, closed):
    connection = Connection(disposed=True, closed=closed)
    error = primary(kind)
    with pytest.raises(type(error)) as caught:
        recovery_owner(monkeypatch, error, connection)
    assert caught.value is error and connection.calls == []


def test_removed_recovery_owner_disposal_guard_is_detected(monkeypatch):
    source = inspect.getsource(rolling_recovery.advance_one)
    guard = 'if not writer_schedule.connection_discarded(exc):'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if True:'), 'unguarded disposed recovery owner', 'exec'),
         rolling_recovery.__dict__, namespace)
    monkeypatch.setattr(rolling_recovery, 'advance_one', namespace['advance_one'])
    with pytest.raises(AssertionError, match='disposed session reused'):
        test_recovery_owner_preserves_disposed_primary_without_cleanup(monkeypatch, 'interrupt', False)


def test_healthy_recovery_owner_keeps_original_rollback(monkeypatch):
    connection = Connection(disposed=False)
    error = RuntimeError('ordinary reconstruction refusal')
    with pytest.raises(RuntimeError) as caught:
        recovery_owner(monkeypatch, error, connection)
    assert caught.value is error and connection.calls == ['rollback']


@pytest.mark.parametrize('closed', [False, True], ids=['close-failed', 'closed'])
def test_retained_backup_wait_never_reuses_or_retries_disposed_session(monkeypatch, closed):
    from sentinel import backup_runtime_authority
    from sentinel.feed import progress
    connection = Connection(disposed=True, closed=closed)
    error = backup_runtime_authority.BackupRuntimeUnavailable('original backup availability failure')
    setattr(error, writer_schedule._DISCARDED, True)
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(shadow_budget, 'now', lambda: now)
    monkeypatch.setattr(retained_go.time, 'sleep', lambda _: pytest.fail('disposed backup wait retried'))
    monkeypatch.setattr(progress, 'emit', lambda *a, **k: pytest.fail('disposed backup wait emitted progress'))
    calls = []

    def operation():
        calls.append('operation')
        raise error
    with pytest.raises(type(error)) as caught:
        retained_go._with_backup_wait(connection, operation,
            deadline=datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert caught.value is error and connection.calls == [] and calls == ['operation']


def test_removed_retained_backup_wait_disposal_guard_is_detected(monkeypatch):
    source = inspect.getsource(retained_go._with_backup_wait)
    guard = 'if writer_schedule.connection_discarded(exc):'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if False:'), 'unguarded disposed backup wait', 'exec'),
         retained_go.__dict__, namespace)
    monkeypatch.setattr(retained_go, '_with_backup_wait', namespace['_with_backup_wait'])
    with pytest.raises(AssertionError, match='disposed session reused'):
        test_retained_backup_wait_never_reuses_or_retries_disposed_session(monkeypatch, False)
