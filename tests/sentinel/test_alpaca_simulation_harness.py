"""Alpaca HTTP -> production adapter -> execution/recovery falsifiers."""
from __future__ import annotations

import asyncio
import copy
import json
import random
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from sentinel.execution import alpaca, recovery
from sentinel.config import LiveEndpointRefused
from sentinel.execution.commands import Command, compute_delta
from sentinel.execution.contract import BrokerInstrument, Completeness, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S
from sentinel.paper.inspection import _account_or_refuse
from sentinel.paper.model import PaperActivationRefused
from tests.support.alpaca_simulator import (
    ASSET_UUID, EPOCH, LIVE_URL, PAPER_URL, AlpacaSimulator, Profile,
)

INSTRUMENT = BrokerInstrument("SEC-AAA", "AAA", ASSET_UUID)
DEPLOY = DeploymentIdentity("alpaca-lab", "alpaca", "SIM-ALPACA-1", 1)


def run(coro):
    return asyncio.run(coro)


def command(key="plan-1", quantity="10", side=Side.BUY):
    return Command(identity=CommandIdentity(DEPLOY, key, "SEC-AAA", 0),
                   instrument=INSTRUMENT, side=side, quantity=D(quantity))


@pytest.fixture(params=list(Profile), ids=lambda p: p.value)
def world(request):
    world = AlpacaSimulator(request.param)
    yield world
    assert not world.faults, "scenario left a fault unexercised"


def submit(world, *, key="key-1", quantity="10", side=Side.BUY):
    return run(world.adapter().submit(client_key=key, instrument=INSTRUMENT,
                                     side=side, quantity=D(quantity)))


def test_happy_buy_partial_fill_sell_and_adapter_restart(world):
    outcome = submit(world)
    assert outcome.state is S.ACKNOWLEDGED
    world.fill(outcome.broker_order_id, "4", "100")
    observed = run(world.adapter().observe())
    assert observed.completeness is Completeness.COMPLETE
    assert observed.positions[0].quantity == D(4)
    assert observed.orders[0].filled_quantity == D(4)
    assert observed.orders[0].quantity - observed.orders[0].filled_quantity == D(6)
    world.fill(outcome.broker_order_id, "6", "105")
    found = run(world.adapter().find_by_client_key("key-1")).order
    assert (found.state, found.filled_quantity, found.filled_average_price) == \
        (S.FILLED, D(10), D(103))
    sell = submit(world, key="key-sell", side=Side.SELL)
    world.fill(sell.broker_order_id, price="110")
    assert run(world.adapter().observe()).positions == ()
    assert run(world.adapter().account_snapshot()).cash == D(100070)
    world.settle()
    world.assert_conservation()


@pytest.mark.parametrize("accepted", [False, True])
def test_lost_post_is_unknown_and_same_key_retry_never_duplicates(world, accepted):
    world.timeout(after_effect=accepted)
    cmd = run(recovery.dispatch(world.adapter(), recovery.prepare_send(command())))
    assert cmd.state is S.UNKNOWN
    assert len(world.orders) == int(accepted)
    if accepted:
        world.fill(next(iter(world.orders)))
    broker = world.adapter()  # all client process memory lost
    lookup = run(broker.find_by_client_key(cmd.client_key))
    assert (lookup.order is not None) == accepted
    retry = run(broker.submit(client_key=cmd.client_key, instrument=INSTRUMENT,
                             side=Side.BUY, quantity=D(10)))
    assert retry.state is (S.UNKNOWN if accepted else S.ACKNOWLEDGED)
    assert len(world.orders) == 1
    if not accepted:
        world.fill(next(iter(world.orders)))
    assert world.positions == {"AAA": D(10)}
    world.assert_conservation()


@pytest.mark.parametrize("status", [400, 404, 408, 409, 418, 429, 500, 502, 503, 504])
def test_error_after_acceptance_never_erases_broker_order(world, status):
    world.reply("POST", "/v2/orders", {"message": "intermediary failure"},
                status=status, after_effect=True)
    outcome = submit(world)
    assert outcome.state is S.UNKNOWN
    assert len(world.orders) == 1
    assert run(world.adapter().find_by_client_key("key-1")).order is not None


@pytest.mark.parametrize("status", [403, 422])
def test_documented_broker_reject_requires_origin_witness(world, status):
    world.reply("POST", "/v2/orders", {"message": "invalid quantity"},
                status=status, headers={"X-Request-ID": "sim-origin"})
    assert submit(world).state is S.REJECTED
    assert not world.orders


