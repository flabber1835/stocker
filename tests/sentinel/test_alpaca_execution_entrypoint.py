"""Public execute_session coverage for the Alpaca simulation gate."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel import binding, schema
from sentinel.execution import alpaca, broker_cash, executor, journal
from sentinel.execution.contract import BrokerInstrument, Completeness
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState as S
from sentinel.feed import store
from tests.support.alpaca_simulator import AlpacaSimulator, EPOCH, Profile
from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from test_alpaca_simulation_harness import DEPLOY, INSTRUMENT, run


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    try:
        server.start()
    except Exception as exc:
        server.stop()
        if os.environ.get("ALPACA_HARNESS_REQUIRE_POSTGRES") == "1":
            pytest.fail(f"required PostgreSQL unavailable: {exc}")
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg):
    with store.connect(pg.sync_dsn) as connection:
        drop_public_tables(connection)
        schema.ensure_schema(connection)
        binding.bind(
            connection, deployment_id=DEPLOY.deployment_id, broker="alpaca",
            broker_account_id=DEPLOY.broker_account_id)
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_account_binding SET established_at=%s WHERE id=1",
                (EPOCH - timedelta(days=1),))
        connection.commit()
        yield connection


@pytest.fixture(params=list(Profile), ids=lambda profile: profile.value)
def world(request):
    simulated = AlpacaSimulator(request.param)
    yield simulated
    assert not simulated.faults


@pytest.fixture(autouse=True)
def open_simulation_only_alpaca_fences(monkeypatch):
    monkeypatch.setattr(alpaca, "upgrade_restore_reason", lambda conn: "")
    monkeypatch.setattr(
        alpaca, "execution_increase_fence_reason", lambda **kwargs: "")


def plan(plan_id: str, basket: dict[str, D]) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=plan_id,
        decision_session=EPOCH.date(),
        effective_session=EPOCH.date(),
        target_exposure=D(1),
        target_basket=basket,
        data_version=1,
        deployment_id=DEPLOY.deployment_id,
        broker=DEPLOY.broker,
        broker_account_id=DEPLOY.broker_account_id,
        takeover_epoch=DEPLOY.takeover_epoch,
        account_nav=D("100000"),
        account_cash=D("100000"),
    )


def execute(conn, world, current_plan, *, instruments=None):
    executor.adopt_plan(conn, current_plan)
    return run(executor.execute_session(
        broker=world.adapter(),
        conn=conn,
        deployment=DEPLOY,
        plan=current_plan,
        instruments=instruments or {"SEC-AAA": INSTRUMENT},
        today=EPOCH.date(),
        settle_cycles=3,
    ))


def ingest(conn, world, *, adapter=None):
    state = run(broker_cash.ingest_account_cash(
        conn,
        broker_adapter=adapter or world.adapter(),
        broker="alpaca",
        account_id=DEPLOY.broker_account_id,
        through=world.now,
    ))
    conn.commit()
    return state


def test_public_execute_session_converges_after_fill(conn, world):
    first = execute(conn, world, plan("entry-converge-1", {"SEC-AAA": D(10)}))
    assert len(first.submitted) == 1
    assert first.submitted[0].state is S.ACKNOWLEDGED
    world.fill(first.submitted[0].broker_order_id)

    second = execute(conn, world, plan("entry-converge-2", {"SEC-AAA": D(10)}))

    assert second.submitted == ()
    assert world.counts[("POST", "/v2/orders")] == 1
    assert any(command.state is S.FILLED
               for command in journal.load_commands(conn, DEPLOY))


def test_public_execute_session_resolves_unknown_before_overlap(conn, world):
    world.timeout(after_effect=True)
    first = execute(conn, world, plan("entry-unknown-1", {"SEC-AAA": D(10)}))
    assert len(first.submitted) == 1
    assert first.submitted[0].state is S.UNKNOWN
    assert len(world.orders) == 1

    second = execute(conn, world, plan("entry-unknown-2", {"SEC-AAA": D(10)}))

    assert second.submitted == ()
    assert world.counts[("POST", "/v2/orders")] == 1
    assert any(command.state is S.ACKNOWLEDGED
               for command in journal.load_commands(conn, DEPLOY))


def test_public_execute_session_sells_before_buy_and_converges(conn, world):
    world.add_asset("BBB")
    bbb = BrokerInstrument(
        security_id="SEC-BBB", symbol="BBB", broker_id=world.assets["BBB"]["id"])
    instruments = {"SEC-AAA": INSTRUMENT, "SEC-BBB": bbb}

    seed = execute(
        conn, world, plan("entry-order-seed", {"SEC-BBB": D(10)}),
        instruments=instruments)
    assert len(seed.submitted) == 1
    world.fill(seed.submitted[0].broker_order_id)

    reduction = execute(
        conn, world,
        plan("entry-order-reduce", {"SEC-AAA": D(5), "SEC-BBB": D(0)}),
        instruments=instruments)
    assert len(reduction.submitted) == 1
    assert world.orders[reduction.submitted[0].broker_order_id]["side"] == "sell"
    assert not any(order["side"] == "buy" and order["symbol"] == "AAA"
                   for order in world.orders.values())
    world.fill(reduction.submitted[0].broker_order_id)

    increase = execute(
        conn, world,
        plan("entry-order-increase", {"SEC-AAA": D(5), "SEC-BBB": D(0)}),
        instruments=instruments)
    assert len(increase.submitted) == 1
    assert world.orders[increase.submitted[0].broker_order_id]["side"] == "buy"
    world.fill(increase.submitted[0].broker_order_id)

    final = execute(
        conn, world,
        plan("entry-order-final", {"SEC-AAA": D(5), "SEC-BBB": D(0)}),
        instruments=instruments)
    assert final.submitted == ()
    assert world.positions.get("BBB", D(0)) == 0
    assert world.positions.get("AAA", D(0)) == D(5)


@pytest.mark.parametrize("idle_seconds", [0, 3600], ids=["recent", "older-than-overlap"])
def test_zero_value_legacy_cursor_without_cash_row_is_accepted(conn, world, idle_seconds):
    activity_at = world.now - timedelta(seconds=idle_seconds)
    activity = broker_cash.BrokerCashActivity(
        activity_id="legacy-zero-split",
        activity_type="SPLIT",
        activity_date=activity_at.date(),
        net_amount=D(0),
        raw={"source": "legacy-rest"},
    )

    class LegacyZeroReplay:
        financial_activity_sse = False

        async def account_cash_activities(self, *, after, through):
            activities = (activity,) if after <= activity_at <= through else ()
            return broker_cash.BrokerCashActivityBatch(
                activities=activities,
                processed_through=through,
                completeness=Completeness.COMPLETE,
                last_activity_id=activity.activity_id if activities else None,
            )

    cursor = {
        "kind": "broker-cash-activity/v2",
        "broker": "alpaca",
        "account_id": DEPLOY.broker_account_id,
        "processed_through": world.now.isoformat(),
        "last_activity_id": activity.activity_id,
        "last_event_id": None,
        "balance_total": "0",
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
            (broker_cash._activity_cursor_name("alpaca", DEPLOY.broker_account_id),
             world.now.date().isoformat(), json.dumps(cursor, sort_keys=True)))
    conn.commit()
    world.advance(60)

    state = ingest(conn, world, adapter=LegacyZeroReplay())

    assert state.balance_total == 0
    assert state.last_activity_id is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_cash_flows WHERE flow_id LIKE %s",
            (f"{broker_cash.FLOW_PREFIX}alpaca:{DEPLOY.broker_account_id}:%",))
        assert int(cur.fetchone()[0]) == 0


def test_cash_cursor_total_detects_nonlast_ledger_loss(conn, world):
    first = world.cash_event("CSD", "1000", adversarial=True)
    world.cash_event("CSD", "500", adversarial=True)
    state = ingest(conn, world)
    assert state.balance_total == D("1500")

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sentinel_cash_flows WHERE flow_id=%s",
            (broker_cash.broker_flow_id(
                broker="alpaca", account_id=DEPLOY.broker_account_id,
                activity_id=first["ref_id"]),))
    conn.commit()
    world.advance(60)

    with pytest.raises(
            broker_cash.BrokerCashAuthorityRefused,
            match="ledger disagrees"):
        ingest(conn, world)
    conn.rollback()
