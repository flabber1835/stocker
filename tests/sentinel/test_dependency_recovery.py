"""Temporary authority observation failures remain fenced and recoverable."""
import asyncio
import time

import psycopg
import pytest

from sentinel import automation_runtime, automation_recovery, shadow_worker
from sentinel.backup_runtime_authority import BackupRuntimeUnavailable
from sentinel.automation.model import NonRetryableCallbackRefused, TransientInfrastructureFailure
from sentinel.execution.guarded import ExecutionBrokerGuard, GuardedExecutionBroker
from tests.sentinel import test_automation_runtime as fixture
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg


@pytest.mark.parametrize('error', [psycopg.errors.QueryCanceled,
    psycopg.OperationalError, psycopg.errors.SerializationFailure,
    psycopg.errors.LockNotAvailable, BackupRuntimeUnavailable])
def test_shadow_preflight_database_outage_is_retryable(monkeypatch, error):
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: object())
    def unavailable(_):
        raise error('temporary local database condition')
    monkeypatch.setattr(shadow_worker, 'advance_once', unavailable)
    assert shadow_worker.main() == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE
    assert isinstance(automation_runtime.classify_dependency_failure(error()),
                      TransientInfrastructureFailure)


@pytest.mark.parametrize('phase', ['prepare', 'recover', 'execute'])
@pytest.mark.parametrize('boundary', ['before_read', 'after_read'])
@pytest.mark.parametrize('error,expected', [
    (psycopg.errors.QueryCanceled, TransientInfrastructureFailure),
    (psycopg.OperationalError, TransientInfrastructureFailure),
    (RuntimeError, NonRetryableCallbackRefused),
])
def test_guarded_callback_preserves_observation_failure_class(
        monkeypatch, phase, boundary, error, expected):
    cfg = fixture.config()
    ctx = fixture.context(cfg, plan=fixture.plan())
    inner = fixture.SimulatedBroker()
    async def before(*_):
        if boundary == 'before_read':
            raise error('authority cannot currently be read')
    async def after(*_):
        if boundary == 'after_read':
            raise error('authority cannot currently be read')
    async def mutation(*_):
        pytest.fail('no transport is authorized')
    broker = GuardedExecutionBroker(inner=inner,
        grant=automation_runtime._grant(ctx, phase.upper(), binding=fixture.control(cfg).binding),
        guard=ExecutionBrokerGuard(before_read=before, after_read=after, before_mutation=mutation))
    runtime = fixture.production(cfg)
    fixture.install_runtime_seams(monkeypatch, runtime, fixture.FakeConnection(), ctx, broker)
    # This callback-classification unit uses the existing SQL double, not a
    # schema/authority acceptance fixture. SQL-backed restart tests are separate.
    monkeypatch.setattr(automation_runtime.schema, 'require_runtime_schema', lambda _: None)
    async def read(**kwargs):
        return await kwargs['broker'].observe()
    monkeypatch.setattr(fixture.paper, {'prepare':'prepare_paper_plan',
        'recover':'recover_automated_paper_cycle', 'execute':'execute_automated_paper_plan'}[phase], read)
    with pytest.raises(expected):
        asyncio.run(getattr(runtime, phase)(ctx))
    assert not any(call.startswith(('submit:', 'cancel:')) for call in inner.calls)
    if boundary == 'before_read':
        assert not inner.calls


@pytest.mark.parametrize('boundary', ['connect', 'proof', 'rollback', 'close'])
def test_backup_database_failure_is_classified_before_callback_ipc(monkeypatch, boundary):
    runtime = object.__new__(automation_recovery.ProductionAutomation)
    def unavailable(*_, **__):
        raise psycopg.errors.QueryCanceled('local statement timeout')
    class Connection:
        rollback = unavailable if boundary == 'rollback' else lambda _: None
        close = unavailable if boundary == 'close' else lambda _: None
    runtime.connect = unavailable if boundary == 'connect' else lambda: Connection()
    monkeypatch.setattr(automation_recovery.backup_runtime_authority, 'require',
                        unavailable if boundary == 'proof' else lambda *_, **__: None)
    monkeypatch.setattr(automation_recovery.backup_guard, 'require_writes_permitted',
                        lambda *_, **__: None)
    with pytest.raises(TransientInfrastructureFailure):
        runtime._require_backup_for_new_mutation('local acceptance')


def test_real_query_timeout_recovers_and_permission_refusal_stays_terminal(conn):
    from sentinel.automation.model import PermanentOperationalRefusal
    conn.execute("SET LOCAL statement_timeout='20ms'")
    with pytest.raises(psycopg.errors.QueryCanceled) as failure:
        conn.execute('SELECT pg_sleep(1)')
    assert shadow_worker._availability_failure(failure.value)
    assert isinstance(automation_runtime.classify_dependency_failure(failure.value),
                      TransientInfrastructureFailure)
    conn.rollback()
    assert conn.execute('SELECT 42').fetchone()[0] == 42
    denied = psycopg.errors.InsufficientPrivilege('not authorized')
    denied.__context__ = failure.value
    assert not shadow_worker._availability_failure(denied)
    assert isinstance(automation_runtime.classify_dependency_failure(denied),
                      PermanentOperationalRefusal)


