from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinel import schema
from sentinel.automation import schedule, store
from sentinel.automation.model import (
    AutomationConfig,
    ControlBinding,
    CycleState,
    MissingAutomationState,
    NonRetryableCallbackRefused,
    StaleLeaderRefused,
    TickAction,
)
from sentinel.automation.service import AutomationService
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


UTC = timezone.utc
AFTER_WEDNESDAY_CLOSE = datetime(2026, 8, 12, 20, 1, tzinfo=UTC)
THURSDAY_BEFORE_OPEN = datetime(2026, 8, 13, 13, 29, tzinfo=UTC)
THURSDAY_AFTER_OPEN = datetime(2026, 8, 13, 13, 31, tzinfo=UTC)
THURSDAY_AFTER_CLOSE = datetime(2026, 8, 13, 20, 1, tzinfo=UTC)
FRIDAY_AFTER_OPEN = datetime(2026, 8, 14, 13, 31, tzinfo=UTC)


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


def config() -> AutomationConfig:
    # This module drives deterministic 2026 historical clocks through run().
    # Clock-skew enforcement itself is covered separately by the #201 tests.
    return AutomationConfig(
        publication_delay_seconds=0,
        execution_delay_seconds=60,
        maximum_clock_skew_seconds=1_000_000,
        lease_seconds=30,
        heartbeat_seconds=5,
        retry_base_seconds=5,
        retry_max_seconds=30,
    )


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
    store.activate(
        conn, binding=expected, actor="operator", reason="test activation")
    store.release_kill(
        conn, expected_binding=expected, actor="operator",
        reason="test unattended authority")


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


def refresh_result(context):
    return {
        "already_published": False,
        "data_version": f"publication-{context.cycle.decision_session}",
        "publication_fingerprint": "p" * 64,
    }


def recovery_success(context):
    return execution_success(context)


def service_for(cfg, *, holder="worker-a", refresh=refresh_result,
                prepare=prepare_result, recover=recovery_success,
                execute=execution_success):
    return AutomationService(
        config=cfg, holder_id=holder, refresh=refresh, prepare=prepare,
        recover=recover, execute=execute)


@pytest.mark.asyncio
async def test_disabled_and_killed_ticks_make_zero_callback_calls(conn) -> None:
    calls = []
    cfg = config()
    service = AutomationService(
        config=cfg, holder_id="worker-a", refresh=lambda context: calls.append("refresh"),
        prepare=lambda context: calls.append("prepare"),
        recover=lambda context: calls.append("recover"),
        execute=lambda context: calls.append("execute"))

    disabled = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert disabled.action is TickAction.INERT

    store.activate(
        conn, binding=binding(cfg), actor="operator", reason="remain killed")
    killed = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert killed.action is TickAction.INERT
    assert calls == []
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_automation_cycles")
        assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_changed_runtime_config_durably_kills_and_cannot_silently_resume(
        conn) -> None:
    activated = config()
    enable(conn, activated)
    first = store.acquire_lease(
        conn, holder_id="original-worker", lease_seconds=30)
    store.record_authority_verdict(
        conn, verdict="PASS", detail="current certificate verified",
        holder_id=first.holder_id, fence_token=first.fence_token,
        control_generation=first.control_generation)
    changed = activated.model_copy(update={"retry_base_seconds": 6})
    calls = []
    mismatched = AutomationService(
        config=changed, holder_id="replacement-worker",
        refresh=lambda context: calls.append("refresh"),
        prepare=lambda context: calls.append("prepare"),
        recover=lambda context: calls.append("recover"),
        execute=lambda context: calls.append("execute"))

    result = await mismatched.tick(conn, now=AFTER_WEDNESDAY_CLOSE)

    assert result.action is TickAction.BLOCKED
    control = store.load_control(conn)
    assert control.generation == first.control_generation + 1
    assert control.enabled and control.kill_switch_engaged
    assert control.authority_verdict is None
    assert calls == []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT holder_id,expires_at FROM sentinel_automation_lease"
            " WHERE id=1")
        assert cur.fetchone() == (None, None)

    restored = service_for(activated, holder="restored-worker")
    still_killed = await restored.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert still_killed.action is TickAction.INERT
    assert "kill" in still_killed.reason


