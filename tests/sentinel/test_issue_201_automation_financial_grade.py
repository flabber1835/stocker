from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import schema
from sentinel.automation import store
from sentinel.automation.model import (
    AutomationConfig,
    AutomationRefused,
    CallbackDeadlineExceeded,
    ControlBinding,
    CycleState,
    DataIntegrityFailure,
    HumanInterventionRequired,
    NonRetryableCallbackRefused,
    SoftwareDefect,
    SupervisorIntegrityFailure,
    StaleLeaderRefused,
    CancellationAuthority,
    TickAction,
)
from sentinel.automation.service import AutomationService
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


UTC = timezone.utc
# First instant used by the lifecycle tests is after the reviewed fixed 23:45
# America/New_York Sharadar publication boundary and before Thursday's open.
AFTER_WEDNESDAY_CLOSE = datetime(2026, 8, 13, 3, 46, tzinfo=UTC)
THURSDAY_BEFORE_EXECUTE = datetime(2026, 8, 13, 13, 30, 30, tzinfo=UTC)
THURSDAY_EXECUTE = datetime(2026, 8, 13, 13, 31, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def config(**changes) -> AutomationConfig:
    base = AutomationConfig(
        # Retained identity field; fixed 23:45 ET policy is authoritative.
        publication_delay_seconds=0,
        execution_delay_seconds=60,
        maximum_execution_lateness_seconds=60,
        lease_seconds=30,
        heartbeat_seconds=5,
        callback_deadline_seconds=30,
        maximum_clock_skew_seconds=5,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )
    return base.model_copy(update=changes)


@pytest.mark.parametrize(("failure", "category"), [
    (DataIntegrityFailure("bad evidence"), "DATA_INTEGRITY"),
    (HumanInterventionRequired("operator needed"),
     "HUMAN_INTERVENTION_REQUIRED"),
    (SoftwareDefect("broken invariant"), "SOFTWARE_DEFECT"),
    (CallbackDeadlineExceeded("hung callback"), "SOFTWARE_DEFECT"),
    (AttributeError("missing field"), "SOFTWARE_DEFECT"),
])
def test_failure_taxonomy_is_terminal_and_explicit(failure, category):
    service = service_for(config())
    terminal, diagnostic = service._failure_diagnostic(  # noqa: SLF001
        cycle=SimpleNamespace(diagnostic={}), phase="PREPARE", exc=failure,
        now=AFTER_WEDNESDAY_CLOSE)
    assert terminal
    assert diagnostic["callback_failure"] == category
    assert len(diagnostic["exception_fingerprint"]) == 64


def binding(cfg: AutomationConfig) -> ControlBinding:
    return ControlBinding(
        deployment_id="sentinel-a",
        broker="alpaca-paper",
        broker_account_id="paper-account-1",
        takeover_epoch=1,
        certificate_sha256="d" * 64,
        rollout_mode="PINNED_1_00",
        rollout_version=1,
        config_sha256=cfg.fingerprint,
    )


def enable(conn, cfg: AutomationConfig) -> None:
    expected = binding(cfg)
    store.activate(conn, binding=expected, actor="operator", reason="issue-201")
    store.release_kill(
        conn, expected_binding=expected, actor="operator", reason="issue-201")


def refresh_result(context):
    return {
        "already_published": False,
        "data_version": f"publication-{context.cycle.decision_session}",
        "publication_fingerprint": "p" * 64,
    }


def prepare_result(context):
    return {
        "plan_id": f"plan-{context.cycle.decision_session}",
        "data_version": f"publication-{context.cycle.decision_session}",
        "publication_fingerprint": "p" * 64,
        "state_fingerprint": "s" * 64,
        "plan_fingerprint": "f" * 64,
    }


def execution_success(context):
    return {
        "disposition": "SUCCEEDED",
        "last_clean_reconciliation_id":
            f"reconciliation-{context.cycle.effective_session}",
    }


def recovery_success(context):
    return execution_success(context)


def service_for(
        cfg: AutomationConfig, *, execute=execution_success,
        recover=recovery_success) -> AutomationService:
    return AutomationService(
        config=cfg,
        holder_id="worker-a",
        refresh=refresh_result,
        prepare=prepare_result,
        recover=recover,
        execute=execute,
    )


async def prepared_waiting(
        conn, cfg: AutomationConfig, *, execute=execution_success):
    enable(conn, cfg)
    service = service_for(cfg, execute=execute)
    assert (await service.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.RECOVERED
    assert (await service.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.REFRESHED
    assert (await service.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.PREPARED
    waiting = await service.tick(conn, now=THURSDAY_BEFORE_EXECUTE)
    assert waiting.action is TickAction.WAITING
    assert waiting.cycle is not None
    assert waiting.cycle.state is CycleState.WAITING_OPEN
    assert waiting.permit is not None
    return service, waiting


def test_safety_limits_are_independently_fingerprinted() -> None:
    base = config()
    assert base.model_copy(update={
        "maximum_execution_lateness_seconds": 61}).fingerprint != base.fingerprint
    assert base.model_copy(update={
        "callback_deadline_seconds": 31}).fingerprint != base.fingerprint
    assert base.model_copy(update={
        "maximum_clock_skew_seconds": 6}).fingerprint != base.fingerprint
    # Unrelated scheduling/retry fields remain distinct concepts.
    assert base.maximum_execution_lateness_seconds == 60
    assert base.execution_delay_seconds == 60
    assert base.callback_deadline_seconds == 30
    assert base.retry_max_seconds == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offset,expected_action,expected_execute_calls",
    [
        (0, TickAction.EXECUTED, 1),
        (30, TickAction.EXECUTED, 1),
        (61, TickAction.SUPERSEDED, 0),
    ],
)
async def test_new_transport_is_bounded_around_execute_at(
        conn, offset, expected_action, expected_execute_calls) -> None:
    calls = []
    cfg = config()

    def execute(context):
        calls.append(context.cycle.cycle_id)
        return execution_success(context)

    service, _ = await prepared_waiting(conn, cfg, execute=execute)
    result = await service.tick(
        conn, now=THURSDAY_EXECUTE + timedelta(seconds=offset))

    assert result.action is expected_action
    assert len(calls) == expected_execute_calls
    if offset > cfg.maximum_execution_lateness_seconds:
        assert result.cycle is not None
        assert result.cycle.state is CycleState.SUPERSEDED
        assert result.cycle.failure_code == "MAX_EXECUTION_LATENESS_EXCEEDED"


@pytest.mark.asyncio
async def test_execute_retry_cannot_bypass_immutable_execute_at(conn) -> None:
    calls = []
    cfg = config()

    def execute(context):
        calls.append(context.cycle.cycle_id)
        return execution_success(context)

    service, waiting = await prepared_waiting(conn, cfg, execute=execute)
    executing = store.transition_cycle(
        conn,
        permit=waiting.permit,
        cycle_id=waiting.cycle.cycle_id,
        to_state=CycleState.EXECUTING,
        increment_attempt=True,
        next_wake_at=None,
    )
    retry = store.transition_cycle(
        conn,
        permit=waiting.permit,
        cycle_id=executing.cycle_id,
        to_state=CycleState.RETRY_WAIT,
        next_wake_at=THURSDAY_BEFORE_EXECUTE,
        diagnostic={"retry_phase": "EXECUTE"},
    )

    result = await service.tick(conn, now=THURSDAY_BEFORE_EXECUTE)

    assert result.action is TickAction.WAITING
    assert result.cycle is not None
    assert result.cycle.cycle_id == retry.cycle_id
    assert calls == []


@pytest.mark.asyncio
async def test_sql_promoted_executing_row_is_refused_before_callback(conn) -> None:
    calls = []
    cfg = config()

    def execute(context):
        calls.append(context.cycle.cycle_id)
        return execution_success(context)

    service, waiting = await prepared_waiting(conn, cfg, execute=execute)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_automation_cycles SET state='EXECUTING' "
            "WHERE cycle_id=%s",
            (waiting.cycle.cycle_id,),
        )
    conn.commit()

    with pytest.raises(AutomationRefused, match="event"):
        await service.tick(conn, now=THURSDAY_BEFORE_EXECUTE)
    assert calls == []


@pytest.mark.asyncio
async def test_late_recovery_can_reconcile_but_cannot_reopen_transport(conn) -> None:
    cfg = config()
    service, waiting = await prepared_waiting(conn, cfg)
    executing = store.transition_cycle(
        conn,
        permit=waiting.permit,
        cycle_id=waiting.cycle.cycle_id,
        to_state=CycleState.EXECUTING,
        increment_attempt=True,
        next_wake_at=None,
    )
    store.transition_cycle(
        conn,
        permit=waiting.permit,
        cycle_id=executing.cycle_id,
        to_state=CycleState.RETRY_WAIT,
        next_wake_at=THURSDAY_EXECUTE + timedelta(seconds=61),
        diagnostic={"retry_phase": "EXECUTE"},
    )

    recovery_calls = []

    def ready(context):
        recovery_calls.append(context.cycle.cycle_id)
        return {
            "disposition": "READY_TO_EXECUTE",
            "last_clean_reconciliation_id": "clean-after-outage",
        }

    replacement = service_for(cfg, recover=ready)
    result = await replacement.tick(
        conn, now=THURSDAY_EXECUTE + timedelta(seconds=61))

    assert recovery_calls
    assert result.action is TickAction.SUPERSEDED
    assert result.cycle is not None
    assert result.cycle.failure_code == "MAX_EXECUTION_LATENESS_EXCEEDED"


@pytest.mark.asyncio
async def test_production_tick_refuses_material_host_database_clock_skew(
        conn, pg) -> None:
    cfg = config()
    enable(conn, cfg)
    with conn.cursor() as cur:
        cur.execute("SELECT clock_timestamp()")
        database_now = cur.fetchone()[0]
    conn.rollback()
    service = service_for(cfg)

    with pytest.raises(AutomationRefused, match="clock skew"):
        await service.tick(
            conn,
            now=database_now + timedelta(minutes=5),
            heartbeat_conn_factory=lambda: feed_store.connect(pg.sync_dsn),
        )


@pytest.mark.asyncio
async def test_callback_result_is_refused_after_bounded_runtime() -> None:
    cfg = config(
        heartbeat_seconds=1,
        callback_deadline_seconds=1,
        retry_base_seconds=1,
        retry_max_seconds=30,
    )
    service = service_for(cfg)

    async def slow(_context):
        await asyncio.sleep(1.05)
        return "late"

    class Context:
        def __init__(self):
            self.cancellation = CancellationAuthority()

        def require_active(self):
            self.cancellation.require_active()

    with pytest.raises(CallbackDeadlineExceeded, match="bounded runtime"):
        await service._invoke(  # noqa: SLF001 - explicit watchdog contract test
            slow,
            Context(),
            permit=object(),
            phase="PREPARE",
            heartbeat_conn_factory=None,
        )


@pytest.mark.asyncio
async def test_crash_signal_is_delivered_on_the_service_caller_task() -> None:
    service = service_for(config())

    class Context:
        def __init__(self):
            self.cancellation = CancellationAuthority()

        def require_active(self):
            self.cancellation.require_active()

    def crash(_context):
        raise SystemExit("injected process death")

    with pytest.raises(SystemExit, match="injected process death"):
        await service._invoke(  # noqa: SLF001 - crash-boundary contract test
            crash, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=None)


@pytest.mark.asyncio
async def test_production_boundary_rejects_in_process_sync_callback() -> None:
    service = service_for(config())

    class Context:
        def __init__(self):
            self.cancellation = CancellationAuthority()

        def require_active(self):
            self.cancellation.require_active()

    with pytest.raises(NonRetryableCallbackRefused, match="killable process"):
        await service._invoke(  # noqa: SLF001 - process-isolation contract test
            lambda _context: {}, Context(), permit=object(), phase="PREPARE",
            heartbeat_conn_factory=lambda: pytest.fail("must not heartbeat"))


@pytest.mark.asyncio
async def test_never_returning_callback_durably_blocks_cycle(conn) -> None:
    cfg = config(
        heartbeat_seconds=1,
        callback_deadline_seconds=1,
        retry_base_seconds=1,
    )
    enable(conn, cfg)

    async def never_returns(_context):
        await asyncio.Event().wait()

    service = AutomationService(
        config=cfg, holder_id="worker-a", refresh=refresh_result,
        prepare=never_returns, recover=recovery_success,
        execute=execution_success)
    assert (await service.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.RECOVERED
    assert (await service.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.REFRESHED

    blocked = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert blocked.action is TickAction.BLOCKED
    assert blocked.cycle.state is CycleState.BLOCKED
    assert blocked.cycle.failure_code == "CallbackDeadlineExceeded"
    assert blocked.cycle.diagnostic["callback_failure"] == "SOFTWARE_DEFECT"
    assert blocked.cycle.diagnostic["terminal_reason"] == "SOFTWARE_DEFECT"


@pytest.mark.asyncio
async def test_supervisor_integrity_failure_exits_run_and_records_failed(
        conn, pg, monkeypatch) -> None:
    cfg = config(heartbeat_seconds=1, callback_deadline_seconds=5)
    enable(conn, cfg)
    runtime = service_for(cfg)
    monkeypatch.setattr(runtime, "_assert_clock_skew", lambda **_kwargs: None)
    assert (await runtime.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.RECOVERED
    assert (await runtime.tick(
        conn, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.REFRESHED

    async def fail_supervisor_integrity(*_args, **_kwargs):
        raise SupervisorIntegrityFailure(
            "PREPARE heartbeat supervisor did not stop within the certified "
            "boundary")

    monkeypatch.setattr(runtime, "_invoke", fail_supervisor_integrity)
    with pytest.raises(
            SupervisorIntegrityFailure, match="did not stop"):
        await runtime.run(
            lambda: feed_store.connect(pg.sync_dsn),
            stop=asyncio.Event(), clock=lambda: AFTER_WEDNESDAY_CLOSE,
            max_ticks=1)

    verify = feed_store.connect(pg.sync_dsn)
    try:
        with verify.cursor() as cur:
            cur.execute(
                "SELECT state,last_error FROM "
                "sentinel_automation_service_instances WHERE instance_id=%s",
                (runtime.holder_id,))
            state, last_error = cur.fetchone()
        assert state == "FAILED"
        assert "SupervisorIntegrityFailure" in last_error
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_that_suppresses_cancellation_cannot_hold_tick_open():
    cfg = config(
        heartbeat_seconds=1,
        callback_deadline_seconds=1,
        retry_base_seconds=1,
        retry_max_seconds=30,
    )
    service = service_for(cfg)
    release = asyncio.Event()
    cancellation_seen = asyncio.Event()

    class Context:
        def __init__(self):
            self.cancellation = CancellationAuthority()

        def require_active(self):
            self.cancellation.require_active()

    context = Context()

    async def stubborn(_context):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()
        return "late"

    with pytest.raises(CallbackDeadlineExceeded, match="bounded runtime"):
        await asyncio.wait_for(
            service._invoke(  # noqa: SLF001 - watchdog fault injection
                stubborn, context, permit=object(), phase="EXECUTE",
                heartbeat_conn_factory=None),
            timeout=1.5)
    assert context.cancellation.cancelled
    await asyncio.wait_for(cancellation_seen.wait(), timeout=0.5)
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_late_database_boundary_rejects_cancelled_authority():
    cfg = config(heartbeat_seconds=1, callback_deadline_seconds=1)
    service = service_for(cfg)
    release = asyncio.Event()
    rejected = asyncio.Event()
    mutations = []

    class Context:
        def __init__(self):
            self.cancellation = CancellationAuthority()

        def require_active(self):
            self.cancellation.require_active()

    context = Context()

    async def late_writer(actual):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        try:
            actual.require_active()
        except StaleLeaderRefused:
            rejected.set()
            raise
        mutations.append("committed")

    with pytest.raises(CallbackDeadlineExceeded, match="bounded runtime"):
        await service._invoke(  # noqa: SLF001 - durable boundary injection
            late_writer, context, permit=object(), phase="PREPARE",
            heartbeat_conn_factory=None)
    release.set()
    await asyncio.wait_for(rejected.wait(), timeout=0.5)
    assert mutations == []
