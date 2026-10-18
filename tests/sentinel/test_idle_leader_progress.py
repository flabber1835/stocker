"""Idle liveness follows main-loop progress without extending a blocked stage."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from sentinel.automation import integrity, store
from sentinel.automation.model import (
    AutomationRefused, CycleState, StaleLeaderRefused, TickAction,
    TransientInfrastructureFailure,
)
from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_service import (
    THURSDAY_AFTER_OPEN, THURSDAY_BEFORE_OPEN, config, conn, enable, pg,
    recovery_success, service_for,
)


async def waiting_service(connection, cfg):
    enable(connection, cfg)
    service = service_for(cfg)
    for _ in range(4):
        result = await service.tick(connection, now=THURSDAY_BEFORE_OPEN)
    assert result.cycle.state is CycleState.WAITING_OPEN
    return service, result


def small_config():
    return config().model_copy(update={
        "lease_seconds": 3, "heartbeat_seconds": 1,
        "control_poll_seconds": 1,
    })


@pytest.mark.asyncio
async def test_instance_exists_before_first_lease_acquisition(conn, pg, monkeypatch):
    cfg = small_config()
    enable(conn, cfg)
    service = service_for(cfg)
    acquire = store.acquire_lease
    observed = []

    def inspect_startup(connection, **kwargs):
        row = connection.execute(
            "SELECT state,heartbeat_at FROM sentinel_automation_service_instances "
            "WHERE instance_id=%s", (service.holder_id,)).fetchone()
        assert row is not None and row[0] == "WAITING" and row[1] is not None
        connection.rollback()
        observed.append(row)
        return acquire(connection, **kwargs)

    async def recover(context):
        return recovery_success(context)

    service.recover = recover
    instant = THURSDAY_BEFORE_OPEN - timedelta(days=1, hours=13)
    monkeypatch.setattr(store, "acquire_lease", inspect_startup)
    monkeypatch.setattr(service, "_assert_clock_skew", lambda **kwargs: kwargs["now"])
    await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
                      clock=lambda: instant, max_ticks=1)
    assert len(observed) == 1


@pytest.mark.asyncio
async def test_established_leader_survives_repeated_uncertain_samples(conn, pg, monkeypatch):
    service, prepared = await waiting_service(conn, small_config())
    before = conn.execute(
        "SELECT count(*) FROM sentinel_automation_cycle_events").fetchone()[0]
    conn.rollback()
    samples = 0

    def sample(**kwargs):
        nonlocal samples
        samples += 1
        if samples > 1:
            raise TransientInfrastructureFailure("bounded uncertain clock sample")
        return kwargs["now"]

    async def sleep(_seconds):
        await asyncio.sleep(1.05)
        current = store.require_leader(conn, prepared.permit)
        assert current.fence_token == prepared.permit.fence_token

    monkeypatch.setattr(service, "_assert_clock_skew", sample)
    await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
                      clock=lambda: THURSDAY_BEFORE_OPEN, sleep=sleep, max_ticks=5)
    current = store.require_leader(conn, prepared.permit)
    assert samples == 5 and current.fence_token == prepared.permit.fence_token
    assert current.expires_at > prepared.permit.expires_at
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0
    assert conn.execute(
        "SELECT count(*) FROM sentinel_automation_cycle_events").fetchone()[0] == before
    conn.rollback()


@pytest.mark.asyncio
async def test_sequential_slow_idle_stages_keep_one_live_permit(conn, pg, monkeypatch):
    service, prepared = await waiting_service(conn, small_config())
    tick = service.tick
    stage_checks = []

    async def slow_tick(*args, **kwargs):
        result = await tick(*args, **kwargs)
        await asyncio.sleep(1.15)
        return result

    async def idle_check(_connection):
        await asyncio.sleep(1.15)
        stage_checks.append(store.require_leader(conn, prepared.permit).fence_token)

    async def sleep(_seconds):
        await asyncio.sleep(.25)

    monkeypatch.setattr(service, "tick", slow_tick)
    monkeypatch.setattr(service, "_assert_clock_skew", lambda **kwargs: kwargs["now"])
    await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
                      clock=lambda: THURSDAY_BEFORE_OPEN, sleep=sleep,
                      control_wake=idle_check, max_ticks=2)
    assert stage_checks == [prepared.permit.fence_token] * 2
    assert store.require_leader(conn, prepared.permit).fence_token == prepared.permit.fence_token


@pytest.mark.asyncio
async def test_blocked_idle_stage_receives_no_independent_renewal(conn, pg, monkeypatch):
    service, prepared = await waiting_service(conn, small_config())
    observed_expiry = []

    async def blocked_check(_connection):
        await asyncio.sleep(3.2)
        with pytest.raises(StaleLeaderRefused):
            store.require_leader(conn, prepared.permit)
        observed_expiry.append(True)

    monkeypatch.setattr(service, "_assert_clock_skew", lambda **kwargs: kwargs["now"])
    await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
                      clock=lambda: THURSDAY_BEFORE_OPEN,
                      control_wake=blocked_check, max_ticks=1)
    assert observed_expiry == [True]
    with pytest.raises(StaleLeaderRefused):
        store.require_leader(conn, prepared.permit)
    row = conn.execute(
        "SELECT fence_token,expires_at<clock_timestamp() "
        "FROM sentinel_automation_lease WHERE id=1").fetchone()
    conn.rollback()
    assert row == (prepared.permit.fence_token, True)
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0
    conn.rollback()


@pytest.mark.parametrize("loss", ["expired", "replaced", "killed"])
@pytest.mark.asyncio
async def test_main_progress_discards_lost_permit_without_reacquisition(conn, loss):
    service, prepared = await waiting_service(conn, config())
    if loss == "expired":
        conn.execute("UPDATE sentinel_automation_lease SET "
                     "expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id=1")
        conn.commit()
    elif loss == "replaced":
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='replacement',"
                     "fence_token=fence_token+1 WHERE id=1")
        conn.commit()
    else:
        store.engage_kill(conn, actor="operator", reason="isolated test")
    query = ("SELECT holder_id,fence_token,control_generation,expires_at "
             "FROM sentinel_automation_lease WHERE id=1")
    before = conn.execute(query).fetchone()
    conn.rollback()
    assert service._record_main_progress(
        conn, permit=prepared.permit, state="WAITING",
        next_wake_at=THURSDAY_BEFORE_OPEN) is None
    after = conn.execute(query).fetchone()
    conn.rollback()
    assert after == before


def test_main_progress_cannot_renew_another_holders_live_permit(conn):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    foreign = store.acquire_lease(conn, holder_id="another-worker", lease_seconds=30)
    query = "SELECT holder_id,fence_token,heartbeat_at,expires_at FROM sentinel_automation_lease WHERE id=1"
    before = conn.execute(query).fetchone()
    conn.rollback()
    assert service._record_main_progress(
        conn, permit=foreign, state="WAITING",
        next_wake_at=THURSDAY_BEFORE_OPEN) is None
    assert conn.execute(query).fetchone() == before
    conn.rollback()


@pytest.mark.asyncio
async def test_identical_cycle_lineage_is_read_once_per_tick_only(conn, monkeypatch):
    service, _prepared = await waiting_service(conn, config())
    validate = integrity.validate_cycle_lineage
    checks = []

    def counted(connection, cycle):
        checks.append(cycle.cycle_id)
        return validate(connection, cycle)

    monkeypatch.setattr(integrity, "validate_cycle_lineage", counted)
    await service.tick(conn, now=THURSDAY_BEFORE_OPEN)
    assert len(checks) == 1
    await service.tick(conn, now=THURSDAY_BEFORE_OPEN)
    assert len(checks) == 2


@pytest.mark.asyncio
async def test_same_tick_changed_cycle_cannot_reuse_lineage_validation(conn, monkeypatch):
    service, _prepared = await waiting_service(conn, config())
    create = store.create_cycle

    def changed(connection, **kwargs):
        cycle = create(connection, **kwargs)
        return cycle.model_copy(update={"failure_code": "UNEXPLAINED_MUTATION"})

    monkeypatch.setattr(store, "create_cycle", changed)
    with pytest.raises(AutomationRefused, match="failure_code.*event history"):
        await service.tick(conn, now=THURSDAY_BEFORE_OPEN)


@pytest.mark.asyncio
async def test_execution_keeps_its_fresh_lineage_validation(conn, monkeypatch):
    service, prepared = await waiting_service(conn, config())
    validate = integrity.validate_cycle_lineage
    checks = []

    def counted(connection, cycle):
        checks.append((cycle.cycle_id, cycle.state))
        return validate(connection, cycle)

    monkeypatch.setattr(integrity, "validate_cycle_lineage", counted)
    result = await service.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert result.action is TickAction.EXECUTED
    assert result.cycle.cycle_id == prepared.cycle.cycle_id
    assert any(state is CycleState.WAITING_OPEN for _, state in checks)
    assert any(state is CycleState.EXECUTING for _, state in checks)
    assert result.cycle.state is CycleState.SUCCEEDED
