"""Dated XNYS expectations independent of the simulator's session lookup."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from sentinel.execution.contract import Side
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant,
    PreTransportAuthorityRefused,
)
from sentinel.execution.states import CommandState as S
from tests.support.alpaca_simulator import AlpacaSimulator, Profile
from test_alpaca_simulation_harness import INSTRUMENT, run, submit


@pytest.fixture(params=list(Profile), ids=lambda profile: profile.value)
def world(request):
    simulated = AlpacaSimulator(request.param)
    yield simulated
    assert not simulated.faults


def at(world, stamp):
    target = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
    world.advance(int((target - world.now).total_seconds()))


@pytest.mark.parametrize("placed,opens,closes", [
    ("2026-09-09T14:00:00+00:00", "2026-09-09T13:30:00+00:00", "2026-09-09T20:00:00+00:00"),
    ("2026-11-02T14:30:00+00:00", "2026-11-02T14:30:00+00:00", "2026-11-02T21:00:00+00:00"),
    ("2026-11-27T14:30:00+00:00", "2026-11-27T14:30:00+00:00", "2026-11-27T18:00:00+00:00"),
    ("2026-09-11T20:00:00+00:00", "2026-09-14T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-11-25T21:00:00+00:00", "2026-11-27T14:30:00+00:00", "2026-11-27T18:00:00+00:00"),
    ("2026-09-12T14:00:00+00:00", "2026-09-14T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-09-14T12:00:00+00:00", "2026-09-14T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
], ids=["summer", "winter", "early-close", "weekend-queue", "holiday-queue",
        "saturday-queue", "preopen-queue"])
def test_day_order_preserves_partial_fill_until_eligible_session_close(
        world, placed, opens, closes):
    at(world, placed)
    opened, closed = datetime.fromisoformat(opens), datetime.fromisoformat(closes)
    outcome = submit(world)
    assert outcome.state is S.ACKNOWLEDGED
    order = world.orders[outcome.broker_order_id]
    assert order["status"] == ("accepted" if world.now < opened else "new")
    assert run(world.adapter().account_snapshot()).buying_power == D(99000)

    if world.now < opened:
        at(world, opened - timedelta(seconds=1))
        assert order["status"] == "accepted"
        with pytest.raises(ValueError, match="session"):
            world.fill(outcome.broker_order_id)
        at(world, opened)
        assert order["status"] == "new"

    at(world, closed - timedelta(seconds=1))
    assert order["status"] == "new"
    world.fill(outcome.broker_order_id, "4")
    at(world, closed)

    assert order["status"] == "expired"
    assert datetime.fromisoformat(order["updated_at"]) == closed
    assert D(order["filled_qty"]) == 4
    snapshot = run(world.adapter().account_snapshot())
    assert snapshot.buying_power == snapshot.cash == D(99600)
    recovered = run(world.adapter().find_by_client_key("key-1")).order
    assert recovered.state is S.CANCELLED
    assert recovered.filled_quantity == 4
    with pytest.raises(ValueError):
        world.fill(outcome.broker_order_id)
    world.assert_conservation()


@pytest.mark.parametrize("stamp,is_open,next_open,next_close", [
    ("2026-09-14T13:29:59+00:00", False, "2026-09-14T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-09-14T13:30:00+00:00", True, "2026-09-15T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-09-14T19:59:59+00:00", True, "2026-09-15T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-09-14T20:00:00+00:00", False, "2026-09-15T13:30:00+00:00", "2026-09-15T20:00:00+00:00"),
    ("2026-11-02T14:29:59+00:00", False, "2026-11-02T14:30:00+00:00", "2026-11-02T21:00:00+00:00"),
    ("2026-11-02T20:00:00+00:00", True, "2026-11-03T14:30:00+00:00", "2026-11-02T21:00:00+00:00"),
    ("2026-11-02T21:00:00+00:00", False, "2026-11-03T14:30:00+00:00", "2026-11-03T21:00:00+00:00"),
    ("2026-11-27T18:00:00+00:00", False, "2026-11-30T14:30:00+00:00", "2026-11-30T21:00:00+00:00"),
    ("2026-09-11T20:00:01+00:00", False, "2026-09-14T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-09-12T14:00:00+00:00", False, "2026-09-14T13:30:00+00:00", "2026-09-14T20:00:00+00:00"),
    ("2026-11-26T14:00:00+00:00", False, "2026-11-27T14:30:00+00:00", "2026-11-27T18:00:00+00:00"),
])
def test_clock_names_actual_future_session_boundaries(
        world, stamp, is_open, next_open, next_close):
    at(world, stamp)
    clock = run(world.adapter().market_clock())
    assert clock.timestamp == world.now
    assert clock.is_open is is_open
    assert clock.next_open == datetime.fromisoformat(next_open)
    assert clock.next_close == datetime.fromisoformat(next_close)
    assert clock.next_open > clock.timestamp
    assert clock.next_close > clock.timestamp


CLOSED_TIMES = [
    "2026-09-09T20:00:01+00:00",  # ordinary after-close
    "2026-09-12T14:00:00+00:00",  # Saturday
    "2026-11-26T14:00:00+00:00",  # Thanksgiving
    "2026-11-27T18:00:01+00:00",  # early close
    "2026-11-02T14:29:59+00:00",  # winter pre-open
]


@pytest.mark.parametrize("stamp", CLOSED_TIMES)
def test_closed_session_fill_cannot_change_broker_economics(world, stamp):
    at(world, stamp)
    outcome = submit(world)
    before = copy.deepcopy((world.account(), world.positions, world.orders, world.events))
    with pytest.raises(ValueError, match="session"):
        world.fill(outcome.broker_order_id)
    assert (world.account(), world.positions, world.orders, world.events) == before
    world.assert_conservation()


@pytest.mark.parametrize("stamp", CLOSED_TIMES)
def test_production_guard_refuses_closed_simulated_clock(world, stamp):
    at(world, stamp)

    async def noop(*args):
        return None

    broker = GuardedExecutionBroker(
        inner=world.adapter(),
        grant=ManualExecutionGrant(world.account_id, "closed-session", world.now.date(), True),
        guard=ExecutionBrokerGuard(noop, noop, noop))
    with pytest.raises(PreTransportAuthorityRefused, match="market closed"):
        run(broker.submit(client_key="closed-session", instrument=INSTRUMENT,
                          side=Side.BUY, quantity=D(10)))
    assert world.counts[("POST", "/v2/orders")] == 0
    assert world.orders == {}


def test_day_expiry_keeps_event_time_across_a_client_absence(world):
    order_id = submit(world).broker_order_id
    at(world, "2026-09-14T14:00:00+00:00")
    order = world.orders[order_id]
    assert order["status"] == "expired"
    assert order["updated_at"] == "2026-09-09T20:00:00+00:00"
    assert run(world.adapter().account_snapshot()).buying_power == D(100000)
    assert run(world.adapter().find_by_client_key("key-1")).order.state is S.CANCELLED


def test_explicit_late_report_survives_session_gate(world):
    order_id = submit(world).broker_order_id
    world.fill(order_id, "4")
    at(world, "2026-09-09T20:00:01+00:00")
    assert world.orders[order_id]["status"] == "expired"
    with pytest.raises(ValueError):
        world.fill(order_id, "1")
    world.fill(order_id, "1", late=True)
    assert D(world.orders[order_id]["filled_qty"]) == 5
    assert world.positions == {"AAA": D(5)}
    world.assert_conservation()
