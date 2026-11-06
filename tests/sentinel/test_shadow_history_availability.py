"""History reads preserve dependency availability before making an integrity decision."""
import asyncio
from copy import deepcopy
import inspect
import textwrap

import psycopg
import pytest

from sentinel import automation_runtime, dual_reconciliation, rolling_runtime
from sentinel import shadow_observation as observation
from sentinel import shadow_runtime, shadow_worker
from sentinel.automation.model import TransientInfrastructureFailure
from sentinel.execution import journal
from sentinel.feed import publication
from tests.sentinel import test_automation_runtime as callback
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401
from tests.sentinel.test_shadow_observation import (
    FIRST, MemoryStore, _fully_published, _observer,
)


class InterruptedHistory(MemoryStore):
    failure = None
    stream_failure = False

    def records(self):
        if self.failure is not None:
            if self.stream_failure:
                def interrupted():
                    yield from super(InterruptedHistory, self).records()
                    self.failure()
                return interrupted()
            self.failure()
        return super().records()


def history_reader(monkeypatch, *, consume_seed=False):
    retained = InterruptedHistory()
    observer, _ = _observer(store=retained)
    expected = observer.observe(_fully_published(FIRST))
    monkeypatch.setattr(rolling_runtime, 'selected', lambda _: False)
    monkeypatch.setattr(shadow_runtime, '_verified_shadow_status',
        lambda *_, **__: observer.verify_history(consume_seed=consume_seed))
    return observer, retained, expected


@pytest.mark.parametrize('error', [
    psycopg.errors.QueryCanceled, psycopg.OperationalError,
    psycopg.errors.SerializationFailure, psycopg.errors.LockNotAvailable,
    journal.WriterLockUnavailable, publication.CorpusLockUnavailable,
])
@pytest.mark.parametrize('streamed', [False, True])
def test_direct_reviewed_history_dependency_reaches_public_paper_boundary(monkeypatch, error, streamed):
    observer, retained, expected = history_reader(monkeypatch)
    failure = error('temporary read dependency')
    def unavailable():
        raise failure
    before = deepcopy(retained.rows)
    retained.failure = unavailable
    retained.stream_failure = streamed
    with pytest.raises(error) as caught:
        dual_reconciliation.verified_shadow_intent(None, decision_session=FIRST,
            observation_id=observer.observation_id, starting_cash=100000)
    assert caught.value is failure
    assert isinstance(automation_runtime.classify_dependency_failure(caught.value),
                      TransientInfrastructureFailure)
    assert retained.rows == before
    retained.failure = None
    assert observer.verify_history().record_sha256 == expected.record_sha256


def test_consumed_status_failure_requires_fresh_full_verification(conn, monkeypatch):
    observer, retained, expected = history_reader(monkeypatch, consume_seed=True)
    before = deepcopy(retained.rows)
    def timed_out():
        conn.execute("SET LOCAL statement_timeout='20ms'")
        conn.execute('SELECT pg_sleep(1)')
    retained.failure = timed_out
    with pytest.raises(psycopg.errors.QueryCanceled):
        dual_reconciliation.verified_shadow_intent(None, decision_session=FIRST,
            observation_id=observer.observation_id, starting_cash=100000)
    assert observer.initial_state is None and observer._consumed_for_status
    assert retained.rows == before
    conn.rollback()
    retained.failure = None
    restarted, _ = _observer(store=retained)
    assert restarted.verify_history().record_sha256 == expected.record_sha256


@pytest.mark.parametrize('phase', ['prepare', 'recover', 'execute'])
def test_real_history_timeout_reaches_callback_without_broker_or_history_mutation(
        conn, monkeypatch, phase):
    observer, retained, expected = history_reader(monkeypatch)
    before = deepcopy(retained.rows)
    def timed_out():
        conn.execute("SET LOCAL statement_timeout='20ms'")
        conn.execute('SELECT pg_sleep(1)')
    retained.failure = timed_out
    cfg = callback.config()
    context = callback.context(cfg, plan=callback.plan())
    broker = callback.SimulatedBroker()
    runtime = callback.production(cfg)
    callback.install_runtime_seams(monkeypatch, runtime, callback.FakeConnection(), context, broker)
    monkeypatch.setattr(automation_runtime.schema, 'require_runtime_schema', lambda _: None)
    async def read(**_):
        return dual_reconciliation.verified_shadow_intent(None, decision_session=FIRST,
            observation_id=observer.observation_id, starting_cash=100000)
    monkeypatch.setattr(callback.paper, {'prepare': 'prepare_paper_plan',
        'recover': 'recover_automated_paper_cycle', 'execute': 'execute_automated_paper_plan'}[phase], read)
    with pytest.raises(TransientInfrastructureFailure) as caught:
        asyncio.run(getattr(runtime, phase)(context))
    assert isinstance(caught.value.__cause__, psycopg.errors.QueryCanceled)
    assert caught.value.__cause__.sqlstate == '57014'
    assert retained.rows == before
    assert not broker.calls
    conn.rollback()
    retained.failure = None
    assert observer.verify_history().record_sha256 == expected.record_sha256
    assert not broker.calls


