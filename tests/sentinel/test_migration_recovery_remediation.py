"""Focused falsifiers for durable administrative liquidation recovery."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import binding, handover, schema  # noqa: E402
from sentinel.broker import (  # noqa: E402
    AdministrativeObservationRefused, AlpacaSentinelBroker, CloseResult,
    SentinelBroker)
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.commands import (  # noqa: E402
    LEGACY_MIGRATION_PLAN_PREFIX, Command)
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, CommandOutcome, Side)
from sentinel.execution.identity import (  # noqa: E402
    CommandIdentity, DeploymentIdentity)
from sentinel.execution.states import CommandState  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402
from sentinel.ownership import AccountObservation, OpenOrder  # noqa: E402
from sentinel.startup import OwnershipNotEstablished  # noqa: E402
from stock_strategy_shared.broker.base import (  # noqa: E402
    AccountSnapshot, BrokerPosition)


def run(coro):
    return asyncio.run(coro)


async def no_sleep(_seconds):
    return None


def test_untyped_adapter_error_is_unknown_never_rejected():
    class LegacyTripleAdapter:
        name = "sim"

        async def submit_order(self, _payload):
            return None, None, "503 upstream response was lost"

    identity = DeploymentIdentity("nas-1", "sim", "ACC-123", 1)
    command = Command(
        identity=CommandIdentity(
            deployment=identity,
            plan_id=(f"{LEGACY_MIGRATION_PLAN_PREFIX}sim:ACC-123"),
            security_id="legacy:sim:asset-aapl", revision=0),
        instrument=BrokerInstrument(
            security_id="legacy:sim:asset-aapl", symbol="AAPL",
            broker_id="asset-aapl"),
        side=Side.SELL, quantity=Decimal("10"))

    outcome = run(AlpacaSentinelBroker(
        LegacyTripleAdapter()).submit_liquidation(command))

    assert outcome.state is CommandState.UNKNOWN


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
        for table in (
                "sentinel_account_binding", "sentinel_ownership_events",
                "sentinel_commands", "sentinel_command_events",
                "sentinel_execution_plans", "sentinel_fills",
                "sentinel_observations",
                "sentinel_terminal_recovery_watermark"):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    connection.commit()
    schema.ensure_schema(connection)
    yield connection
    connection.close()


class AcceptedThenHiddenBroker(SentinelBroker):
    """Accepts a SELL, times out, then delays both visibility surfaces."""

    adapter = type("Adapter", (), {"name": "sim"})()

    def __init__(self):
        self.position = Decimal("10")
        self.command = None
        self.working = None
        self.observations = 0
        self.exact_lookups = 0
        self.submits = 0
        self.native_closes = 0

    async def account(self):
        return BrokerAccountIdentity("sim", "ACC-123")

    async def observe(self):
        self.observations += 1
        if self.command is not None and self.observations >= 4:
            self.working = replace(
                self.working, state=CommandState.FILLED,
                filled_quantity=self.working.quantity,
                filled_average_price=Decimal("100"))
        # The exact order endpoint exposes FILLED one complete observation
        # before the positions endpoint catches up. A second SELL in this gap
        # would create a short position.
        if self.command is not None and self.observations >= 5:
            self.position = Decimal(0)
        visible = (
            (self.working,) if self.command is not None
            and self.observations == 3 else ())
        return AccountObservation(
            positions=({"AAPL": self.position} if self.position else {}),
            position_security_ids=({"AAPL": "asset-aapl"}
                                   if self.position else {}),
            open_orders=visible)

    async def cancel_orders(self, _order_ids):
        raise AssertionError("fixture begins with no inherited open orders")

    async def close_position(self, _ticker):
        self.native_closes += 1
        return CloseResult("AAPL", None, None, "must not be called")

    async def submit_liquidation(self, command):
        self.submits += 1
        self.command = command
        self.working = OpenOrder(
            order_id="broker-sell-1", ticker="AAPL", side="sell",
            client_key=command.client_key,
            state=CommandState.ACKNOWLEDGED,
            quantity=command.quantity, filled_quantity=Decimal(0),
            broker_instrument_id="asset-aapl")
        # The broker accepted the order, but the response never reached us.
        raise TimeoutError("accepted, response lost")

    async def find_liquidation(self, client_key):
        if self.command is None:
            # A durable PLANNED crash remnant may be checked defensively before
            # it is resumed. There is no broker receipt yet.
            return None
        assert client_key == self.command.client_key
        self.exact_lookups += 1
        # First exact lookup shares the broker's visibility lag. It must not
        # free the key for a second SELL. The later lookup is positive terminal
    # evidence. The position surface deliberately lags that terminal result;
    # durable FILLED authority must prevent a duplicate SELL in the gap.
        if self.exact_lookups == 1:
            return None
        return self.working


def test_short_inherited_position_refuses_full_migration_before_mutation(conn):
    class ShortPositionAdapter:
        name = "sim"

        def __init__(self):
            self.mutations = 0

        async def get_account(self):
            return AccountSnapshot(
                equity=None, buying_power=None, cash=None,
                raw={"id": "ACC-123"})

        async def list_orders(self, *, status="open", limit=500):
            assert status == "open"
            assert limit == 500
            return []

        async def get_positions(self):
            return [BrokerPosition(
                ticker="AAPL", qty=Decimal("10"), side="short",
                broker_instrument_id="asset-aapl")]

        async def cancel_order(self, _order_id):
            self.mutations += 1
            raise AssertionError("short position authorized cancellation")

        async def submit_order(self, _payload):
            self.mutations += 1
            raise AssertionError("short position authorized another SELL")

    adapter = ShortPositionAdapter()
    with pytest.raises(AdministrativeObservationRefused, match="long positions"):
        run(handover.migrate_account(
            broker=AlpacaSentinelBroker(adapter), conn=conn,
            deployment_id="nas-1", expected_account="ACC-123",
            max_cycles=2, poll_seconds=0, sleep=no_sleep))

    assert adapter.mutations == 0
    assert binding.load(conn) is None


def test_accept_timeout_visibility_lag_survives_restart_without_duplicate(conn):
    broker = AcceptedThenHiddenBroker()
    identity = DeploymentIdentity("nas-1", "sim", "ACC-123", 1)

    # Simulate a process death after the first durable boundary but before
    # SEND_PENDING. The explicit rerun must resume this exact promise/key.
    planned = Command(
        identity=CommandIdentity(
            deployment=identity,
            plan_id=(f"{LEGACY_MIGRATION_PLAN_PREFIX}sim:ACC-123"),
            security_id="legacy:sim:asset-aapl", revision=0),
        instrument=BrokerInstrument(
            security_id="legacy:sim:asset-aapl", symbol="AAPL",
            broker_id="asset-aapl"),
        side=Side.SELL, quantity=Decimal("10"),
        detail="legacy account liquidation")
    journal.save_command(conn, planned)

    # First invocation dies at a durable boundary after the accepted POST. The
    # command remains UNKNOWN while the account is deliberately still unbound.
    with pytest.raises(OwnershipNotEstablished):
        run(handover.migrate_account(
            broker=broker, conn=conn, deployment_id="nas-1",
            expected_account="ACC-123", max_cycles=1,
            poll_seconds=0, sleep=no_sleep))
    command = journal.load_commands(conn, identity)[0]
    assert command.client_key == planned.client_key
    assert command.state is CommandState.UNKNOWN
    assert broker.submits == 1
    assert binding.load(conn) is None

    # A fresh explicit invocation sees one complete read plus exact absence,
    # keeps UNKNOWN, then sees positive evidence and converges. It never calls
    # broker-native close and never mints a second order identity.
    result = run(handover.migrate_account(
        broker=broker, conn=conn, deployment_id="nas-1",
        expected_account="ACC-123", max_cycles=8,
        poll_seconds=0, sleep=no_sleep))

    assert result.binding.is_owned
    assert broker.submits == 1
    assert broker.native_closes == 0
    assert broker.exact_lookups == 2
    stored = journal.load_commands(conn, result.binding.identity)
    assert len(stored) == 1
    assert stored[0].client_key == command.client_key
    assert stored[0].state is CommandState.FILLED
    assert stored[0].filled_quantity == Decimal("10")
    assert [event["to"] for event in journal.command_history(
            conn, command.client_key)] == [
        "PLANNED", "SEND_PENDING", "UNKNOWN", "UNKNOWN",
        "ACKNOWLEDGED", "FILLED"]