@pytest.mark.asyncio
async def test_prepare_restart_and_execution_use_durable_boundaries(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    prepared_calls = []
    executed_calls = []

    def prepare(context):
        prepared_calls.append(context.cycle.cycle_id)
        return prepare_result(context)

    def execute(context):
        executed_calls.append(context.cycle.plan_id)
        return execution_success(context)

    first_process = service_for(cfg, prepare=prepare, execute=execute)
    recovered = await first_process.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert recovered.action is TickAction.RECOVERED
    refreshed = await first_process.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert refreshed.action is TickAction.REFRESHED
    prepared = await first_process.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert prepared.action is TickAction.PREPARED
    assert prepared.cycle.state is CycleState.PLAN_READY

    restarted = service_for(cfg, prepare=prepare, execute=execute)
    waiting = await restarted.tick(conn, now=THURSDAY_BEFORE_OPEN)
    assert waiting.action is TickAction.WAITING
    assert waiting.cycle.state is CycleState.WAITING_OPEN
    assert prepared_calls == [prepared.cycle.cycle_id]
    assert executed_calls == []

    completed = await restarted.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert completed.action is TickAction.EXECUTED
    assert completed.cycle.state is CycleState.SUCCEEDED
    assert executed_calls == [prepared.cycle.plan_id]

    second_restart = await restarted.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert second_restart.cycle.state is CycleState.SUCCEEDED
    assert executed_calls == [prepared.cycle.plan_id]


@pytest.mark.asyncio
async def test_crash_after_preparing_commit_replays_canonical_prepare(conn) -> None:
    cfg = config()
    enable(conn, cfg)

    def crash_after_entry(context):
        assert context.cycle.state is CycleState.PREPARING
        raise SystemExit("simulated process death")

    crashing = service_for(cfg, prepare=crash_after_entry)
    recovered = await crashing.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert recovered.action is TickAction.RECOVERED
    refreshed = await crashing.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert refreshed.action is TickAction.REFRESHED
    with pytest.raises(SystemExit, match="simulated process death"):
        await crashing.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    durable = store.latest_cycle(conn)
    assert durable is not None
    assert durable.state is CycleState.PREPARING

    calls = []

    def recover(context):
        calls.append(context.cycle.cycle_id)
        return prepare_result(context)

    restarted = service_for(cfg, prepare=recover)
    result = await restarted.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert result.cycle.state is CycleState.PLAN_READY
    assert calls == [durable.cycle_id]


@pytest.mark.asyncio
async def test_refresh_crash_restart_recognizes_existing_publication(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    calls = []

    def die_after_publication(context):
        calls.append("published")
        raise SystemExit("crash after atomic publication")

    crashing = service_for(cfg, refresh=die_after_publication)
    recovered = await crashing.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert recovered.action is TickAction.RECOVERED
    with pytest.raises(SystemExit):
        await crashing.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    durable = store.latest_cycle(conn)
    assert durable is not None
    assert durable.state is CycleState.REFRESHING_DATA

    def recognize(context):
        calls.append("recognized")
        return {
            "already_published": True,
            "data_version": "publication-2026-08-12",
            "publication_fingerprint": "p" * 64,
        }

    restarted = service_for(cfg, refresh=recognize)
    refreshed = await restarted.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert refreshed.action is TickAction.REFRESHED
    assert refreshed.cycle.state is CycleState.PREPARING
    assert refreshed.cycle.diagnostic["already_published"] is True
    assert calls == ["published", "recognized"]


@pytest.mark.asyncio
async def test_old_unresolved_execution_recovers_before_new_refresh(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    order = []

    base = service_for(
        cfg,
        refresh=lambda context: (
            order.append("old-refresh") or refresh_result(context)),
        prepare=lambda context: (
            order.append("old-prepare") or prepare_result(context)),
        execute=lambda context: {
            "disposition": "RECONCILE",
            "failure_code": "UNKNOWN_SUBMIT",
            "failure_detail": "submit outcome unknown",
        })
    await base.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await base.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await base.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await base.tick(conn, now=THURSDAY_BEFORE_OPEN)
    executing = await base.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert executing.cycle.state is CycleState.RECONCILING

    def recover(context):
        order.append("recover")
        return {
            "disposition": "SUCCEEDED",
            "last_clean_reconciliation_id": "clean-old-cycle",
        }

    def newest_refresh(context):
        order.append("new-refresh")
        return refresh_result(context)

    replacement = service_for(
        cfg, recover=recover, refresh=newest_refresh)
    recovered = await replacement.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert recovered.cycle.state is CycleState.SUCCEEDED
    assert order[-1] == "recover"

    preflight = await replacement.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert preflight.action is TickAction.RECOVERED
    refreshed = await replacement.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert refreshed.action is TickAction.REFRESHED
    assert order[-1] == "new-refresh"


@pytest.mark.asyncio
async def test_unresolved_journal_preflight_blocks_publication(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    calls = []

    def incomplete(context):
        calls.append("recover")
        return {
            "disposition": "RECONCILE",
            "failure_code": "OPEN_COMMANDS",
            "failure_detail": "one command remains in flight",
        }

    service = service_for(
        cfg, recover=incomplete,
        refresh=lambda context: calls.append("refresh") or refresh_result(context))
    result = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)

    assert result.action is TickAction.RETRY_SCHEDULED
    assert result.cycle.state is CycleState.RETRY_WAIT
    assert result.cycle.diagnostic["retry_phase"] == "PREFLIGHT_RECOVER"
    assert calls == ["recover"]


@pytest.mark.asyncio
async def test_blocked_cycle_latches_across_later_sessions(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    calls = []

    def blocked(context):
        calls.append("recover")
        return {
            "disposition": "BLOCKED",
            "failure_code": "FOREIGN_ACTIVITY",
            "failure_detail": "operator acknowledgement required",
        }

    service = service_for(
        cfg, recover=blocked,
        refresh=lambda context: calls.append("refresh") or refresh_result(context))
    first = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert first.cycle.state is CycleState.BLOCKED

    later = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert later.action is TickAction.BLOCKED
    assert later.cycle.cycle_id == first.cycle.cycle_id
    assert calls == ["recover"]


@pytest.mark.asyncio
async def test_newest_cycle_supersedes_an_unexecuted_older_plan(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    prepared = []
    executed = []

    def prepare(context):
        prepared.append(context.cycle.decision_session.isoformat())
        return prepare_result(context)

    def execute(context):
        executed.append(context.cycle.plan_id)
        return execution_success(context)

    service = service_for(cfg, prepare=prepare, execute=execute)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    old = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert old.cycle.state is CycleState.PLAN_READY

    superseded = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert superseded.action is TickAction.SUPERSEDED
    preflight = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert preflight.action is TickAction.RECOVERED
    refreshed = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert refreshed.action is TickAction.REFRESHED
    newest = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert newest.action is TickAction.PREPARED
    old_reloaded = store.load_cycle(conn, old.cycle.cycle_id)
    assert old_reloaded.state is CycleState.SUPERSEDED
    assert prepared == ["2026-08-12", "2026-08-13"]
    assert executed == []

    completed = await service.tick(conn, now=FRIDAY_AFTER_OPEN)
    assert completed.cycle.state is CycleState.SUCCEEDED
    assert executed == ["plan-2026-08-13"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_automation_cycles"
            " WHERE state NOT IN ('SUPERSEDED','SUCCEEDED')")
        assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_canonical_catchup_reports_historical_state_only_cycles(conn) -> None:
    cfg = config()
    enable(conn, cfg)

    def catchup(context):
        value = prepare_result(context)
        value["missed_sessions"] = ["2026-08-10", "2026-08-11"]
        return value

    service = service_for(cfg, prepare=catchup)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    current = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert current.cycle.state is CycleState.PLAN_READY
    with conn.cursor() as cur:
        cur.execute(
            "SELECT decision_session,state,historical_state_only,plan_id"
            " FROM sentinel_automation_cycles ORDER BY decision_session")
        rows = cur.fetchall()
    assert [(str(row[0]), row[1], row[2]) for row in rows] == [
        ("2026-08-10", "MISSED_STATE_ONLY", True),
        ("2026-08-11", "MISSED_STATE_ONLY", True),
        ("2026-08-12", "PLAN_READY", False),
    ]
    assert rows[0][3] is None and rows[1][3] is None


@pytest.mark.asyncio
async def test_authority_loss_inside_callback_rejects_stale_worker(
        conn, pg) -> None:
    cfg = config()
    enable(conn, cfg)
    operator = feed_store.connect(pg.sync_dsn)

    def revoke_during_prepare(context):
        store.engage_kill(
            operator, actor="operator", reason="certificate revoked")
        return prepare_result(context)

    service = service_for(cfg, prepare=revoke_during_prepare)
    try:
        await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
        await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
        with pytest.raises(StaleLeaderRefused):
            await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
        cycle = store.latest_cycle(conn)
        assert cycle is not None
        assert cycle.state is CycleState.PREPARING
    finally:
        operator.close()


@pytest.mark.asyncio
async def test_missing_control_singleton_refuses_instead_of_reseeding(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_automation_control WHERE id=1")
    conn.commit()
    schema.ensure_schema(conn)
    service = service_for(config())

    with pytest.raises(MissingAutomationState):
        await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)


@pytest.mark.asyncio
async def test_persistent_run_recomputes_boundaries_across_connections(
        conn, pg) -> None:
    cfg = config()
    enable(conn, cfg)
    calls = []

    class NeverStop:
        def is_set(self):
            return False

    async def no_wait(seconds):
        assert seconds >= 0

    service = service_for(
        cfg,
        recover=lambda context: (
            calls.append("recover") or recovery_success(context)),
        refresh=lambda context: (
            calls.append("refresh") or refresh_result(context)),
        prepare=lambda context: (
            calls.append("prepare") or prepare_result(context)))
    ticks = await service.run(
        lambda: feed_store.connect(pg.sync_dsn), stop=NeverStop(),
        clock=lambda: AFTER_WEDNESDAY_CLOSE, sleep=no_wait, max_ticks=3)

    assert ticks == 3
    assert calls == ["recover", "refresh", "prepare"]


@pytest.mark.asyncio
async def test_generation_change_supersedes_pretransport_cycle_without_execute(
        conn) -> None:
    cfg = config()
    enable(conn, cfg)
    executed = []
    service = service_for(
        cfg, execute=lambda context: executed.append(context) or
        execution_success(context))
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert ready.cycle.state is CycleState.PLAN_READY
    origin_generation = ready.cycle.control_generation

    store.engage_kill(conn, actor="operator", reason="test generation fence")
    current_binding = store.load_control(conn).binding
    assert current_binding is not None
    control = store.release_kill(
        conn, expected_binding=current_binding, actor="operator",
        reason="test generation recovery")

    adopted = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert adopted.action is TickAction.SUPERSEDED
    assert adopted.cycle.state is CycleState.SUPERSEDED
    assert adopted.cycle.control_generation == origin_generation
    assert adopted.permit.control_generation == control.generation
    assert executed == []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT control_generation,fence_token,detail"
            " FROM sentinel_automation_cycle_events WHERE cycle_id=%s"
            " ORDER BY seq DESC LIMIT 1", (ready.cycle.cycle_id,))
        event_generation, event_fence, detail = cur.fetchone()
    assert event_generation == control.generation
    assert event_fence == adopted.permit.fence_token
    assert detail["adoption"] is True

    same_session = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert same_session.action is TickAction.WAITING
    assert same_session.cycle.cycle_id == ready.cycle.cycle_id
    assert executed == []


@pytest.mark.asyncio
async def test_generation_change_recovers_transport_read_only_under_current_fence(
        conn) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    old_permit = ready.permit
    waiting = store.transition_cycle(
        conn, permit=old_permit, cycle_id=ready.cycle.cycle_id,
        to_state=CycleState.WAITING_OPEN)
    executing = store.transition_cycle(
        conn, permit=old_permit, cycle_id=waiting.cycle_id,
        to_state=CycleState.EXECUTING, increment_attempt=True)

    store.engage_kill(conn, actor="operator", reason="fence old sender")
    current_binding = store.load_control(conn).binding
    assert current_binding is not None
    control = store.release_kill(
        conn, expected_binding=current_binding, actor="operator",
        reason="recover old sender")
    recovered_contexts = []
    executed_contexts = []

    def recover(context):
        recovered_contexts.append(context)
        return recovery_success(context)

    replacement = service_for(
        cfg, holder="worker-b", recover=recover,
        execute=lambda context: executed_contexts.append(context) or
        execution_success(context))
    result = await replacement.tick(conn, now=THURSDAY_AFTER_OPEN)

    assert result.action is TickAction.RECOVERED
    assert result.cycle.state is CycleState.SUCCEEDED
    assert result.cycle.control_generation == executing.control_generation
    assert result.permit.control_generation == control.generation
    assert len(recovered_contexts) == 1
    assert recovered_contexts[0].cycle.cycle_id == executing.cycle_id
    assert recovered_contexts[0].permit.control_generation == control.generation
    assert recovered_contexts[0].cycle.last_fence_token == result.permit.fence_token
    assert executed_contexts == []


@pytest.mark.asyncio
async def test_nonretryable_recovery_refusal_latches_adopted_cycle_blocked(
        conn) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    waiting = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=ready.cycle.cycle_id,
        to_state=CycleState.WAITING_OPEN)
    store.transition_cycle(
        conn, permit=ready.permit, cycle_id=waiting.cycle_id,
        to_state=CycleState.EXECUTING)
    store.engage_kill(conn, actor="operator", reason="test authority loss")
    expected = store.load_control(conn).binding
    assert expected is not None
    store.release_kill(
        conn, expected_binding=expected, actor="operator",
        reason="test recovery authority")

    def refuse(context):
        raise NonRetryableCallbackRefused("signed authority is invalid")

    replacement = service_for(
        cfg, holder="worker-b", recover=refuse,
        execute=lambda context: pytest.fail("old plan must not execute"))
    blocked = await replacement.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert blocked.action is TickAction.BLOCKED
    assert blocked.cycle.state is CycleState.BLOCKED
    assert blocked.cycle.failure_code == "NonRetryableCallbackRefused"
    assert blocked.cycle.diagnostic["callback_failure"] == "NONRETRYABLE"
    latched = await replacement.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert latched.action is TickAction.BLOCKED
    assert latched.cycle.cycle_id == blocked.cycle.cycle_id


@pytest.mark.asyncio
async def test_malformed_callback_result_latches_integrity_block(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(
        cfg, refresh=lambda context: {"unknown_contract_field": True})
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    blocked = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert blocked.action is TickAction.BLOCKED
    assert blocked.cycle.state is CycleState.BLOCKED
    assert blocked.cycle.failure_code == "ValidationError"
    assert blocked.cycle.diagnostic["callback_failure"] == "NONRETRYABLE"


@pytest.mark.asyncio
async def test_rebound_account_blocks_ambiguous_cycle_without_broker_callback(
        conn) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    waiting = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=ready.cycle.cycle_id,
        to_state=CycleState.WAITING_OPEN)
    store.transition_cycle(
        conn, permit=ready.permit, cycle_id=waiting.cycle_id,
        to_state=CycleState.EXECUTING)
    store.engage_kill(conn, actor="operator", reason="change paper binding")
    store.deactivate(conn, actor="operator", reason="rebind after takeover")
    changed = binding(cfg).model_copy(update={
        "broker_account_id": "paper-account-2",
        "takeover_epoch": 2,
    })
    store.activate(
        conn, binding=changed, actor="operator", reason="new paper binding")
    released = store.release_kill(
        conn, expected_binding=changed, actor="operator",
        reason="new paper authority")
    callbacks = []
    replacement = service_for(
        cfg, holder="worker-b",
        recover=lambda context: callbacks.append("recover") or
        recovery_success(context),
        execute=lambda context: callbacks.append("execute") or
        execution_success(context))

    result = await replacement.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert result.action is TickAction.BLOCKED
    assert result.cycle.failure_code == "ADOPTION_ACCOUNT_IDENTITY_MISMATCH"
    assert callbacks == []
    assert result.permit.control_generation == released.generation


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_wait", [False, True])
async def test_transport_state_after_close_enters_recovery_not_execution(
        conn, retry_wait) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    waiting = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=ready.cycle.cycle_id,
        to_state=CycleState.WAITING_OPEN)
    transport = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=waiting.cycle_id,
        to_state=CycleState.EXECUTING)
    if retry_wait:
        transport = store.transition_cycle(
            conn, permit=ready.permit, cycle_id=transport.cycle_id,
            to_state=CycleState.RETRY_WAIT,
            diagnostic={"retry_phase": "EXECUTE"},
            next_wake_at=THURSDAY_AFTER_CLOSE)
    calls = []
    replacement = service_for(
        cfg,
        recover=lambda context: calls.append("recover") or
        recovery_success(context),
        execute=lambda context: calls.append("execute") or
        execution_success(context))
    result = await replacement.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert result.action is TickAction.RECOVERED
    assert result.cycle.state is CycleState.SUCCEEDED
    assert calls == ["recover"]


@pytest.mark.asyncio
async def test_lease_token_takeover_recovers_execution_retry_before_close(
        conn) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    waiting = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=ready.cycle.cycle_id,
        to_state=CycleState.WAITING_OPEN)
    executing = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=waiting.cycle_id,
        to_state=CycleState.EXECUTING)
    retry = store.transition_cycle(
        conn, permit=ready.permit, cycle_id=executing.cycle_id,
        to_state=CycleState.RETRY_WAIT,
        diagnostic={"retry_phase": "EXECUTE"},
        next_wake_at=THURSDAY_AFTER_OPEN)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_automation_lease"
            " SET expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=1")
    conn.commit()
    calls = []
    replacement = service_for(
        cfg, holder="worker-b",
        recover=lambda context: calls.append((
            "recover", context.cycle.last_fence_token,
            context.permit.fence_token)) or recovery_success(context),
        execute=lambda context: calls.append(("execute",)) or
        execution_success(context))

    result = await replacement.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert result.action is TickAction.RECOVERED
    assert result.cycle.state is CycleState.SUCCEEDED
    assert result.permit.fence_token > retry.last_fence_token
    assert calls == [(
        "recover", result.permit.fence_token, result.permit.fence_token)]


