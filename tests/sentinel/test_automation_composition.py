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


@pytest.mark.parametrize("fractional", [False, True], ids=["whole", "fractional"])
def test_market_paper_callbacks_wait_for_settled_cash_and_resume_same_cycle(assembly, monkeypatch, fractional):
    """Real scheduler, PAPER gateway, guard, journal and recovery over private PG."""
    from dataclasses import replace
    from datetime import timedelta
    from decimal import Decimal as D
    from zoneinfo import ZoneInfo

    from sentinel import binding, dual_plan_authority, local_paper
    from sentinel.authority import load_rollout_state
    from sentinel.automation import store
    from sentinel.automation.model import CycleState, TickAction
    from sentinel.execution import feed_inputs, held_targets, target_reprojection
    from sentinel.execution.market_buy_policy import MARKET_MODE, FRACTIONAL_MODE, MarketBuyPolicy
    from sentinel.execution.opening_prices import QUOTE_SOURCE
    from sentinel.execution.simulator import SimulatedBroker
    from sentinel.execution.states import CommandState as S
    from sentinel.feed import calendar
    from test_market_day_execution import MarketBroker
    from test_opening_submit_freshness_boundary import ClockedBroker

    # The legacy assembly supplies synthetic external authority and source.
    # Prepare its canonical plan, then stamp the matching simulated authority
    # through the actual durable contract before selecting market execution.
    monkeypatch.delenv(local_paper.MODE_ENV, raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    enabled = [False]
    monkeypatch.setattr(MarketBuyPolicy, "from_env",
                        classmethod(lambda cls, values=None: cls(fractional) if enabled[0] else None))
    profile = MarketBuyPolicy(fractional)
    fixture_worker = assembly.create()
    config = fixture_worker.automation_config.model_copy(
        update={"market_buy_policy_sha256": profile.fingerprint()})
    control = assembly.control.model_copy(update={"config_sha256": config.fingerprint})
    monkeypatch.setattr(runtime, "config_from_env", lambda *args, **kwargs: config)

    def worker():
        return runtime.ProductionAutomation(
            sentinel_config=fixture_worker.sentinel_config, automation_config=config,
            holder_id="assembly-worker")

    def advance(*args, **kwargs):
        state = fixture._advance_stub(*args, **kwargs)
        state["last_decision"]["target_core_exposure"] = "0.5"
        return state

    monkeypatch.setattr(fixture.paper_preparation, "advance_and_persist", advance)
    monkeypatch.setattr(SimulatedBroker, "market_clock", ClockedBroker.market_clock)
    monkeypatch.setattr(SimulatedBroker, "_now", ClockedBroker._now, raising=False)
    monkeypatch.setattr(SimulatedBroker, "opening_prices", MarketBroker.opening_prices)
    inner = SimulatedBroker(account=assembly.broker.account, cash=D(1000), equity=D(1000),
        capabilities=replace(assembly.broker.capabilities, regular_session_quote_prices=True,
                             regular_session_open_prices=True, pre_submit_instrument_revalidation=True))
    if fractional:
        from sentinel.execution.contract import BrokerAssetRules
        from sentinel.execution import protected_limits
        from test_limit_day_sizing import references
        def simulated_references(conn, *, plan, projection):
            refs = references(plan, projection)
            return replace(refs, provider_asset_ids={sid: "sim-asset-" + sid
                for sid in refs.symbols if sid != "SENTINEL:BIL"})
        monkeypatch.setattr(protected_limits, "build_references", simulated_references)
        inner.capabilities = replace(inner.capabilities, notional_market_buys=True,
                                     minimum_quantity_increment=D("0.000000001"))
        inner.dollars = {}
        original_submit = SimulatedBroker.submit
        original_orders = SimulatedBroker._snapshot_orders
        original_exact = SimulatedBroker.find_by_client_key
        def native_order(order):
            return replace(order, quantity=None, notional=inner.dollars[order.client_key]) if (
                order is not None and order.client_key in inner.dollars) else order
        async def submit(self, *, client_key, instrument, side, quantity, notional=None):
            if notional is not None:
                assert quantity is None
                self.dollars[client_key] = notional
                quantity = notional / D(100)
            return await original_submit(self, client_key=client_key, instrument=instrument, side=side, quantity=quantity)
        async def exact(self, client_key):
            result = await original_exact(self, client_key)
            return replace(result, order=native_order(result.order))
        async def asset_rules(self, *, instrument):
            return BrokerAssetRules(instrument, self.now, True)
        monkeypatch.setattr(SimulatedBroker, "submit", submit)
        monkeypatch.setattr(SimulatedBroker, "_snapshot_orders", lambda self: (native_order(o) for o in original_orders(self)))
        monkeypatch.setattr(SimulatedBroker, "find_by_client_key", exact)
        monkeypatch.setattr(SimulatedBroker, "asset_rules", asset_rules)
    inner.ask = D(95)
    inner.missing_quote = False
    inner.quote_source = QUOTE_SOURCE
    monkeypatch.setattr(runtime, "build_execution_broker", lambda *args, **kwargs: inner)

    def run_tick(*, advance_seconds=0):
        assembly.clock[0] += timedelta(seconds=advance_seconds)
        inner.now = assembly.clock[0].astimezone(ZoneInfo(calendar.EXCHANGE_TZ))
        return tick(assembly, worker())

    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        store.activate(conn, binding=control, actor="fixture", reason="market assembly")
        store.release_kill(conn, expected_binding=control, actor="fixture", reason="market assembly")
    for action in (TickAction.RECOVERED, TickAction.REFRESHED, TickAction.PREPARED):
        result = run_tick()
        assert result.action is action, result
    assert result.cycle.state is CycleState.PLAN_READY
    cycle_id = result.cycle.cycle_id
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        state, plan, _ = fixture.paper_validation._state_and_plan_or_refuse(conn)
        assert plan.plan_id == result.cycle.plan_id
        assert sum(quantity > 0 for quantity in plan.target_basket.values()) == 2
        bound = binding.require(conn)
        with feed_inputs.pinned(conn, commit=False) as pinned:
            authority = dual_plan_authority.build_authority(
                plan=plan, shadow_result=SimpleNamespace(
                    state=state, record_sha256="a" * 64, runtime_authority_sha256="b" * 64),
                publication=pinned, account_snapshot=asyncio.run(inner.account_snapshot()),
                observation=asyncio.run(inner.observe()), marks={}, tickers={},
                held_share_targets=held_targets.build_basis(
                    conn, previous=None, state=state, binding=bound, rollout=load_rollout_state(conn)),
                market_buy_policy_sha256=profile.fingerprint())
            dual_plan_authority.record_authority(conn, authority)

    enabled[0] = True
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", FRACTIONAL_MODE if fractional else MARKET_MODE)
    assembly.clock[0] = assembly.clock[0].replace(hour=13, minute=29)
    assert run_tick().action is TickAction.WAITING
    sent = run_tick(advance_seconds=120)
    assert sent.cycle.state is CycleState.RECONCILING, sent
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        commands = journal.load_commands(conn, bound.identity)
        assert len(commands) == 1, sent
        first = commands[0]
        assert first.state is S.ACKNOWLEDGED
        original = target_reprojection.load_projection(conn, plan_id=plan.plan_id)

    inner.fill(first.client_key, "1")
    pending = run_tick(advance_seconds=3)
    assert pending.cycle.state is not CycleState.SUCCEEDED, pending
    assert fixture._mutations(inner) == [f"submit:{first.client_key}"]

    old_cash = inner.cash
    inner.fill(first.client_key)
    actual_cash, inner.cash = inner.cash, old_cash  # Delayed cash endpoint after terminal fill.
    lagging = run_tick(advance_seconds=3)
    assert lagging.cycle.state is not CycleState.SUCCEEDED, lagging
    assert fixture._mutations(inner) == [f"submit:{first.client_key}"]
    inner.cash = actual_cash

    ready = run_tick(advance_seconds=3)
    assert ready.action is TickAction.RECOVERED, ready
    assert ready.cycle.cycle_id == cycle_id
    assert ready.cycle.diagnostic["retry_phase"] == "EXECUTE"
    second_send = run_tick(advance_seconds=3)
    assert second_send.cycle.state is CycleState.RECONCILING, second_send
    with feed_store.connect(assembly.pg.sync_dsn) as conn:
        commands = journal.load_commands(conn, bound.identity)
        second, = [command for command in commands if command.client_key != first.client_key]
        assert second.state is S.ACKNOWLEDGED
        assert target_reprojection.load_projection(conn, plan_id=plan.plan_id) == original
    assert fixture._mutations(inner) == [f"submit:{first.client_key}", f"submit:{second.client_key}"]

    inner.fill(second.client_key)
    done = run_tick(advance_seconds=3)
    assert done.cycle.state is CycleState.SUCCEEDED and done.cycle.cycle_id == cycle_id, done
    if fractional:
        assert first.quantity is None and second.quantity is None
        assert first.notional > 0 and second.notional > 0
