"""Adversarial acceptance tests for issue #183."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel.core import cashflow
from sentinel.execution import broker_cash, recovery
from sentinel.execution.alpaca import (
    AlpacaCredentialsRefused, AlpacaExecutionBroker, AlpacaMarketClock,
    MalformedBrokerPayload)
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerInstrument, BrokerObservation, BrokerOrder, CommandOutcome,
    Completeness, Side)
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, ExecutionBrokerGuard, GuardedExecutionBroker,
    ManualExecutionGrant, PreTransportAuthorityRefused)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S

UTC = timezone.utc
PAPER = "https://paper-api.alpaca.markets"
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAPL", symbol="AAPL", broker_id="asset-aapl")
DEPLOYMENT = DeploymentIdentity("test", "alpaca", "PA-1", 1)


def run(coro):
    return asyncio.run(coro)


class Response:
    def __init__(self, payload=None, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            exc = RuntimeError(f"HTTP {self.status_code}")
            exc.response = self
            raise exc


class Httpx:
    def __init__(self, *, post=None, routes=None):
        self.post_result = post
        self.routes = routes or {}
        self.calls = []
        outer = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, url, headers=None, json=None):
                outer.calls.append(("POST", url, json))
                if isinstance(outer.post_result, Exception):
                    raise outer.post_result
                return outer.post_result

            async def get(self, url, headers=None, params=None):
                path = "/v2" + url.split("/v2", 1)[1]
                params = dict(params or {})
                outer.calls.append(("GET", path, params))
                result = outer.routes.get(path)
                if callable(result):
                    result = result(params)
                if isinstance(result, Response):
                    return result
                return Response(result if result is not None else [])

        self.AsyncClient = Client


def adapter(*, post=None, routes=None):
    http = Httpx(post=post, routes=routes)
    broker = AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
        http_provider=lambda: http)
    return broker, http


def full_order(*, status="new", quantity="2", filled="0", **changes):
    payload = {
        "id": "order-1",
        "client_order_id": "key-1",
        "symbol": "AAPL",
        "asset_id": "asset-aapl",
        "side": "buy",
        "status": status,
        "qty": quantity,
        "filled_qty": filled,
        "filled_avg_price": "101.25" if Decimal(filled) else None,
        "submitted_at": "2026-08-18T17:00:00Z",
        "type": "market",
        "order_type": "market",
        "time_in_force": "day",
        "order_class": "simple",
        "extended_hours": False,
    }
    payload.update(changes)
    return payload


def submit(response: Response):
    broker, http = adapter(post=response)
    outcome = run(broker.submit(
        client_key="key-1", instrument=INSTRUMENT,
        side=Side.BUY, quantity=Decimal(2)))
    return outcome, http


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_transport_or_service_status_is_unknown_not_rejected(status):
    outcome, _ = submit(Response(status_code=status, text="service condition"))
    assert outcome.state is S.UNKNOWN


@pytest.mark.parametrize("status", [401, 403])
def test_credentials_or_authority_status_is_typed_not_economic(status):
    broker, _ = adapter(post=Response(status_code=status, text="denied"))
    with pytest.raises(AlpacaCredentialsRefused):
        run(broker.submit(
            client_key="key-1", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal(2)))


@pytest.mark.parametrize("status", [400, 409, 422])
def test_definite_validation_4xx_is_rejected(status):
    outcome, _ = submit(Response(status_code=status, text="invalid quantity"))
    assert outcome.state is S.REJECTED


def test_duplicate_client_key_422_is_unknown_until_exact_lookup():
    outcome, _ = submit(Response(
        status_code=422, text="client_order_id must be unique"))
    assert outcome.state is S.UNKNOWN


@pytest.mark.parametrize("status,filled", [
    ("new", "0"), ("accepted", "0"),
    ("partially_filled", "1"), ("filled", "2")])
def test_fast_fill_post_is_only_acknowledgement(status, filled):
    outcome, _ = submit(Response(full_order(status=status, filled=filled), 200))
    assert outcome.state is S.ACKNOWLEDGED
    assert outcome.broker_order_id == "order-1"


@pytest.mark.parametrize("field,value", [
    ("client_order_id", "another-key"),
    ("side", "sell"),
    ("qty", "3"),
    ("symbol", "MSFT"),
    ("asset_id", "another-asset"),
    ("type", "limit"),
    ("time_in_force", "gtc"),
    ("order_class", "bracket"),
    ("extended_hours", True),
])
def test_success_response_contradiction_fails_closed(field, value):
    broker, _ = adapter(post=Response(full_order(**{field: value}), 200))
    with pytest.raises(MalformedBrokerPayload):
        run(broker.submit(
            client_key="key-1", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal(2)))


def test_incomplete_2xx_is_unknown_not_acknowledged():
    outcome, _ = submit(Response({"id": "order-1", "status": "new"}, 200))
    assert outcome.state is S.UNKNOWN
    assert outcome.broker_order_id == "order-1"


def test_429_that_actually_landed_resolves_by_same_key_without_second_post():
    exact = full_order()
    broker, http = adapter(
        post=Response(status_code=429, text="rate limited"),
        routes={"/v2/orders:by_client_order_id": exact})
    identity = CommandIdentity(
        deployment=DEPLOYMENT, plan_id="plan-1", security_id="SEC-AAPL")
    command = Command(
        identity=identity, instrument=INSTRUMENT, side=Side.BUY,
        quantity=Decimal(2), state=S.SEND_PENDING)
    # Exact lookup payload must carry the actual durable client key.
    exact["client_order_id"] = command.client_key

    uncertain = run(recovery.dispatch(broker, command))
    assert uncertain.state is S.UNKNOWN
    observation = BrokerObservation(
        observed_at=datetime.now(UTC), orders=(), positions=(),
        completeness=Completeness.COMPLETE)
    resolved = run(recovery.resolve_unknown(broker, uncertain, observation))

    assert resolved.state is S.ACKNOWLEDGED
    assert len([call for call in http.calls if call[0] == "POST"]) == 1


def test_exact_key_recovery_refuses_changed_economics():
    identity = CommandIdentity(
        deployment=DEPLOYMENT, plan_id="plan-2", security_id="SEC-AAPL")
    command = Command(
        identity=identity, instrument=INSTRUMENT, side=Side.BUY,
        quantity=Decimal(2), state=S.UNKNOWN)
    found = BrokerOrder(
        broker_order_id="order-x", client_key=command.client_key,
        instrument=INSTRUMENT, side=Side.BUY, state=S.ACKNOWLEDGED,
        quantity=Decimal(3), filled_quantity=Decimal(0))

    class Broker:
        async def find_by_client_key(self, _key):
            return found

    observation = BrokerObservation(
        observed_at=datetime.now(UTC), orders=(), positions=(),
        completeness=Completeness.COMPLETE)
    with pytest.raises(BrokerAuthorityRefused, match="contradictory economics"):
        run(recovery.resolve_unknown(Broker(), command, observation))


def activity(aid, activity_type, amount):
    return {
        "id": aid, "activity_type": activity_type,
        "date": "2026-08-18", "net_amount": str(amount)}


def test_account_activity_pagination_uses_native_page_token(monkeypatch):
    from sentinel.execution import alpaca as alpaca_module
    monkeypatch.setattr(alpaca_module, "ACTIVITY_PAGE_SIZE", 2)
    seen = []

    def pages(params):
        seen.append(dict(params))
        if params.get("page_token") == "a-2":
            return [activity("a-3", "DIV", "5")]
        return [activity("a-1", "CSD", "100"),
                activity("a-2", "FEE", "-1")]

    broker, _ = adapter(routes={"/v2/account/activities": pages})
    lower = datetime(2026, 8, 18, 16, tzinfo=UTC)
    upper = datetime(2026, 8, 18, 18, tzinfo=UTC)
    batch = run(broker.account_cash_activities(after=lower, through=upper))

    assert batch.completeness is Completeness.COMPLETE
    assert [row.activity_id for row in batch.activities] == ["a-1", "a-2", "a-3"]
    assert seen[1]["page_token"] == "a-2"
    assert all(call["direction"] == "asc" for call in seen)


class MemoryConnection:
    """Minimal transactional surface for broker_cash's durable invariants."""

    def __init__(self):
        self.binding = (
            "alpaca", "PA-1", datetime(2026, 8, 18, 15, tzinfo=UTC))
        self.cash_flows = {}
        self.cursors = {}

    def cursor(self):
        return MemoryCursor(self)