def test_integrity_refusal_is_not_hidden_by_transient_context_or_cleanup(monkeypatch):
    failure = psycopg.errors.QueryCanceled('prior transient error')
    refusal = shadow_worker.ShadowServiceRefused('state integrity')
    refusal.__context__ = failure
    assert not shadow_worker._availability_failure(refusal)
    runtime = object.__new__(automation_recovery.ProductionAutomation)
    class Connection:
        def rollback(self):
            raise failure
        def close(self):
            raise failure
    runtime.connect = Connection
    def corrupt(*_, **__):
        raise automation_recovery.backup_runtime_authority.BackupRuntimeRefused('changed WAL')
    monkeypatch.setattr(automation_recovery.backup_runtime_authority, 'require', corrupt)
    with pytest.raises(automation_recovery.BackupIntegrityRefused, match='changed WAL'):
        runtime._require_backup_for_new_mutation('local acceptance')


@pytest.mark.parametrize('error', [psycopg.OperationalError,
    psycopg.errors.SerializationFailure, psycopg.errors.LockNotAvailable])
def test_owned_observation_wrapper_preserves_dependency_failure(error):
    from sentinel.shadow_observation import ShadowObservationRefused
    cause = error('temporary observation persistence failure')
    wrapped = ShadowObservationRefused('shadow observation append failed')
    wrapped.__cause__ = cause
    retry = shadow_worker.ShadowServiceRetry('rolling service dependency unavailable')
    retry.__cause__ = wrapped
    assert shadow_worker._availability_failure(wrapped)
    assert shadow_worker._availability_failure(retry)
    assert shadow_worker._availability_exit(retry) == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE


def test_dependency_walk_stops_at_integrity_decisions_and_cause_cycles():
    from sentinel.shadow_observation import ShadowObservationRefused
    transient = psycopg.OperationalError('older connection failure')
    refused = shadow_worker.ShadowServiceRefused('authenticated state changed')
    refused.__cause__ = transient
    outer = ShadowObservationRefused('observation could not be appended')
    outer.__cause__ = refused
    assert not shadow_worker._availability_failure(outer)
    assert shadow_worker._availability_exit(outer) == shadow_worker.EXIT_AVAILABILITY
    outer.__cause__ = outer
    assert not shadow_worker._availability_failure(outer)


def test_wrapped_database_timeout_retries_one_durable_transition(conn, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from sentinel import rolling_runtime, shadow_budget, shadow_service
    from sentinel.shadow_observation import ShadowObservationRefused

    conn.execute('CREATE TEMP TABLE autonomy_transition (session text PRIMARY KEY)')
    conn.commit()
    config = SimpleNamespace(operational_source_only=True, observation_id='test',
        starting_cash=50000, database_url='isolated', poll_seconds=1)
    attempts = []

    class BorrowedConnection:
        def rollback(self): conn.rollback()
        def close(self): pass

    def advance(*args, **kwargs):
        attempts.append(len(attempts))
        try:
            if len(attempts) == 1:
                conn.execute("SET LOCAL statement_timeout='10ms'")
                conn.execute('SELECT pg_sleep(1)')
            conn.execute("INSERT INTO autonomy_transition VALUES ('2026-10-15')")
            conn.commit()
            return SimpleNamespace(to_dict=lambda: {'session': '2026-10-15'})
        except Exception as exc:
            raise ShadowObservationRefused('shadow observation append failed') from exc

    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: config)
    monkeypatch.setattr(shadow_service, 'preflight', lambda *a, **k: {
        'status': 'ATTESTED_STRUCTURAL', 'input_contract': rolling_runtime.SCHEMA})
    monkeypatch.setattr(shadow_service, '_causal_target', lambda **k: '2026-10-15')
    monkeypatch.setattr(shadow_budget, 'cutoff', lambda: datetime.now(timezone.utc))
    monkeypatch.setattr(shadow_service.feed_store, 'connect', lambda *a, **k: BorrowedConnection())
    monkeypatch.setattr(rolling_runtime, 'service_advance', advance)
    monkeypatch.setattr(shadow_worker, 'advance_once', shadow_service.advance_once)
    assert shadow_worker.main() == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE
    assert shadow_worker.main() == 0
    assert conn.execute('SELECT count(*) FROM autonomy_transition').fetchone()[0] == 1
    conn.rollback()


def test_post_commit_retention_diagnostic_has_its_own_lock_budget(conn):
    from sentinel.feed import retention, store
    from sentinel import schema
    schema.ensure_schema(conn)
    # Independent test safety bound also makes removal of the local budgets
    # fail promptly instead of leaving a mutation campaign blocked forever.
    conn.execute("SET statement_timeout='2s'")
    conn.commit()
    with store.connect(conn.info.dsn) as locker:
        class DiagnosticLock:
            def __getattr__(self, name):
                return getattr(conn, name)
            def execute(self, statement, *args, **kwargs):
                if statement.startswith('INSERT INTO sentinel_snapshot_maintenance'):
                    locker.execute('LOCK TABLE sentinel_snapshot_maintenance IN ACCESS EXCLUSIVE MODE')
                return conn.execute(statement, *args, **kwargs)
        started = time.monotonic()
        result = retention.maintain(DiagnosticLock())
        assert result['status'] == 'COMPLETE'
        assert time.monotonic() - started < 1.2
        locker.rollback()
    assert conn.execute('SHOW statement_timeout').fetchone()[0] == '2s'
    conn.rollback()
    assert retention.maintain(conn)['status'] == 'COMPLETE'


__all__ = ['conn', 'pg']