@pytest.mark.parametrize('error', [ValueError('malformed retained history'),
    RuntimeError('statement timeout'), psycopg.errors.InsufficientPrivilege('denied'),
    psycopg.errors.UndefinedColumn('changed schema')])
def test_unknown_integrity_and_permission_failures_remain_terminal(monkeypatch, error):
    observer, retained, _ = history_reader(monkeypatch)
    def refused():
        raise error
    retained.failure = refused
    with pytest.raises(dual_reconciliation.DualReconciliationRefused) as caught:
        dual_reconciliation.verified_shadow_intent(None, decision_session=FIRST,
            observation_id=observer.observation_id, starting_cash=100000)
    assert not isinstance(automation_runtime.classify_dependency_failure(caught.value),
                          TransientInfrastructureFailure)
    assert not shadow_worker._availability_failure(caught.value)


def test_existing_integrity_refusal_keeps_its_transient_cause_terminal(monkeypatch):
    observer, retained, _ = history_reader(monkeypatch)
    def refused():
        try:
            raise psycopg.errors.QueryCanceled('incidental earlier timeout')
        except psycopg.errors.QueryCanceled as cause:
            raise observation.ShadowObservationRefused('retained state commitment changed') from cause
    retained.failure = refused
    with pytest.raises(dual_reconciliation.DualReconciliationRefused) as caught:
        dual_reconciliation.verified_shadow_intent(None, decision_session=FIRST,
            observation_id=observer.observation_id, starting_cash=100000)
    assert not isinstance(automation_runtime.classify_dependency_failure(caught.value),
                          TransientInfrastructureFailure)
    assert not shadow_worker._availability_failure(caught.value)


def _invoke_owned_read(entry, observer, retained, failure):
    def unavailable():
        raise failure
    retained.genesis = unavailable
    if entry == 'resume':
        return observation.ShadowObserver.resume(store=retained,
            observation_id=observer.observation_id, starting_cash=observer.starting_cash,
            first_session=observer.first_session, controller_config=observer.controller_config,
            strategy_identity=observer.strategy_identity, runtime_identity=observer.runtime_identity)
    if entry == 'genesis':
        return observer._persist_and_verify_genesis()
    runtime = object.__new__(observation.PostgresShadowRuntime)
    runtime.observer = observer
    runtime.warmup_input_loader = unavailable
    return runtime._require_current_warmup_input()


@pytest.mark.parametrize('entry', ['resume', 'genesis', 'warmup'])
@pytest.mark.parametrize('kind', ['deadline', 'permission', 'integrity'])
def test_other_canonical_read_boundaries_keep_the_same_availability_contract(
        monkeypatch, entry, kind):
    observer, retained, _ = history_reader(monkeypatch)
    errors = {'deadline': psycopg.errors.QueryCanceled('bounded read unavailable'),
        'permission': psycopg.errors.InsufficientPrivilege('denied'),
        'integrity': observation.ShadowObservationRefused('retained state changed')}
    error = errors[kind]
    error.__cause__ = psycopg.errors.QueryCanceled('incidental earlier error')
    before = deepcopy((retained.rows, retained.seed))
    expected = psycopg.errors.QueryCanceled if kind == 'deadline' else observation.ShadowObservationRefused
    with pytest.raises(expected) as caught:
        _invoke_owned_read(entry, observer, retained, error)
    if kind == 'deadline':
        assert caught.value is error
    assert isinstance(automation_runtime.classify_dependency_failure(caught.value),
                      TransientInfrastructureFailure) == (kind == 'deadline')
    assert (retained.rows, retained.seed) == before


@pytest.mark.parametrize('entry,method', [('resume', 'resume'),
    ('genesis', '_persist_and_verify_genesis'), ('warmup', '_require_current_warmup_input')])
def test_removing_each_other_read_guard_breaks_its_timeout_oracle(monkeypatch, entry, method):
    owner = (observation.PostgresShadowRuntime if entry == 'warmup'
             else observation.ShadowObserver)
    source = textwrap.dedent(inspect.getsource(getattr(owner, method)))
    guard = ('        from sentinel.dependency_availability import database_unavailable, local_contention\n'
             '        if database_unavailable(exc) or local_contention(exc):\n'
             '            raise\n')
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, ''), 'old-owned-read-classification', 'exec'),
         observation.__dict__, namespace)
    monkeypatch.setattr(owner, method, namespace[method])
    with pytest.raises(observation.ShadowObservationRefused):
        test_other_canonical_read_boundaries_keep_the_same_availability_contract(
            monkeypatch, entry, 'deadline')


def test_old_history_wrapper_breaks_the_actual_timeout_callback_oracle(conn, monkeypatch):
    source = textwrap.dedent(inspect.getsource(observation.ShadowObserver._history))
    guard = ('        from sentinel.dependency_availability import database_unavailable, local_contention\n'
             '        if database_unavailable(exc) or local_contention(exc):\n'
             '            raise\n')
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, ''), 'old-history-read-classification', 'exec'),
         observation.__dict__, namespace)
    monkeypatch.setattr(observation.ShadowObserver, '_history', namespace['_history'])
    with pytest.raises(dual_reconciliation.DualReconciliationRefused, match='history is unreadable'):
        test_real_history_timeout_reaches_callback_without_broker_or_history_mutation(
            conn, monkeypatch, 'recover')