class MemoryCursor:
    def __init__(self, conn):
        self.conn = conn
        self.one = None
        self.all = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        pass

    def execute(self, sql, params=()):
        q = " ".join(sql.lower().split())
        self.one = None
        self.all = []
        if q.startswith("select state from sentinel_processed_sessions"):
            row = self.conn.cursors.get(params[0])
            self.one = None if row is None else (row[1],)
            return
        if q.startswith("select session,state from sentinel_processed_sessions"):
            self.one = self.conn.cursors.get(params[0])
            return
        if q.startswith("select broker,broker_account_id,established_at"):
            self.one = self.conn.binding
            return
        if q.startswith("select count(*) from sentinel_cash_flows"):
            prefix = params[0][:-1]
            count = sum(fid.startswith(prefix) for fid in self.conn.cash_flows)
            self.one = (count,)
            return
        if q.startswith("insert into sentinel_cash_flows"):
            fid, session, amount, detail = params
            if fid not in self.conn.cash_flows:
                self.conn.cash_flows[fid] = (
                    str(session), Decimal(str(amount)), str(detail))
                self.one = (fid,)
            return
        if q.startswith("select session,amount,detail from sentinel_cash_flows"):
            self.one = self.conn.cash_flows.get(params[0])
            return
        if q.startswith("insert into sentinel_processed_sessions"):
            name, session, state = params
            self.conn.cursors[name] = (date.fromisoformat(str(session)), state)
            return
        if q.startswith("select flow_id, session, amount, detail, recorded_at"):
            start, end = map(str, params)
            self.all = [
                (fid, date.fromisoformat(session), amount, detail, None)
                for fid, (session, amount, detail) in sorted(
                    self.conn.cash_flows.items())
                if start <= session <= end]
            return
        raise AssertionError(f"unexpected SQL in issue-183 fake: {q}")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return list(self.all)


