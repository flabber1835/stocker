"""Regressions for review-discovered Alpaca harness authority gaps."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import MagicMock

import pytest

from sentinel.execution import broker_cash, recovery
from sentinel.execution.contract import Completeness
from sentinel.execution.states import CommandState as S, blocks_overlapping
from tests.support.alpaca_simulator import AlpacaSimulator, EPOCH, Profile
from test_alpaca_simulation_harness import command, run, submit
from tools import sentinel_mutation_certify


@pytest.fixture(params=list(Profile), ids=lambda profile: profile.value)
def world(request):
    simulated = AlpacaSimulator(request.param)
    yield simulated
    assert not simulated.faults


def test_exact_404_cannot_cancel_order_present_in_complete_observation(world):
    world.timeout(after_effect=True)
    unknown = run(recovery.dispatch(
        world.adapter(), recovery.prepare_send(command())))
    assert unknown.state is S.UNKNOWN

    observation = run(world.adapter().observe())
    assert observation.by_client_key(unknown.client_key) is not None
    world.reply("GET", "/v2/orders:by_client_order_id", {}, status=404)

    resolved = run(recovery.resolve_unknown(
        world.adapter(), unknown, observation))
    assert resolved.state is S.ACKNOWLEDGED
    assert resolved.broker_order_id == next(iter(world.orders))
    assert next(iter(world.orders.values()))["status"] == "new"


@pytest.mark.parametrize("terminal", ["canceled", "filled"])
@pytest.mark.parametrize("exact_absent", [False, True], ids=["exact-positive", "exact-404"])
def test_unknown_pending_cancel_recovery_preserves_terminal_race(
        world, terminal, exact_absent):
    world.timeout(after_effect=True)
    unknown = run(recovery.dispatch(
        world.adapter(), recovery.prepare_send(command())))
    assert unknown.state is S.UNKNOWN
    order_id = next(iter(world.orders))

    # The original POST landed and a cancellation was initiated while Sentinel
    # still held only UNKNOWN evidence from the lost submit response.
    world.orders[order_id]["status"] = "pending_cancel"
    pending_observation = run(world.adapter().observe())
    if exact_absent:
        world.reply("GET", "/v2/orders:by_client_order_id", {}, status=404)
    pending = run(recovery.resolve_unknown(
        world.adapter(), unknown, pending_observation))

    assert pending.state is S.CANCEL_PENDING
    assert pending.broker_order_id == order_id
    assert pending.client_key == unknown.client_key
    assert pending.quantity == unknown.quantity
    assert blocks_overlapping(pending.state)
    assert world.counts[("POST", "/v2/orders")] == 1
    assert not any(method == "DELETE" for method, _ in world.counts)

    if terminal == "canceled":
        world.orders[order_id]["status"] = "canceled"
    else:
        world.fill(order_id)

    terminal_observation = run(world.adapter().observe_with_terminal_recovery(
        submitted_after=EPOCH - timedelta(days=1), processed_through=EPOCH))
    settled = recovery.confirm_cancellation(pending, terminal_observation)

    assert settled.state is (S.CANCELLED if terminal == "canceled" else S.FILLED)
    if terminal == "filled":
        assert settled.filled_quantity == D(10)


@pytest.mark.parametrize("profile", list(Profile), ids=lambda profile: profile.value)
def test_pending_buy_reduces_reported_buying_power(profile):
    world = AlpacaSimulator(profile, cash="10000")
    outcome = submit(world, key="reserve-3000", quantity="30")
    assert outcome.state is S.ACKNOWLEDGED

    snapshot = run(world.adapter().account_snapshot())
    assert snapshot.cash == D("10000")
    assert snapshot.buying_power == D("7000")


@pytest.mark.parametrize("profile", list(Profile), ids=lambda profile: profile.value)
def test_unfilled_day_order_expires_at_session_close(profile):
    world = AlpacaSimulator(profile, cash="10000")
    outcome = submit(world, key="day-order", quantity="30")
    assert outcome.state is S.ACKNOWLEDGED
    assert run(world.adapter().account_snapshot()).buying_power == D("7000")

    world.advance(6 * 60 * 60 + 1)

    assert world.orders[outcome.broker_order_id]["status"] == "expired"
    assert run(world.adapter().account_snapshot()).buying_power == D("10000")
    assert run(world.adapter().find_by_client_key("day-order")).order.state is S.CANCELLED


def test_pytest_setup_errors_cannot_count_as_mutant_kill(tmp_path):
    junit = tmp_path / "junit.xml"
    cases = "".join(
        '<testcase name="setup"><error message="PostgreSQL failed to start"/></testcase>'
        for _ in range(4))
    junit.write_text(
        f'<testsuite tests="4" failures="0" errors="4">{cases}</testsuite>',
        encoding="utf-8")

    killed, counts = sentinel_mutation_certify._mutation_verdict(1, junit)

    assert counts["failures"] == 0
    assert counts["errors"] == 4
    assert killed is False


@pytest.mark.parametrize("financial_sse", [False, True], ids=["legacy-rest", "sse"])
@pytest.mark.parametrize("advance_seconds", [0, 60], ids=["same-time", "later"])
def test_old_zero_cursor_replays_owned_interval(
        monkeypatch, financial_sse, advance_seconds):
    established = EPOCH - timedelta(days=1)
    activity_at = EPOCH - timedelta(hours=1)
    activity = broker_cash.BrokerCashActivity(
        activity_id="old-zero-split", activity_type="SPLIT",
        activity_date=activity_at.date(), net_amount=D(0), raw={})
    prior = broker_cash.CashActivityState(
        broker="alpaca", account_id="old-zero-account", processed_through=EPOCH,
        last_activity_id=activity.activity_id, balance_total=D(0),
        last_event_id="event-100" if financial_sse else None,
        activity_identity_scheme=(
            broker_cash.ACTIVITY_IDENTITY_SCHEME if financial_sse else None))
    monkeypatch.setattr(broker_cash, "load_activity_state", lambda *a, **kw: prior)
    monkeypatch.setattr(
        broker_cash, "_binding_established_at", lambda *a, **kw: established)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (D(0), False)
    calls = []

    class BoundedReplay:
        async def account_cash_activities(self, *, after, through, since_event_id=None):
            calls.append((after, through, since_event_id))
            visible = after <= activity_at <= through and since_event_id is None
            return broker_cash.BrokerCashActivityBatch(
                activities=(activity,) if visible else (),
                processed_through=through, completeness=Completeness.COMPLETE,
                last_activity_id=activity.activity_id if visible else None,
                last_event_id="event-100" if financial_sse else None)

    adapter = BoundedReplay()
    adapter.financial_activity_sse = financial_sse
    upper = EPOCH + timedelta(seconds=advance_seconds)
    state = run(broker_cash.ingest_account_cash(
        conn, broker_adapter=adapter, broker="alpaca", account_id=prior.account_id,
        through=upper))

    assert calls == [(established, upper, None)]
    assert state.balance_total == 0
    assert state.last_activity_id is None
    assert state.last_event_id == prior.last_event_id
    assert state.activity_identity_scheme == prior.activity_identity_scheme

    monkeypatch.setattr(broker_cash, "load_activity_state", lambda *a, **kw: state)
    next_upper = upper + timedelta(seconds=60)
    run(broker_cash.ingest_account_cash(
        conn, broker_adapter=adapter, broker="alpaca", account_id=prior.account_id,
        through=next_upper))
    expected_after = established if financial_sse else upper - timedelta(minutes=5)
    assert calls[-1] == (expected_after, next_upper, prior.last_event_id)
