"""Real adapter GETs refresh display evidence without financial authority."""
import asyncio
from copy import deepcopy
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from sentinel import binding, local_paper
from sentinel.config import SentinelConfig, LiveEndpointRefused
from sentinel.execution import account_status as module, journal
from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, OrderTerms, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.states import CommandState as S
from sentinel.panel import sources, model
from tests.sentinel.test_operator_monitoring import db, issue369_pg

NATIVE = "11111111-1111-4111-8111-111111111111"


def fixture(db, monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PAfixture")
    binding.bind(db, deployment_id="account-display", broker="alpaca",
                 broker_account_id="PAfixture")
    account = dict(id=NATIVE, account_number="PAfixture", currency="USD",
        equity="50000", cash="10000", buying_power="8959.27", multiplier="1",
        status="ACTIVE", trading_blocked=False, account_blocked=False,
        trade_suspended_by_user=False)
    calls = []
    change = []
    orders = []
    account_calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        assert db.info.transaction_status.name == "IDLE"
        if request.url.path == "/v2/orders":
            assert request.url.params["status"] == "open"
            return httpx.Response(200, json=deepcopy(orders))
        assert request.url.path == "/v2/account"
        account_calls.append(True)
        payload = deepcopy(account)
        if len(account_calls) % 2 == 0 and change:
            payload.update(change[0])
        return httpx.Response(200, json=payload)
    provider = SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), **kw))
    reader = AlpacaExecutionBroker(api_key="fixture", secret_key="fixture",
        base_url="https://paper-api.alpaca.markets", http_provider=lambda: provider)
    config = SentinelConfig.from_env({})
    return SimpleNamespace(account=account, calls=calls, change=change,
                           orders=orders, reader=reader, config=config)


def collect(db, f):
    return asyncio.run(module.collect(db, config=f.config, reader=f.reader))


def test_real_gets_refresh_only_append_only_panel_evidence(db, monkeypatch):
    f = fixture(db, monkeypatch)
    assert collect(db, f) is True
    first = sources._latest_account_evidence(db)
    assert first["account_id"] == "PAfixture" and first["cash"] == 10000
    assert first["buying_power"].as_tuple().exponent == -2
    db.rollback()
    assert collect(db, f) is True
    last = sources._latest_account_evidence(db)
    assert last["observed_at"] > first["observed_at"]
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 2
    for table in ("sentinel_commands", "sentinel_fills", "sentinel_observations", "sentinel_execution_plans"):
        assert db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
    assert len(f.calls) == 4


@pytest.mark.parametrize("field,value", [
    ("account_number", "PAforeign"), ("id", "not-a-uuid"),
    ("currency", "EUR"), ("currency", None), ("cash", "NaN"),
    ("equity", None), ("status", ""), ("trading_blocked", "false"),
])
def test_invalid_or_foreign_account_does_not_refresh_evidence(db, monkeypatch, field, value):
    f = fixture(db, monkeypatch)
    assert collect(db, f)
    retained = db.execute("SELECT seq,observed_at FROM sentinel_broker_account_evidence").fetchall()
    db.rollback()
    f.account[field] = value
    with pytest.raises((ValueError, RuntimeError)):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT seq,observed_at FROM sentinel_broker_account_evidence").fetchall() == retained


@pytest.mark.parametrize("change", [
    {"account_number": "PAforeign"}, {"id": "22222222-2222-4222-8222-222222222222"},
    {"currency": "EUR"},
])
def test_native_account_must_match_across_reads(db, monkeypatch, change):
    f = fixture(db, monkeypatch)
    f.change.append(change)
    with pytest.raises((ValueError, RuntimeError)):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 0


def test_binding_rechecked_after_network_reads(db, monkeypatch):
    f = fixture(db, monkeypatch)
    original = module._bound
    count = 0
    def changed(conn):
        nonlocal count
        count += 1
        result = original(conn)
        return result if count == 1 else (*result[:3], result[3]+1)
    monkeypatch.setattr(module, "_bound", changed)
    with pytest.raises(module.AccountStatusRefused, match="DURABLE_BINDING_CHANGED"):
        collect(db, f)
    db.rollback()
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 0