@pytest.mark.asyncio
async def test_precreated_historical_cycles_mark_after_successful_prepare(conn) -> None:
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    refreshed = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    control = store.load_control(conn)
    timing = schedule.for_decision_session("2026-08-11", cfg)
    current_spec = service._spec(control, timing)
    store.ensure_historical_cycles(
        conn, permit=refreshed.permit,
        specs=(current_spec.model_copy(
            update={"historical_state_only": True}),))

    prepared = await service.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    historical = store.load_cycle(conn, current_spec.cycle_id)
    assert historical.state is CycleState.MISSED_STATE_ONLY
    assert prepared.action is TickAction.PREPARED
    assert "1 MISSED_STATE_ONLY" in prepared.reason


@pytest.mark.asyncio
async def test_notify_distinguishes_explicit_kill_from_inert_schema(conn, pg) -> None:
    cfg = config()
    notifications = []

    class NeverStop:
        def is_set(self):
            return False

    async def notify(_conn, result):
        notifications.append(result)

    service = AutomationService(
        config=cfg, holder_id="worker-a", refresh=refresh_result,
        prepare=prepare_result, recover=recovery_success,
        execute=execution_success, notify=notify)
    await service.run(
        lambda: feed_store.connect(pg.sync_dsn), stop=NeverStop(),
        clock=lambda: AFTER_WEDNESDAY_CLOSE, max_ticks=1)
    assert notifications == []

    enable(conn, cfg)
    store.engage_kill(conn, actor="operator", reason="emergency test")
    await service.run(
        lambda: feed_store.connect(pg.sync_dsn), stop=NeverStop(),
        clock=lambda: AFTER_WEDNESDAY_CLOSE, max_ticks=1)
    assert len(notifications) == 1
    assert "explicitly engaged" in notifications[0].reason


@pytest.mark.asyncio
async def test_missed_window_supersession_is_notifier_eligible(conn, pg) -> None:
    cfg = config()
    enable(conn, cfg)
    setup = service_for(cfg)
    await setup.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    await setup.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    ready = await setup.tick(conn, now=AFTER_WEDNESDAY_CLOSE)
    assert ready.cycle.state is CycleState.PLAN_READY
    notifications = []

    class NeverStop:
        def is_set(self):
            return False

    async def notify(_conn, result):
        notifications.append(result)

    runner = AutomationService(
        config=cfg, holder_id="worker-a", refresh=refresh_result,
        prepare=prepare_result, recover=recovery_success,
        execute=execution_success, notify=notify)
    await runner.run(
        lambda: feed_store.connect(pg.sync_dsn), stop=NeverStop(),
        clock=lambda: THURSDAY_AFTER_CLOSE, max_ticks=1)
    assert len(notifications) == 1
    assert notifications[0].action is TickAction.SUPERSEDED
    assert notifications[0].cycle.failure_code == "MISSED_EXECUTION_WINDOW"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_automation_service_instances"
            " WHERE instance_id='worker-a'")
        assert cur.fetchone()[0] == "SUPERSEDED"
