"""Real disabled-history Alpaca adapter -> native receipts -> push outbox."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
import json
from types import SimpleNamespace

import httpx
import pytest

from sentinel import binding, local_paper
from sentinel.automation import outbox
from sentinel.config import SentinelConfig
from sentinel.execution import fill_notifications as module, journal
from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, OrderTerms, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_operator_monitoring import issue369_pg
from tests.sentinel.test_notification_recovery import db, historical_db

NOW = datetime(2026, 10, 22, 14, tzinfo=timezone.utc)
SUBMITTED = NOW - timedelta(minutes=20)
FILLED = SUBMITTED + timedelta(minutes=1)
NATIVE_ACCOUNT = "11111111-1111-4111-8111-111111111111"
ORDER_ID = "22222222-2222-4222-8222-222222222222"
ASSET_ID = "33333333-3333-4333-8333-333333333333"


def fixture(db, monkeypatch, *, filled="2"):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PAfixture")
    monkeypatch.setenv(module.SINCE_ENV, NOW.replace(hour=4).isoformat())
    db.execute("UPDATE sentinel_notification_policy SET web_push_activated_at=%s",
               (NOW - timedelta(days=1),))
    db.commit()
    owner = binding.bind(db, deployment_id="notifications", broker="alpaca",
                         broker_account_id="PAfixture")
    terms = OrderTerms("limit", "day", D("101"))
    command = Command(CommandIdentity(owner.identity, "plan", "SEC-BIL"),
        BrokerInstrument("SEC-BIL", "BIL", ASSET_ID), Side.BUY, D("2"), order_terms=terms)
    journal.save_command(db, command)
    pending = command.transition(S.SEND_PENDING)
    journal.save_command(db, pending, previous=S.PLANNED)
    ack = pending.transition(S.ACKNOWLEDGED, broker_order_id=ORDER_ID)
    journal.save_command(db, ack, previous=S.SEND_PENDING)
    progress = replace(ack, state=S.FILLED if filled == "2" else S.PARTIALLY_FILLED,
                       filled_quantity=D(filled), filled_average_price=D("100"))
    journal.save_command(db, progress, previous=S.ACKNOWLEDGED)
    db.execute("UPDATE sentinel_commands SET created_at=%s", (SUBMITTED,))
    db.commit()
    account = {"id": NATIVE_ACCOUNT, "account_number": "PAfixture"}
    order = dict(id=ORDER_ID, client_order_id=command.client_key, asset_id=ASSET_ID,
        symbol="BIL", side="buy", qty="2", filled_qty=filled, filled_avg_price="100",
        type="limit", time_in_force="day", limit_price="101", order_class="simple",
        extended_hours=False, status="filled" if filled == "2" else "partially_filled",
        submitted_at=SUBMITTED.isoformat(), filled_at=FILLED.isoformat() if filled == "2" else None)
    activities = [dict(id="20261022094100000::" + str(i), activity_type="FILL",
        order_id=ORDER_ID, transaction_time=FILLED.isoformat(), type="partial_fill",
        price="100", qty="1", side="buy", symbol="BIL") for i in range(1, int(filled)+1)]
    calls = []
    account_calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        if request.url.path == "/v2/account":
            account_calls.append(True)
            payload = account
        elif request.url.path == "/v2/orders/" + ORDER_ID:
            payload = order
        elif request.url.path == "/v2/account/activities/FILL":
            assert request.url.params["order_id"] == ORDER_ID
            payload = activities
        else:
            raise AssertionError(request.url)
        return httpx.Response(200, json=deepcopy(payload))
    provider = SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), **kw))
    broker = AlpacaExecutionBroker(api_key="fixture-key", secret_key="fixture-secret",
        base_url="https://paper-api.alpaca.markets", http_provider=lambda: provider)
    config = SentinelConfig.from_env({"ALPACA_BASE_URL": "https://paper-api.alpaca.markets"})
    assert broker.capabilities.recent_fill_history is False
    return SimpleNamespace(command=command, order=order, account=account,
        activities=activities, calls=calls, account_calls=account_calls,
        broker=broker, config=config)


def collect(db, f):
    return asyncio.run(module.collect(db, config=f.config, reader=f.broker, now=NOW))


def test_native_partial_fills_notify_once_across_restart_without_financial_authority(db, monkeypatch):
    f = fixture(db, monkeypatch)
    before = db.execute("SELECT client_key,state,filled_quantity,order_terms FROM sentinel_commands").fetchall()
    assert collect(db, f) == 2
    rows = db.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchall()
    assert len(rows) == 2 and all(p[0]["notification_only"] for p in rows)
    assert {p[0]["quantity"] for p in rows} == {"1"}
    assert {p[0]["price"] for p in rows} == {"100"}
    assert db.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0
    assert db.execute("SELECT client_key,state,filled_quantity,order_terms FROM sentinel_commands").fetchall() == before
    class Sender:
        def __init__(self): self.keys = []
        def deliver(self, alert, key): self.keys.append(key)
    sender = Sender()
    for _ in range(2):
        assert asyncio.run(outbox.dispatch_once(db, adapter=sender, holder_id="fixture")).delivered
    assert len(set(sender.keys)) == 2
    calls = len(f.calls)
    assert collect(db, f) == 0
    assert len(f.calls) == calls  # Covered terminal fills require no broker polling.
    assert not asyncio.run(outbox.dispatch_once(db, adapter=sender, holder_id="restart")).delivered


def test_delayed_native_activity_retries_and_partial_progress_adds_only_new_execution(db, monkeypatch):
    f = fixture(db, monkeypatch, filled="1")
    saved = deepcopy(f.activities)
    f.activities.clear()
    assert collect(db, f) == 0
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0
    f.activities[:] = saved
    assert collect(db, f) == 1
    db.execute("UPDATE sentinel_commands SET filled_quantity=2,state='FILLED'")
    db.commit()
    f.order.update(filled_qty="2", status="filled", filled_at=FILLED.isoformat())
    f.activities.append(dict(saved[0], id=saved[0]["id"] + "-next"))
    assert collect(db, f) == 2
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0] == 2


@pytest.mark.parametrize("fault", ["account", "client", "asset", "side", "terms", "replacement",
    "activity_order", "activity_side", "quantity", "price", "future", "duplicate", "correction"])
def test_wrong_identity_or_economics_never_notifies(db, monkeypatch, fault):
    f = fixture(db, monkeypatch)
    if fault == "account": f.account["account_number"] = "PAwrong"
    elif fault == "client": f.order["client_order_id"] = "sntl-wrong"
    elif fault == "asset": f.order["asset_id"] = NATIVE_ACCOUNT
    elif fault == "side": f.order["side"] = "sell"
    elif fault == "terms": f.order["limit_price"] = "102"
    elif fault == "replacement": f.order["replaces"] = NATIVE_ACCOUNT
    elif fault == "activity_order": f.activities[0]["order_id"] = NATIVE_ACCOUNT
    elif fault == "activity_side": f.activities[0]["side"] = "sell"
    elif fault == "quantity": f.activities[0]["qty"] = "3"
    elif fault == "price": f.activities[0]["price"] = "101"
    elif fault == "future": f.activities[0]["transaction_time"] = (NOW + timedelta(seconds=1)).isoformat()
    elif fault == "duplicate": f.activities.append(deepcopy(f.activities[0]))
    elif fault == "correction": f.activities[0]["type"] = "trade_bust"
    with pytest.raises((ValueError, RuntimeError)):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0


def test_unaccepted_history_flags_cannot_disable_positive_notifications(db, monkeypatch):
    f = fixture(db, monkeypatch)
    # Falsifier: restoring the former dependency on accepted history loses both fills.
    original = module._collect
    async def broken(conn, *, reader, **kw):
        if not reader.capabilities.recent_fill_history:
            return 0
        return await original(conn, reader=reader, **kw)
    monkeypatch.setattr(module, "_collect", broken)
    with pytest.raises(AssertionError):
        assert collect(db, f) == 2


def test_native_id_reused_across_commands_is_refused(db, monkeypatch):
    f = fixture(db, monkeypatch)
    native = f.activities[0]
    from sentinel.execution.alpaca import NativeBrokerFill
    key = journal.fill_fingerprint(NativeBrokerFill(None, ORDER_ID, D(1), D(100), FILLED,
        activity_id=native["id"]))
    outbox.enqueue(db, idempotency_key="previous-native", event_type="BROKER_FILL", severity="TRADE",
        payload=dict(client_key="other-command", fill_key=key, broker_order_id="other-order",
                     quantity="1", price="100", filled_at=FILLED.isoformat()))
    with pytest.raises(module.FillNotificationRefused, match="NATIVE_FILL_ID_REUSED"):
        collect(db, f)
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 1


def test_account_identity_flip_after_native_read_is_refused(db, monkeypatch):
    f = fixture(db, monkeypatch)
    original = f.broker.identify_account
    calls = []
    async def identify():
        value = await original()
        calls.append(True)
        return replace(value, account_id="PAwrong") if len(calls) > 1 else value
    monkeypatch.setattr(f.broker, "identify_account", identify)
    with pytest.raises(module.FillNotificationRefused, match="BROKER_ACCOUNT_CHANGED"):
        collect(db, f)
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


def test_network_stall_has_fixed_deadline_and_no_partial_publication(db, monkeypatch):
    f = fixture(db, monkeypatch)
    async def stalled():
        await asyncio.Event().wait()
    monkeypatch.setattr(f.broker, "identify_account", stalled)
    monkeypatch.setattr(module, "DEADLINE_SECONDS", .02)
    with pytest.raises(TimeoutError):
        collect(db, f)
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


def test_collection_is_explicit_and_cannot_run_in_normal_mode(db, monkeypatch):
    f = fixture(db, monkeypatch)
    monkeypatch.delenv(module.SINCE_ENV)
    assert collect(db, f) == 0 and f.calls == []
    monkeypatch.setenv(module.SINCE_ENV, NOW.replace(hour=4).isoformat())
    monkeypatch.delenv(local_paper.MODE_ENV)
    with pytest.raises(module.FillNotificationRefused, match="LOCAL_PAPER_REQUIRED"):
        collect(db, f)
    assert f.calls == []


def test_removed_command_identity_guard_is_detected(db, monkeypatch):
    text = inspect.getsource(module._check_order)
    guard = 'if any(order.get(k) != v for k, v in expected.items()):'
    assert guard in text
    namespace = {}
    exec(compile(text.replace(guard, 'if False:'), 'removed-order-identity', 'exec'),
         module.__dict__, namespace)
    monkeypatch.setattr(module, "_check_order", namespace["_check_order"])
    with pytest.raises(pytest.fail.Exception):
        test_wrong_identity_or_economics_never_notifies(db, monkeypatch, "asset")


@pytest.mark.parametrize("activity_fraction,accepted", [("229501", True), ("229502", True), ("229503", False)])
def test_native_nanosecond_order_and_rounded_microsecond_activity(db, monkeypatch, activity_fraction, accepted):
    f = fixture(db, monkeypatch)
    native = "2026-10-22T13:45:17.229501912Z"
    f.order["filled_at"] = native
    for activity in f.activities:
        activity["transaction_time"] = "2026-10-22T13:45:17." + activity_fraction + "Z"
    if accepted:
        assert collect(db, f) == 2
        rows = db.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchall()
        assert len(rows) == 2 and all(p[0]["native_order_filled_at"] == native for p in rows)
        assert f.order["filled_at"] == native
    else:
        with pytest.raises(module.FillNotificationRefused, match="FILL_FOLLOWS_ORDER_FILL"):
            collect(db, f)
        assert db.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


def test_microsecond_order_time_does_not_get_a_tolerance(db, monkeypatch):
    f = fixture(db, monkeypatch)
    f.activities[0]["transaction_time"] = (FILLED + timedelta(microseconds=1)).isoformat()
    with pytest.raises(module.FillNotificationRefused, match="FILL_FOLLOWS_ORDER_FILL"):
        collect(db, f)