class CashActivityBroker:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = []

    async def account_cash_activities(self, *, after, through):
        self.calls.append((after, through))
        return broker_cash.BrokerCashActivityBatch(
            activities=self.rows, processed_through=through,
            completeness=Completeness.COMPLETE,
            last_activity_id=(self.rows[-1].activity_id if self.rows else None))


def cash_activity(aid, kind, amount):
    return broker_cash.BrokerCashActivity(
        activity_id=aid, activity_type=kind,
        activity_date=date(2026, 8, 18), net_amount=Decimal(amount), raw={})


def test_cash_activity_restart_overlap_is_idempotent_and_pnl_classified():
    conn = MemoryConnection()
    rows = [cash_activity("deposit-1", "CSD", "100"),
            cash_activity("fee-1", "FEE", "-10")]
    broker = CashActivityBroker(rows)
    first_through = datetime(2026, 8, 18, 18, tzinfo=UTC)
    second_through = first_through + timedelta(hours=1)

    first = run(broker_cash.ingest_account_cash(
        conn, broker_adapter=broker, broker="alpaca", account_id="PA-1",
        through=first_through))
    second = run(broker_cash.ingest_account_cash(
        conn, broker_adapter=broker, broker="alpaca", account_id="PA-1",
        through=second_through))

    assert first.balance_total == second.balance_total == Decimal(90)
    assert len(conn.cash_flows) == 2
    assert broker.calls[1][0] == first_through - broker_cash.ACTIVITY_OVERLAP
    # The deposit is external capital; the fee remains strategy economics.
    assert cashflow.net_external(
        conn, date(2026, 8, 18), date(2026, 8, 18)) == Decimal(100)


def test_replayed_native_activity_id_cannot_change_economics():
    conn = MemoryConnection()
    through = datetime(2026, 8, 18, 18, tzinfo=UTC)
    run(broker_cash.ingest_account_cash(
        conn, broker_adapter=CashActivityBroker([
            cash_activity("deposit-1", "CSD", "100")]),
        broker="alpaca", account_id="PA-1", through=through))

    with pytest.raises(
            broker_cash.BrokerCashAuthorityRefused, match="changed economics"):
        run(broker_cash.ingest_account_cash(
            conn, broker_adapter=CashActivityBroker([
                cash_activity("deposit-1", "CSD", "101")]),
            broker="alpaca", account_id="PA-1",
            through=through + timedelta(hours=1)))


class ClockBroker:
    capabilities = AlpacaExecutionBroker.capabilities

    def __init__(self, *, is_open=True, clock_error=None):
        self.is_open = is_open
        self.clock_error = clock_error
        self.submits = 0

    async def market_clock(self):
        if self.clock_error is not None:
            raise self.clock_error
        now = datetime(2026, 8, 18, 17, tzinfo=UTC)
        return AlpacaMarketClock(
            timestamp=now, is_open=self.is_open,
            next_open=now + timedelta(days=1),
            next_close=now + timedelta(hours=3))

    async def submit(self, **_kwargs):
        self.submits += 1
        return CommandOutcome(state=S.ACKNOWLEDGED, broker_order_id="o-1")


async def _noop_before(_grant, _operation):
    return None


async def _noop_after(_grant, _operation, _result):
    return None


def guarded_clock_broker(inner):
    grant = ManualExecutionGrant(
        confirm_paper_account="PA-1", confirm_plan_id="plan-1",
        confirm_effective_session=date(2026, 8, 18),
        confirm_submit_paper_orders=True)
    guard = ExecutionBrokerGuard(
        before_read=_noop_before, after_read=_noop_after,
        before_mutation=_noop_before)
    return GuardedExecutionBroker(inner=inner, grant=grant, guard=guard)


def test_broker_closed_refuses_increase_before_transport():
    inner = ClockBroker(is_open=False)
    broker = guarded_clock_broker(inner)
    with pytest.raises(PreTransportAuthorityRefused, match="market closed"):
        run(broker.submit(
            client_key="key", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal(1)))
    assert inner.submits == 0


def test_clock_outage_refuses_increase_before_transport():
    inner = ClockBroker(clock_error=RuntimeError("clock unavailable"))
    broker = guarded_clock_broker(inner)
    with pytest.raises(PreTransportAuthorityRefused, match="clock unavailable"):
        run(broker.submit(
            client_key="key", instrument=INSTRUMENT,
            side=Side.BUY, quantity=Decimal(1)))
    assert inner.submits == 0


def test_broker_clock_does_not_veto_reduction():
    inner = ClockBroker(is_open=False)
    broker = guarded_clock_broker(inner)
    outcome = run(broker.submit(
        client_key="key", instrument=INSTRUMENT,
        side=Side.SELL, quantity=Decimal(1)))
    assert outcome.state is S.ACKNOWLEDGED
    assert inner.submits == 1
