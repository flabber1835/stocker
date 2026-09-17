"""Real automation callbacks + SQL + paper gateway; explicit external fixtures.

Scope and exclusions: docs/automation-composition-regressions.md.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime as runtime, schema
from sentinel.automation import store
from sentinel.automation.model import AutomationConfig, ControlBinding, CycleState, TickAction
from sentinel.config import SentinelConfig, DEFAULT_BASE_URL
from sentinel.execution import journal, preopen_authority
from sentinel.execution.simulator import FaultKind
from sentinel.execution.states import CommandState
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres
import test_paper_activation as fixture

# Preserve the real validator before the legacy suite's autouse compatibility
# shim runs. This new composition test must never migrate during runtime reads.
REAL_FEED_VALIDATOR = feed_store.require_feed_schema


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    try:
        server.start()  # Required dependency: missing PostgreSQL is a failure.
        yield server
    finally:
        server.stop()


@pytest.fixture
def assembly(pg, monkeypatch):
    monkeypatch.setattr(feed_store, "require_feed_schema", REAL_FEED_VALIDATOR)
    with feed_store.connect(pg.sync_dsn) as conn:
        from tests.support.postgres import drop_public_tables
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        feed_store.migrate_schema(conn)
        conn.execute(
            "INSERT INTO sentinel_system_certificates"
            " (certificate_sha256,manifest_bytes,manifest,allowed_rollout_modes)"
            " VALUES (%s,'{}'::bytea,'{}'::jsonb,'[\"CONTROLLER\"]'::jsonb)",
            (fixture.ROLLOUT_CERTIFICATE,))
        conn.execute("UPDATE sentinel_rollout_state SET mode='CONTROLLER',"
                     "version=2,certificate_sha256=%s WHERE id=1",
                     (fixture.ROLLOUT_CERTIFICATE,))
        conn.execute("INSERT INTO sentinel_rollout_events"
                     " (version,from_mode,to_mode,certificate_sha256,reason)"
                     " VALUES (2,'PINNED_1_00','CONTROLLER',%s,'assembly fixture')",
                     (fixture.ROLLOUT_CERTIFICATE,))
        conn.commit()
        bound = fixture._bind(conn)
        feed_store.write_bars(conn, [fixture.VendorBar(
            session=fixture.DECISION.isoformat(), security_id=fixture.AAA.security_id,
            ticker="AAA", raw_open=100.0, raw_close=100.0, volume=1_000_000.0)])
        current = fixture._publish(conn)
        fixture._persist_state(conn, fixture._state(
            session=fixture.PRIOR, data_version=current.version, with_target=True))

    # Explicit external inputs, shared with the existing paper gateway tests.
    fixture.simulator_is_certified.__wrapped__(monkeypatch)
    fixture._ready(monkeypatch)
    from sentinel.feed.readiness import Readiness, Check, PASS
    monkeypatch.setattr(runtime.readiness, "check_readiness", lambda *a, **k: Readiness([
        Check("synthetic source fixture", PASS, "bounded assembly input")]))
    monkeypatch.setattr(runtime, "production_strategy", lambda: (fixture.CONFIG, dict(fixture.IDENTITY)))
    monkeypatch.setattr(runtime, "require_current_authority", lambda *a, **k: SimpleNamespace(
        certificate_sha256=fixture.ROLLOUT_CERTIFICATE,
        authorization_mode="PAPER_OBSERVATION_ONLY"))
    monkeypatch.setattr(fixture.paper_preparation, "advance_and_persist", fixture._advance_stub)
    monkeypatch.setattr(fixture.paper_preparation, "_load_marks_and_tickers", lambda *a: (
        {fixture.AAA.security_id: fixture.D(100), fixture.DEFENSIVE_SECURITY_ID: fixture.D(90)},
        {fixture.AAA.security_id: "AAA", fixture.DEFENSIVE_SECURITY_ID: "BIL"}))
    broker = fixture._broker()
    monkeypatch.setattr(runtime, "build_execution_broker", lambda *a, **k: broker)
    clock = [dt.datetime(2026, 8, 12, 3, 46, tzinfo=dt.timezone.utc)]

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    for owner in (runtime, fixture.paper_preparation, fixture.paper_execution, fixture.paper_recovery):
        monkeypatch.setattr(owner, "datetime", Clock)
    cfg = AutomationConfig(publication_delay_seconds=0, execution_delay_seconds=60,
                           lease_seconds=30, heartbeat_seconds=5,
                           retry_base_seconds=1, retry_max_seconds=2)
    config = SentinelConfig(alpaca_key="", alpaca_secret="", base_url=DEFAULT_BASE_URL,
                            state_dir=Path("/tmp"), max_cycles=1, poll_seconds=0,
                            database_url=pg.sync_dsn)
    control = ControlBinding(
        deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        certificate_sha256=fixture.ROLLOUT_CERTIFICATE,
        rollout_mode="CONTROLLER", rollout_version=2, config_sha256=cfg.fingerprint)

    def create():
        return runtime.ProductionAutomation(sentinel_config=config, automation_config=cfg,
                                            holder_id="assembly-worker")

    return SimpleNamespace(pg=pg, broker=broker, clock=clock, create=create, control=control)


def tick(assembly, worker):
    # Every boundary opens a fresh connection, including after runtime restart.
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        return asyncio.run(worker.service.tick(conn, now=assembly.clock[0]))


@pytest.mark.parametrize("fault", [
    "acknowledged", "accepted-response-lost", "kill-before-open", "missing-preopen",
])
def test_real_callbacks_prepare_submit_restart_and_reconcile_once(assembly, fault):
    worker = assembly.create()
    assert tick(assembly, worker).action is TickAction.INERT
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        store.activate(conn, binding=assembly.control, actor="fixture", reason="assembly")
    assert tick(assembly, worker).action is TickAction.INERT
    assert not fixture._mutations(assembly.broker)
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        store.release_kill(conn, expected_binding=assembly.control, actor="fixture", reason="assembly")
    for action in (TickAction.RECOVERED, TickAction.REFRESHED, TickAction.PREPARED):
        result = tick(assembly, worker)
        assert result.action is action, result
    assert result.cycle.state is CycleState.PLAN_READY
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        plan = journal.latest_plan(conn)
        assert plan.plan_id == result.cycle.plan_id
        cutoff = fixture.paper_targets._official_preopen_cutoff(plan)
        if fault != "missing-preopen":
            preopen_authority.record_authority(conn, preopen_authority.PreOpenShareUnitAuthority(
                plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
                effective_session=plan.effective_session, provider="assembly-input",
                publication_id="assembly-input", as_of=cutoff, cutoff_at=cutoff, complete=True,
                coverage=(preopen_authority.ShareUnitCoverage.no_event(fixture.AAA.security_id),)))
    assembly.clock[0] = dt.datetime(2026, 8, 12, 13, 29, tzinfo=dt.timezone.utc)
    assert tick(assembly, assembly.create()).action is TickAction.WAITING
    assert not fixture._mutations(assembly.broker)
    if fault == "kill-before-open":
        with feed_store.connect(assembly.pg.sync_dsn) as conn:
            store.engage_kill(conn, actor="fixture", reason="revoke before open")
        assembly.clock[0] = dt.datetime(2026, 8, 12, 13, 31, tzinfo=dt.timezone.utc)
        calls = list(assembly.broker.calls)
        assert tick(assembly, assembly.create()).action is TickAction.INERT
        assert assembly.broker.calls == calls
        assert not fixture._mutations(assembly.broker)
        return
    lost_ack = fault == "accepted-response-lost"
    if lost_ack:
        assembly.broker.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)
    assembly.clock[0] = dt.datetime(2026, 8, 12, 13, 31, tzinfo=dt.timezone.utc)
    sent = tick(assembly, assembly.create())
    assert sent.cycle.state is CycleState.RECONCILING, sent
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        commands = journal.load_commands(conn, fixture.binding.require(conn).identity)
        assert len(commands) == 1
        assert commands[0].state is (CommandState.UNKNOWN if lost_ack else CommandState.ACKNOWLEDGED)
    key = commands[0].client_key
    pending = tick(assembly, assembly.create())
    assert pending.cycle.state is not CycleState.SUCCEEDED
    assert fixture._mutations(assembly.broker) == ["submit:" + key]
    assembly.broker.fill(key)
    assembly.clock[0] += dt.timedelta(seconds=3)
    completed = tick(assembly, assembly.create())
    assert completed.cycle.state is CycleState.SUCCEEDED, completed
    assert completed.cycle.last_clean_reconciliation_id is not None
    assert tick(assembly, assembly.create()).cycle.state is CycleState.SUCCEEDED
    assert fixture._mutations(assembly.broker) == ["submit:" + key]
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        commands = journal.load_commands(conn, fixture.binding.require(conn).identity)
        assert len(commands) == 1 and commands[0].state is CommandState.FILLED
        assert commands[0].filled_quantity == plan.target_basket[fixture.AAA.security_id]