@pytest.mark.parametrize("body", [b"", b"{", b"<html>gateway</html>", b"\xff\xfe"])
def test_corrupt_post_body_preserves_unknown_and_positive_recovery(world, body):
    world.reply("POST", "/v2/orders", content=body, after_effect=True)
    assert submit(world).state is S.UNKNOWN
    assert run(world.adapter().find_by_client_key("key-1")).order.quantity == D(10)


@pytest.mark.parametrize("kind", ["ignore", "confirm", "fill"])
def test_cancel_acknowledgement_and_fill_races_use_observed_lifecycle(world, kind):
    order_id = submit(world).broker_order_id
    world.fill(order_id, "3")
    world.cancel_mode = kind
    assert run(world.adapter().cancel(order_id)).state is S.ACKNOWLEDGED
    found = run(world.adapter().find_by_client_key("key-1")).order
    assert found.state is {"ignore": S.PARTIALLY_FILLED,
                           "confirm": S.CANCELLED, "fill": S.FILLED}[kind]
    assert world.positions["AAA"] == D(10 if kind == "fill" else 3)
    world.assert_conservation()


def test_fill_between_order_and_position_reads_is_inconsistent_then_converges(world):
    order_id = submit(world).broker_order_id

    def fill_after_first_orders(w, request, response):
        w.fill(order_id)
        return response

    world.fault("GET", "/v2/orders", fill_after_first_orders, after_effect=True)
    assert run(world.adapter().observe()).completeness is Completeness.INCONSISTENT
    observed = run(world.adapter().observe())
    assert observed.completeness is Completeness.COMPLETE
    assert observed.positions[0].quantity == D(10)
    assert observed.orders == ()


def test_stale_position_endpoint_detects_cross_read_lag(world):
    order_id = submit(world).broker_order_id
    world.fill(order_id)
    world.reply("GET", "/v2/positions", [])
    assert run(world.adapter().observe()).completeness is Completeness.INCONSISTENT
    assert run(world.adapter().observe()).positions[0].quantity == D(10)


@pytest.mark.parametrize("phase", [1, 2, 3, 4, 5])
def test_account_flip_at_each_observation_bracket_refuses(world, phase):
    changed = world.account() | {"account_number": "OTHER-ACCOUNT"}
    world.reply("GET", "/v2/account", changed, occurrence=phase)
    with pytest.raises(alpaca.MalformedBrokerPayload, match="identity changed"):
        run(world.adapter().observe())
    assert not world.orders


@pytest.mark.parametrize("path,payload", [
    ("/v2/orders", {}), ("/v2/orders", [None]),
    ("/v2/positions", {}), ("/v2/positions", [False]),
    ("/v2/account", []), ("/v2/account", {}),
])
def test_malformed_collection_or_account_never_becomes_empty_authority(world, path, payload):
    world.reply("GET", path, payload)
    with pytest.raises(alpaca.MalformedBrokerPayload):
        run(world.adapter().observe())


@pytest.mark.parametrize("field,value", [
    ("cash", "NaN"), ("equity", "Infinity"), ("buying_power", "-Infinity"),
    ("cash", None), ("cash", "1\x00.00"), ("cash", "1,000"),
    ("trading_blocked", "false"), ("account_blocked", 0),
    ("trade_suspended_by_user", None), ("multiplier", "garbage"),
])
def test_corrupted_money_and_flags_are_refused(world, field, value):
    world.account_overrides[field] = value
    with pytest.raises(alpaca.MalformedBrokerPayload):
        run(world.adapter().account_snapshot())
    assert not world.orders


@pytest.mark.parametrize("change", [
    {"cash": "-1"}, {"equity": "0"}, {"buying_power": "99900"},
    {"buying_power": "200000"}, {"multiplier": "2"},
    {"status": "ACCOUNT_CLOSED"}, {"status": "ONBOARDING"},
    {"trading_blocked": True}, {"account_blocked": True},
    {"trade_suspended_by_user": True},
])
def test_account_risk_and_settlement_gates_refuse(world, change):
    world.account_overrides.update(change)
    snapshot = run(world.adapter().account_snapshot())
    with pytest.raises(PaperActivationRefused):
        _account_or_refuse(snapshot, SimpleNamespace(identity=DEPLOY), DEPLOY.broker_account_id)
    assert not world.orders


