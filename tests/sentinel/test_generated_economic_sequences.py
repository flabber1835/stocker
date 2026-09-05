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
from sentinel.execution import commands as command_rules  # noqa: E402
from sentinel.execution import executor, journal, reconcile, recovery  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity,
    BrokerInstrument,
    IncompleteObservation,
)
from sentinel.execution.identity import (  # noqa: E402
    CommandIdentity,
    DeploymentIdentity,
)
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import (  # noqa: E402
    BrokerUnavailable,
    FaultKind,
    SimulatedBroker,
)
from sentinel.execution.states import (  # noqa: E402
    CommandState,
    RuntimeState,
    blocks_overlapping,
)
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


def _restart_soak(dsn: str, seed: int, *, combined_faults: bool = False,
                  steps: int = 24) -> tuple:
    """Exercise the same durable book through repeated connection loss."""
    rng = random.Random(seed)
    conn = _new_connection(dsn)
    broker = SimulatedBroker(
        account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
        equity=INITIAL_EQUITY,
        cash=INITIAL_EQUITY,
    )
    try:
        for step in range(steps):
            desired = {
                security_id: D(rng.randrange(0, 61))
                for security_id in SECURITIES
            }
            plan = ExecutionPlan(
                plan_id=(f"combined-fi-{seed}-{step}" if combined_faults
                         else f"restart-soak-{seed}-{step}"),
                decision_session=DAY,
                effective_session=DAY,
                target_exposure=D("1"),
                target_basket=desired,
                data_version=1,
            )
            executor.adopt_plan(conn, plan)
            if combined_faults:
                # This schedule guarantees that every seed crosses every
                # supported submit ambiguity and observation-quality failure.
                # A queued submit fault survives an earlier observation outage
                # and is consumed by the next retry of the SAME durable plan.
                broker.schedule_submit((
                    FaultKind.ACCEPT_THEN_TIMEOUT,
                    FaultKind.NEVER_RECEIVED,
                    FaultKind.OUTAGE,
                    FaultKind.REJECT,
                )[step % 4])
                broker.schedule_observe((
                    FaultKind.OUTAGE,
                    FaultKind.TRUNCATED_ORDERS,
                    FaultKind.PARTIAL_OBSERVATION,
                )[step % 3])
            else:
                if step % 7 == 0:
                    broker.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)
                if step % 11 == 0:
                    broker.schedule_observe(FaultKind.OUTAGE)

            # A transport/read failure may leave durable uncertainty.  Every
            # retry begins with a fresh database connection, as a restarted
            # service would, and retains the same immutable plan identity.
            for _attempt in range(6 if combined_faults else 3):
                run(executor.execute_session(
                    broker=broker,
                    conn=conn,
                    deployment=DEPLOYMENT,
                    plan=plan,
                    instruments=INSTRUMENTS,
                    today=DAY,
                ))
                _assert_invariants(conn, broker)
                conn.close()
                conn = feed_store.connect(dsn)

            # A reduction can intentionally defer an increase until its sale
            # has settled.  Keep restarting and driving the SAME immutable
            # plan until both phases converge; otherwise the first post-sale
            # retry is legitimate work, not the durable no-op asserted below.
            for _settle_round in range(4):
                working = sorted(
                    (order for order in broker._orders.values()
                     if blocks_overlapping(order.state)),
                    key=lambda order: str(order.client_key),
                )
                for order in working:
                    if order.remaining > 1:
                        broker.fill(
                            order.client_key,
                            str(max(D(1), order.remaining // D(2))),
                        )
                        # Duplicate delivery and repeated observation must not
                        # change the economic ledger a second time.
                        fills = tuple(run(broker.recent_fills(broker.now)))
                        journal.record_fills(
                            conn, fills + tuple(reversed(fills)))
                        journal.record_fills(conn, tuple(reversed(fills)))
                        run(reconcile.reconcile(
                            broker=broker, conn=conn, binding=None,
                            deployment=DEPLOYMENT))
                        run(reconcile.reconcile(
                            broker=broker, conn=conn, binding=None,
                            deployment=DEPLOYMENT))
                        _assert_invariants(conn, broker)
                        conn.close()
                        conn = feed_store.connect(dsn)
                    broker.tick(1)
                    broker.fill(order.client_key)
                    run(reconcile.reconcile(
                        broker=broker, conn=conn, binding=None,
                        deployment=DEPLOYMENT))
                    _assert_invariants(conn, broker)

                conn.close()
                conn = feed_store.connect(dsn)
                resumed = run(executor.execute_session(
                    broker=broker,
                    conn=conn,
                    deployment=DEPLOYMENT,
                    plan=plan,
                    instruments=INSTRUMENTS,
                    today=DAY,
                ))
                _assert_invariants(conn, broker)
                if not resumed.submitted and not any(
                    blocks_overlapping(order.state)
                    for order in broker._orders.values()
                ):
                    break
            else:
                pytest.fail("immutable plan did not converge after four restarts")

            # A fully settled plan is a durable no-op after another restart.
            conn.close()
            conn = feed_store.connect(dsn)
            before = Counter(broker.calls)
            repeated = run(executor.execute_session(
                broker=broker,
                conn=conn,
                deployment=DEPLOYMENT,
                plan=plan,
                instruments=INSTRUMENTS,
                today=DAY,
            ))
            assert repeated.submitted == ()
            after = Counter(broker.calls)
            assert {
                key: value for key, value in after.items()
                if key.startswith("submit:")
            } == {
                key: value for key, value in before.items()
                if key.startswith("submit:")
            }
            _assert_invariants(conn, broker)
        return _ledger_digest(conn, broker)
    finally:
        conn.close()


@pytest.mark.parametrize("seed", range(4), ids=lambda seed: f"soak-{seed}")
def test_restart_soak_replays_duplicate_and_reordered_evidence_exactly(pg, seed):
    first = _restart_soak(pg.sync_dsn, seed)
    second = _restart_soak(pg.sync_dsn, seed)
    assert second == first


@pytest.mark.parametrize("seed", range(2), ids=lambda seed: f"combined-{seed}")
def test_combined_fault_injection_converges_and_replays_exactly(pg, seed):
    """Overlap every offline broker fault with reconnect/fill replay recovery."""
    first = _restart_soak(
        pg.sync_dsn, seed, combined_faults=True, steps=20)
    second = _restart_soak(
        pg.sync_dsn, seed, combined_faults=True, steps=20)
    assert second == first


def test_unknown_command_blocks_overlap_after_database_restart(pg):
    """Ambiguous transport cannot license a second order after restart."""
    conn = _new_connection(pg.sync_dsn)
    broker = SimulatedBroker(
        account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
        equity=INITIAL_EQUITY,
        cash=INITIAL_EQUITY,
    )
    try:
        observation = run(broker.observe())
        delta = command_rules.compute_delta(
            security_id="SEC-AAA", desired=D(10), observation=observation)
        command = command_rules.build(
            delta=delta,
            identity=CommandIdentity(
                deployment=DEPLOYMENT,
                plan_id="unknown-before-restart",
                security_id="SEC-AAA",
                revision=0,
            ),
            instrument=INSTRUMENTS["SEC-AAA"],
        )
        journal.save_command(conn, command)
        pending = command.transition(CommandState.SEND_PENDING)
        journal.save_command(conn, pending, previous=CommandState.PLANNED)
        unknown = pending.transition(
            CommandState.UNKNOWN, detail="injected ambiguous transport")
        journal.save_command(conn, unknown, previous=CommandState.SEND_PENDING)

        conn.close()
        conn = feed_store.connect(pg.sync_dsn)
        durable_open = journal.in_flight_commands(conn, DEPLOYMENT)
        assert [item.state for item in durable_open] == [CommandState.UNKNOWN]

        with pytest.raises(command_rules.CommandRefused, match="no overlapping"):
            command_rules.authorize(
                delta=delta,
                runtime=RuntimeState.RUNNING,
                binding=DEPLOYMENT,
                observed_account=broker.account,
                observation=observation,
                open_commands=durable_open,
            )
        assert len(journal.load_commands(conn, DEPLOYMENT)) == 1
        assert not broker._orders
    finally:
        conn.close()


def test_cancel_outage_ignored_cancel_and_fill_race_converge_after_restart(pg):
    """A cancel acknowledgement is not terminal evidence; a fill may win."""
    conn = _new_connection(pg.sync_dsn)
    broker = SimulatedBroker(
        account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
        equity=INITIAL_EQUITY,
        cash=INITIAL_EQUITY,
    )
    try:
        observation = run(broker.observe())
        delta = command_rules.compute_delta(
            security_id="SEC-AAA", desired=D(10), observation=observation)
        command = command_rules.build(
            delta=delta,
            identity=CommandIdentity(
                deployment=DEPLOYMENT,
                plan_id="cancel-fault-race",
                security_id="SEC-AAA",
                revision=0,
            ),
            instrument=INSTRUMENTS["SEC-AAA"],
        )
        journal.save_command(conn, command)
        pending = command.transition(CommandState.SEND_PENDING)
        journal.save_command(conn, pending, previous=command.state)
        acknowledged = run(recovery.dispatch(broker, pending))
        journal.save_command(conn, acknowledged, previous=pending.state)
        cancelling = acknowledged.transition(CommandState.CANCEL_PENDING)
        journal.save_command(conn, cancelling, previous=acknowledged.state)

        broker.schedule_cancel(FaultKind.OUTAGE)
        with pytest.raises(BrokerUnavailable):
            run(broker.cancel(cancelling.broker_order_id))
        broker.schedule_cancel(FaultKind.CANCEL_ACCEPTED_BUT_IGNORED)
        run(broker.cancel(cancelling.broker_order_id))

        broker.schedule_observe(FaultKind.TRUNCATED_ORDERS)
        with pytest.raises(IncompleteObservation):
            recovery.confirm_cancellation(cancelling, run(broker.observe()))
        assert journal.load_commands(conn, DEPLOYMENT)[0].state is CommandState.CANCEL_PENDING

        broker.fill(cancelling.client_key, "4")
        partial = recovery.confirm_cancellation(cancelling, run(broker.observe()))
        assert partial.state is CommandState.PARTIALLY_FILLED
        journal.save_command(conn, partial, previous=cancelling.state)

        cancelling_again = partial.transition(CommandState.CANCEL_PENDING)
        journal.save_command(conn, cancelling_again, previous=partial.state)
        broker.schedule_cancel(FaultKind.CANCEL_ACCEPTED_BUT_IGNORED)
        run(broker.cancel(cancelling_again.broker_order_id))
        broker.fill(cancelling_again.client_key)
        filled = recovery.confirm_cancellation(
            cancelling_again, run(broker.observe()))
        assert filled.state is CommandState.FILLED
        assert filled.filled_quantity == D(10)
        journal.save_command(conn, filled, previous=cancelling_again.state)

        conn.close()
        conn = feed_store.connect(pg.sync_dsn)
        restored = journal.load_commands(conn, DEPLOYMENT)
        assert [(item.state, item.filled_quantity) for item in restored] == [
            (CommandState.FILLED, D(10))]
        _assert_invariants(conn, broker)
    finally:
        conn.close()
