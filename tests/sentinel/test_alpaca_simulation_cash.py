"""Candidate Activity-SSE parsing and broker cash/P&L boundaries.

Direct candidate calls do not promote the adapter's production capabilities.
"""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel.execution import alpaca, broker_cash
from sentinel.execution.contract import Completeness
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, ExecutionBrokerGuard, GuardedExecutionBroker,
    ManualExecutionGrant,
)
from tests.support.alpaca_simulator import AlpacaSimulator, EPOCH, Profile
from test_alpaca_simulation_harness import run, submit


@pytest.fixture(params=list(Profile), ids=lambda p: p.value)
def world(request):
    w = AlpacaSimulator(request.param)
    yield w
    assert not w.faults


def batch(world, **kwargs):
    return run(world.adapter().account_cash_activities(
        after=EPOCH - timedelta(days=1), through=world.now, **kwargs))


def event(world, kind="CSD", amount="2500", **kwargs):
    return world.cash_event(kind, amount, adversarial=True, **kwargs)


def test_deposit_withdrawal_fees_and_dividends_have_distinct_attribution(world):
    event(world, "CSD", "10000")
    event(world, "CSW", "-3000")
    event(world, "JNLC", "500")
    event(world, "DIV", "25")
    event(world, "FEE", "-2")
    event(world, "INT", "1")
    observed = batch(world)
    assert observed.completeness is Completeness.COMPLETE
    external = sum((x.net_amount for x in observed.activities
                    if x.classification == "EXTERNAL"), D(0))
    assert external == D(7500)
    assert sum((x.net_amount for x in observed.activities), D(0)) == D(7524)
    assert world.cash == D(107524)
    assert world.adapter().financial_activity_sse is False
    world.assert_conservation()


def test_cash_event_published_late_is_seen_by_event_cursor(world):
    first = event(world)
    initial = batch(world)
    world.advance(86400)
    late = event(world, "CSW", "-700", at=EPOCH - timedelta(days=10))
    resumed = batch(world, since_event_id=initial.last_event_id)
    assert [x.activity_id for x in resumed.activities] == [late["ref_id"]]
    assert resumed.last_event_id > first["event_id"]
    queries = [r["params"] for r in world.requests
               if r["path"] == "/v2beta1/events/activities"]
    assert any(q.get("since_id") == initial.last_event_id for q in queries)
    assert batch(world, since_event_id=resumed.last_event_id).activities == ()


def test_trade_notional_is_not_booked_again_as_cash_flow(world):
    oid = submit(world).broker_order_id
    world.fill(oid, "4")
    world.fill(oid, "6")
    observed = batch(world)
    assert observed.activities == ()
    assert observed.last_event_id == world.events[-1]["event_id"]
    fills = run(world.adapter().recent_fills(EPOCH - timedelta(days=1)))
    assert len(fills) == 2
    assert sum((f.quantity * f.price for f in fills), D(0)) == D(1000)
    assert world.cash == D(99000)


@pytest.mark.parametrize("field,value", [
    ("account_id", "other-account"), ("ref_id", ""), ("event_id", ""),
    ("currency", "EUR"), ("currency", None), ("status", "pending"),
    ("status", None), ("details", []), ("at", "invalid"),
    ("at", "2026-09-09T14:00:00"), ("executed_at", None),
    ("settle_date", "09/09/2026"), ("net_amount", "NaN"),
    ("net_amount", "Infinity"), ("net_amount", None),
    ("activity_type", "NEW_UNKNOWN_CASH_TYPE"),
])
def test_malformed_or_nonfinal_cash_event_refuses_entire_batch(world, field, value):
    event(world)[field] = value
    world.reply("GET", "/v2beta1/events/activities",
                content=("data: " + json.dumps(world.events[0]) + "\n\n").encode())
    with pytest.raises(alpaca.MalformedBrokerPayload):
        batch(world)


@pytest.mark.parametrize("kind", ["CSD", "CSW", "JNLC", "JNL", "DIV", "FEE", "INT"])
def test_missing_cash_amount_is_not_an_ignorable_event(world, kind):
    row = event(world, kind)
    del row["net_amount"]
    with pytest.raises(alpaca.MalformedBrokerPayload, match="net_amount"):
        batch(world)


@pytest.mark.parametrize("kind", ["ACATS", "FOPT", "JNLS"])
def test_securities_transfers_refuse_until_in_kind_valuation_exists(world, kind):
    event(world, kind, "0")
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="securities transfer"):
        batch(world)


@pytest.mark.parametrize("fault", ["duplicate_event", "duplicate_ref", "reverse", "missing_cursor"])
def test_corrupt_stream_identity_and_order_never_advance_cursor(world, fault):
    event(world)
    initial = batch(world)
    event(world, "CSW", "-100")
    if fault == "duplicate_event":
        world.events.append(copy.deepcopy(world.events[0]))
    elif fault == "duplicate_ref":
        world.events[1]["ref_id"] = world.events[0]["ref_id"]
    elif fault == "reverse":
        world.events.reverse()
    else:
        world.events.clear()
    with pytest.raises(alpaca.MalformedBrokerPayload):
        batch(world, since_event_id=initial.last_event_id)


@pytest.mark.parametrize("kind", ["trade_correct", "trade_bust"])
def test_corrections_and_busts_are_refused_by_cash_and_fill_consumers(world, kind):
    oid = submit(world).broker_order_id
    row = world.fill(oid)
    row["details"]["execution_type"] = kind
    row["previous_id"] = "prior-native-id"
    with pytest.raises(alpaca.ActivityCorrectionRequiresRecovery):
        batch(world)
    with pytest.raises(alpaca.ActivityCorrectionRequiresRecovery):
        run(world.adapter().recent_fills(EPOCH - timedelta(days=1)))


def test_late_fill_after_terminal_order_aged_out_is_discovered(world):
    oid = submit(world).broker_order_id
    world.orders[oid]["submitted_at"] = (EPOCH - timedelta(days=30)).isoformat()
    run(world.adapter().cancel(oid))
    world.advance(5)
    world.fill(oid, "2", late=True)
    # The late report revises cumulative fills without reopening the order.
    # Its old submitted_at excludes it from the closed-order recovery window.
    world.orders[oid]["status"] = "canceled"
    observed = run(world.adapter().observe_with_terminal_recovery(
        submitted_after=EPOCH - timedelta(days=1), processed_through=EPOCH))
    assert observed.orders[0].broker_order_id == oid
    assert observed.orders[0].filled_quantity == D(2)
    assert observed.positions[0].quantity == D(2)
    assert observed.orders[0].state is alpaca.CommandState.CANCELLED
    assert world.counts[("GET", f"/v2/orders/{oid}")] == 1


def test_candidate_capabilities_are_refused_at_real_guard_before_http(world):
    async def noop(*args):
        return None
    guard = GuardedExecutionBroker(
        inner=world.adapter(),
        grant=ManualExecutionGrant("SIM-ALPACA-1", "plan", EPOCH.date(), True),
        guard=ExecutionBrokerGuard(noop, noop, noop))
    assert guard.supports_account_cash_activities is False
    assert guard.supports_account_close_valuation is False
    assert guard.supports_account_fill_interval_evidence is False
    with pytest.raises(AttributeError, match="does not expose"):
        run(guard.account_cash_activities(after=EPOCH - timedelta(days=1), through=EPOCH))
    assert world.requests == []
