"""Reproducible generated sequences through executor, broker and journal.

This is property testing without sampled nondeterminism: every campaign seed is
part of the test id and a repeated run must produce the identical economic
ledger.  A failure is therefore a replayable scenario, not a flaky anecdote.
"""
from __future__ import annotations

import asyncio
import random
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres, drop_public_tables  # noqa: E402

from sentinel import binding, schema  # noqa: E402
from sentinel.execution import executor, journal, reconcile  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity,
    BrokerInstrument,
)
from sentinel.execution.identity import DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import (  # noqa: E402
    FaultKind,
    SimulatedBroker,
)
from sentinel.execution.states import CommandState, blocks_overlapping  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402


D = Decimal
DAY = date(2026, 8, 11)
DEPLOYMENT = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
SECURITIES = tuple(f"SEC-{name}" for name in ("AAA", "BBB", "CCC"))
INSTRUMENTS = {
    security_id: BrokerInstrument(
        security_id=security_id,
        symbol=security_id.removeprefix("SEC-"),
        broker_id=f"sim-{security_id}",
    )
    for security_id in SECURITIES
}
INITIAL_EQUITY = D("100000")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


def _new_connection(dsn):
    conn = feed_store.connect(dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    feed_store.require_feed_schema(conn)
    binding.bind(
        conn,
        deployment_id=DEPLOYMENT.deployment_id,
        broker=DEPLOYMENT.broker,
        broker_account_id=DEPLOYMENT.broker_account_id,
    )
    return conn


def _assert_invariants(conn, broker: SimulatedBroker) -> None:
    commands = journal.load_commands(conn, DEPLOYMENT)
    commands_by_key = {command.client_key: command for command in commands}
    assert len(commands_by_key) == len(commands), "client keys must be unique"

    orders_by_key = {
        order.client_key: order for order in broker._orders.values()
        if order.client_key is not None
    }
    assert len(orders_by_key) == len([
        order for order in broker._orders.values()
        if order.client_key is not None
    ]), "one client key created more than one broker order"
    assert set(orders_by_key) <= set(commands_by_key), (
        "a broker order has no durable authorized origin")

    fills_per_key = Counter(fill.client_key for fill in broker._fills)
    for fill in broker._fills:
        assert fill.client_key in commands_by_key
        assert fill.broker_order_id in broker._orders
        assert broker._orders[fill.broker_order_id].client_key == fill.client_key
        assert fill.quantity > 0 and fill.price > 0

    for command in commands:
        assert command.quantity > 0
        assert D(0) <= command.filled_quantity <= command.quantity
        if command.state is CommandState.FILLED:
            assert command.filled_quantity == command.quantity
        if command.client_key in fills_per_key:
            broker_filled = sum(
                fill.quantity for fill in broker._fills
                if fill.client_key == command.client_key
            )
            assert broker_filled <= command.quantity

    held_value = D(0)
    for _instrument, quantity in broker._positions.values():
        assert quantity >= 0, "long-only positions cannot become negative"
        held_value += quantity * D("100")
    assert broker.cash >= 0
    assert broker.cash + held_value == INITIAL_EQUITY

    submit_counts = Counter(
        call.removeprefix("submit:") for call in broker.calls
        if call.startswith("submit:")
    )
    assert all(count == 1 for count in submit_counts.values()), (
        "an economic identity was submitted more than once")


def _settle_all(conn, broker: SimulatedBroker, rng: random.Random) -> None:
    working = [
        order for order in broker._orders.values()
        if blocks_overlapping(order.state)
    ]
    for order in working:
        if order.remaining > 1 and rng.randrange(2) == 0:
            partial = max(D(1), order.remaining // D(2))
            broker.fill(order.client_key, str(partial))
            run(reconcile.reconcile(
                broker=broker,
                conn=conn,
                binding=None,
                deployment=DEPLOYMENT,
            ))
            _assert_invariants(conn, broker)
        broker.fill(order.client_key)
        run(reconcile.reconcile(
            broker=broker,
            conn=conn,
            binding=None,
            deployment=DEPLOYMENT,
        ))
        _assert_invariants(conn, broker)


def _ledger_digest(conn, broker: SimulatedBroker) -> tuple:
    commands = tuple(sorted(
        (
            command.client_key,
            command.security_id,
            command.side.value,
            str(command.quantity),
            str(command.filled_quantity),
            command.state.value,
        )
        for command in journal.load_commands(conn, DEPLOYMENT)
    ))
    orders = tuple(sorted(
        (
            order.client_key,
            order.instrument.security_id,
            order.side.value,
            str(order.quantity),
            str(order.filled),
            order.state.value,
        )
        for order in broker._orders.values()
    ))
    positions = tuple(sorted(
        (security_id, str(quantity))
        for security_id, (_instrument, quantity) in broker._positions.items()
    ))
    fills = tuple(
        (fill.client_key, str(fill.quantity), str(fill.price))
        for fill in broker._fills
    )
    return commands, orders, positions, fills, str(broker.cash)


def _campaign(dsn: str, seed: int) -> tuple:
    rng = random.Random(seed)
    conn = _new_connection(dsn)
    broker = SimulatedBroker(
        account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
        equity=INITIAL_EQUITY,
        cash=INITIAL_EQUITY,
    )
    try:
        for step in range(10):
            desired = {
                security_id: D(rng.randrange(0, 81))
                for security_id in SECURITIES
            }
            plan = ExecutionPlan(
                plan_id=f"generated-{seed}-{step}",
                decision_session=DAY,
                effective_session=DAY,
                target_exposure=D("1"),
                target_basket=desired,
                data_version=1,
            )
            executor.adopt_plan(conn, plan)

            observe_roll = rng.randrange(12)
            if observe_roll == 0:
                broker.schedule_observe(FaultKind.OUTAGE)

            submit_roll = rng.randrange(10)
            if submit_roll == 0:
                broker.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)
            elif submit_roll == 1:
                broker.schedule_submit(FaultKind.REJECT)

            run(executor.execute_session(
                broker=broker,
                conn=conn,
                deployment=DEPLOYMENT,
                plan=plan,
                instruments=INSTRUMENTS,
                today=DAY,
            ))
            _assert_invariants(conn, broker)
            _settle_all(conn, broker, rng)

        _settle_all(conn, broker, rng)
        return _ledger_digest(conn, broker)
    finally:
        conn.close()


@pytest.mark.parametrize("seed", range(8), ids=lambda seed: f"seed-{seed}")
def test_generated_failures_preserve_invariants_and_replay_exactly(pg, seed):
    first = _campaign(pg.sync_dsn, seed)
    second = _campaign(pg.sync_dsn, seed)
    assert second == first

