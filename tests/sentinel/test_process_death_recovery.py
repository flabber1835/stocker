"""Real-process recovery at the two economic persistence boundaries.

These are deliberately Linux/PostgreSQL integration tests.  Exceptions exercise
rollback; SIGKILL proves that recovery does not depend on finally blocks,
in-memory broker objects, or an orderly connection close.
"""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import pickle
import signal
import sys
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
from sentinel.execution.simulator import SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402


D = Decimal
DAY = date(2026, 8, 11)
DEPLOYMENT = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAA", symbol="AAA", broker_id="sim-SEC-AAA")
INSTRUMENTS = {INSTRUMENT.security_id: INSTRUMENT}


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="process-death-plan",
        decision_session=DAY,
        effective_session=DAY,
        target_exposure=D("1"),
        target_basket={INSTRUMENT.security_id: D("100")},
        data_version=1,
    )


class _DurableProcessBroker(SimulatedBroker):
    """Simulator state shared outside the process that is about to die.

    The typed behavior remains the normal deterministic simulator.  Pickling
    its economic state into a multiprocessing-manager process models the fact
    that a broker survives the trading process.  Calls are serialized: this
    test is about restart ordering, not concurrent adapter access.
    """

    def __init__(self, shared, *, kill_after_accept: bool = False) -> None:
        super().__init__(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        self._shared = shared
        self._kill_after_accept = kill_after_accept
        if not hasattr(shared, "broker_state"):
            self._persist()
        else:
            self._reload()

    def _snapshot(self) -> bytes:
        return pickle.dumps({
            "orders": self._orders,
            "positions": self._positions,
            "fills": self._fills,
            "seq": self._seq,
            "cash": self.cash,
            "calls": self.calls,
        })

    def _persist(self) -> None:
        self._shared.broker_state = self._snapshot()

    def _reload(self) -> None:
        state = pickle.loads(self._shared.broker_state)
        self._orders = state["orders"]
        self._positions = state["positions"]
        self._fills = state["fills"]
        self._seq = state["seq"]
        self.cash = state["cash"]
        self.calls = state["calls"]

    async def observe(self):
        self._reload()
        value = await super().observe()
        self._persist()
        return value

    async def find_by_client_key(self, client_key):
        self._reload()
        value = await super().find_by_client_key(client_key)
        self._persist()
        return value

    async def submit(self, **kwargs):
        self._reload()
        value = await super().submit(**kwargs)
        self._persist()
        if self._kill_after_accept:
            os.kill(os.getpid(), signal.SIGKILL)
        return value

    async def recent_fills(self, since):
        self._reload()
        value = await super().recent_fills(since)
        self._persist()
        return value

    def fill(self, client_key: str, qty: str | None = None) -> None:
        self._reload()
        super().fill(client_key, qty)
        self._persist()


def _execute_then_die(dsn: str, shared) -> None:
    conn = feed_store.connect(dsn)
    broker = _DurableProcessBroker(shared, kill_after_accept=True)
    asyncio.run(executor.execute_session(
        broker=broker,
        conn=conn,
        deployment=DEPLOYMENT,
        plan=_plan(),
        instruments=INSTRUMENTS,
        today=DAY,
    ))
    os._exit(91)  # pragma: no cover - reaching this means the kill hook failed


def _observe_fill_then_die(dsn: str, shared) -> None:
    conn = feed_store.connect(dsn)
    broker = _DurableProcessBroker(shared)
    real_save = journal.save_command

    def kill_before_filled_persistence(conn_, command, *args, **kwargs):
        if command.state is CommandState.FILLED:
            os.kill(os.getpid(), signal.SIGKILL)
        return real_save(conn_, command, *args, **kwargs)

    journal.save_command = kill_before_filled_persistence
    asyncio.run(reconcile.reconcile(
        broker=broker,
        conn=conn,
        binding=None,
        deployment=DEPLOYMENT,
    ))
    os._exit(92)  # pragma: no cover - reaching this means the kill hook failed


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


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    drop_public_tables(connection)
    schema.ensure_schema(connection)
    feed_store.require_feed_schema(connection)
    binding.bind(
        connection,
        deployment_id=DEPLOYMENT.deployment_id,
        broker=DEPLOYMENT.broker,
        broker_account_id=DEPLOYMENT.broker_account_id,
    )
    executor.adopt_plan(connection, _plan())
    yield connection
    connection.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux SIGKILL test")
def test_process_death_recovers_one_order_and_one_fill_without_duplication(
        conn, pg):
    """Two hard deaths converge to one exact economic action.

    The first assertion is the write-order falsifier: if SEND_PENDING moves to
    after transport, the killed process leaves no command identity to recover.
    """
    context = multiprocessing.get_context("fork")
    with multiprocessing.Manager() as manager:
        shared = manager.Namespace()

        submitter = context.Process(
            target=_execute_then_die, args=(pg.sync_dsn, shared))
        submitter.start()
        submitter.join(timeout=20)
        assert not submitter.is_alive(), "submit process did not terminate"
        assert submitter.exitcode == -signal.SIGKILL

        commands = journal.load_commands(conn, DEPLOYMENT)
        assert len(commands) == 1
        command = commands[0]
        assert command.state is CommandState.SEND_PENDING

        restarted = _DurableProcessBroker(shared)
        resolved = asyncio.run(executor.resolve_outstanding(
            broker=restarted, conn=conn, deployment=DEPLOYMENT))
        assert len(resolved) == 1
        assert resolved[0].client_key == command.client_key
        assert resolved[0].state is CommandState.ACKNOWLEDGED

        before_retry = restarted.calls.count(f"submit:{command.client_key}")
        retry = asyncio.run(executor.execute_session(
            broker=restarted,
            conn=conn,
            deployment=DEPLOYMENT,
            plan=_plan(),
            instruments=INSTRUMENTS,
            today=DAY,
        ))
        assert retry.submitted == ()
        restarted._reload()
        assert restarted.calls.count(
            f"submit:{command.client_key}") == before_retry

        restarted.fill(command.client_key)
        observer = context.Process(
            target=_observe_fill_then_die, args=(pg.sync_dsn, shared))
        observer.start()
        observer.join(timeout=20)
        assert not observer.is_alive(), "fill-observer process did not terminate"
        assert observer.exitcode == -signal.SIGKILL

        still_acknowledged = journal.load_commands(conn, DEPLOYMENT)[0]
        assert still_acknowledged.state is CommandState.ACKNOWLEDGED

        recovered = asyncio.run(reconcile.reconcile(
            broker=restarted,
            conn=conn,
            binding=None,
            deployment=DEPLOYMENT,
        ))
        final = journal.load_commands(conn, DEPLOYMENT)[0]
        assert final.state is CommandState.FILLED
        assert final.filled_quantity == D("100")
        assert recovered.observed == {INSTRUMENT.security_id: D("100")}

        restarted._reload()
        broker_orders = [
            order for order in restarted._orders.values()
            if order.client_key == command.client_key
        ]
        assert len(broker_orders) == 1
        assert len(restarted._fills) == 1

        final_retry = asyncio.run(executor.execute_session(
            broker=restarted,
            conn=conn,
            deployment=DEPLOYMENT,
            plan=_plan(),
            instruments=INSTRUMENTS,
            today=DAY,
        ))
        assert final_retry.submitted == ()
        restarted._reload()
        assert len(restarted._orders) == 1
        assert len(restarted._fills) == 1