def test_disabled_local_mode_and_live_endpoint_never_poll(db, monkeypatch):
    f = fixture(db, monkeypatch)
    monkeypatch.delenv(local_paper.MODE_ENV)
    assert collect(db, f) is False and not f.calls
    from dataclasses import replace
    f.config = replace(f.config, base_url="https://api.alpaca.markets")
    with pytest.raises(LiveEndpointRefused):
        collect(db, f)
    assert not f.calls


def test_blocked_and_negative_cash_are_visible_facts_not_permission(db, monkeypatch):
    f = fixture(db, monkeypatch)
    f.account.update(cash="-1", trading_blocked=True)
    assert collect(db, f)
    actual = sources._latest_account_evidence(db)
    assert actual["cash"] == -1 and actual["flags"]["trading_blocked"] is True


def test_network_deadline_is_bounded_and_leaves_no_new_evidence(db, monkeypatch):
    f = fixture(db, monkeypatch)
    async def hanging():
        await asyncio.sleep(30)
    monkeypatch.setattr(f.reader, "account_snapshot", hanging)
    monkeypatch.setattr(module, "DEADLINE_SECONDS", .02)
    with pytest.raises(TimeoutError):
        collect(db, f)
    assert db.info.transaction_status.name == "IDLE"
    assert db.execute("SELECT count(*) FROM sentinel_broker_account_evidence").fetchone()[0] == 0


def test_account_identity_guard_falsifier_is_detected(db, monkeypatch):
    source = inspect.getsource(module._collect)
    needle = "    _inspection_account_or_refuse(snapshot, bound[2])"
    last = "    _inspection_account_or_refuse(last, bound[2])"
    assert source.count(needle) == source.count(last) == 1
    namespace = {}
    exec(compile(source.replace(needle, "    pass").replace(last, "    pass"), "<removed-account-identity-guard>", "exec"),
         module._collect.__globals__, namespace)
    monkeypatch.setattr(module, "_collect", namespace["_collect"])
    with pytest.raises(pytest.fail.Exception):
        test_invalid_or_foreign_account_does_not_refresh_evidence(
            db, monkeypatch, "account_number", "PAforeign")


NOW = datetime(2026, 10, 22, 18, 30, tzinfo=timezone.utc)
ASSET = "33333333-3333-4333-8333-333333333333"
ORDER = "22222222-2222-4222-8222-222222222222"


def resting(db, f):
    owner = binding.require(db)
    command = Command(CommandIdentity(owner.identity, "plan", "SEC-PANW"),
        BrokerInstrument("SEC-PANW", "PANW", ASSET), Side.BUY, D(3),
        order_terms=OrderTerms("limit", "day", D("346.91")))
    journal.save_command(db, command)
    sent = command.transition(S.SEND_PENDING)
    journal.save_command(db, sent, previous=S.PLANNED)
    ack = sent.transition(S.ACKNOWLEDGED, broker_order_id=ORDER)
    journal.save_command(db, ack, previous=S.SEND_PENDING)
    db.commit()
    f.orders.append(dict(id=ORDER, client_order_id=command.client_key, asset_id=ASSET,
        symbol="PANW", side="buy", qty="3", filled_qty="0", status="new",
        submitted_at=NOW.isoformat(), type="limit", time_in_force="day", limit_price="346.91",
        order_class="simple", extended_hours=False))
    return ack


def observed(db):
    actual = sources._latest_account_evidence(db)
    actual["observed_at"] = NOW
    return actual


def account_row(account, proof):
    return model.alpaca_account_row(available=True, expected_account_id="PAfixture",
        matched_operator_reservation=(proof or {}).get("reserved_cash"), **account)