@pytest.mark.parametrize("field,value", [
    ("qty", "NaN"), ("qty", "0"), ("filled_qty", "11"),
    ("filled_qty", "-1"), ("filled_qty", "Infinity"),
    ("side", "BUY_OR_SELL"), ("status", "new-vendor-status"),
    ("id", ""),
])
def test_corrupt_order_payload_cannot_authorize_recovery(world, field, value):
    order_id = submit(world).broker_order_id
    row = copy.deepcopy(world.orders[order_id]) | {field: value}
    world.reply("GET", "/v2/orders", [row])
    with pytest.raises((alpaca.MalformedBrokerPayload, alpaca.UnmappedBrokerStatus, ValueError)):
        run(world.adapter().observe())


def test_duplicate_position_identity_is_not_summed(world):
    order_id = submit(world).broker_order_id
    world.fill(order_id)
    rows = world.position_rows()
    world.reply("GET", "/v2/positions", rows + rows)
    with pytest.raises(alpaca.MalformedBrokerPayload, match="repeats"):
        run(world.adapter().observe())


def test_tied_order_timestamps_page_by_native_id_and_hit_cap(world, monkeypatch):
    monkeypatch.setattr(alpaca, "PAGE_SIZE", 2)
    for i in range(5):
        assert submit(world, key=f"page-{i}", quantity="1").state is S.ACKNOWLEDGED
    observed = run(world.adapter().observe())
    assert observed.completeness is Completeness.COMPLETE
    assert len(observed.orders) == 5
    queries = [r["params"] for r in world.requests if r["path"] == "/v2/orders"]
    assert any("before_order_id" in q for q in queries)
    assert all("until" not in q for q in queries)
    monkeypatch.setattr(alpaca, "MAX_PAGES", 1)
    assert run(world.adapter().observe()).completeness is Completeness.TRUNCATED


def test_repeated_page_is_refused(world, monkeypatch):
    monkeypatch.setattr(alpaca, "PAGE_SIZE", 2)
    for i in range(3):
        submit(world, key=f"repeat-{i}", quantity="1")
    first = list(reversed(list(world.orders.values())))[:2]
    world.reply("GET", "/v2/orders", first, occurrence=2)
    with pytest.raises(alpaca.MalformedBrokerPayload, match="repeated"):
        run(world.adapter().observe())


def test_stable_asset_handle_is_used_at_post(world):
    outcome = submit(world)
    post = next(r for r in world.requests if r["method"] == "POST")
    assert post["body"]["symbol"] == ASSET_UUID
    assert world.orders[outcome.broker_order_id]["asset_id"] == ASSET_UUID


def test_wrong_asset_on_exact_lookup_cannot_recover_unknown(world):
    cmd = command()
    world.timeout(after_effect=True)
    unknown = run(recovery.dispatch(world.adapter(), recovery.prepare_send(cmd)))
    row = next(iter(world.orders.values())) | {"asset_id": "another-asset"}
    world.reply("GET", "/v2/orders:by_client_order_id", row)
    with pytest.raises(recovery.BrokerAuthorityRefused, match="broker_id"):
        run(recovery.resolve_unknown(world.adapter(), unknown, run(world.adapter().observe())))


@pytest.mark.parametrize("payload", [{}, [], False, 0, "", None])
def test_empty_successful_exact_lookup_is_corruption_not_absence(world, payload):
    world.timeout(after_effect=True)
    unknown = run(recovery.dispatch(world.adapter(), recovery.prepare_send(command())))
    # Simulate omission from the open snapshot plus a corrupted exact 200.
    world.reply("GET", "/v2/orders", [])
    world.reply("GET", "/v2/orders", [], occurrence=2)
    observation = run(world.adapter().observe())
    world.reply("GET", "/v2/orders:by_client_order_id", payload)
    with pytest.raises(alpaca.MalformedBrokerPayload):
        run(recovery.resolve_unknown(world.adapter(), unknown, observation))
    assert unknown.state is S.UNKNOWN
    assert len(world.orders) == 1


def test_missing_asset_cannot_recover_a_durable_command(world):
    world.timeout(after_effect=True)
    unknown = run(recovery.dispatch(world.adapter(), recovery.prepare_send(command())))
    row = next(iter(world.orders.values())) | {"asset_id": None}
    world.reply("GET", "/v2/orders:by_client_order_id", row)
    with pytest.raises(recovery.BrokerAuthorityRefused, match="broker_id"):
        run(recovery.resolve_unknown(world.adapter(), unknown, run(world.adapter().observe())))


