"""Idle liveness follows main-loop progress without extending a blocked stage."""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from psycopg.errors import ReadOnlySqlTransaction

from sentinel import automation_runtime
from sentinel.automation import integrity, store
from sentinel.automation.model import (
    AutomationRefused, CycleState, StaleLeaderRefused, TickAction,
    TransientInfrastructureFailure,
)
from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_service import (
    THURSDAY_AFTER_OPEN, THURSDAY_BEFORE_OPEN, binding, config, conn, enable, pg,
    recovery_success, service_for,
)
from tests.sentinel.test_automation_runtime import production


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
async def test_slow_idle_observer_converges_under_same_live_twelve_second_lease(
        conn, pg, monkeypatch):
    cfg = config().model_copy(update={
        "lease_seconds": 12, "heartbeat_seconds": 3,
        "control_poll_seconds": 1})
    service, prepared = await waiting_service(conn, cfg)
    runtime = production(cfg)
    runtime.sentinel_config = replace(
        runtime.sentinel_config, database_url=pg.sync_dsn)
    expected = binding(cfg)
    monkeypatch.setattr(service, "_assert_clock_skew",
                        lambda **kwargs: kwargs["now"])
    monkeypatch.setattr(runtime, "_idle_certificate_identity",
                        lambda _conn, **_kw: SimpleNamespace(
                            certificate_sha256=expected.certificate_sha256))
    monkeypatch.setattr(automation_runtime, "load_rollout_state",
                        lambda _conn: SimpleNamespace(
                            mode=SimpleNamespace(value=expected.rollout_mode),
                            version=expected.rollout_version,
                            certificate_sha256=None))
    monkeypatch.setattr(automation_runtime.feed_inputs, "require_current",
                        lambda _conn: SimpleNamespace(version=1))
    flights = []

    class SlowFlight:
        stage = "SIGNED_AUTHORITY_PUBLICATION"
        backend_pid = None
        timeout_seconds = 25
        error = None

        def __init__(self, control):
            self.started_monotonic = time.monotonic()
            self.cancelled = threading.Event()
            self.finished = threading.Event()
            self.value = {
                "status": "PASS", "generation": control.generation,
                "binding": control.binding.model_dump(mode="json"),
                "publication_version": 1,
                "rollout_mode": expected.rollout_mode,
                "rollout_version": expected.rollout_version,
                "certificate_sha256": expected.certificate_sha256,
            }
            self.thread = threading.Thread(target=self._complete, daemon=True)
            self.thread.start()

        def _complete(self):
            time.sleep(13.1)
            self.finished.set()

        @property
        def elapsed_seconds(self):
            return time.monotonic() - self.started_monotonic

        def stop(self, **_kwargs):
            self.cancelled.set()
            self.thread.join(1)
            return not self.thread.is_alive()

    def start(control, permit, observed_at):
        flight = SlowFlight(control)
        flights.append(flight)
        runtime._idle_authority_flight = (
            flight, runtime._idle_attestation_key(control, permit), observed_at)
        return flight

    monkeypatch.setattr(runtime, "_start_idle_authority_observer", start)
    started = time.monotonic()

    async def bounded_sleep(_seconds):
        await asyncio.sleep(.75)

    await service.run(lambda: feed_store.connect(pg.sync_dsn),
                      stop=asyncio.Event(), clock=lambda: THURSDAY_BEFORE_OPEN,
                      sleep=bounded_sleep, control_wake=runtime.bounded_control_wake,
                      max_ticks=21)
    assert time.monotonic() - started > 13.1
    assert len(flights) == 1 and flights[0].finished.is_set()
    assert not flights[0].cancelled.is_set()
    assert runtime._idle_attestation is not None
    assert store.load_control(conn).authority_verdict == "PASS"
    assert store.require_leader(conn, prepared.permit).fence_token == prepared.permit.fence_token
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0
    conn.rollback()


@pytest.mark.asyncio
async def test_idle_observer_database_session_remains_read_only_after_fence_read(
        conn, pg):
    cfg = config().model_copy(update={
        "lease_seconds": 12, "heartbeat_seconds": 3})
    _service, prepared = await waiting_service(conn, cfg)
    observer_conn = feed_store.connect(pg.sync_dsn)
    try:
        observer_conn.read_only = True
        assert store.require_leader(
            observer_conn, prepared.permit).fence_token == prepared.permit.fence_token
        observer_conn.rollback()
        with pytest.raises(ReadOnlySqlTransaction):
            observer_conn.execute(
                "UPDATE sentinel_automation_control SET updated_at=clock_timestamp() WHERE id=1")
        observer_conn.rollback()
    finally:
        observer_conn.close()


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


@pytest.mark.parametrize('case, expected', [('same', 9), ('replaced', 7), ('slow', 10)])
@pytest.mark.asyncio
async def test_waiting_open_tick_reuses_only_recent_fenced_progress(conn, pg, monkeypatch, case, expected):
    from types import SimpleNamespace
    from sentinel.automation import service as module

    cfg = small_config()
    service, prepared = await waiting_service(conn, cfg)
    real_heartbeat = store.heartbeat_lease
    pulse_count = 0
    checks = 0
    monotonic = 0.

    def heartbeat(connection, **kwargs):
        nonlocal pulse_count
        observed = real_heartbeat(connection, **kwargs)
        pulse_count += 1
        return observed

    def sample(**kwargs):
        nonlocal checks, monotonic
        checks += 1
        if checks == 3 and case == 'replaced':
            conn.execute("UPDATE sentinel_automation_lease SET holder_id='replacement',"
                         'fence_token=fence_token+1 WHERE id=1')
            conn.commit()
        if checks == 3 and case == 'slow':
            monotonic += cfg.heartbeat_seconds
        return kwargs['now']

    async def immediate(_):
        pass

    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: monotonic))
    monkeypatch.setattr(service, '_assert_clock_skew', sample)
    monkeypatch.setattr(store, 'heartbeat_lease', heartbeat)
    await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
                      clock=lambda: THURSDAY_BEFORE_OPEN, sleep=immediate,
                      control_wake=immediate, max_ticks=3)
    assert pulse_count == expected
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    assert store.load_cycle(conn, prepared.cycle.cycle_id).state is CycleState.WAITING_OPEN
    conn.rollback()


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