def test_exact_native_resting_hold_explains_cash_for_display_only(db, monkeypatch):
    f = fixture(db, monkeypatch)
    command = resting(db, f)
    assert collect(db, f)
    account = observed(db)
    proof = module.recorded_reservation(db, account=account, now=NOW)
    assert proof["reserved_cash"] == "1040.73"
    row = account_row(account, proof)
    assert row.effective_status(NOW) == model.OK
    assert "freshly matched native LIMIT/DAY buys" in row.detail
    assert row.effective_status(NOW+timedelta(minutes=11)) == model.FAIL
    assert account_row(account, None).effective_status(NOW) == model.FAIL
    retained = journal.load_commands(db, binding.require(db).identity)[0]
    assert module._fact(retained) == module._fact(command)
    assert db.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM sentinel_observations").fetchone()[0] == 0
    monkeypatch.delenv(local_paper.MODE_ENV)
    assert module.recorded_reservation(db, account=account, now=NOW) is None


@pytest.mark.parametrize("field,value", [
    ("id", NATIVE), ("client_order_id", "other"), ("asset_id", NATIVE),
    ("side", "sell"), ("qty", "4"), ("filled_qty", "1"),
    ("status", "canceled"), ("limit_price", "347"), ("time_in_force", "gtc"),
    ("replaces", NATIVE), ("legs", [{"id": "hidden-order"}]),
])
def test_changed_native_order_never_explains_cash(db, monkeypatch, field, value):
    f = fixture(db, monkeypatch)
    resting(db, f)
    f.orders[0][field] = value
    if field == "filled_qty":
        f.orders[0].update(filled_avg_price="346", status="partially_filled")
    collect(db, f)
    account = observed(db)
    assert module.recorded_reservation(db, account=account, now=NOW) is None
    assert account_row(account, None).effective_status(NOW) == model.FAIL


def test_foreign_orders_account_change_and_journal_changes_remove_display_proof(db, monkeypatch):
    f = fixture(db, monkeypatch)
    resting(db, f)
    f.orders.append(dict(f.orders[0], id=NATIVE, client_order_id="foreign"))
    assert collect(db, f)
    assert module.RESERVATION_FLAG not in observed(db)["flags"]
    db.rollback()
    f.orders.pop()
    f.change.append({"cash": "10001"})
    assert collect(db, f)
    assert module.RESERVATION_FLAG not in observed(db)["flags"]
    db.rollback()
    f.change.clear()
    assert collect(db, f)
    account = observed(db)
    assert module.recorded_reservation(db, account=account, now=NOW)
    db.execute("UPDATE sentinel_commands SET state='UNKNOWN'")
    assert module.recorded_reservation(db, account=account, now=NOW) is None


def test_display_match_cannot_hide_invalid_account_economics_or_escape_session(db, monkeypatch):
    f = fixture(db, monkeypatch)
    resting(db, f)
    assert collect(db, f)
    account = observed(db)
    proof = module.recorded_reservation(db, account=account, now=NOW)
    for changes in ({"cash": -1}, {"multiplier": 2}, {"buying_power": -1},
            {"equity": 0}, {"status": "REJECTED"}, {"flags": {"trading_blocked": True}}):
        assert account_row({**account, **changes}, proof).effective_status(NOW) == model.FAIL
    for when in (NOW-timedelta(seconds=1), NOW.replace(hour=21), NOW+timedelta(days=1)):
        assert module.recorded_reservation(db, account=account, now=when) is None
    account["flags"][module.RESERVATION_FLAG]["binding"][-1] += 1
    assert module.recorded_reservation(db, account=account, now=NOW) is None


def test_native_identity_guard_falsifier_is_detected(db, monkeypatch):
    source = inspect.getsource(module._native_orders)
    needle = "return native if native == commands else None"
    assert source.count(needle) == 1
    namespace = {}
    # Mutant substitutes journal intent for native proof even after a mismatch.
    exec(compile(source.replace(needle, "return commands"), "<removed-native-order-match>", "exec"),
         module._native_orders.__globals__, namespace)
    monkeypatch.setattr(module, "_native_orders", namespace["_native_orders"])
    with pytest.raises(AssertionError):
        test_changed_native_order_never_explains_cash(db, monkeypatch, "id", NATIVE)
