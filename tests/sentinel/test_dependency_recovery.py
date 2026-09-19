"""Temporary authority observation failures remain fenced and recoverable."""
import asyncio
import time

import psycopg
import pytest

from sentinel import automation_runtime, automation_recovery, shadow_worker
from sentinel.automation.model import NonRetryableCallbackRefused, TransientInfrastructureFailure
from sentinel.execution.guarded import ExecutionBrokerGuard, GuardedExecutionBroker
from tests.sentinel import test_automation_runtime as fixture
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg


@pytest.mark.parametrize('error', [psycopg.errors.QueryCanceled,
    psycopg.OperationalError, psycopg.errors.SerializationFailure,
    psycopg.errors.LockNotAvailable])
def test_shadow_preflight_database_outage_is_retryable(monkeypatch, error):
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: object())
    def unavailable(_):
        raise error('temporary local database condition')
    monkeypatch.setattr(shadow_worker, 'advance_once', unavailable)
    assert shadow_worker.main() == shadow_worker.EXIT_AVAILABILITY
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
