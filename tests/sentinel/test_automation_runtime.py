"""Adversarial composition tests for the broker-facing Stage 4 runtime.

The automation state machine has its own exhaustive transition tests.  These
tests target the narrower, more dangerous seam where a fenced cycle becomes a
signed paper grant, touches the canonical broker membrane, and is classified
back into durable orchestration outcomes.  Every broker is the deterministic
simulator; no network or real account is involved.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import (
    authority, automation_runtime, informational_paper_mirror, paper)
from sentinel.paper import (
    inspection as paper_inspection,
    validation as paper_validation,
)
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
    TickAction,
    TickResult,
    TransientInfrastructureFailure,
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

    def close(self) -> None:
        self.closed += 1

    def rollback(self) -> None:
        self.rollbacks += 1

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
        return None

    def fetchone(self):
        return self.conn.lease_row


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
        automation_runtime.feed_store, "ensure_schema", lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.schema, "ensure_schema", lambda _conn: None)


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
        automation_runtime.feed_store, "require_feed_schema",
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


@async_test
async def test_dual_prepare_bypasses_legacy_paper_catchup_lineage(
        monkeypatch) -> None:
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
        automation_runtime.feed_store, "require_feed_schema",
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
        return paper.PreparationResult(
            plan=current_plan, sessions_replayed=0, warmup_sessions=0,
            state_fingerprint="state", publication_version=1,
            frontier=DECISION.isoformat(), reconciliation=DictEvidence())

    monkeypatch.setattr(paper, "prepare_paper_plan", prepare_current)
    monkeypatch.setattr(
        runtime, "_require_dual_plan_shadow_match",
        lambda *_args, **_kwargs: {"status": "MATCHED"})

    result = await runtime.prepare(ctx)

    assert result.plan_id == current_plan.plan_id
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
        automation_runtime.publication, "require_current",
        lambda _conn: SimpleNamespace(version=7))
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
        lambda *_args, **_kwargs: pytest.fail(
            "dual raw convergence loaded strict target projection"))

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


@async_test
async def test_dual_run_refuses_before_broker_construction_when_shadow_differs(
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
        automation_runtime.feed_store, "require_feed_schema",
        lambda _conn: None)
    monkeypatch.setattr(
        automation_runtime.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: current_plan)
    broker_builds = []
    monkeypatch.setattr(
        runtime, "_broker",
        lambda *_args, **_kwargs: broker_builds.append(True))

    def mismatch(*_args, **_kwargs):
        raise NonRetryableCallbackRefused(
            "dual-run plan/shadow reconciliation refused")

    monkeypatch.setattr(runtime, "_require_dual_plan_shadow_match", mismatch)

    with pytest.raises(
            NonRetryableCallbackRefused, match="plan/shadow"):
        await runtime.execute(ctx)
    assert broker_builds == []


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
        automation_runtime.publication, "require_current",
        lambda _conn: SimpleNamespace(version=81))
    monkeypatch.setattr(automation_runtime, "load_controller", lambda: object())
    monkeypatch.setattr(
        automation_runtime, "runtime_strategy_identity",
        lambda _value: {"strategy": "sentinel-runtime-test"})
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
    assert verdicts[-1]["verdict"] == "PASS"


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
        automation_runtime.publication, "require_current",
        lambda _conn: SimpleNamespace(version=1))
    monkeypatch.setattr(
        automation_runtime, "load_controller", lambda: object())
    monkeypatch.setattr(
        automation_runtime, "runtime_strategy_identity", lambda _value: {})
    monkeypatch.setattr(
        automation_runtime.system_identity, "rehearsal_identity", lambda: {})
    monkeypatch.setattr(
        automation_runtime, "require_current_authority",
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

    # Restored certificate validity cannot silently resume the same generation.
    monkeypatch.setattr(
        automation_runtime, "require_current_authority",
        lambda *_args, **_kwargs: SimpleNamespace(
            certificate_sha256=CERTIFICATE))
    await runtime.control_wake(conn)
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
        automation_runtime.publication, "require_current",
        lambda _conn: SimpleNamespace(version=1))
    monkeypatch.setattr(automation_runtime, "load_controller", lambda: object())
    monkeypatch.setattr(
        automation_runtime, "runtime_strategy_identity", lambda _value: {})
    monkeypatch.setattr(
        automation_runtime.system_identity, "rehearsal_identity", lambda: {})
    monkeypatch.setattr(
        automation_runtime, "require_current_authority",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            authority.AuthorityRefused("certificate revoked while idle")))

    def engage_kill(_conn, *, actor, reason):
        kills.append({"actor": actor, "reason": reason})
        current_control[0] = current_control[0].model_copy(update={
            "generation": current_control[0].generation + 1,
            "kill_switch_engaged": True,
            "authority_verdict": None,
            "authority_detail": None,
            "authority_checked_at": None,
        })
        return current_control[0]

    monkeypatch.setattr(store, "engage_kill", engage_kill)

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
        monkeypatch) -> None:
    cfg = config()
    current_control = control(cfg)
    old = cycle(
        cfg, generation=2, state=CycleState.RETRY_WAIT,
        last_fence_token=17).model_copy(update={
            "diagnostic": {"retry_phase": "RECOVER"}})
    conn = FakeConnection(lease_row=(
        "worker-a", 17, 3, NOW, NOW + timedelta(seconds=30)))
    runtime = production(cfg)
    scopes = []

    monkeypatch.setattr(store, "load_control", lambda _conn: current_control)
    monkeypatch.setattr(store, "oldest_nonterminal_cycle", lambda _conn: old)
    monkeypatch.setattr(
        runtime, "_assert_control_authority",
        lambda _conn, _permit: (
            current_control,
            SimpleNamespace(certificate_sha256=CERTIFICATE)))
    monkeypatch.setattr(
        runtime, "_assert_cycle_authority",
        lambda _conn, _context, *, operation_scope, verified_control: (
            scopes.append(operation_scope) or (old, current_control)))
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
async def test_terminal_rejection_blocks_revision_loop(monkeypatch) -> None:
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

    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == "TERMINAL_COMMAND_REFUSAL"
    assert not any(call.startswith(("submit:", "cancel:"))
                   for call in broker.calls)


@async_test
async def test_newly_rejected_submit_is_immediately_blocked(monkeypatch) -> None:
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

    assert result.disposition is ExecuteDisposition.BLOCKED
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
