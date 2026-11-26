"""Adversarial composition tests for the broker-facing Stage 4 runtime.

The automation state machine has its own exhaustive transition tests.  These
tests target the narrower, more dangerous seam where a fenced cycle becomes a
signed paper grant, touches the canonical broker membrane, and is classified
back into durable orchestration outcomes.  Every broker is the deterministic
simulator; no network or real account is involved.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from sentinel import (
    authority, automation_runtime, informational_paper_mirror, paper)
from sentinel.paper import (
    inspection as paper_inspection,
    validation as paper_validation,
)
from sentinel.paper.model import PaperDataIntegrityRefused
from sentinel.automation import store
from sentinel.automation.model import (
    AutomationConfig,
    AutomationControl,
    ControlBinding,
    CycleContext,
    CycleRecord,
    CycleState,
    ExecuteDisposition,
    ExecuteResult,
    LeaderPermit,
    NonRetryableCallbackRefused,
    PreflightPublicationPinUnavailable,
    PrepareResult,
    SoftwareDefect,
    StaleLeaderRefused,
    TickAction,
    TickResult,
    TransientInfrastructureFailure,
    SourceDataPending,
)
from sentinel.automation.service import AutomationService
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.execution import journal, target_reprojection
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerInstrument,
    Completeness,
    Side,
)
from sentinel.execution.executor import SessionResult
from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityCheckFailed,
    BrokerAuthorityRefused,
    ExecutionBrokerGuard,
    GuardedExecutionBroker,
    PreTransportAuthorityRefused,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.simulator import FaultKind, SimulatedBroker
from sentinel.execution.states import CommandState, RuntimeState
from tests.sentinel.test_corpus_publication import pg  # noqa: F401


UTC = timezone.utc
NOW = datetime(2026, 8, 13, 13, 31, tzinfo=UTC)
DECISION = date(2026, 8, 12)
EFFECTIVE = date(2026, 8, 13)
CERTIFICATE = "c" * 64
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAA", symbol="AAA", broker_id="sim-asset-SEC-AAA")


@pytest.mark.parametrize("disposition", [
    ExecuteDisposition.SUCCEEDED,
    ExecuteDisposition.READY_TO_EXECUTE,
    ExecuteDisposition.SUPERSEDED,
])
def test_conclusive_dispositions_require_clean_reconciliation(disposition):
    with pytest.raises(ValueError, match="clean reconciliation identity"):
        ExecuteResult(disposition=disposition)


def test_transport_evidence_never_claims_clean_success():
    for disposition in (ExecuteDisposition.READY_TO_EXECUTE, ExecuteDisposition.SUPERSEDED):
        result = ExecuteResult(disposition=disposition, transport_reconciliation_id="12")
        assert result.last_clean_reconciliation_id is None
    with pytest.raises(ValueError, match="clean reconciliation identity"):
        ExecuteResult(disposition=ExecuteDisposition.SUCCEEDED,
                      transport_reconciliation_id="12")


@pytest.mark.parametrize("invalid", [0, -1, True, "587"])
def test_preparation_observation_is_a_positive_journal_sequence(invalid):
    with pytest.raises(ValueError, match="clean_observation_id"):
        PrepareResult(plan_id="plan", clean_observation_id=invalid)


@pytest.mark.parametrize("invalid", [
    {"transport_reconciliation_id": None},
    {"transport_reconciliation_id": ""},
    {"last_clean_reconciliation_id": "clean-is-not-restricted"},
    {"last_clean_reconciliation_id": ""},
    {"diagnostic": {}},
    {"diagnostic": {"restricted_securities": {}}},
    {"diagnostic": {"restricted_securities": ["SEC-AAA"]}},
])
def test_preparation_readiness_requires_restricted_transport_not_clean(invalid):
    evidence = dict(disposition=ExecuteDisposition.READY_TO_PREPARE,
                    transport_reconciliation_id="12",
                    diagnostic={"restricted_securities": {"SEC-AAA": "pending"}})
    assert ExecuteResult(**evidence).last_clean_reconciliation_id is None
    with pytest.raises(ValueError, match="requires restricted transport evidence"):
        ExecuteResult(**{**evidence, **invalid})


def test_deployed_automation_refuses_legacy_publication_before_source_fallback(
        monkeypatch):
    class Connection:
        def close(self):
            pass

    worker = object.__new__(automation_runtime.ProductionAutomation)
    worker._operational_source_only = True
    worker.connect = Connection
    worker._assert_cycle_authority = lambda *_a, **_k: (
        SimpleNamespace(decision_session=DECISION), None)
    monkeypatch.setattr(automation_runtime, "require_execution_schemas",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime, "require_observation_integrity",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, "current",
                        lambda *_a: SimpleNamespace(version=1))
    monkeypatch.setattr(automation_runtime.feed_inputs, "is_rolling",
                        lambda *_a: False)
    monkeypatch.setattr(automation_runtime.feed_inputs, "frontier",
                        lambda *_a: pytest.fail("legacy publisher reached"))
    with pytest.raises(NonRetryableCallbackRefused,
                       match="rolling Alpaca inputs"):
        asyncio.run(worker.refresh(SimpleNamespace()))


@pytest.mark.parametrize("callback", ["prepare", "execute"])
def test_resumed_operational_cycle_rechecks_alpaca_source_before_broker(
        monkeypatch, callback):
    from contextlib import contextmanager

    class Connection:
        def close(self):
            pass

    worker = object.__new__(automation_runtime.ProductionAutomation)
    worker._operational_source_only = True
    worker._dual_run_enabled = True
    worker.connect = Connection
    worker._assert_cycle_authority = lambda *_a, **_k: (
        SimpleNamespace(decision_session=DECISION), None)
    worker._broker = lambda *_a, **_k: pytest.fail("broker reached")
    monkeypatch.setattr(automation_runtime, "require_execution_schemas",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime, "require_observation_integrity",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, "current",
                        lambda *_a: SimpleNamespace(version=1))
    @contextmanager
    def pinned(conn, *, commit):
        assert commit is False
        yield automation_runtime.feed_inputs.current(conn)

    monkeypatch.setattr(automation_runtime.feed_inputs, 'pinned', pinned)
    monkeypatch.setattr(automation_runtime.feed_inputs, "is_rolling",
                        lambda *_a: False)
    monkeypatch.setattr(automation_runtime.journal, "latest_plan",
                        lambda *_a: pytest.fail("legacy plan reached"))
    with pytest.raises(NonRetryableCallbackRefused,
                       match="rolling Alpaca inputs"):
        asyncio.run(getattr(worker, callback)(SimpleNamespace()))


def test_deployed_automation_refuses_wrong_rolling_provider_before_plan(
        monkeypatch):
    from sentinel.feed import operational_snapshot

    class Connection:
        def close(self):
            pass

    worker = object.__new__(automation_runtime.ProductionAutomation)
    worker._operational_source_only = True
    worker.connect = Connection
    worker._assert_cycle_authority = lambda *_a, **_k: (
        SimpleNamespace(decision_session=DECISION), None)
    monkeypatch.setattr(automation_runtime, "require_execution_schemas",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime, "require_observation_integrity",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, "current",
                        lambda *_a: SimpleNamespace(version=1))
    monkeypatch.setattr(automation_runtime.feed_inputs, "is_rolling",
                        lambda *_a: True)
    monkeypatch.setattr(operational_snapshot, "require_alpaca_openfigi",
                        lambda *_a: (_ for _ in ()).throw(
                            operational_snapshot.OperationalSnapshotRefused(
                                "OPERATIONAL_ALPACA_OPENFIGI_SOURCE_REQUIRED")))
    monkeypatch.setattr(automation_runtime.feed_inputs, "require_shadow_mode",
                        lambda *_a: pytest.fail("plan path reached"))
    with pytest.raises(NonRetryableCallbackRefused,
                       match="ALPACA_OPENFIGI_SOURCE_REQUIRED"):
        asyncio.run(worker.refresh(SimpleNamespace()))


def test_fenced_deployed_wake_alerts_without_legacy_ingest(monkeypatch):
    class Connection:
        def rollback(self):
            pass

    worker = object.__new__(automation_runtime.ProductionAutomation)
    worker._operational_source_only = True
    worker._fenced_data_next_wake = None
    worker._fenced_data_poll_seconds = 30
    worker.automation_config = config()
    conn = Connection()
    alerts = []
    monkeypatch.setattr(automation_runtime.feed_store, "require_feed_schema",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema",
                        lambda *_a: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, "current",
                        lambda *_a: SimpleNamespace(version=1))
    monkeypatch.setattr(automation_runtime.feed_inputs, "is_rolling",
                        lambda *_a: False)
    monkeypatch.setattr(automation_runtime.ingest, "daily",
                        lambda *_a, **_k: pytest.fail("legacy ingest reached"))
    monkeypatch.setattr(automation_runtime, "_enqueue_fenced_recovery_alert",
                        lambda *_a, **_k: alerts.append(True))
    assert asyncio.run(worker._fenced_data_wake(conn)) is not None
    assert alerts == [True]


def async_test(function):
    """Keep focused async tests runnable in the dependency-minimal image."""
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


class FakeConnection:
    def __init__(self, lease_row=None) -> None:
        self.lease_row = lease_row
        self.closed = 0
        self.rollbacks = 0
        self.commits = 0
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.pending_work = []
        self.committed_work = []
        self.statements = []

    def close(self) -> None:
        self.closed += 1
        # Reused by the factory seam for successive owned connections. A real
        # close releases uncommitted work before the next connection is opened.
        self.pending_work.clear()
        self.info.transaction_status = TransactionStatus.IDLE

    def rollback(self) -> None:
        self.rollbacks += 1
        self.pending_work.clear()
        self.info.transaction_status = TransactionStatus.IDLE

    def commit(self) -> None:
        self.commits += 1
        self.committed_work.extend(self.pending_work)
        self.pending_work.clear()
        self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def cursor(self):
        return FakeCursor(self)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, _params=None) -> None:
        self.sql = _sql
        self.conn.info.transaction_status = TransactionStatus.INTRANS
        self.conn.statements.append((_sql, _params))
        return None

    def fetchone(self):
        # This historical fake models the complete absence of the additive
        # operational extension, so the real integrity owner uses its retained
        # independent verifier. It never models installed coverage as passed.
        if self.sql.startswith(('SELECT count(*) FROM pg_class',
                'SELECT count(*) FROM pg_proc', 'SELECT count(*) FROM pg_trigger',
                'SELECT count(*) FROM pg_event_trigger')):
            return (0,)
        if self.sql == "SELECT to_regclass('public.sentinel_processed_sessions')":
            return (None,)
        if self.sql == "SELECT to_regprocedure('public.sentinel_operational_installation_guard()') IS NOT NULL":
            return (False,)
        if 'SELECT COALESCE(MAX(o.seq),0)' in self.sql:
            return (0, 'sim', 'SIM-ACCOUNT', NOW)
        if 'SELECT broker,broker_account_id,established_at' in self.sql:
            return ('sim', 'SIM-ACCOUNT', NOW)
        return self.conn.lease_row

    def fetchall(self):
        return []


def test_fake_integrity_owner_verifies_absent_extension_and_finishes_its_read():
    conn = FakeConnection()
    automation_runtime.require_observation_integrity(conn)
    assert conn.info.transaction_status == TransactionStatus.IDLE
    assert conn.rollbacks == 1 and conn.commits == 0
    assert any(sql.startswith('SELECT count(*) FROM pg_class') for sql, _ in conn.statements)
    assert any('SELECT COALESCE(MAX(o.seq),0)' in sql for sql, _ in conn.statements)


def test_fake_integrity_owner_preserves_active_caller_work():
    conn = FakeConnection()
    conn.execute('SELECT caller_owned_read')
    conn.pending_work.append('caller-owned mutation')
    before = list(conn.statements)
    with pytest.raises(automation_runtime.DataIntegrityFailure, match='idle owned connection'):
        automation_runtime.require_observation_integrity(conn)
    assert conn.info.transaction_status == TransactionStatus.INTRANS
    assert conn.pending_work == ['caller-owned mutation']
    assert conn.statements == before
    assert conn.rollbacks == conn.commits == 0


def test_fake_close_releases_only_uncommitted_work_for_next_owned_connection():
    conn = FakeConnection()
    conn.execute('SELECT committed_read')
    conn.pending_work.append('committed mutation')
    conn.commit()
    conn.execute('SELECT uncommitted_read')
    conn.pending_work.append('uncommitted mutation')
    conn.close()
    assert conn.closed == 1
    assert conn.info.transaction_status == TransactionStatus.IDLE
    assert conn.pending_work == []
    assert conn.committed_work == ['committed mutation']
    assert conn.rollbacks == 0 and conn.commits == 1


class DictEvidence:
    def to_dict(self) -> dict:
        return {"kind": "test-preflight"}


def config() -> AutomationConfig:
    return AutomationConfig(
        publication_delay_seconds=0,
        execution_delay_seconds=60,
        lease_seconds=30,
        heartbeat_seconds=5,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )


def binding(cfg: AutomationConfig) -> ControlBinding:
    return ControlBinding(
        deployment_id="sentinel-runtime-test",
        broker="sim",
        broker_account_id="SIM-ACCOUNT",
        takeover_epoch=1,
        certificate_sha256=CERTIFICATE,
        rollout_mode="PINNED_1_00",
        rollout_version=1,
        config_sha256=cfg.fingerprint,
    )


def control(cfg: AutomationConfig, *, generation=3) -> AutomationControl:
    value = binding(cfg)
    return AutomationControl(
        enabled=True, generation=generation, kill_switch_engaged=False,
        **value.model_dump(), updated_at=NOW)


def cycle(cfg: AutomationConfig, *, generation=3,
          state=CycleState.EXECUTING, plan=None,
          last_fence_token=17) -> CycleRecord:
    value = binding(cfg)
    return CycleRecord(
        cycle_id="cycle-2026-08-12", state=state,
        decision_session=DECISION, effective_session=EFFECTIVE,
        deployment_id=value.deployment_id, broker=value.broker,
        broker_account_id=value.broker_account_id,
        takeover_epoch=value.takeover_epoch,
        control_generation=generation,
        certificate_sha256=value.certificate_sha256,
        rollout_mode=value.rollout_mode,
        rollout_version=value.rollout_version,
        config_sha256=value.config_sha256,
        decision_close_at=NOW - timedelta(hours=18),
        prepare_at=NOW - timedelta(hours=17),
        execution_open_at=NOW - timedelta(minutes=1),
        execute_at=NOW,
        execution_close_at=NOW + timedelta(hours=6),
        historical_state_only=False,
        plan_id=plan.plan_id if plan is not None else None,
        plan_fingerprint=plan.fingerprint() if plan is not None else None,
        attempt_count=1, last_fence_token=last_fence_token,
        diagnostic={}, created_at=NOW - timedelta(hours=1),
        updated_at=NOW)


def context(cfg: AutomationConfig, *, generation=3,
            state=CycleState.EXECUTING, plan=None) -> CycleContext:
    current = cycle(cfg, generation=generation, state=state, plan=plan)
    return CycleContext(
        cycle=current,
        permit=LeaderPermit(
            holder_id="worker-a", fence_token=17,
            control_generation=3, acquired_at=NOW,
            expires_at=NOW + timedelta(seconds=30)))


def plan(*, target="1") -> ExecutionPlan:
    pending = ExecutionPlan(
        plan_id="pending", decision_session=DECISION,
        effective_session=EFFECTIVE, target_exposure=Decimal("1"),
        target_basket={INSTRUMENT.security_id: Decimal(target)},
        data_version=1, deployment_id="sentinel-runtime-test",
        broker="sim", broker_account_id="SIM-ACCOUNT", takeover_epoch=1,
        account_nav=Decimal("1000"), account_cash=Decimal("1000"),
        cash_residual=Decimal("900"), rollout_mode="PINNED_1_00",
        rollout_version=1)
    return ExecutionPlan(**{
        **pending.__dict__, "plan_id": f"sentinel-{pending.fingerprint()}"})


def command(plan_id: str, *, state=CommandState.ACKNOWLEDGED) -> Command:
    deployment = DeploymentIdentity(
        deployment_id="sentinel-runtime-test", broker="sim",
        broker_account_id="SIM-ACCOUNT", takeover_epoch=1)
    return Command(
        identity=CommandIdentity(
            deployment=deployment, plan_id=plan_id,
            security_id=INSTRUMENT.security_id),
        instrument=INSTRUMENT, side=Side.BUY, quantity=Decimal("1"),
        state=state,
        broker_order_id="sim-1" if state is not CommandState.PLANNED else None)


def reconciliation(observation, *, observation_id=11,
                   runtime_state=RuntimeState.RUNNING) -> ReconciliationResult:
    return ReconciliationResult(
        runtime_state=runtime_state, observation=observation,
        expected=observation.positions_by_security(),
        observed=observation.positions_by_security(),
        observation_id=observation_id, detail="test reconciliation")


def production(cfg: AutomationConfig) -> automation_runtime.ProductionAutomation:
    sentinel_config = SentinelConfig(
        alpaca_key="", alpaca_secret="", base_url=DEFAULT_BASE_URL,
        state_dir=Path("."), max_cycles=1, poll_seconds=0,
        database_url="postgresql://unused")
    return automation_runtime.ProductionAutomation(
        sentinel_config=sentinel_config, automation_config=cfg,
        holder_id="worker-a")


def test_production_composition_accepts_only_an_explicit_typed_alert_adapter():
    cfg = config()

    class RecordingAdapter:
        def deliver(self, alert, idempotency_key):
            return (alert, idempotency_key)

    adapter = RecordingAdapter()
    sentinel_config = SentinelConfig(
        alpaca_key="", alpaca_secret="", base_url=DEFAULT_BASE_URL,
        state_dir=Path("."), max_cycles=1, poll_seconds=0,
        database_url="postgresql://unused")
    runtime = automation_runtime.ProductionAutomation(
        sentinel_config=sentinel_config, automation_config=cfg,
        holder_id="worker-a", alert_adapter=adapter)

    assert runtime.alert_adapter is adapter


def test_deployed_automation_mode_enables_operational_source_guard(monkeypatch):
    monkeypatch.setenv("SENTINEL_FEED_SERVICE_MODE", "AUTOMATION")
    assert production(config())._operational_source_only is True


@async_test
async def test_successful_cycle_financial_certificate_waits_for_session_close(
        monkeypatch) -> None:
    cfg = config()
    runtime = production(cfg)
    conn = FakeConnection()
    succeeded = cycle(cfg, state=CycleState.SUCCEEDED)
    result = TickResult(action=TickAction.EXECUTED, cycle=succeeded)
    calls = []
    monkeypatch.setattr(
        automation_runtime.trial, "record_cycle_verification",
        lambda _conn, *, cycle_id: calls.append(cycle_id))
    monkeypatch.setattr(
        automation_runtime.outbox, "enqueue",
        lambda *_args, **_kwargs: pytest.fail(
            "a healthy trial certificate became alert noise"))

    verdict = await runtime.certify_terminal_cycle(conn, result)

    assert verdict is None
    assert calls == []


@async_test
async def test_terminal_financial_refusal_creates_a_critical_alert(
        monkeypatch) -> None:
    cfg = config()
    runtime = production(cfg)
    conn = FakeConnection()
    missed = cycle(cfg, state=CycleState.MISSED_STATE_ONLY)
    result = TickResult(action=TickAction.SUPERSEDED, cycle=missed)
    monkeypatch.setattr(
        automation_runtime.trial, "record_cycle_verification",
        lambda _conn, *, cycle_id: {
            "verdict": "NOT_VERIFIED",
            "reason_codes": ["CYCLE_MISSED_STATE_ONLY"],
            "cycle_id": cycle_id})
    alerts = []
    monkeypatch.setattr(
        automation_runtime.outbox, "enqueue",
        lambda _conn, **kwargs: alerts.append(kwargs) or kwargs)

    await runtime.certify_terminal_cycle(conn, result)

    assert alerts[0]["event_type"] == "TRIAL_NOT_VERIFIED"
    assert alerts[0]["severity"] == "CRITICAL"


def install_runtime_seams(monkeypatch, runtime, conn, ctx, broker) -> None:
    monkeypatch.setattr(runtime, "connect", lambda: conn)
    monkeypatch.setattr(runtime, "_broker", lambda _conn, _session: broker)
    monkeypatch.setattr(
        runtime, "_assert_cycle_authority",
        lambda _conn, _context, *, operation_scope: (
            ctx.cycle, control(runtime.automation_config)))
    monkeypatch.setattr(
        automation_runtime, "require_execution_schemas", lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.schema, "ensure_schema", lambda _conn: None)




@async_test
@pytest.mark.parametrize("phase", ["execute", "recover"])
async def test_unavailable_protected_zero_target_never_reports_automation_convergence(monkeypatch, phase):
    from sentinel.execution import protected_limits
    cfg = config()
    current_plan = plan(target="0")
    ctx = context(cfg, state=(CycleState.EXECUTING if phase == "execute" else CycleState.RECONCILING),
                  plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    install_durable_projection(monkeypatch, current_plan)
    monkeypatch.setattr(protected_limits, "unavailable_opening_intents",
                        lambda projection: {INSTRUMENT.security_id: "REFERENCE_UNAVAILABLE"})
    async def clean(**kwargs):
        rec = reconciliation(await kwargs["broker"].observe())
        if phase == "recover":
            return rec
        return paper.ExecutionResult(plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(runtime_state=RuntimeState.RUNNING,
                                  reconciliation=rec, detail="zero projected shares"))
    monkeypatch.setattr(paper, "recover_automated_paper_cycle" if phase == "recover"
                        else "execute_automated_paper_plan", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    result = await getattr(runtime, phase)(ctx)
    assert result.disposition is ExecuteDisposition.SUPERSEDED
    assert result.failure_code == "PROTECTED_REFERENCE_UNAVAILABLE"
    assert result.last_clean_reconciliation_id == "11"
    assert result.diagnostic["incomplete_protected_projection"] is True
    assert not any(call.startswith("submit:") for call in broker.calls)


def test_removing_automation_unavailable_reference_guard_is_detected(monkeypatch):
    import inspect
    from sentinel.execution import protected_limits
    current_plan = plan(target="0")
    projection = install_durable_projection(monkeypatch, current_plan)
    monkeypatch.setattr(protected_limits, "unavailable_opening_intents",
                        lambda _projection: {INSTRUMENT.security_id: "REFERENCE_UNAVAILABLE"})
    observed = asyncio.run(SimulatedBroker().observe())
    def checked():
        with pytest.raises(protected_limits.ProtectedReferenceUnavailable):
            automation_runtime._actionable_projection_deltas(object(), plan=current_plan,
                effective_session=EFFECTIVE, observation=observed,
                minimum_quantity_increment=Decimal(1))
    checked()
    source = inspect.getsource(automation_runtime._actionable_projection_deltas)
    assert source.count("if unavailable:") == 1
    local = {}
    exec(compile(source.replace("if unavailable:", "if False:"),
                 "<private-automation-protected-reference>", "exec"), vars(automation_runtime), local)
    monkeypatch.setattr(automation_runtime, "_actionable_projection_deltas",
                        local["_actionable_projection_deltas"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        checked()


def install_durable_projection(monkeypatch, current_plan, *, multiplier="1"):
    multipliers = (
        {} if Decimal(multiplier) == 1
        else {INSTRUMENT.security_id: Decimal(multiplier)})
    projection = target_reprojection.project_target(
        current_plan, through_session=EFFECTIVE,
        action_multipliers=multipliers)
    monkeypatch.setattr(
        target_reprojection, "load_projection",
        lambda _conn, *, plan_id: (
            projection if plan_id == current_plan.plan_id else None))
    return projection


@async_test
@pytest.mark.parametrize('failure_at', ['resolver', 'execution'])
async def test_operational_execute_pins_before_resolver_and_releases_on_failure(monkeypatch, failure_at):
    from contextlib import contextmanager
    current_plan = plan()
    cfg=config(); ctx=context(cfg, plan=current_plan); conn=FakeConnection(); worker=production(cfg)
    install_runtime_seams(monkeypatch,worker,conn,ctx,SimulatedBroker())
    monkeypatch.setattr(journal, 'latest_plan', lambda _conn: current_plan)
    worker._operational_source_only=True
    worker._dual_run_enabled=True
    monkeypatch.setattr(automation_runtime,'require_observation_integrity',lambda _:None)
    trace=[]; held=[False]
    publication=object()
    def inputs(reader, *, current):
        assert reader is conn and held[0] and current is publication
        trace.append('INPUTS')
    monkeypatch.setattr(worker,'_require_operational_inputs',inputs)
    @contextmanager
    def pin(reader,*,commit):
        assert reader is conn and not commit
        held[0]=True;trace.append('PIN')
        try:yield publication
        finally:held[0]=False;trace.append('RELEASE')
    monkeypatch.setattr(automation_runtime.feed_inputs,'pinned',pin)
    def resolver(*a):
        assert held[0],'resolver performed an unscoped full scan'
        trace.append('RESOLVER')
        if failure_at=='resolver':raise NonRetryableCallbackRefused('resolver refused')
        return SimulatedBroker()
    monkeypatch.setattr(worker,'_broker',resolver)
    async def execute(**kwargs):
        assert held[0],'execution lost its original publication pin'
        trace.append('EXECUTE');raise paper.PaperActivationRefused('execution refused')
    monkeypatch.setattr(paper,'execute_automated_paper_plan',execute)
    with pytest.raises(NonRetryableCallbackRefused):await worker.execute(ctx)
    assert trace==(['PIN','INPUTS','RESOLVER','RELEASE'] if failure_at=='resolver'
                   else ['PIN','INPUTS','RESOLVER','EXECUTE','RELEASE'])
    assert conn.closed==1 and not held[0]


def test_removed_operational_execution_pin_is_detected(monkeypatch):
    import inspect,textwrap
    source=textwrap.dedent(inspect.getsource(automation_runtime.ProductionAutomation.execute))
    line='pinned = input_scope.enter_context(feed_inputs.pinned(conn, commit=False))'
    assert line in source
    namespace={};exec(compile(source.replace(line,'pinned = object()'),'execution-pin-falsifier','exec'),automation_runtime.__dict__,namespace)
    monkeypatch.setattr(automation_runtime.ProductionAutomation,'execute',namespace['execute'])
    with pytest.raises(AssertionError):
        test_operational_execute_pins_before_resolver_and_releases_on_failure(monkeypatch,'resolver')


@async_test
@pytest.mark.parametrize('pending', [False, True])
async def test_close_preflight_observes_monday_with_friday_identity_frontier(monkeypatch, pending):
    from sentinel.feed import source_aliases
    cfg = config()
    ctx = context(cfg, state=CycleState.REFRESHING_DATA if pending else CycleState.DISCOVERED)
    ctx = CycleContext(cycle=ctx.cycle.model_copy(update={
        'decision_session': date(2026, 10, 12),
        'effective_session': date(2026, 10, 13)}), permit=ctx.permit)
    conn = FakeConnection()
    validation_query = ('SELECT validation_sha256 FROM sentinel_snapshot_validations '
                        'WHERE candidate_id=%s')
    original_execute = conn.execute
    def validation_or_default(sql, params=None):
        result = original_execute(sql, params)
        if sql == validation_query:
            assert params == ('c',)
            return SimpleNamespace(fetchone=lambda: ('v'*64,))
        return result
    conn.execute = validation_or_default
    runtime = production(cfg)
    broker = SimulatedBroker()
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    monkeypatch.setattr(automation_runtime, '_now_utc',
                        lambda: datetime(2026, 10, 12, 20, 1, tzinfo=UTC))
    monkeypatch.setattr(store, 'cycle_preflight_recovery_pending', lambda c: pending)
    refs = SimpleNamespace(manifest=SimpleNamespace(window=SimpleNamespace(end='2026-10-09')),
                           tickers=[], actions=[], candidate_id='c')
    from sentinel.core import rolling_inputs
    def checked_refs(*_a, manifest, **_kw):
        assert manifest is refs.manifest
        return refs
    monkeypatch.setattr(rolling_inputs.SnapshotReferences, '_from_bound_manifest', checked_refs)
    monkeypatch.setattr(automation_runtime.feed_inputs.snapshots, '_bound_and_manifest',
                        lambda *a: ({'candidate_id': 'c', 'snapshot_id': 's'}, refs.manifest))
    monkeypatch.setattr(automation_runtime.feed_inputs.snapshots, '_current', lambda *a: None)
    monkeypatch.setattr(automation_runtime.feed_inputs.rolling_store, 'require_payload', lambda *a: None)
    monkeypatch.setattr(automation_runtime.feed_inputs.rolling_store, 'load_evidence',
                        lambda *a: {'alias_rejections': source_aliases.evidence()})
    sessions = []
    def build(_conn, session):
        sessions.append(session)
        automation_runtime.feed_inputs._snapshot_identity_authorities(conn, None, session=session)
        return broker
    monkeypatch.setattr(runtime, '_broker', build)
    async def clean(**kwargs):
        return reconciliation(await kwargs['broker'].observe())
    monkeypatch.setattr(paper, 'recover_automated_paper_cycle', clean)
    monkeypatch.setattr(journal, 'in_flight_commands', lambda *a: ())
    with pytest.raises(automation_runtime.feed_inputs.ExecutionInputsRefused,
                       match='ROLLING_IDENTITY_BEYOND_NEXT_SESSION'):
        automation_runtime.feed_inputs._snapshot_identity_authorities(conn, None, session='2026-10-13')
    result = await runtime.recover(ctx)
    assert sessions == ['2026-10-12']
    assert result.disposition is ExecuteDisposition.SUCCEEDED
    assert any(sql.startswith('SELECT count(*) FROM pg_class') for sql, _ in conn.statements)
    assert [params for sql, params in conn.statements if sql == validation_query] == [('c',)]
    assert not any(call.startswith(('submit:', 'cancel:')) for call in broker.calls)


@async_test
@pytest.mark.parametrize('preflight,cause', [
    (True, 'ROLLING_IDENTITY_BEYOND_NEXT_SESSION'),
    (True, 'ROLLING_IDENTITY_HISTORY_CHANGED'),
    (False, 'ROLLING_IDENTITY_BEYOND_NEXT_SESSION')])
async def test_only_preflight_identity_horizon_is_typed_availability(monkeypatch, preflight, cause):
    cfg = config()
    ctx = context(cfg, state=CycleState.DISCOVERED if preflight else CycleState.RECONCILING,
                  plan=None if preflight else plan())
    runtime = production(cfg)
    conn = FakeConnection()
    install_runtime_seams(monkeypatch, runtime, conn, ctx, SimulatedBroker())
    monkeypatch.setattr(automation_runtime, '_now_utc', lambda: NOW)
    monkeypatch.setattr(store, 'cycle_preflight_recovery_pending', lambda c: False)
    sessions = []
    def refused(_conn, session):
        sessions.append(session)
        raise automation_runtime.feed_inputs.ExecutionInputsRefused(cause)
    monkeypatch.setattr(runtime, '_broker', refused)
    expected = SourceDataPending if preflight and cause == 'ROLLING_IDENTITY_BEYOND_NEXT_SESSION' else automation_runtime.feed_inputs.ExecutionInputsRefused
    with pytest.raises(expected):
        await runtime.recover(ctx)
    assert sessions == [str(EFFECTIVE)]
    assert conn.closed == 1


@async_test
@pytest.mark.parametrize('kind,typed', [
    ('planless', True), ('before_authority', True), ('bound_plan', False),
    ('live', False), ('other_db_failure', False), ('unreviewed', False),
])
async def test_preflight_preserves_exact_guarded_read_corpus_pin(monkeypatch, kind, typed):
    from contextlib import nullcontext
    from sentinel.feed.publication import CorpusLockUnavailable

    cfg = config()
    state = CycleState.RECONCILING if kind == 'bound_plan' else CycleState.DISCOVERED
    ctx = context(cfg, state=state, plan=plan() if kind == 'bound_plan' else None)
    runtime = production(cfg)
    conn = FakeConnection()
    broker = SimulatedBroker()
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    runtime._operational_source_only = True
    runtime._live_run_enabled = kind == 'live'
    monkeypatch.setattr(automation_runtime.feed_inputs, 'pinned',
                        lambda *_a, **_k: nullcontext())
    native = (ConnectionError('database unavailable') if kind == 'other_db_failure'
              else CorpusLockUnavailable('snapshot reader cannot pin during publication or retirement'))
    wrapper_type = BrokerAuthorityCheckFailed
    if kind == 'unreviewed':
        class UnknownGuardFailure(BrokerAuthorityCheckFailed):
            pass
        wrapper_type = UnknownGuardFailure

    def guard(*_a, **_k):
        raise wrapper_type('fixture guarded broker check failed') from native

    if kind == 'before_authority':
        monkeypatch.setattr(runtime, '_assert_cycle_authority', guard)

    async def recover(**_kw):
        guard()

    from sentinel import trading
    monkeypatch.setattr(trading, 'recover_trading_account', recover)
    monkeypatch.setattr(paper, 'recover_automated_paper_cycle', recover)
    expected = PreflightPublicationPinUnavailable if typed else TransientInfrastructureFailure
    with pytest.raises(expected) as caught:
        await runtime.recover(ctx)
    assert type(caught.value) is expected
    assert broker.calls == [] and conn.closed == 1


def test_unrelated_outer_failure_cannot_claim_a_guarded_pin():
    from sentinel.feed.publication import CorpusLockUnavailable

    native = CorpusLockUnavailable('busy')
    wrapper = BrokerAuthorityCheckFailed('fixture guarded broker check failed')
    wrapper.__cause__ = native
    wrong = TransientInfrastructureFailure('unexpected outer failure')
    wrong.__cause__ = wrapper
    assert automation_runtime._native_publication_pin(wrong, broker_read=True) is None
    assert automation_runtime._native_publication_pin(wrapper) is None


@async_test
@pytest.mark.parametrize('guard_removed', [False, True])
async def test_preflight_reader_pin_retry_under_real_writer_queue(monkeypatch, pg, guard_removed):
    from contextlib import contextmanager

    import psycopg

    from sentinel.feed import publication, rolling_store
    from tests.sentinel.test_corpus_writer_scheduling import _queued, _spawn

    cfg = config()
    ctx = context(cfg, state=CycleState.DISCOVERED)
    runtime = production(cfg)
    runtime._operational_source_only = True
    broker = SimulatedBroker()
    key = publication.CORPUS_LOCK_KEY
    with (psycopg.connect(pg.sync_dsn) as owner,
          psycopg.connect(pg.sync_dsn) as writer,
          psycopg.connect(pg.sync_dsn) as inspector):
        install_runtime_seams(monkeypatch, runtime, owner, ctx, broker)
        # The setup seams grant no simulated broker permission. The leaf still
        # attempts a real same-corpus pin from a separate guard connection.
        monkeypatch.setattr(automation_runtime.schema, 'require_runtime_schema', lambda _c: None)
        monkeypatch.setattr(automation_runtime, 'require_observation_integrity', lambda _c: None)
        thread = None
        outcome = None

        @contextmanager
        def pinned(conn, *, commit):
            nonlocal thread, outcome
            assert conn is owner and not commit
            assert owner.execute('SELECT pg_try_advisory_lock_shared(%s)', (key,)).fetchone()[0]
            try:
                def exclusive_turn():
                    writer.execute('SELECT pg_advisory_xact_lock(%s)', (key,))
                    writer.rollback()

                thread, outcome = _spawn(exclusive_turn)
                _queued(inspector, writer.info.backend_pid, outcome)
                yield object()
            finally:
                owner.execute('SELECT pg_advisory_unlock_shared(%s)', (key,))
                owner.rollback()

        async def guarded_read(grant, operation):
            with psycopg.connect(pg.sync_dsn) as fresh:
                rolling_store._pin_reader(fresh)

        async def unexpected(*_a, **_k):
            pytest.fail('this preflight performed a post-read check or attempted a mutation')

        async def recovering(*, conn, broker, grant, **_kw):
            wrapped = GuardedExecutionBroker(inner=broker, grant=grant,
                guard=ExecutionBrokerGuard(guarded_read, unexpected, unexpected))
            await wrapped.account_snapshot()
            pytest.fail('the reader entered ahead of a queued exclusive writer')

        monkeypatch.setattr(automation_runtime.feed_inputs, 'pinned', pinned)
        monkeypatch.setattr(paper, 'recover_automated_paper_cycle', recovering)
        if guard_removed:
            classifier = automation_runtime._native_publication_pin
            monkeypatch.setattr(automation_runtime, '_native_publication_pin',
                                lambda exc, **_kw: classifier(exc))
        try:
            with pytest.raises(TransientInfrastructureFailure) as caught:
                await runtime.recover(ctx)
            assert type(caught.value) is (TransientInfrastructureFailure if guard_removed
                                          else PreflightPublicationPinUnavailable)
            mapped = caught.value if guard_removed else caught.value.__cause__
            assert type(mapped.__cause__) is BrokerAuthorityCheckFailed
            assert type(mapped.__cause__.__cause__) is publication.CorpusLockUnavailable
            assert not broker.calls and owner.closed
        finally:
            if thread is not None:
                thread.join(8)
                assert not thread.is_alive() and not outcome.get('error')


def test_removing_preflight_date_guard_is_detected(monkeypatch):
    runtime = production(config())
    ctx = context(config(), state=CycleState.DISCOVERED)
    monkeypatch.setattr(automation_runtime, '_now_utc',
                        lambda: datetime(2026, 8, 12, 20, 1, tzinfo=UTC))
    assert runtime._recovery_identity_session(ctx.cycle) == ('2026-08-12', True)
    monkeypatch.setattr(runtime, '_recovery_identity_session', lambda c: (str(c.effective_session), True))
    with pytest.raises(AssertionError):
        assert runtime._recovery_identity_session(ctx.cycle) == ('2026-08-12', True)


@async_test
async def test_native_close_frontier_wait_reaches_source_retry_without_broker_or_publisher(monkeypatch):
    from sentinel import rolling_runtime
    from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending

    cfg = config()
    ctx = context(cfg, state=CycleState.REFRESHING_DATA)
    conn = FakeConnection()
    runtime = production(cfg)
    runtime._dual_run_enabled = True
    runtime._shadow_observation_id = 'primary'
    runtime._shadow_starting_cash = Decimal('50000')
    monkeypatch.setattr(runtime, 'connect', lambda: conn)
    monkeypatch.setattr(runtime, '_assert_cycle_authority',
                        lambda *args, **kwargs: (ctx.cycle, control(cfg)))
    monkeypatch.setattr(automation_runtime.schema, 'require_runtime_schema', lambda _: None)
    monkeypatch.setattr(automation_runtime, 'require_execution_schemas', lambda _: None)
    monkeypatch.setattr(automation_runtime, 'require_observation_integrity', lambda _: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, 'current', lambda _: SimpleNamespace(version=7))
    monkeypatch.setattr(automation_runtime.feed_inputs, 'is_rolling', lambda _: True)
    monkeypatch.setattr(automation_runtime.feed_inputs, 'require_shadow_mode', lambda *args: None)
    monkeypatch.setattr(rolling_runtime, 'selected', lambda _: True)

    def pending(*args, **kwargs):
        raise RollingSourceFrontierPending('ROLLING_INPUTS_NOT_READY: rolling source-final frontier')

    monkeypatch.setattr(rolling_runtime, 'status', pending)
    monkeypatch.setattr(runtime, '_broker', lambda *args: pytest.fail('waiting reached broker'))
    monkeypatch.setattr(automation_runtime.ingest, 'daily',
                        lambda *args, **kwargs: pytest.fail('waiting raced publisher'))
    with pytest.raises(SourceDataPending, match='source-final close'):
        await runtime.refresh(ctx)
    assert conn.closed == 1


@async_test
async def test_dual_refresh_never_races_the_shadow_publication_writer(
        monkeypatch) -> None:
    cfg = config()
    ctx = context(cfg, state=CycleState.REFRESHING_DATA)
    conn = FakeConnection()
    runtime = production(cfg)
    runtime._dual_run_enabled = True  # noqa: SLF001 - reviewed-mode seam
    monkeypatch.setattr(runtime, "connect", lambda: conn)
    monkeypatch.setattr(
        runtime, "_assert_cycle_authority",
        lambda _conn, _context, *, operation_scope: (
            ctx.cycle, control(cfg)))
    monkeypatch.setattr(
        automation_runtime, "require_execution_schemas",
        lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.schema, "require_runtime_schema",
        lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.feed_store, "latest_visible_session",
        lambda _conn: "2026-08-11")
    monkeypatch.setattr(
        automation_runtime.ingest, "daily",
        lambda *_args, **_kwargs: pytest.fail(
            "broker-capable dual runtime raced the shadow publisher"))

    with pytest.raises(RuntimeError, match="dedicated shadow data publisher"):
        await runtime.refresh(ctx)

    assert conn.closed == 1


@pytest.mark.parametrize("restricted", [False, True])
@async_test
async def test_dual_prepare_bypasses_legacy_paper_catchup_lineage(
        monkeypatch, restricted) -> None:
    """An upgraded dual NAS must not synthesize legacy PAPER gap cycles."""
    cfg = config()
    ctx = context(cfg, state=CycleState.PREPARING)
    conn = FakeConnection()
    runtime = production(cfg)
    runtime._dual_run_enabled = True  # noqa: SLF001 - reviewed-mode seam
    runtime._shadow_observation_id = "shadow-observation"  # noqa: SLF001
    runtime._shadow_starting_cash = Decimal("1000")  # noqa: SLF001
    monkeypatch.setattr(runtime, "connect", lambda: conn)
    monkeypatch.setattr(
        runtime, "_assert_cycle_authority",
        lambda _conn, _context, *, operation_scope: (
            ctx.cycle, control(cfg)))
    monkeypatch.setattr(
        automation_runtime, "require_execution_schemas",
        lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.schema, "require_runtime_schema",
        lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.catchup, "last_processed_session",
        lambda _conn: pytest.fail("dual mode read the legacy PAPER cursor"))
    monkeypatch.setattr(
        store, "ensure_historical_cycles",
        lambda *_args, **_kwargs: pytest.fail(
            "dual mode synthesized legacy PAPER history"))
    monkeypatch.setattr(runtime, "_broker", lambda *_args: SimulatedBroker())
    current_plan = plan()
    calls = []

    async def prepare_current(**kwargs):
        calls.append(kwargs)
        rec = ReconciliationResult(runtime_state=RuntimeState.RUNNING,
            observation=await SimulatedBroker().observe(), observation_id=587,
            restricted_securities={"SEC-AAA": "pending"} if restricted else {})
        return paper.PreparationResult(
            plan=current_plan, sessions_replayed=0, warmup_sessions=0,
            state_fingerprint="state", publication_version=1,
            frontier=DECISION.isoformat(), reconciliation=rec)

    monkeypatch.setattr(paper, "prepare_paper_plan", prepare_current)
    monkeypatch.setattr(
        runtime, "_require_dual_plan_shadow_match",
        lambda *_args, **_kwargs: {"status": "MATCHED"})

    result = await runtime.prepare(ctx)

    assert result.plan_id == current_plan.plan_id
    assert result.clean_observation_id == (None if restricted else 587)
    assert result.missed_sessions == ()
    assert calls[0]["dual_shadow_observation_id"] == "shadow-observation"
    assert calls[0]["dual_shadow_starting_cash"] == Decimal("1000")
    assert conn.closed == 1


def permissive_guard() -> ExecutionBrokerGuard:
    async def before_read(_grant, _operation):
        return None

    async def after_read(_grant, _operation, _result):
        return None

    async def before_mutation(_grant, _operation):
        return None

    return ExecutionBrokerGuard(
        before_read=before_read, after_read=after_read,
        before_mutation=before_mutation)


@async_test
async def test_accepted_submit_needs_restart_reobservation_and_final_fill(
        monkeypatch) -> None:
    """ACK is never success; only a later clean, zero-delta read is success."""
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    inner = SimulatedBroker()
    grant = automation_runtime._grant(  # noqa: SLF001
        ctx, "EXECUTE", binding=control(cfg).binding)
    guarded = GuardedExecutionBroker(
        inner=inner, grant=grant, guard=permissive_guard())
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, guarded)
    install_durable_projection(monkeypatch, current_plan)
    submitted = command(current_plan.plan_id)
    in_flight = [submitted]

    async def execute_through_membrane(**kwargs):
        assert kwargs["grant"] == grant
        outcome = await kwargs["broker"].submit(
            client_key=submitted.client_key, instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1"))
        assert outcome.state is CommandState.ACKNOWLEDGED
        observed = await kwargs["broker"].observe()
        rec = reconciliation(observed)
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=rec, submitted=(submitted,), detail="accepted"))

    async def recover_through_membrane(**kwargs):
        observed = await kwargs["broker"].observe()
        return reconciliation(observed, observation_id=12)

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", execute_through_membrane)
    monkeypatch.setattr(
        paper, "recover_automated_paper_cycle", recover_through_membrane)
    monkeypatch.setattr(
        journal, "in_flight_commands", lambda _conn, _deployment: tuple(in_flight))
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)

    accepted = await runtime.execute(ctx)
    assert accepted.disposition is ExecuteDisposition.RECONCILE
    assert any(call.startswith("submit:") for call in inner.calls)

    still_open = await runtime.recover(ctx)
    assert still_open.disposition is ExecuteDisposition.RECONCILE
    assert still_open.failure_code == "COMMANDS_IN_FLIGHT"

    inner.fill(submitted.client_key)
    in_flight.clear()
    completed = await runtime.recover(ctx)
    assert completed.disposition is ExecuteDisposition.SUCCEEDED
    assert completed.last_clean_reconciliation_id == "12"


@async_test
async def test_postsubmit_native_refusal_keeps_ack_for_read_only_recovery(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    execute_ctx = context(cfg, plan=current_plan)
    inner = SimulatedBroker()
    grant = automation_runtime._grant(  # noqa: SLF001
        execute_ctx, "EXECUTE", binding=control(cfg).binding)
    guarded = GuardedExecutionBroker(
        inner=inner, grant=grant, guard=permissive_guard())
    runtime = production(cfg)
    install_runtime_seams(
        monkeypatch, runtime, FakeConnection(), execute_ctx, guarded)
    submitted = command(current_plan.plan_id)

    async def execute_through_membrane(**kwargs):
        outcome = await kwargs["broker"].submit(
            client_key=submitted.client_key, instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1"))
        assert outcome.state is CommandState.ACKNOWLEDGED
        refused = ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING,
            detail="unsupported native TRD execution_type",
            native_fill_integrity_refused=True)
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RECONCILING,
                reconciliation=refused, submitted=(submitted,),
                detail=refused.detail))

    async def recover_refusal(**_kwargs):
        raise PaperDataIntegrityRefused(
            "unsupported native TRD execution_type")

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", execute_through_membrane)
    monkeypatch.setattr(
        paper, "recover_automated_paper_cycle", recover_refusal)
    monkeypatch.setattr(journal, "in_flight_commands",
                        lambda *_args: (submitted,))

    executed = await runtime.execute(execute_ctx)
    assert executed.disposition is ExecuteDisposition.RECONCILE
    assert executed.failure_code == "COMMANDS_IN_FLIGHT"
    assert executed.diagnostic["execution"]["reconciliation"][  # noqa: SLF001
        "native_fill_integrity_refused"] is True

    recover_ctx = context(cfg, state=CycleState.RECONCILING,
                          plan=current_plan)
    install_runtime_seams(
        monkeypatch, runtime, FakeConnection(), recover_ctx, guarded)
    with pytest.raises(automation_runtime.DataIntegrityFailure,
                       match="unsupported native TRD"):
        await runtime.recover(recover_ctx)
    assert submitted.state is CommandState.ACKNOWLEDGED
    assert sum(call.startswith("submit:") for call in inner.calls) == 1
    assert not any(call.startswith("cancel:") for call in inner.calls)


@async_test
async def test_dual_raw_buy_ack_fill_recovery_converges_without_projection(
        monkeypatch) -> None:
    """The informational raw plan still needs a later exact filled-book read."""
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    inner = SimulatedBroker()
    grant = automation_runtime._grant(  # noqa: SLF001
        ctx, "EXECUTE", binding=control(cfg).binding)
    guarded = GuardedExecutionBroker(
        inner=inner, grant=grant, guard=permissive_guard())
    runtime = production(cfg)
    runtime._dual_run_enabled = True  # noqa: SLF001 - reviewed-mode seam
    install_runtime_seams(monkeypatch, runtime, conn, ctx, guarded)
    submitted = command(current_plan.plan_id)
    in_flight = [submitted]
    proof = {
        "sizing_authority_sha256": "d" * 64,
        "shadow_record_sha256": "e" * 64,
    }
    monkeypatch.setattr(
        runtime, "_require_dual_plan_shadow_match",
        lambda *_args, **_kwargs: proof)
    monkeypatch.setattr(
        automation_runtime.feed_inputs, "require_current",
        lambda _conn: SimpleNamespace(version=7, evidence={}))
    monkeypatch.setattr(
        automation_runtime.feed_store, "latest_visible_session",
        lambda _conn: DECISION.isoformat())
    monkeypatch.setattr(
        informational_paper_mirror, "require_transport_permitted",
        lambda *_args, **_kwargs: {"status": "PREOPEN_UNPROVEN_PENDING"})
    pending_calls = []
    monkeypatch.setattr(
        informational_paper_mirror, "require_pending_for_plan",
        lambda *_args, **kwargs: pending_calls.append(kwargs) or {})
    monkeypatch.setattr(
        target_reprojection, "load_projection",
        lambda *_args, **_kwargs: None)

    async def execute_through_membrane(**kwargs):
        outcome = await kwargs["broker"].submit(
            client_key=submitted.client_key, instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1"))
        assert outcome.state is CommandState.ACKNOWLEDGED
        return paper.ExecutionResult(
            plan=current_plan,
            preflight=reconciliation(
                await kwargs["broker"].observe(), observation_id=10),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=reconciliation(
                    await kwargs["broker"].observe()),
                submitted=(submitted,), detail="accepted"))

    async def recover_through_membrane(**kwargs):
        return reconciliation(
            await kwargs["broker"].observe(), observation_id=12)

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", execute_through_membrane)
    monkeypatch.setattr(
        paper, "recover_automated_paper_cycle", recover_through_membrane)
    monkeypatch.setattr(
        journal, "in_flight_commands", lambda *_args: tuple(in_flight))
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)

    accepted = await runtime.execute(ctx)
    assert accepted.disposition is ExecuteDisposition.RECONCILE
    still_open = await runtime.recover(ctx)
    assert still_open.disposition is ExecuteDisposition.RECONCILE

    inner.fill(submitted.client_key)
    in_flight.clear()
    completed = await runtime.recover(ctx)

    assert completed.disposition is ExecuteDisposition.SUCCEEDED
    assert completed.last_clean_reconciliation_id == "12"
    assert pending_calls[-1]["sizing_authority_sha256"] == "d" * 64


@pytest.mark.parametrize('existing_state', [None, *CommandState])
@async_test
async def test_unstamped_raw_recovery_requires_no_durable_command(monkeypatch, existing_state):
    cfg = config()
    runtime = production(cfg)
    runtime._dual_run_enabled = True
    p = plan()
    broker = SimulatedBroker()
    observation = await broker.observe()
    monkeypatch.setattr(runtime, '_require_dual_plan_shadow_match',
                        lambda *_a, **_k: {'sizing_authority_sha256':'d'*64,
                                          'shadow_record_sha256':'e'*64})
    monkeypatch.setattr(target_reprojection, 'load_projection', lambda *_a, **_k: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, 'require_current',
                        lambda _c: SimpleNamespace(version=7))
    monkeypatch.setattr(automation_runtime.feed_inputs, 'frontier', lambda _c: DECISION.isoformat())
    monkeypatch.setattr(informational_paper_mirror, 'require_transport_permitted', lambda *_a, **_k: {})
    def unstamped(*_a, **_k):
        raise informational_paper_mirror.InformationalPaperMirrorUnstamped('not reached')
    monkeypatch.setattr(informational_paper_mirror, 'require_pending_for_plan', unstamped)
    monkeypatch.setattr(journal, 'load_commands',
                        lambda *_a, **_k: (() if existing_state is None else
                                          (SimpleNamespace(state=existing_state),)))
    kwargs = dict(plan=p, effective_session=EFFECTIVE, observation=observation,
                  minimum_quantity_increment=Decimal(1), reconciliation=reconciliation(observation))
    if existing_state is None:
        assert len(runtime._actionable_current_plan_deltas(FakeConnection(), **kwargs)) == 1
        for evidence in (None, replace(kwargs['reconciliation'], runtime_state=RuntimeState.FOREIGN_ACTIVITY),
                         replace(kwargs['reconciliation'], observation=replace(observation))):
            with pytest.raises(NonRetryableCallbackRefused, match='clean transport reconciliation'):
                runtime._actionable_current_plan_deltas(FakeConnection(), **{**kwargs,'reconciliation':evidence})
        from sentinel.execution.contract import BrokerPosition
        held=replace(observation,positions=(BrokerPosition(INSTRUMENT,Decimal(1)),))
        assert runtime._actionable_current_plan_deltas(FakeConnection(),
            **{**kwargs,'observation':held,'reconciliation':reconciliation(held)}) == ()
    else:
        with pytest.raises(NonRetryableCallbackRefused, match='commands but no PENDING'):
            runtime._actionable_current_plan_deltas(FakeConnection(), **kwargs)
        import inspect,textwrap
        from types import MethodType
        source=textwrap.dedent(inspect.getsource(type(runtime)._actionable_current_plan_deltas))
        weakened=source.replace('if journal.load_commands(conn, deployment, plan_id=plan.plan_id):','if False:')
        assert weakened!=source
        namespace=dict(vars(automation_runtime));exec(weakened,namespace)
        unsafe=MethodType(namespace['_actionable_current_plan_deltas'],runtime)
        # The same durable command would become executable without this guard.
        assert len(unsafe(FakeConnection(),**kwargs))==1


@async_test
async def test_scoped_recovery_retries_and_expires_without_operator_latch(monkeypatch):
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    runtime = production(cfg)
    broker = SimulatedBroker()
    install_runtime_seams(monkeypatch, runtime, FakeConnection(), ctx, broker)
    install_durable_projection(monkeypatch, current_plan)
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: ())
    now = [NOW]
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: now[0])
    restricted = [True]

    async def recover(**kwargs):
        return replace(reconciliation(await broker.observe(), observation_id=12),
                       restricted_securities=({INSTRUMENT.security_id: "split pending"}
                                              if restricted[0] else {}))

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", recover)
    ready = await runtime.recover(ctx)
    assert ready.disposition is ExecuteDisposition.READY_TO_EXECUTE
    assert ready.last_clean_reconciliation_id is None
    assert ready.transport_reconciliation_id == "12"
    now[0] = ctx.cycle.execution_close_at
    expired = await runtime.recover(ctx)
    assert expired.disposition is ExecuteDisposition.SUPERSEDED
    assert expired.last_clean_reconciliation_id is None
    now[0] = NOW
    broker.seed_position(INSTRUMENT, "1")
    restricted[0] = False
    cleared = await runtime.recover(ctx)
    assert cleared.disposition is ExecuteDisposition.SUCCEEDED
    assert cleared.last_clean_reconciliation_id == "12"


async def _restricted_preflight_result(monkeypatch, *, state=CycleState.DISCOVERED,
                                      failure=None):
    cfg = config()
    ctx = context(cfg, state=state, generation=2 if failure == "old_generation" else 3)
    if state in {CycleState.RETRY_WAIT, CycleState.RECONCILING}:
        ctx = ctx.model_copy(update={"cycle": ctx.cycle.model_copy(update={
            "diagnostic": {"retry_phase": "PREFLIGHT_RECOVER"}})})
    runtime, broker = production(cfg), SimulatedBroker()
    install_runtime_seams(monkeypatch, runtime, FakeConnection(), ctx, broker)
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: NOW)
    pending = (() if failure != "in_flight" else
               (command("previous", state=CommandState.UNKNOWN),))
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_a: pending)

    async def recover(**_kwargs):
        observed = await broker.observe()
        if failure == "incomplete":
            observed = replace(observed, completeness=Completeness.PARTIAL)
        result = replace(reconciliation(observed, observation_id=(
            None if failure == "missing_id" else 12)),
            restricted_securities={INSTRUMENT.security_id: "split pending"})
        if failure == "foreign":
            result = replace(result, runtime_state=RuntimeState.FOREIGN_ACTIVITY,
                             foreign_positions=(INSTRUMENT.security_id,))
        result.cash_correction_classifications = [{"evidence_sha256": "f" * 64}]
        return result

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", recover)
    return await runtime.recover(ctx), broker


@async_test
@pytest.mark.parametrize("state", [CycleState.DISCOVERED, CycleState.RETRY_WAIT,
                                  CycleState.RECONCILING])
async def test_scoped_planless_preflight_can_prepare_without_clean_success(monkeypatch, state):
    result, broker = await _restricted_preflight_result(monkeypatch, state=state)
    assert result.disposition is ExecuteDisposition.READY_TO_PREPARE
    assert result.last_clean_reconciliation_id is None
    assert result.transport_reconciliation_id == "12"
    assert result.diagnostic["restricted_securities"] == {INSTRUMENT.security_id: "split pending"}
    assert result.diagnostic["cash_correction_classifications"] == [{"evidence_sha256": "f" * 64}]
    assert not any(call.startswith("submit:") for call in broker.calls)


@async_test
@pytest.mark.parametrize("failure,expected", [
    ("in_flight", ExecuteDisposition.RECONCILE),
    ("incomplete", ExecuteDisposition.RECONCILE),
    ("missing_id", ExecuteDisposition.BLOCKED),
    ("foreign", ExecuteDisposition.BLOCKED),
    ("old_generation", ExecuteDisposition.SUPERSEDED),
    ("not_preflight", ExecuteDisposition.RECONCILE),
])
async def test_preparation_continuation_preserves_recovery_guards(monkeypatch, failure, expected):
    result, _broker = await _restricted_preflight_result(
        monkeypatch, state=(CycleState.EXECUTING if failure == "not_preflight"
                            else CycleState.DISCOVERED), failure=failure)
    assert result.disposition is expected
    assert result.last_clean_reconciliation_id is None


def test_preparation_continuation_scope_guard_has_a_falsifier(monkeypatch):
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(automation_runtime.ProductionAutomation.recover))
    original = "if preflight and cycle.plan_id is None:"
    assert source.count(original) == 1
    namespace = {}
    exec(compile(source.replace(original, "if True:", 1), "unscoped-preparation", "exec"),
         vars(automation_runtime), namespace)
    monkeypatch.setattr(automation_runtime.ProductionAutomation, "recover", namespace["recover"])
    with pytest.raises(AssertionError):
        test_preparation_continuation_preserves_recovery_guards(
            monkeypatch, "not_preflight", ExecuteDisposition.RECONCILE)


@async_test
async def test_dual_run_propagates_gateway_shadow_refusal_without_repeat_verification(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    runtime = production(cfg)
    runtime._dual_run_enabled = True  # noqa: SLF001 - explicit mode seam
    monkeypatch.setattr(runtime, "connect", lambda: conn)
    monkeypatch.setattr(
        runtime, "_assert_cycle_authority",
        lambda _conn, _context, *, operation_scope: (
            ctx.cycle, control(runtime.automation_config)))
    monkeypatch.setattr(
        automation_runtime, "require_execution_schemas",
        lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    broker_builds = []
    monkeypatch.setattr(
        runtime, "_broker",
        lambda *_args, **_kwargs: broker_builds.append(True))

    monkeypatch.setattr(runtime, "_require_dual_plan_shadow_match",
                        lambda *_a, **_k: pytest.fail("adapter repeated gateway proof"))

    async def gateway_refusal(**kwargs):
        assert kwargs["conn"] is conn
        assert kwargs["grant"].operation_scope == "EXECUTE"
        assert kwargs["automation_config_sha256"] == cfg.fingerprint
        assert kwargs["dual_shadow_observation_id"] == runtime._shadow_observation_id
        raise automation_runtime.paper.PaperActivationRefused(
            "dual-run plan/shadow reconciliation refused")

    monkeypatch.setattr(automation_runtime.paper, "execute_automated_paper_plan", gateway_refusal)

    with pytest.raises(
            NonRetryableCallbackRefused, match="plan/shadow"):
        await runtime.execute(ctx)
    assert broker_builds == [True]


@async_test
async def test_partial_recovery_requires_reobservation_not_success(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="0")
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker().schedule_observe(FaultKind.PARTIAL_OBSERVATION)
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def partial(**kwargs):
        observed = await kwargs["broker"].observe()
        assert observed.completeness is Completeness.PARTIAL
        return reconciliation(
            observed, runtime_state=RuntimeState.RECONCILING)

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", partial)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())

    result = await runtime.recover(ctx)

    assert result.disposition is ExecuteDisposition.RECONCILE
    assert result.failure_code == "RECOVERY_REOBSERVATION_REQUIRED"


@async_test
async def test_current_cycle_clean_read_still_requires_zero_share_delta(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="3")
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "1")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    install_durable_projection(monkeypatch, current_plan)

    async def clean(**kwargs):
        return reconciliation(await kwargs["broker"].observe())

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: NOW)

    result = await runtime.recover(ctx)

    assert result.disposition is ExecuteDisposition.READY_TO_EXECUTE
    assert result.failure_code == "READY_FOR_FRESH_EXECUTION"


@async_test
async def test_split_projected_book_is_converged_during_recovery(
        monkeypatch) -> None:
    """A 2-for-1 target of 10 is complete at 20, not a corrective SELL."""
    cfg = config()
    current_plan = plan(target="10")
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "20")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    projection = install_durable_projection(
        monkeypatch, current_plan, multiplier="2")

    async def clean(**kwargs):
        return reconciliation(await kwargs["broker"].observe())

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    monkeypatch.setattr(
        journal, "load_commands",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a converged split target was treated as actionable")))

    result = await runtime.recover(ctx)

    assert projection.target_basket == {INSTRUMENT.security_id: Decimal("20")}
    assert result.disposition is ExecuteDisposition.SUCCEEDED


@async_test
async def test_split_projected_book_is_converged_after_execute(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="10")
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "20")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    install_durable_projection(monkeypatch, current_plan, multiplier="2")

    async def no_submit(**kwargs):
        rec = reconciliation(await kwargs["broker"].observe())
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=rec, detail="already projected"))

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", no_submit)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())

    result = await runtime.execute(ctx)

    assert result.disposition is ExecuteDisposition.SUCCEEDED


@async_test
@pytest.mark.parametrize('change', [
    'unchanged', 'actionable', 'control', 'writer', 'scope', 'cancel', 'plan'])
async def test_operational_completion_reenters_owned_proof_with_fresh_fences(
        monkeypatch, caplog, change) -> None:
    from contextlib import contextmanager
    from sentinel import structural_verification
    caplog.set_level('INFO', logger=automation_runtime.opening_stage_log.LOGGER_NAME)

    cfg = config()
    current_plan = plan(target="1")
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "1")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    runtime._dual_run_enabled = True
    runtime._operational_source_only = True
    monkeypatch.setattr(runtime, '_require_operational_inputs', lambda _conn, **_kwargs: None)
    monkeypatch.setattr(automation_runtime, 'require_observation_integrity',
                        lambda _conn: None)
    plan_reads = []

    def latest(_conn):
        assert _conn is conn
        plan_reads.append(len(plan_reads) + 1)
        return (plan(target="2") if change == 'plan' and len(plan_reads) > 1
                else current_plan)

    monkeypatch.setattr(journal, 'latest_plan', latest)
    monkeypatch.setattr(journal, 'in_flight_commands', lambda *_args: ())
    trace = []
    held = {'pin': False, 'writer': False, 'scope': False}

    @contextmanager
    def pinned(_conn, *, commit):
        assert _conn is conn and commit is False
        held['pin'] = True
        trace.append('pin')
        try:
            yield object()
        finally:
            held['pin'] = False

    @contextmanager
    def writer(_conn):
        assert _conn is conn and held['pin']
        trace.append('writer')
        if change == 'writer':
            raise journal.WriterLockUnavailable('simulated busy writer')
        held['writer'] = True
        try:
            yield
        finally:
            held['writer'] = False

    class Scope:
        @contextmanager
        def resume(self, owner):
            assert owner is conn and held['pin'] and held['writer']
            trace.append('scope')
            if change == 'scope':
                raise structural_verification.VerificationScopeRefused(
                    'STRUCTURAL_RESUME_OWNER_OR_PIN_CHANGED')
            held['scope'] = True
            try:
                yield
            finally:
                held['scope'] = False

    monkeypatch.setattr(automation_runtime.feed_inputs, 'pinned', pinned)
    monkeypatch.setattr(journal, 'writer_lock', writer)
    authority_calls = []

    def authorize(_conn, _context, *, operation_scope, record_verdict=True):
        assert _conn is conn and operation_scope == 'EXECUTE'
        authority_calls.append(record_verdict)
        if not record_verdict:
            assert held['writer'] and held['pin']
            if change == 'control':
                raise NonRetryableCallbackRefused('control changed after gateway')
        return ctx.cycle, control(cfg)

    monkeypatch.setattr(runtime, '_assert_cycle_authority', authorize)

    async def no_submit(**kwargs):
        assert held['pin']
        rec = reconciliation(await kwargs['broker'].observe())
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(runtime_state=RuntimeState.RUNNING,
                                  reconciliation=rec, detail='already held'),
            structural_scope=Scope())

    monkeypatch.setattr(paper, 'execute_automated_paper_plan', no_submit)

    def deltas(*_args, **_kwargs):
        assert held['pin'] and held['writer'] and held['scope']
        trace.append('deltas')
        if change == 'cancel':
            ctx.cancellation.cancel('leader revoked during completion')
        return (object(),) if change == 'actionable' else ()

    monkeypatch.setattr(runtime, '_actionable_current_plan_deltas', deltas)
    if change == 'control':
        with pytest.raises(NonRetryableCallbackRefused,
                           match='control changed after gateway'):
            await runtime.execute(ctx)
    elif change == 'writer':
        with pytest.raises(TransientInfrastructureFailure,
                           match='simulated busy writer'):
            await runtime.execute(ctx)
    elif change == 'scope':
        with pytest.raises(structural_verification.VerificationScopeRefused):
            await runtime.execute(ctx)
    elif change == 'plan':
        with pytest.raises(NonRetryableCallbackRefused,
                           match='lost the current durable PAPER plan'):
            await runtime.execute(ctx)
    elif change == 'cancel':
        with pytest.raises(StaleLeaderRefused,
                           match='leader revoked during completion'):
            await runtime.execute(ctx)
    else:
        result = await runtime.execute(ctx)
        assert result.disposition is (
            ExecuteDisposition.RECONCILE if change == 'actionable'
            else ExecuteDisposition.SUCCEEDED)
        assert set(result.diagnostic['opening_callback_stages_ms']) == {
            'paper_gateway', 'completion_proof'}
    assert not held['pin'] and not held['writer'] and not held['scope']
    assert authority_calls == ([True] if change == 'writer'
                               else [True, False])
    assert ('deltas' in trace) == (change in {'unchanged', 'actionable', 'cancel'})
    assert len(plan_reads) == (1 if change in {'writer', 'control'} else 2)
    prefix = 'automation_preflight_stage stage='
    assert [message.removeprefix(prefix).split()[0] for message in caplog.messages
            if message.startswith(prefix)] == [
                'connection_schema', 'observation_integrity', 'cycle_authority', 'operational_inputs',
                'plan_pin', 'broker_adapter']


@async_test
async def test_execute_refuses_clean_success_without_durable_projection(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="3")
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "1")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def no_submit(**kwargs):
        rec = reconciliation(await kwargs["broker"].observe())
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=rec, detail="apparently converged"))

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", no_submit)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())

    result = await runtime.execute(ctx)

    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == automation_runtime.TARGET_PROJECTION_REFUSED
    assert "is absent" in result.failure_detail


@async_test
async def test_execute_refuses_nonempty_raw_share_noop_without_projection(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="1")
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "1")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def no_submit(**kwargs):
        rec = reconciliation(await kwargs["broker"].observe())
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=rec,
                detail="complete clean empty no-op; no command transport"))

    monkeypatch.setattr(paper, "execute_automated_paper_plan", no_submit)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())

    result = await runtime.execute(ctx)

    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == automation_runtime.TARGET_PROJECTION_REFUSED


@async_test
async def test_execute_allows_empty_book_noop_without_projection(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="0")
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def no_submit(**kwargs):
        rec = reconciliation(await kwargs["broker"].observe())
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=rec,
                detail="complete clean empty no-op; no command transport"))

    monkeypatch.setattr(paper, "execute_automated_paper_plan", no_submit)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())

    result = await runtime.execute(ctx)

    assert result.disposition is ExecuteDisposition.SUCCEEDED


@async_test
async def test_recovery_refuses_corrupt_durable_projection(monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    broker.seed_position(INSTRUMENT, "1")
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def clean(**kwargs):
        return reconciliation(await kwargs["broker"].observe())

    def corrupt(_conn, *, plan_id):
        raise target_reprojection.TargetProjectionRefused(
            f"target projection for {plan_id} has a corrupt fingerprint")

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    monkeypatch.setattr(target_reprojection, "load_projection", corrupt)

    result = await runtime.recover(ctx)

    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == automation_runtime.TARGET_PROJECTION_REFUSED
    assert "corrupt fingerprint" in result.failure_detail


@async_test
async def test_adopted_old_generation_recovery_never_loads_stale_plan(
        monkeypatch) -> None:
    cfg = config()
    old = context(cfg, generation=2, state=CycleState.RECONCILING)
    # The current permit and adoption fence are generation 3 even though the
    # immutable cycle retains its generation-2 audit identity.
    old = CycleContext(
        cycle=old.cycle.model_copy(update={"last_fence_token": 17}),
        permit=old.permit)
    conn = FakeConnection()
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, old, broker)

    async def clean(**kwargs):
        return reconciliation(await kwargs["broker"].observe())

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(
        journal, "latest_plan",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("old-generation economics were loaded")))

    result = await runtime.recover(old)

    assert result.disposition is ExecuteDisposition.SUPERSEDED
    assert result.failure_code == "OLD_GENERATION_RECOVERED"


@async_test
async def test_revocation_between_read_and_submit_latches_without_mutation(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    inner = SimulatedBroker()
    revoked = False

    async def before_read(_grant, _operation):
        return None

    async def after_read(_grant, _operation, _result):
        return None

    async def before_mutation(_grant, _operation):
        if revoked:
            raise RuntimeError("signed authority revoked")

    grant = automation_runtime._grant(  # noqa: SLF001
        ctx, "EXECUTE", binding=control(cfg).binding)
    broker = GuardedExecutionBroker(
        inner=inner, grant=grant,
        guard=ExecutionBrokerGuard(
            before_read=before_read, after_read=after_read,
            before_mutation=before_mutation))
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def revoke_after_read(**kwargs):
        nonlocal revoked
        await kwargs["broker"].observe()
        revoked = True
        await kwargs["broker"].submit(
            client_key="must-not-land", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal("1"))
        raise AssertionError("unreachable")

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", revoke_after_read)

    with pytest.raises(NonRetryableCallbackRefused, match="revoked"):
        await runtime.execute(ctx)

    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in inner.calls)


@async_test
async def test_true_broker_read_outage_remains_retryable_transport(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    inner = SimulatedBroker().schedule_observe(FaultKind.OUTAGE)
    grant = automation_runtime._grant(  # noqa: SLF001
        ctx, "EXECUTE", binding=control(cfg).binding)
    broker = GuardedExecutionBroker(
        inner=inner, grant=grant, guard=permissive_guard())
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)

    async def read(**kwargs):
        return await kwargs["broker"].observe()

    monkeypatch.setattr(paper, "execute_automated_paper_plan", read)

    with pytest.raises(Exception, match="simulated transport failure") as caught:
        await runtime.execute(ctx)

    assert not isinstance(caught.value, BrokerAuthorityRefused)
    assert not isinstance(caught.value, NonRetryableCallbackRefused)


@pytest.mark.parametrize("retryable", [False, True])
@async_test
async def test_paper_refusal_class_controls_durable_latching(
        monkeypatch, retryable) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    runtime = production(cfg)
    install_runtime_seams(
        monkeypatch, runtime, FakeConnection(), ctx, SimulatedBroker())
    refusal = (paper.PaperRetryableRefused("settlement pending")
               if retryable
               else paper.PaperActivationRefused("plan identity corrupt"))

    async def refuse(**_kwargs):
        raise refusal

    monkeypatch.setattr(paper, "execute_automated_paper_plan", refuse)

    expected = (TransientInfrastructureFailure if retryable
                else NonRetryableCallbackRefused)
    with pytest.raises(expected):
        await runtime.execute(ctx)


@pytest.mark.parametrize("phase", ["prepare", "execute", "recover"])
@async_test
async def test_native_fill_integrity_refusal_maps_to_terminal_data_integrity(
        monkeypatch, phase) -> None:
    cfg = config()
    current_plan = plan()
    state = {"prepare": CycleState.PREPARING,
             "execute": CycleState.EXECUTING,
             "recover": CycleState.RECONCILING}[phase]
    ctx = context(cfg, state=state,
                  plan=None if phase == "prepare" else current_plan)
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(
        monkeypatch, runtime, FakeConnection(), ctx, broker)
    if phase == "prepare":
        runtime._dual_run_enabled = True  # noqa: SLF001 - bypass legacy cursor
        monkeypatch.setattr(automation_runtime.schema,
                            "require_runtime_schema", lambda _conn: None)
        monkeypatch.setattr(automation_runtime,
                            "require_observation_integrity", lambda _conn: None)
        monkeypatch.setattr(runtime, "_require_operational_inputs",
                            lambda _conn: None)

    async def refused(**_kwargs):
        raise PaperDataIntegrityRefused(
            "retained native TRD execution_type is unsupported")

    callback = {"prepare": "prepare_paper_plan",
                "execute": "execute_automated_paper_plan",
                "recover": "recover_automated_paper_cycle"}[phase]
    monkeypatch.setattr(paper, callback, refused)

    with pytest.raises(automation_runtime.DataIntegrityFailure,
                       match="execution_type is unsupported"):
        await getattr(runtime, phase)(ctx)
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)


@async_test
async def test_missing_preopen_units_return_stable_terminal_failure_code(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(cfg, plan=current_plan)
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(
        monkeypatch, runtime, FakeConnection(), ctx, broker)

    async def refuse(**_kwargs):
        raise paper.PreOpenShareUnitAuthorityUnavailable(
            "complete provider publication is absent")

    monkeypatch.setattr(paper, "execute_automated_paper_plan", refuse)

    result = await runtime.execute(ctx)

    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == (
        automation_runtime.PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE)
    assert result.diagnostic["plan_id"] == current_plan.plan_id
    assert "provider publication" in result.failure_detail
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)


@async_test
async def test_recovery_missing_preopen_units_keep_stable_failure_code(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan()
    ctx = context(
        cfg, state=CycleState.RECONCILING, plan=current_plan)
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(
        monkeypatch, runtime, FakeConnection(), ctx, broker)

    async def refuse(**_kwargs):
        raise paper.PreOpenShareUnitAuthorityUnavailable(
            "recovered command lacks complete provider coverage")

    monkeypatch.setattr(
        paper, "recover_automated_paper_cycle", refuse)

    result = await runtime.recover(ctx)

    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == (
        automation_runtime.PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE)
    assert result.diagnostic["plan_id"] == current_plan.plan_id
    assert "recovered command" in result.failure_detail
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)


@pytest.mark.parametrize(("state", "diagnostic"), [
    (CycleState.RECONCILING, {}),
    (CycleState.RETRY_WAIT, {"retry_phase": "PREFLIGHT_RECOVER"}),
    (CycleState.RECONCILING, {"retry_phase": "PREFLIGHT_RECOVER"}),
], ids=["transport", "planless-preflight", "stranded-planless-preflight"])
def test_old_generation_grant_is_read_only_recovery_only(
        monkeypatch, state, diagnostic) -> None:
    cfg = config()
    current_control = control(cfg)
    old_cycle = cycle(
        cfg, generation=2, state=state, last_fence_token=17).model_copy(
            update={"diagnostic": diagnostic})
    assert store.cycle_recovery_capable(old_cycle)
    if diagnostic:
        assert store.cycle_preflight_recovery_pending(old_cycle)
        assert not store.cycle_transport_capable(old_cycle)
    conn = FakeConnection()
    monkeypatch.setattr(store, "load_control", lambda _conn: current_control)
    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)
    monkeypatch.setattr(store, "load_cycle", lambda _conn, _cycle_id: old_cycle)
    grant_values = dict(
        cycle_id=old_cycle.cycle_id, control_generation=3,
        holder_id="worker-a", fence_token=17,
        broker_account_id=current_control.broker_account_id,
        takeover_epoch=current_control.takeover_epoch,
        rollout_mode=current_control.rollout_mode,
        rollout_version=current_control.rollout_version,
        certificate_sha256=current_control.certificate_sha256)

    accepted = AutomationExecutionGrant(
        operation_scope="RECOVER", **grant_values)
    _control, validated = paper_validation._validate_automation_grant(  # noqa: SLF001
        conn, accepted)
    assert validated is old_cycle

    executable = AutomationExecutionGrant(
        operation_scope="EXECUTE", **grant_values)
    with pytest.raises(paper.PaperActivationRefused, match="read-only recovery"):
        paper_validation._validate_automation_grant(conn, executable)  # noqa: SLF001


def test_composition_requires_exact_signed_automation_authority(
        monkeypatch) -> None:
    cfg = config()
    ctx = context(cfg, plan=plan())
    runtime = production(cfg)
    conn = FakeConnection()
    calls = []
    verdicts = []

    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)
    monkeypatch.setattr(store, "load_control", lambda _conn: control(cfg))
    monkeypatch.setattr(store, "load_cycle", lambda _conn, _id: ctx.cycle)
    monkeypatch.setattr(
        store, "record_authority_verdict",
        lambda _conn, **kwargs: verdicts.append(kwargs))
    monkeypatch.setattr(
        automation_runtime, "load_rollout_state",
        lambda _conn: authority.RolloutState(
            authority.RolloutMode.PINNED_1_00, 1, None))
    monkeypatch.setattr(
        automation_runtime.feed_inputs, "require_current",
        lambda _conn: SimpleNamespace(version=81, evidence={}))
    monkeypatch.setattr(
        automation_runtime, "production_strategy",
        lambda: (object(), {"strategy": "sentinel-runtime-test"}))
    monkeypatch.setattr(
        automation_runtime.system_identity, "rehearsal_identity",
        lambda: {"runtime": "certified-image"})

    def signed_gate(_conn, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(certificate_sha256=CERTIFICATE)

    monkeypatch.setattr(
        automation_runtime, "require_current_authority", signed_gate)

    checked, checked_control = runtime._assert_cycle_authority(  # noqa: SLF001
        conn, ctx, operation_scope="EXECUTE")

    assert checked == ctx.cycle
    assert checked_control.binding == control(cfg).binding
    assert calls == [{
        "runtime_identity": {"runtime": "certified-image"},
        "strategy_identity": {"strategy": "sentinel-runtime-test"},
        "required_mode": authority.RolloutMode.PINNED_1_00,
        "required_operation": "AUTOMATION",
        "paper_base_url": DEFAULT_BASE_URL,
        "current_publication_version": 81,
        "automation_config_sha256": cfg.fingerprint,
    }]
    assert [item["verdict"] for item in verdicts] == ["PASS"]

    verdicts.clear()
    runtime._assert_cycle_authority(conn, ctx, operation_scope="REFRESH", record_verdict=False)
    assert verdicts == []

    monkeypatch.setattr(store, "load_cycle", lambda _conn, _id: ctx.cycle.model_copy(
        update={"certificate_sha256": "0" * 64}))
    with pytest.raises(NonRetryableCallbackRefused, match="cycle authority is stale"):
        runtime._assert_cycle_authority(conn, ctx, operation_scope="EXECUTE")
    assert [item["verdict"] for item in verdicts] == ["FAIL"]


def test_publishing_a_control_pass_before_cycle_validation_is_detected(monkeypatch):
    from inspect import getsource
    from textwrap import dedent

    cls = automation_runtime.ProductionAutomation
    source = dedent(getsource(cls._assert_cycle_authority))
    validation = 'self._validate_control_authority(conn, context.permit)'
    assert source.count(validation) == 1
    namespace = dict(vars(automation_runtime))
    exec(source.replace(validation, 'self._assert_control_authority(conn, context.permit)'), namespace)
    monkeypatch.setattr(cls, '_assert_cycle_authority', namespace['_assert_cycle_authority'])
    with pytest.raises(AssertionError):
        test_composition_requires_exact_signed_automation_authority(monkeypatch)


@pytest.fixture
def idle_attestation(monkeypatch):
    cfg = config().model_copy(update={"control_poll_seconds": 3, "heartbeat_seconds": 3})
    runtime = production(cfg)
    waiting = cycle(cfg, state=CycleState.WAITING_OPEN)
    conn = FakeConnection(lease_row=(
        "worker-a", 17, 3, NOW, NOW + timedelta(seconds=90)))
    state = dict(now=NOW, control=control(cfg), runtime="reviewed",
                 publication=1, revoked=False)
    full_checks, lifecycle_checks, verdicts, blocked = [], [], [], []
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: state["now"])
    monkeypatch.setattr(store, "require_leader", lambda _c, permit: permit)
    monkeypatch.setattr(store, "load_control", lambda _c: state["control"])
    monkeypatch.setattr(store, "load_cycle", lambda _c, _id: waiting)
    monkeypatch.setattr(store, "oldest_nonterminal_cycle", lambda _c: waiting)
    monkeypatch.setattr(store, "record_authority_verdict",
                        lambda _c, **kw: verdicts.append(kw))
    monkeypatch.setattr(automation_runtime, "load_rollout_state", lambda _c:
                        authority.RolloutState(authority.RolloutMode.PINNED_1_00, 1, None))
    monkeypatch.setattr(automation_runtime.feed_inputs, "require_current", lambda _c:
                        SimpleNamespace(version=state["publication"]))
    monkeypatch.setattr(runtime, "_idle_pin_mutable_authority", lambda _c: None)
    monkeypatch.setattr(runtime, "_idle_publication_head", lambda _c, **_kw:
                        {"version": state["publication"],
                         "receipt_sha256": "r" * 64})
    monkeypatch.setattr(automation_runtime, "production_strategy", lambda: (None, {}))
    monkeypatch.setattr(automation_runtime.system_identity, "rehearsal_identity",
                        lambda: {"runtime": state["runtime"]})

    def lifecycle(_c, **kw):
        lifecycle_checks.append(kw)
        if state["revoked"]:
            raise authority.AuthorityRefused("certificate revoked")
        return SimpleNamespace(certificate_sha256=CERTIFICATE)

    def full(_c, **kw):
        full_checks.append(kw)
        if state["revoked"] or state["runtime"] != "reviewed":
            raise authority.AuthorityRefused("current authority refused")
        return SimpleNamespace(certificate_sha256=CERTIFICATE)

    def block(_c, **kw):
        blocked.append(kw)
        return waiting.model_copy(update={"state": CycleState.BLOCKED})

    async def notify(*_a, **_kw):
        return None

    monkeypatch.setattr(runtime, "_idle_certificate_identity", lifecycle)
    monkeypatch.setattr(automation_runtime, "require_current_authority", full)
    monkeypatch.setattr(store, "transition_cycle", block)
    monkeypatch.setattr(store, "adopt_cycle", block)
    monkeypatch.setattr(runtime, "notify", notify)
    monkeypatch.setattr(runtime, "_broker", lambda *_a, **_k: pytest.fail("idle broker"))

    class CompletedFlight:
        timeout_seconds = 25
        backend_pid = None
        stage = "COMPLETE"
        elapsed_seconds = 0.01

        def __init__(self, value):
            self.value = value
            self.error = None
            self.finished = threading.Event()
            self.finished.set()
            self.cancelled = threading.Event()

        def stop(self, **_kwargs):
            self.cancelled.set()
            return True

    def start_idle(control_value, permit, observed_at):
        subject = {}

        def retain(checked, rollout, current):
            subject.update(
                generation=checked.generation,
                binding=checked.binding.model_dump(mode="json"),
                publication_version=current.version,
                publication_head=runtime._idle_publication_head(
                    conn, authenticated=current),
                rollout_mode=rollout.mode.value,
                rollout_version=rollout.version)

        try:
            _checked, certificate, _publication_version = (
                runtime._validate_control_authority(
                    conn, permit, include_publication_version=True,
                    retain_subject=retain))
            value = {"status": "PASS", **subject,
                     "certificate_sha256": certificate.certificate_sha256}
        except Exception as exc:  # noqa: BLE001
            try:
                runtime._raise_authority_refusal(exc)
            except NonRetryableCallbackRefused as refusal:
                value = {"status": "REFUSED", "detail": str(refusal),
                         "subject": subject or None}
            except TransientInfrastructureFailure:
                value = {"status": "TRANSIENT"}
            except StaleLeaderRefused:
                value = {"status": "STALE"}
        flight = CompletedFlight(value)
        runtime._idle_authority_flight = (
            flight, runtime._idle_attestation_key(control_value, permit),
            observed_at)
        return flight

    monkeypatch.setattr(runtime, "_start_idle_authority_observer", start_idle)
    return SimpleNamespace(runtime=runtime, conn=conn, state=state,
                           full=full_checks, lifecycle=lifecycle_checks,
                           verdicts=verdicts, blocked=blocked, cfg=cfg,
                           flight_type=CompletedFlight)


@async_test
@pytest.mark.parametrize("phase", range(4))
async def test_idle_renewal_during_recurring_writer_windows(idle_attestation, monkeypatch, phase):
    item = idle_attestation
    runtime = item.runtime
    await runtime.control_wake(item.conn)
    assert [v["verdict"] for v in item.verdicts] == ["PASS"]
    last_pass = NOW
    # The first full observer encounters a writer after the parent admits it.
    item.state["now"] = NOW + timedelta(seconds=30)

    def busy(_conn):
        raise automation_runtime.publication.CorpusLockUnavailable("cleanup writer")

    with monkeypatch.context() as child:
        child.setattr(automation_runtime.feed_inputs, "require_current", busy)
        await runtime.control_wake(item.conn)
    assert len(item.verdicts) == 1

    for tick in range(210):
        now = NOW + timedelta(seconds=33 + 3 * tick)
        item.state["now"] = now
        item.conn.lease_row = (*item.conn.lease_row[:-1], now + timedelta(seconds=12))
        count = len(item.verdicts)
        with monkeypatch.context() as parent:
            if tick % 4 == phase:
                parent.setattr(runtime, "_idle_pin_mutable_authority", busy)
            await runtime.control_wake(item.conn)
        assert now - last_pass < timedelta(minutes=5), "eligible idle renewal starved"
        if len(item.verdicts) > count:
            assert item.verdicts[-1]["verdict"] == "PASS"
            last_pass = now
    assert not item.blocked


@async_test
async def test_idle_retry_counts_new_attempts_and_observes_revocation(idle_attestation, monkeypatch):
    item = idle_attestation
    runtime = item.runtime

    def busy(_conn):
        raise automation_runtime.publication.CorpusLockUnavailable("observer lost the pin")

    monkeypatch.setattr(automation_runtime.feed_inputs, "require_current", busy)
    for delay in (5, 10, 20, 40):
        now = item.state["now"]
        due = now + timedelta(seconds=delay)
        assert await runtime.control_wake(item.conn) == due
        item.state["now"] = now + timedelta(seconds=1)
        assert await runtime.control_wake(item.conn) == due
        item.state["now"] = due
    assert not item.verdicts
    item.state.update(now=due - timedelta(seconds=1), revoked=True)
    await runtime.control_wake(item.conn)
    assert [v["verdict"] for v in item.verdicts] == ["FAIL"]
    assert item.blocked


@async_test
async def test_due_idle_retry_waits_one_poll_for_cancelled_observer_reap(idle_attestation):
    item = idle_attestation
    runtime = item.runtime
    flight = item.flight_type({})
    flight.cancelled.set()
    flight.finished.clear()
    permit = context(item.cfg).permit
    runtime._idle_authority_flight = (
        flight, runtime._idle_attestation_key(item.state["control"], permit), NOW)
    due = runtime._idle_authority_retry(NOW)
    item.state["now"] = due + timedelta(seconds=1)
    assert await runtime.control_wake(item.conn) > item.state["now"]
    assert runtime._idle_authority_retry_at == due
    assert runtime._idle_authority_flight[0] is flight and not item.verdicts


@async_test
@pytest.mark.parametrize("first_failure", ["parent_pin", "connect"])
async def test_clock_rollback_invalidates_pending_idle_retry(idle_attestation, monkeypatch, first_failure):
    item = idle_attestation
    item.state["now"] = NOW + timedelta(seconds=30)
    with monkeypatch.context() as conflict:
        def busy(_conn):
            raise automation_runtime.publication.CorpusLockUnavailable("writer")

        if first_failure == "connect":
            from psycopg import OperationalError

            def unavailable(*args, **kwargs):
                raise OperationalError("unavailable")

            conflict.setattr(automation_runtime.feed_store, "connect", unavailable)
            wake = await item.runtime.bounded_control_wake(item.conn)
        else:
            conflict.setattr(item.runtime, "_idle_pin_mutable_authority", busy)
            wake = await item.runtime.control_wake(item.conn)
        assert wake > item.state["now"]
    item.state["now"] -= timedelta(seconds=1)
    await item.runtime.control_wake(item.conn)
    assert [v["verdict"] for v in item.verdicts] == ["PASS"]


@async_test
async def test_idle_attestation_bounds_full_checks_without_refreshing_pass(idle_attestation):
    item = idle_attestation
    for elapsed in range(0, 31, 3):
        item.state["now"] = NOW + timedelta(seconds=elapsed)
        await item.runtime.control_wake(item.conn)
        assert len(item.full) == (1 if elapsed < 30 else 2)
        # One display write per full check; skips retain original evidence time.
        assert len(item.verdicts) == len(item.full)
    assert len(item.lifecycle) >= 9
    assert all(call == {"expected_sha256": CERTIFICATE}
               for call in item.lifecycle)
    assert item.runtime._idle_attestation[0] == NOW + timedelta(seconds=30)


@async_test
async def test_idle_attestation_publication_change_requires_new_full_proof(
        idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.state.update(now=NOW + timedelta(seconds=3), publication=2)
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 2
    assert [row["verdict"] for row in item.verdicts] == ["PASS", "PASS"]
    assert item.runtime._idle_attestation_publication_head["version"] == 2


@async_test
async def test_idle_attestation_revocation_immediately_runs_existing_block(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.state.update(now=NOW + timedelta(seconds=3), revoked=True)
    await item.runtime.control_wake(item.conn)
    # A known revoked certificate is terminal from the cheap current
    # lifecycle check; the full source proof need not repeat first.
    assert len(item.full) == 1
    assert item.blocked
    assert item.verdicts[-1]["verdict"] == "FAIL"
    assert item.runtime._idle_attestation is None


@async_test
async def test_idle_attestation_kill_is_observed_without_another_full_check(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.state["control"] = item.state["control"].model_copy(
        update={"kill_switch_engaged": True})
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 1
    assert item.runtime._idle_attestation is None


@async_test
async def test_idle_attestation_read_failure_cannot_resume_old_cadence(idle_attestation, monkeypatch):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)

    def unavailable(_conn):
        raise OSError("current control unavailable")

    monkeypatch.setattr(store, "load_control", unavailable)
    with pytest.raises(OSError, match="current control unavailable"):
        await item.runtime.control_wake(item.conn)
    assert item.runtime._idle_attestation is None
    monkeypatch.setattr(store, "load_control", lambda _c: item.state["control"])
    item.state["now"] = NOW + timedelta(seconds=3)
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 2
    assert item.lifecycle


@async_test
async def test_idle_attestation_detects_rollback_between_skipped_polls(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.state["now"] = NOW + timedelta(seconds=12)
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 1
    item.state["now"] = NOW + timedelta(seconds=9)
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 2
    assert item.lifecycle


@pytest.mark.parametrize("next_poll", [9, 30])
@async_test
async def test_idle_attestation_slow_check_cannot_extend_original_cadence(idle_attestation, monkeypatch, next_poll):
    item = idle_attestation
    original = automation_runtime.require_current_authority

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        item.state["now"] += timedelta(seconds=10)
        return result

    monkeypatch.setattr(automation_runtime, "require_current_authority", slow)
    await item.runtime.control_wake(item.conn)
    assert item.runtime._idle_attestation[0] == NOW
    if next_poll == 30:
        item.state["now"] = NOW + timedelta(seconds=29)
        await item.runtime.control_wake(item.conn)
        assert len(item.full) == 1
    # Nine is a rollback relative to the observed ten-second completion;
    # thirty is the original full-check deadline, regardless of its duration.
    item.state["now"] = NOW + timedelta(seconds=next_poll)
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 2


@pytest.mark.parametrize("change", ["rollback", "owner", "generation", "expired"])
@async_test
async def test_idle_attestation_invalidates_on_clock_or_ownership_change(idle_attestation, change):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.state["now"] = NOW + timedelta(seconds=3)
    if change == "rollback":
        item.state["now"] = NOW - timedelta(seconds=1)
    elif change == "owner":
        item.conn.lease_row = ("worker-a", 18, 3, NOW + timedelta(seconds=1),
                               NOW + timedelta(seconds=90))
    elif change == "generation":
        item.state["control"] = control(item.cfg, generation=4)
        item.conn.lease_row = ("worker-a", 18, 4, NOW + timedelta(seconds=1),
                               NOW + timedelta(seconds=90))
    else:
        item.conn.lease_row = ("worker-a", 17, 3, NOW,
                               NOW + timedelta(seconds=2))
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 2
    assert item.lifecycle


@async_test
async def test_idle_source_drift_rechecked_at_original_deadline_and_execution_boundary(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.state.update(now=NOW + timedelta(seconds=3), runtime="modified")
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 1
    # Financial authority never consumes the nonfinancial cadence record.
    with pytest.raises(NonRetryableCallbackRefused, match="current authority refused"):
        item.runtime._assert_cycle_authority(
            item.conn, context(item.cfg), operation_scope="EXECUTE")
    assert len(item.full) == 2
    item.state["now"] = NOW + timedelta(seconds=30)
    await item.runtime.control_wake(item.conn)
    assert len(item.full) == 3
    assert item.blocked
    assert item.runtime._idle_attestation is None


@async_test
async def test_pending_idle_proof_revocation_blocks_and_cancels(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    item.runtime._idle_attestation = None
    flight = item.flight_type({"status": "PASS"})
    flight.finished.clear()
    item.runtime._idle_authority_flight = (
        flight,
        item.runtime._idle_attestation_key(item.state["control"], context(item.cfg).permit),
        NOW)
    item.state.update(now=NOW + timedelta(seconds=3), revoked=True)
    await item.runtime.control_wake(item.conn)
    assert item.blocked and flight.cancelled.is_set()
    assert item.verdicts[-1]["verdict"] == "FAIL"
    assert len(item.full) == 1


@async_test
async def test_late_idle_proof_cannot_publish_a_new_pass(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    before = len(item.verdicts)
    item.runtime._idle_attestation = None
    flight = item.flight_type({"status": "PASS"})
    flight.elapsed_seconds = 31
    item.runtime._idle_authority_flight = (
        flight,
        item.runtime._idle_attestation_key(item.state["control"], context(item.cfg).permit),
        NOW)
    item.state["now"] = NOW + timedelta(seconds=31)
    retry_at = await item.runtime.control_wake(item.conn)
    assert retry_at > item.state["now"]
    assert flight.cancelled.is_set() and len(item.verdicts) == before
    assert item.runtime._idle_attestation is None


@async_test
async def test_idle_refusal_for_old_publication_is_discarded(idle_attestation):
    item = idle_attestation
    await item.runtime.control_wake(item.conn)
    before = len(item.verdicts)
    item.runtime._idle_attestation = None
    control_value = item.state["control"]
    flight = item.flight_type({
        "status": "REFUSED", "detail": "old source refused",
        "subject": {
            "generation": control_value.generation,
            "binding": control_value.binding.model_dump(mode="json"),
            "publication_version": 1,
            "publication_head": {"version": 1, "receipt_sha256": "r" * 64},
            "rollout_mode": "PINNED_1_00", "rollout_version": 1,
        },
    })
    item.runtime._idle_authority_flight = (
        flight,
        item.runtime._idle_attestation_key(control_value, context(item.cfg).permit),
        NOW)
    item.state.update(now=NOW + timedelta(seconds=3), publication=2)
    retry_at = await item.runtime.control_wake(item.conn)
    assert retry_at > item.state["now"]
    assert len(item.verdicts) == before and not item.blocked


@async_test
async def test_callback_reaps_idle_proof_before_admission(idle_attestation):
    item = idle_attestation
    flight = item.flight_type({"status": "PASS"})
    item.runtime._idle_authority_flight = (
        flight,
        item.runtime._idle_attestation_key(item.state["control"], context(item.cfg).permit),
        NOW)

    async def callback(_context):
        assert flight.cancelled.is_set()
        return "admitted"

    ctx = context(item.cfg)
    assert await item.runtime.service._invoke(
        callback, ctx, permit=ctx.permit, phase="PREPARE") == "admitted"
    assert item.runtime._idle_authority_flight is None


@pytest.mark.parametrize("path", ["immediate", "observed"])
@pytest.mark.parametrize("race", ["fail_write", "takeover"])
@async_test
async def test_idle_refusal_never_terminalizes_after_losing_original_fence(
        idle_attestation, monkeypatch, path, race):
    item = idle_attestation
    runtime, conn = item.runtime, item.conn
    permit = LeaderPermit(
        holder_id="worker-a", fence_token=17, control_generation=3,
        acquired_at=NOW, expires_at=NOW + timedelta(seconds=90))
    monkeypatch.setattr(store, "oldest_nonterminal_cycle", lambda _conn: None)
    monkeypatch.setattr(runtime, "notify", lambda *_args: pytest.fail(
        "stale authority refusal notified a terminal outcome"))
    if path == "immediate":
        monkeypatch.setattr(
            runtime, "_idle_certificate_identity",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                authority.AuthorityRefused("certificate revoked")))
    else:
        bound = item.state["control"].binding
        flight = item.flight_type({
            "status": "REFUSED", "detail": "signed proof refused",
            "subject": {
                "generation": 3, "binding": bound.model_dump(mode="json"),
                "publication_version": 1,
                "publication_head": {"version": 1, "receipt_sha256": "r" * 64},
                "rollout_mode": bound.rollout_mode,
                "rollout_version": bound.rollout_version,
                "certificate_sha256": CERTIFICATE,
            },
        })
        runtime._idle_authority_flight = (
            flight, runtime._idle_attestation_key(item.state["control"], permit),
            NOW)

    if race == "fail_write":
        monkeypatch.setattr(
            store, "record_authority_verdict",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                StaleLeaderRefused("takeover before FAIL")))
        monkeypatch.setattr(
            store, "engage_kill_if_leader",
            lambda *_args, **_kwargs: pytest.fail(
                "unpublished FAIL reached the kill latch"))
    else:
        def stale_latch(_conn, original, **_kwargs):
            assert original == permit
            raise StaleLeaderRefused("takeover between FAIL and latch")

        monkeypatch.setattr(store, "engage_kill_if_leader", stale_latch)
    result = await runtime.control_wake(conn)
    if race == "fail_write":
        assert result == runtime._idle_authority_retry_at
        assert not item.verdicts
    else:
        assert result is None
        assert [row["verdict"] for row in item.verdicts] == ["FAIL"]
    assert runtime._idle_attestation is None


@pytest.mark.parametrize("failure, expect_retry", [
    (automation_runtime.publication.NoPublishedVersion("publication absent"), True),
    (ValueError("unreviewed subject reader defect"), False),
])
@async_test
async def test_unavailable_idle_observation_subject_cannot_terminalize_without_fail(
        idle_attestation, monkeypatch, failure, expect_retry):
    item = idle_attestation
    runtime, conn = item.runtime, item.conn
    permit = LeaderPermit(
        holder_id="worker-a", fence_token=17, control_generation=3,
        acquired_at=NOW, expires_at=NOW + timedelta(seconds=90))
    bound = item.state["control"].binding
    flight = item.flight_type({
        "status": "REFUSED", "detail": "previous publication refused",
        "subject": {
            "generation": 3, "binding": bound.model_dump(mode="json"),
            "publication_version": 1,
            "publication_head": {"version": 1, "receipt_sha256": "r" * 64},
            "rollout_mode": bound.rollout_mode,
            "rollout_version": bound.rollout_version,
            "certificate_sha256": CERTIFICATE,
        },
    })
    runtime._idle_authority_flight = (
        flight, runtime._idle_attestation_key(item.state["control"], permit),
        NOW)
    monkeypatch.setattr(
        runtime, "_idle_publication_head",
        lambda _conn: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(
        automation_runtime.feed_inputs, "require_current",
        lambda _conn: pytest.fail("foreground replayed the publication proof"))
    monkeypatch.setattr(
        store, "engage_kill_if_leader",
        lambda *_args, **_kwargs: pytest.fail(
            "unavailable subject reached the kill latch"))
    monkeypatch.setattr(
        store, "transition_cycle",
        lambda *_args, **_kwargs: pytest.fail(
            "unavailable subject blocked a cycle"))
    if expect_retry:
        assert await runtime.control_wake(conn) == runtime._idle_authority_retry_at
    else:
        with pytest.raises(SoftwareDefect, match="subject observation failed"):
            await runtime.control_wake(conn)
    assert not item.verdicts


@pytest.mark.parametrize("fail_write", [False, True])
@async_test
async def test_idle_cycle_refusal_precedes_any_pass_and_requires_fenced_fail(
        idle_attestation, monkeypatch, fail_write):
    item = idle_attestation
    runtime, conn = item.runtime, item.conn

    def refuse_cycle(*_args, **_kwargs):
        assert item.verdicts == []
        raise NonRetryableCallbackRefused("cycle authority changed")

    monkeypatch.setattr(runtime, "_assert_cycle_authority", refuse_cycle)
    if fail_write:
        monkeypatch.setattr(
            store, "record_authority_verdict",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                StaleLeaderRefused("permit replaced before FAIL")))
        monkeypatch.setattr(
            store, "transition_cycle",
            lambda *_args, **_kwargs: pytest.fail(
                "cycle blocked without durable FAIL"))
    result = await runtime.control_wake(conn)
    if fail_write:
        assert result == runtime._idle_authority_retry_at
        assert item.verdicts == [] and item.blocked == []
    else:
        assert result is None
        assert [row["verdict"] for row in item.verdicts] == ["FAIL"]
        assert len(item.blocked) == 1


@pytest.mark.parametrize("change", ["publication", "revocation"])
@async_test
async def test_idle_refusal_rechecks_subject_inside_terminal_transaction(
        idle_attestation, monkeypatch, change):
    item = idle_attestation
    runtime, conn = item.runtime, item.conn
    permit = LeaderPermit(
        holder_id="worker-a", fence_token=17, control_generation=3,
        acquired_at=NOW, expires_at=NOW + timedelta(seconds=90))
    bound = item.state["control"].binding
    flight = item.flight_type({
        "status": "REFUSED", "detail": "old signed proof refused",
        "subject": {
            "generation": 3, "binding": bound.model_dump(mode="json"),
            "publication_version": 1,
            "publication_head": {"version": 1, "receipt_sha256": "r" * 64},
            "rollout_mode": bound.rollout_mode,
            "rollout_version": bound.rollout_version,
            "certificate_sha256": CERTIFICATE,
        },
    })
    runtime._idle_authority_flight = (
        flight, runtime._idle_attestation_key(item.state["control"], permit),
        NOW)
    monkeypatch.setattr(store, "oldest_nonterminal_cycle", lambda _conn: None)
    kills = []

    def kill(_conn, original, *, reason, actor, before_mutation):
        assert original == permit and actor == "sentinel-automation"
        if not kills:
            if change == "publication":
                item.state["publication"] = 2
            else:
                item.state["revoked"] = True
            with pytest.raises(StaleLeaderRefused):
                before_mutation(_conn)
            kills.append("stale")
            raise StaleLeaderRefused("subject changed before terminal write")
        before_mutation(_conn)
        kills.append(reason)
        item.state["control"] = item.state["control"].model_copy(update={
            "generation": 4, "kill_switch_engaged": True})
        return item.state["control"]

    monkeypatch.setattr(store, "engage_kill_if_leader", kill)
    assert await runtime.control_wake(conn) is None
    assert kills == ["stale"]
    assert [row["verdict"] for row in item.verdicts] == ["FAIL"]
    if change == "revocation":
        assert await runtime.control_wake(conn) is None
        assert len(kills) == 2
        assert "certificate revoked" in kills[1]
        assert [row["verdict"] for row in item.verdicts] == ["FAIL", "FAIL"]


@async_test
async def test_idle_proof_expiring_during_cycle_check_cannot_publish_pass(
        idle_attestation, monkeypatch):
    item = idle_attestation
    runtime, conn = item.runtime, item.conn
    original_start = runtime._start_idle_authority_observer
    flights = []

    def start(*args):
        flight = original_start(*args)
        flights.append(flight)
        return flight

    def slow_cycle(*_args, **_kwargs):
        flights[0].elapsed_seconds = 26
        return None

    monkeypatch.setattr(runtime, "_start_idle_authority_observer", start)
    monkeypatch.setattr(runtime, "_assert_cycle_authority", slow_cycle)
    assert await runtime.control_wake(conn) == runtime._idle_authority_retry_at
    assert len(flights) == 1
    assert item.verdicts == []
    assert runtime._idle_attestation is None


def test_cumulative_foreground_idle_budget_refuses_slow_mutable_reads(
        idle_attestation, monkeypatch):
    item = idle_attestation
    runtime = item.runtime
    control_value = item.state["control"]
    permit = LeaderPermit(
        holder_id="worker-a", fence_token=17, control_generation=3,
        acquired_at=NOW, expires_at=NOW + timedelta(seconds=90))
    original_leader = store.require_leader

    def slow_leader(conn, permit):
        time.sleep(.01)
        return original_leader(conn, permit)

    def slow_control(_conn):
        time.sleep(.01)
        return control_value

    def slow_certificate(_conn, **_kwargs):
        time.sleep(.01)
        return SimpleNamespace(certificate_sha256=CERTIFICATE)

    monkeypatch.setattr(store, "require_leader", slow_leader)
    monkeypatch.setattr(store, "load_control", slow_control)
    monkeypatch.setattr(runtime, "_idle_certificate_identity", slow_certificate)
    monkeypatch.setattr(
        automation_runtime, "load_rollout_state",
        lambda _conn: pytest.fail("expired cumulative budget read rollout"))
    runtime._idle_foreground_deadline = time.monotonic() + .025
    with pytest.raises(TransientInfrastructureFailure, match="foreground budget"):
        runtime._idle_current_facts(item.conn, permit)
    assert not item.verdicts


def test_idle_diagnostics_never_wait_for_child_shared_lock():
    class PoisonedLockProgress:
        def __getitem__(self, index):
            return (1942, 5)[index]

        def get_lock(self):
            pytest.fail("foreground diagnostic took a child-held lock")

    flight = object.__new__(automation_runtime.idle_authority.IdleAuthorityFlight)
    flight.progress = PoisonedLockProgress()
    assert flight.stage == "SIGNED_AUTHORITY_PUBLICATION"
    assert flight.backend_pid == 1942


@pytest.mark.parametrize("corruption", ["raw", "claims", "revoked", "key_revoked"])
def test_idle_mutable_certificate_check_refuses_tampering_without_file_reads(
        monkeypatch, corruption):
    cfg = config()
    runtime = production(cfg)
    claims = {
        "authorization_mode": "PAPER_OBSERVATION_ONLY",
        "certificate_id": "signed-1", "issuer_generation": 1,
        "supersedes_certificate_sha256": None,
        "not_before": "2026-08-01T00:00:00Z",
        "expires_at": "2026-08-12T00:00:00Z",
    }
    envelope = {"key_id": "trusted-key", "claims": claims}
    raw = json.dumps(envelope, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    row = [
        1, sha, raw, envelope, claims, "trusted-key", "signed-1", 1, None,
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 8, 12, tzinfo=UTC),
        "ACTIVE", False, False, NOW,
    ]
    if corruption == "raw":
        row[2] = raw + b" "
    elif corruption == "claims":
        row[4] = {**claims, "certificate_id": "different"}
    elif corruption == "revoked":
        row[12] = True
    else:
        row[13] = True

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, sql):
            assert "sentinel_execution_certificate_revocations" in sql

        def fetchone(self):
            return tuple(row)

    conn = SimpleNamespace(cursor=lambda: Cursor())
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail(
        "foreground idle poll read a trust-root file"))
    with pytest.raises(authority.AuthorityRefused):
        runtime._idle_certificate_identity(conn, expected_sha256=sha)


def test_idle_mutable_certificate_check_preserves_paper_expiry_exception(monkeypatch):
    cfg = config()
    runtime = production(cfg)
    claims = {
        "authorization_mode": "PAPER_OBSERVATION_ONLY",
        "certificate_id": "signed-1", "issuer_generation": 1,
        "supersedes_certificate_sha256": None,
        "not_before": "2026-08-01T00:00:00Z",
        "expires_at": "2026-08-12T00:00:00Z",
    }
    envelope = {"key_id": "trusted-key", "claims": claims}
    raw = json.dumps(envelope, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    row = [1, sha, raw, envelope, claims, "trusted-key", "signed-1", 1, None,
           datetime(2026, 8, 1, tzinfo=UTC),
           datetime(2026, 8, 12, tzinfo=UTC), "ACTIVE", False, False, NOW]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, _sql):
            pass

        def fetchone(self):
            return tuple(row)

    conn = SimpleNamespace(cursor=lambda: Cursor())
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail(
        "foreground idle poll read a trust-root file"))
    assert runtime._idle_certificate_identity(
        conn, expected_sha256=sha).certificate_sha256 == sha
    claims["authorization_mode"] = "EXECUTION"
    envelope["claims"] = claims
    raw = json.dumps(envelope, sort_keys=True).encode()
    row[1] = hashlib.sha256(raw).hexdigest()
    row[2] = raw
    with pytest.raises(authority.AuthorityRefused):
        runtime._idle_certificate_identity(
            conn, expected_sha256=row[1])


@pytest.mark.parametrize("boundary", ["control", "cycle"])
@async_test
async def test_idle_lease_loss_returns_to_scheduler_without_authority_or_broker(
        idle_attestation, monkeypatch, boundary):
    item = idle_attestation
    runtime, conn = item.runtime, item.conn
    calls = []

    def check_control(_c, _permit):
        calls.append("control")
        if boundary == "control":
            raise StaleLeaderRefused("lease expired before idle verification")
        return item.state["control"], SimpleNamespace(
            certificate_sha256=CERTIFICATE)

    def check_cycle(*_args, **_kwargs):
        calls.append("cycle")
        raise StaleLeaderRefused("new generation won before cycle verification")

    monkeypatch.setattr(runtime, "_idle_current_facts", check_control)
    monkeypatch.setattr(runtime, "_assert_cycle_authority", check_cycle)
    for name in ("transition_cycle", "adopt_cycle", "engage_kill_if_leader"):
        monkeypatch.setattr(store, name, lambda *_a, **_kw: pytest.fail("stale poll mutated authority"))
    monkeypatch.setattr(runtime, "_broker", lambda *_a, **_kw: pytest.fail("idle broker reached"))
    monkeypatch.setattr(runtime, "notify", lambda *_a, **_kw: pytest.fail("lease loss is not certificate failure"))
    assert await runtime.control_wake(conn) is None
    assert calls == (["control"] if boundary == "control"
                     else ["control", "control", "cycle"])
    assert conn.rollbacks >= 2
    assert item.verdicts == []


@async_test
async def test_idle_poll_does_not_swallow_unknown_defects(idle_attestation, monkeypatch):
    runtime, conn = idle_attestation.runtime, idle_attestation.conn
    def defect(*_a):
        raise ValueError("unexpected authority reader defect")
    monkeypatch.setattr(runtime, "_idle_current_facts", defect)
    with pytest.raises(ValueError, match="unexpected authority reader defect"):
        await runtime.control_wake(conn)


@async_test
async def test_idle_authority_failure_blocks_cycle_and_enqueues_alert(
        monkeypatch) -> None:
    cfg = config()
    current_control = control(cfg)
    waiting = cycle(cfg, state=CycleState.WAITING_OPEN)
    lease = (
        "worker-a", 17, 3, NOW, NOW + timedelta(seconds=30))
    conn = FakeConnection(lease_row=lease)
    runtime = production(cfg)
    latest = [waiting]
    verdicts = []
    alerts = []
    broker_builds = []
    kills = []
    monkeypatch.setattr(runtime, "_idle_pin_mutable_authority", lambda _conn: None)

    monkeypatch.setattr(store, "load_control", lambda _conn: current_control)
    monkeypatch.setattr(store, "load_cycle", lambda _conn, _id: latest[0])
    monkeypatch.setattr(
        store, "oldest_nonterminal_cycle", lambda _conn: (
            latest[0] if not latest[0].state.terminal else None))
    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)
    monkeypatch.setattr(
        store, "record_authority_verdict",
        lambda _conn, **kwargs: verdicts.append(kwargs))
    monkeypatch.setattr(
        automation_runtime, "load_rollout_state",
        lambda _conn: authority.RolloutState(
            authority.RolloutMode.PINNED_1_00, 1, None))
    monkeypatch.setattr(
        automation_runtime.feed_inputs, "require_current",
        lambda _conn: SimpleNamespace(version=1, evidence={}))
    monkeypatch.setattr(
        automation_runtime, "production_strategy", lambda: (object(), {}))
    monkeypatch.setattr(
        automation_runtime.system_identity, "rehearsal_identity", lambda: {})
    monkeypatch.setattr(
        automation_runtime, "require_current_authority",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            authority.AuthorityRefused("certificate expired")))
    monkeypatch.setattr(
        runtime, "_idle_certificate_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            authority.AuthorityRefused("certificate expired")))

    def block(_conn, **kwargs):
        blocked = latest[0].model_copy(update={
            "state": CycleState.BLOCKED,
            "failure_code": kwargs["failure_code"],
            "failure_detail": kwargs["failure_detail"]})
        latest[0] = blocked
        return blocked

    monkeypatch.setattr(store, "transition_cycle", block)
    monkeypatch.setattr(
        store, "engage_kill",
        lambda *_args, **kwargs: kills.append(kwargs))

    async def notify(_conn, result):
        alerts.append(result)

    monkeypatch.setattr(runtime, "notify", notify)
    monkeypatch.setattr(
        runtime, "_broker",
        lambda *_args: broker_builds.append(True))

    await runtime.control_wake(conn)

    assert latest[0].state is CycleState.BLOCKED
    assert verdicts[-1]["verdict"] == "FAIL"
    assert alerts[-1].action.value == "BLOCKED"
    assert broker_builds == []
    assert kills == []

    assert latest[0].state is CycleState.BLOCKED
    assert len(alerts) == 1


@pytest.mark.parametrize("terminal_cycle", [False, True])
@async_test
async def test_idle_no_live_cycle_authority_failure_engages_durable_kill(
        monkeypatch, terminal_cycle) -> None:
    cfg = config()
    current_control = [control(cfg)]
    stored_cycles = ([cycle(cfg, state=CycleState.SUCCEEDED)]
                     if terminal_cycle else [])
    conn = FakeConnection(lease_row=(
        "worker-a", 17, 3, NOW, NOW + timedelta(seconds=30)))
    runtime = production(cfg)
    verdicts = []
    alerts = []
    kills = []
    monkeypatch.setattr(runtime, "_idle_pin_mutable_authority", lambda _conn: None)

    monkeypatch.setattr(
        store, "load_control", lambda _conn: current_control[0])
    monkeypatch.setattr(
        store, "oldest_nonterminal_cycle",
        lambda _conn: next(
            (item for item in stored_cycles if not item.state.terminal), None))
    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)
    monkeypatch.setattr(
        store, "record_authority_verdict",
        lambda _conn, **kwargs: verdicts.append(kwargs))
    monkeypatch.setattr(
        automation_runtime, "load_rollout_state",
        lambda _conn: authority.RolloutState(
            authority.RolloutMode.PINNED_1_00, 1, None))
    monkeypatch.setattr(
        automation_runtime.feed_inputs, "require_current",
        lambda _conn: SimpleNamespace(version=1, evidence={}))
    monkeypatch.setattr(
        automation_runtime, "production_strategy", lambda: (object(), {}))
    monkeypatch.setattr(
        automation_runtime.system_identity, "rehearsal_identity", lambda: {})
    monkeypatch.setattr(
        automation_runtime, "require_current_authority",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            authority.AuthorityRefused("certificate revoked while idle")))
    monkeypatch.setattr(
        runtime, "_idle_certificate_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            authority.AuthorityRefused("certificate revoked while idle")))

    def engage_kill(_conn, permit, *, actor, reason, before_mutation):
        assert permit.control_generation == current_control[0].generation
        before_mutation(_conn)
        kills.append({"actor": actor, "reason": reason})
        current_control[0] = current_control[0].model_copy(update={
            "generation": current_control[0].generation + 1,
            "kill_switch_engaged": True,
            "authority_verdict": None,
            "authority_detail": None,
            "authority_checked_at": None,
        })
        return current_control[0]

    monkeypatch.setattr(store, "engage_kill_if_leader", engage_kill)

    async def notify(_conn, result):
        alerts.append(result)

    monkeypatch.setattr(runtime, "notify", notify)

    await runtime.control_wake(conn)

    assert verdicts[-1]["verdict"] == "FAIL"
    assert alerts[-1].cycle is None
    assert alerts[-1].permit.control_generation == 3
    assert "generation 3" in alerts[-1].reason
    assert current_control[0].kill_switch_engaged
    assert current_control[0].generation == 4
    assert len(kills) == 1
    assert kills[0]["actor"] == "sentinel-automation"
    assert "nonretryable authority failure" in kills[0]["reason"]
    assert "control generation 3" in kills[0]["reason"]

    # Repairing the external certificate cannot silently release the durable
    # latch. The killed control returns before another authority check or alert.
    monkeypatch.setattr(
        automation_runtime, "require_current_authority",
        lambda *_args, **_kwargs: SimpleNamespace(
            certificate_sha256=CERTIFICATE))
    await runtime.control_wake(conn)
    assert current_control[0].kill_switch_engaged
    assert len(verdicts) == 1
    assert len(alerts) == 1
    assert len(kills) == 1


@async_test
async def test_control_poll_preserves_adopted_old_recovery_obligation(
        idle_attestation, monkeypatch) -> None:
    item = idle_attestation
    cfg = item.cfg
    current_control = item.state["control"]
    old = cycle(
        cfg, generation=2, state=CycleState.RETRY_WAIT,
        last_fence_token=17).model_copy(update={
            "diagnostic": {"retry_phase": "RECOVER"}})
    conn, runtime = item.conn, item.runtime
    scopes = []

    monkeypatch.setattr(store, "load_control", lambda _conn: current_control)
    monkeypatch.setattr(store, "oldest_nonterminal_cycle", lambda _conn: old)
    def verify_cycle(_conn, _context, *, operation_scope, verified_control,
                     record_verdict):
        assert record_verdict is False
        scopes.append(operation_scope)
        return old, current_control

    monkeypatch.setattr(runtime, "_assert_cycle_authority", verify_cycle)
    monkeypatch.setattr(
        store, "transition_cycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("adopted recovery was spuriously blocked")))

    await runtime.control_wake(conn)

    assert scopes == ["RECOVER"]


def test_preparation_and_recovery_grants_cannot_mutate_simulator() -> None:
    cfg = config()
    ctx = context(cfg)
    for scope in ("PREPARE", "RECOVER"):
        inner = SimulatedBroker()
        grant = automation_runtime._grant(  # noqa: SLF001
            ctx, scope, binding=control(cfg).binding)
        broker = GuardedExecutionBroker(
            inner=inner, grant=grant, guard=permissive_guard())

        with pytest.raises(PreTransportAuthorityRefused, match="read-only"):
            import asyncio
            asyncio.run(broker.submit(
                client_key=f"must-not-{scope.lower()}", instrument=INSTRUMENT,
                side=Side.BUY, quantity=Decimal("1")))

        assert not any(call.startswith(("submit:", "cancel:"))
                       for call in inner.calls)


@async_test
async def test_after_close_clean_delta_is_superseded_not_late_submitted(
        monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="2")
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    install_durable_projection(monkeypatch, current_plan)

    async def clean(**kwargs):
        return reconciliation(await kwargs["broker"].observe())

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    monkeypatch.setattr(journal, "load_commands", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        automation_runtime, "_now_utc",
        lambda: ctx.cycle.execution_close_at + timedelta(seconds=1))

    result = await runtime.recover(ctx)

    assert result.disposition is ExecuteDisposition.SUPERSEDED
    assert result.failure_code == "EXECUTION_WINDOW_CLOSED"
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)


@async_test
async def test_terminal_rejection_supersedes_old_intent_without_revision_loop(monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="2")
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    install_durable_projection(monkeypatch, current_plan)
    rejected = command(current_plan.plan_id, state=CommandState.REJECTED)

    async def clean(**kwargs):
        return reconciliation(await kwargs["broker"].observe())

    monkeypatch.setattr(paper, "recover_automated_paper_cycle", clean)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    monkeypatch.setattr(
        journal, "load_commands",
        lambda *_args, **_kwargs: (rejected,))
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: NOW)

    result = await runtime.recover(ctx)

    assert result.disposition is ExecuteDisposition.SUPERSEDED
    assert result.failure_code == "TERMINAL_COMMAND_REFUSAL"
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)


@async_test
async def test_newly_rejected_submit_requires_read_only_recovery(monkeypatch) -> None:
    cfg = config()
    current_plan = plan(target="0")
    ctx = context(cfg, plan=current_plan)
    conn = FakeConnection()
    broker = SimulatedBroker()
    runtime = production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    rejected = command(current_plan.plan_id, state=CommandState.REJECTED)

    async def rejected_result(**kwargs):
        rec = reconciliation(await kwargs["broker"].observe())
        return paper.ExecutionResult(
            plan=current_plan, preflight=DictEvidence(),
            session=SessionResult(
                runtime_state=RuntimeState.RUNNING,
                reconciliation=rec, submitted=(rejected,),
                detail="broker rejected the command"))

    monkeypatch.setattr(
        paper, "execute_automated_paper_plan", rejected_result)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())

    result = await runtime.execute(ctx)

    assert result.disposition is ExecuteDisposition.RECONCILE
    assert result.failure_code == "TERMINAL_COMMAND_REFUSAL"


def test_blocked_unsettled_account_remains_readable_for_recovery() -> None:
    broker = SimulatedBroker(
        status="ACCOUNT_BLOCKED", trading_blocked=True,
        cash=Decimal("1000"), buying_power=Decimal("900"))
    bound = SimpleNamespace(
        broker="sim", broker_account_id="SIM-ACCOUNT",
        identity=SimpleNamespace(
            matches_account=lambda value: (
                value.broker == "sim" and value.account_id == "SIM-ACCOUNT")))
    snapshot = asyncio.run(broker.account_snapshot())

    paper_inspection._recovery_account_identity_or_refuse(  # noqa: SLF001
        snapshot, bound, "SIM-ACCOUNT")
    observation = asyncio.run(broker.observe())

    assert observation.is_complete
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)
    with pytest.raises(paper.PaperRetryableRefused, match="not ACTIVE"):
        paper_inspection._account_or_refuse(  # noqa: SLF001
            snapshot, bound, "SIM-ACCOUNT")


@async_test
async def test_service_reenters_executor_only_at_next_durable_boundary(
        monkeypatch) -> None:
    cfg = config()
    ctx = context(cfg, state=CycleState.RECONCILING, plan=plan())
    transitions = []

    async def recover(_context):
        return {
            "disposition": "READY_TO_EXECUTE",
            "last_clean_reconciliation_id": "clean-12",
            "failure_code": "READY_FOR_FRESH_EXECUTION",
        }

    service = AutomationService(
        config=cfg, holder_id="worker-a",
        refresh=lambda _context: {}, prepare=lambda _context: {},
        recover=recover, execute=lambda _context: {})
    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)

    def transition(_conn, **kwargs):
        transitions.append(kwargs)
        return ctx.cycle.model_copy(update={
            "state": CycleState(kwargs["to_state"]),
            "next_wake_at": kwargs.get("next_wake_at"),
            "diagnostic": kwargs.get("diagnostic", {}),
        })

    monkeypatch.setattr(store, "transition_cycle", transition)

    result = await service._run_recover(  # noqa: SLF001
        FakeConnection(), now=NOW, cycle=ctx.cycle, permit=ctx.permit)

    assert result.action is TickAction.RECOVERED
    assert result.cycle.state is CycleState.RETRY_WAIT
    assert result.cycle.next_wake_at == NOW
    assert result.cycle.diagnostic["retry_phase"] == "EXECUTE"
    assert len(transitions) == 1


@async_test
async def test_service_supersedes_adopted_old_generation_transport(
        monkeypatch) -> None:
    cfg = config()
    ctx = context(cfg, generation=2, state=CycleState.RECONCILING)
    adopted = []

    async def recover(_context):
        return {
            "disposition": "SUPERSEDED",
            "last_clean_reconciliation_id": "clean-old",
            "failure_code": "OLD_GENERATION_RECOVERED",
        }

    service = AutomationService(
        config=cfg, holder_id="worker-a",
        refresh=lambda _context: {}, prepare=lambda _context: {},
        recover=recover, execute=lambda _context: {})
    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)

    def adopt(_conn, **kwargs):
        adopted.append(kwargs)
        return ctx.cycle.model_copy(update={
            "state": CycleState(kwargs.get("to_state", ctx.cycle.state)),
            "last_fence_token": ctx.permit.fence_token,
        })

    monkeypatch.setattr(store, "adopt_cycle", adopt)

    result = await service._run_recover(  # noqa: SLF001
        FakeConnection(), now=NOW, cycle=ctx.cycle, permit=ctx.permit)

    assert result.action is TickAction.SUPERSEDED
    assert result.cycle.state is CycleState.SUPERSEDED
    assert all(call.get("to_state") is not CycleState.EXECUTING
               for call in adopted)


@async_test
async def test_service_supersedes_clean_old_generation_planless_preflight(
        monkeypatch) -> None:
    cfg = config()
    ctx = context(cfg, generation=2, state=CycleState.RETRY_WAIT)
    preflight = ctx.cycle.model_copy(update={
        "diagnostic": {"retry_phase": "PREFLIGHT_RECOVER"},
    })
    adopted = []

    async def recover(_context):
        return {
            "disposition": "SUPERSEDED",
            "last_clean_reconciliation_id": "clean-old-preflight",
            "failure_code": "OLD_GENERATION_RECOVERED",
        }

    service = AutomationService(
        config=cfg, holder_id="worker-a",
        refresh=lambda _context: {}, prepare=lambda _context: {},
        recover=recover, execute=lambda _context: {})
    monkeypatch.setattr(store, "require_leader", lambda _conn, value: value)

    def adopt(_conn, **kwargs):
        adopted.append(kwargs)
        return preflight.model_copy(update={
            "state": CycleState(kwargs.get("to_state", preflight.state)),
            "last_fence_token": ctx.permit.fence_token,
            "last_clean_reconciliation_id":
                kwargs.get("last_clean_reconciliation_id"),
            "failure_code": kwargs.get("failure_code"),
            "diagnostic": kwargs.get("diagnostic", preflight.diagnostic),
        })

    monkeypatch.setattr(store, "adopt_cycle", adopt)

    result = await service._run_preflight_recover(  # noqa: SLF001
        FakeConnection(), now=NOW, cycle=preflight, permit=ctx.permit,
        supersede_on_success=True)

    assert result.action is TickAction.SUPERSEDED
    assert result.cycle.state is CycleState.SUPERSEDED
    assert result.cycle.plan_id is None
    assert result.cycle.failure_code == "STALE_PREFLIGHT_RECOVERED"
    assert (result.cycle.last_clean_reconciliation_id
            == "clean-old-preflight")
    assert result.cycle.diagnostic["stale_preflight_superseded"] is True
    assert len(adopted) == 1
    assert adopted[0]["to_state"] is CycleState.SUPERSEDED


@async_test
async def test_reconciled_native_cash_supersedes_stale_plan_without_transport(monkeypatch):
    cfg = config()
    current_plan = plan(target='2')
    ctx = context(cfg, state=CycleState.RECONCILING, plan=current_plan)
    conn, broker, runtime = FakeConnection(), SimulatedBroker(), production(cfg)
    install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    install_durable_projection(monkeypatch, current_plan)
    async def clean(**kwargs):
        result = reconciliation(await kwargs['broker'].observe())
        result.cash_plan_superseded = True
        return result
    monkeypatch.setattr(paper, 'recover_automated_paper_cycle', clean)
    monkeypatch.setattr(journal, 'in_flight_commands', lambda *_args: ())
    monkeypatch.setattr(journal, 'latest_plan', lambda _conn: current_plan)
    monkeypatch.setattr(journal, 'load_commands', lambda *_args, **_kwargs: ())
    result = await runtime.recover(ctx)
    assert result.disposition is ExecuteDisposition.SUPERSEDED
    assert result.failure_code == 'POST_PLAN_CASH_ACTIVITY_RECONCILED'
    assert not any(call.startswith(('submit:', 'cancel:')) for call in broker.calls)


@pytest.mark.parametrize("carried", [None, "current", "foreign"])
def test_automation_grant_config_sha_matches_durable_control(monkeypatch, carried):
    cfg, conn = config(), FakeConnection()
    current, ctx = control(cfg), context(cfg)
    monkeypatch.setattr(store, "load_control", lambda _conn: current)
    monkeypatch.setattr(store, "require_leader", lambda _conn, permit: permit)
    monkeypatch.setattr(store, "load_cycle", lambda _conn, _cycle_id: ctx.cycle)
    grant = replace(automation_runtime._grant(ctx, "EXECUTE", binding=current.binding),
        config_sha256=(None if carried is None else cfg.fingerprint if carried == "current" else "f"*64))
    if carried == "foreign":
        with pytest.raises(paper.PaperActivationRefused, match="durable control authority"):
            paper_validation._validate_automation_grant(conn, grant)
    else:
        assert paper_validation._validate_automation_grant(conn, grant) == (current, ctx.cycle)


def test_removed_durable_grant_config_binding_is_detected(monkeypatch):
    import inspect
    source = inspect.getsource(paper_validation._validate_automation_grant)
    needle = "grant.config_sha256 is not None and grant.config_sha256 != bound.config_sha256"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "False", 1), "<removed-durable-config-binding>", "exec"),
         vars(paper_validation), namespace)
    monkeypatch.setattr(paper_validation, "_validate_automation_grant", namespace["_validate_automation_grant"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_automation_grant_config_sha_matches_durable_control(monkeypatch, "foreign")


def completed_predecessor_wait(cfg, *, generation=86, fence=118):
    """The exact normal post-activation result, with no execution permission."""
    prior=cycle(cfg,generation=82,state=CycleState.SUCCEEDED)
    permit=context(cfg).permit.model_copy(update={
        'control_generation':generation,'fence_token':fence})
    return TickResult(action=TickAction.WAITING,cycle=prior,permit=permit,
        reason=('this decision-session obligation was terminalized by a '
                'generation boundary; no replacement old plan is created'))


@async_test
async def test_completed_predecessor_wait_is_quiet_across_poll_fence_and_generation(monkeypatch):
    cfg=config();runtime=production(cfg);conn=FakeConnection()
    monkeypatch.setattr(automation_runtime.outbox,'enqueue',
        lambda *_a,**_kw:pytest.fail('normal completed-predecessor wait created an alert'))
    monkeypatch.setattr(automation_runtime.outbox,'enqueue_cycle_transition_alert',
        lambda *_a,**_kw:pytest.fail('completed history became a recovery incident'))
    for generation,fence in ((86,118),(86,118),(86,119),(87,120)):
        assert await runtime.notify(conn,completed_predecessor_wait(
            cfg,generation=generation,fence=fence)) is None
    assert conn.statements==[] and conn.commits==conn.rollbacks==0


@pytest.mark.parametrize('fault',[
    'blocked_state','missed_state','superseded_state','retry_state','executing_state',
    'blocked_action','executed_action','no_permit','same_generation','future_generation',
    'different_reason','no_cycle','exception',
])
@async_test
async def test_quiet_predecessor_guard_preserves_other_notifications(monkeypatch,fault):
    cfg=config();runtime=production(cfg);conn=FakeConnection()
    result=completed_predecessor_wait(cfg)
    alerts=[];events=[]
    monkeypatch.setattr(automation_runtime.outbox,'enqueue',
        lambda _conn,**kwargs:alerts.append(kwargs) or kwargs)
    monkeypatch.setattr(automation_runtime.outbox,'enqueue_cycle_transition_alert',
        lambda _conn,**kwargs:events.append(kwargs) or kwargs)
    if fault.endswith('_state'):
        state={'blocked_state':CycleState.BLOCKED,'missed_state':CycleState.MISSED_STATE_ONLY,
               'superseded_state':CycleState.SUPERSEDED,'retry_state':CycleState.RETRY_WAIT,
               'executing_state':CycleState.EXECUTING}[fault]
        result=result.model_copy(update={'cycle':result.cycle.model_copy(update={'state':state})})
    elif fault in {'blocked_action','executed_action'}:
        result=result.model_copy(update={'action':TickAction.BLOCKED
                                        if fault=='blocked_action' else TickAction.EXECUTED})
    elif fault=='no_permit':result=result.model_copy(update={'permit':None})
    elif fault=='same_generation':
        result=result.model_copy(update={'cycle':result.cycle.model_copy(update={'control_generation':86})})
    elif fault=='future_generation':
        result=result.model_copy(update={'cycle':result.cycle.model_copy(update={'control_generation':87})})
    elif fault=='different_reason':result=result.model_copy(update={'reason':'unexpected wait requires review'})
    elif fault=='no_cycle':result=result.model_copy(update={'cycle':None})
    else:result=RuntimeError('unexpected tick failure')
    await runtime.notify(conn,result)
    assert len(alerts)+len(events)==1
    if fault in {'blocked_state','missed_state','superseded_state','retry_state'}:
        assert len(events)==1
    else:
        assert len(alerts)==1
    if fault in {'blocked_action','exception'}:
        assert alerts[0]['severity']=='CRITICAL'


def _sample_warm_idle_observer(path, permit, progress):
    import os

    from sentinel.automation.idle_authority import set_progress
    from sentinel.economic_manifest import _syntax

    raw = Path(path).read_bytes()
    if raw == b'blocked':
        time.sleep(30)
    facts = _syntax('idle_observer_fixture', raw)
    set_progress(progress, stage=6, backend_pid=42)
    return {'pid': os.getpid(), 'fence': permit.fence_token,
            'names': sorted(facts[1]), 'syntax_hits': _syntax.cache_info().hits}


def test_warm_idle_observer_rechecks_current_bytes_and_permit_and_reaps_on_timeout(tmp_path):
    import sys

    from sentinel.automation.idle_authority import IdleAuthorityFlight, IdleAuthorityObserver

    if sys.platform != 'linux':
        pytest.skip('Linux supervisor process ownership')
    proof_input = tmp_path/'origin'
    proof_input.write_bytes(b'before = 1')
    permit = LeaderPermit(holder_id='worker-a', fence_token=17,
                          control_generation=3, acquired_at=NOW,
                          expires_at=NOW+timedelta(seconds=90))
    observer = IdleAuthorityObserver(_sample_warm_idle_observer, str(proof_input))

    def sample(token, timeout=10):
        flight = IdleAuthorityFlight(observer, permit.model_copy(update={'fence_token': token}),
                                     timeout_seconds=timeout)
        assert flight.finished.wait(timeout+2)
        return flight

    try:
        first = sample(17)
        assert first.error is None
        assert first.stage == 'COMPLETE'
        assert first.backend_pid == 42
        second = sample(18)
        assert second.error is None
        assert first.value['pid'] == second.value['pid']
        assert second.value['syntax_hits'] == first.value['syntax_hits']+1
        assert second.value['fence'] == 18

        proof_input.write_bytes(b'changed = 2')
        changed = sample(19)
        assert changed.error is None
        assert changed.value['pid'] == first.value['pid']
        assert changed.value['names'] == ['changed']

        proof_input.write_bytes(b'blocked')
        late = sample(19, timeout=.25)
        assert isinstance(late.error, TimeoutError)
        assert late.value is None and observer.process is None

        proof_input.write_bytes(b'recovered = 3')
        recovered = sample(20)
        assert recovered.error is None
        assert recovered.value['pid'] != first.value['pid']
        assert recovered.value['names'] == ['recovered']
    finally:
        assert observer.close()