def test_paper_and_live_cash_profiles_exercise_actual_economic_differences():
    results = {}
    for profile in Profile:
        w = AlpacaSimulator(profile)
        oid = submit(w).broker_order_id
        w.fill(oid, liquidity="3")
        w.cash_event("DIV", "5")
        w.cash_event("FEE", "-1")
        results[profile] = (w.positions["AAA"], w.cash, len(w.events))
        w.assert_conservation()
    assert results[Profile.PAPER] == (D(10), D(99000), 1)
    assert results[Profile.LIVE_CASH] == (D(3), D(99704), 3)


def test_live_cash_sale_proceeds_cannot_fund_buy_until_settlement():
    w = AlpacaSimulator(Profile.LIVE_CASH, cash="1000")
    w.fill(submit(w).broker_order_id)
    w.fill(submit(w, key="sell", side=Side.SELL).broker_order_id)
    assert submit(w, key="unsettled-buy").state is S.REJECTED
    snapshot = run(w.adapter().account_snapshot())
    with pytest.raises(PaperActivationRefused, match="buying power"):
        _account_or_refuse(snapshot, SimpleNamespace(identity=DEPLOY), DEPLOY.broker_account_id)
    w.settle()
    assert submit(w, key="settled-buy").state is S.ACKNOWLEDGED


def test_paper_replacement_requires_new_binding():
    w = AlpacaSimulator()
    w.replace_paper_account("50000")
    with pytest.raises(PaperActivationRefused, match="identity"):
        _account_or_refuse(run(w.adapter().account_snapshot()),
                           SimpleNamespace(identity=DEPLOY, broker="alpaca",
                                           broker_account_id=DEPLOY.broker_account_id),
                           DEPLOY.broker_account_id)


@pytest.mark.parametrize("url", [LIVE_URL, LIVE_URL + "/", "http://paper-api.alpaca.markets",
                                  PAPER_URL + ".example.com", "https://user@paper-api.alpaca.markets"])
def test_actual_live_or_untrusted_endpoint_is_refused_before_transport(url):
    def unexpected_http():
        pytest.fail("transport constructed for forbidden endpoint")
    with pytest.raises(LiveEndpointRefused):
        alpaca.AlpacaExecutionBroker(api_key="simulation-key", secret_key="simulation-secret",
                                    base_url=url, http_provider=unexpected_http)


def test_simulation_does_not_promote_unaccepted_production_capabilities(world):
    broker = world.adapter()
    assert broker.financial_activity_sse is False
    assert broker.account_snapshot_freshness is False
    assert broker.restore_grade_order_recovery is False
    assert broker.capabilities.complete_order_pagination is False
    assert broker.capabilities.recent_fill_history is False
    assert broker.previous_session_close_nas_accepted is False
    assert broker.account_fill_interval_nas_accepted is False


@pytest.mark.parametrize("seed", [7, 29, 181, 20260910])
def test_seeded_partial_fill_outage_retry_campaign(world, seed):
    rng = random.Random(seed)
    trace = []
    for i in range(30):
        qty = rng.randint(1, 12)
        accepted = rng.choice([False, True])
        world.timeout(after_effect=accepted)
        key = f"seed-{seed}-order-{i}"
        assert submit(world, key=key, quantity=str(qty)).state is S.UNKNOWN
        lookup = run(world.adapter().find_by_client_key(key))
        if lookup.order is None:
            outcome = submit(world, key=key, quantity=str(qty))
            oid = outcome.broker_order_id
        else:
            oid = lookup.order.broker_order_id
        remaining = qty
        while remaining:
            amount = rng.randint(1, remaining)
            price = rng.randint(80, 120)
            world.fill(oid, str(amount), str(price))
            trace.append((i, accepted, amount, price))
            remaining -= amount
            observed = run(world.adapter().find_by_client_key(key)).order
            assert observed.filled_quantity == D(qty - remaining), (seed, trace)
            world.assert_conservation()
        assert submit(world, key=key, quantity=str(qty)).state is S.UNKNOWN
        assert len(world.orders) == i + 1, (seed, trace)
        world.advance()
    assert len(world.orders) == 30
