"""Regressions for review-discovered Alpaca harness authority gaps."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel.execution import recovery
from sentinel.execution.states import CommandState as S
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
def test_unknown_pending_cancel_recovery_preserves_terminal_race(world, terminal):
    world.timeout(after_effect=True)
    unknown = run(recovery.dispatch(
        world.adapter(), recovery.prepare_send(command())))
    assert unknown.state is S.UNKNOWN
    order_id = next(iter(world.orders))

    # The original POST landed and a cancellation was initiated while Sentinel
    # still held only UNKNOWN evidence from the lost submit response.
    world.orders[order_id]["status"] = "pending_cancel"
    pending_observation = run(world.adapter().observe())
    pending = run(recovery.resolve_unknown(
        world.adapter(), unknown, pending_observation))

    assert pending.state is S.CANCEL_PENDING
    assert pending.broker_order_id == order_id

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
