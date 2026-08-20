"""Focused regressions for the Alpaca boundary hardening overlay."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution import journal
from sentinel.execution.alpaca import (
    AlpacaExecutionBroker,
    MalformedBrokerPayload,
    NativeBrokerFill,
)
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.states import CommandState as S

UTC = timezone.utc
PAPER = "https://paper-api.alpaca.markets"
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAPL", symbol="AAPL", broker_id="asset-aapl")


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
                outer.calls.append(("POST", url, dict(json or {})))
                return outer.post_result

            async def get(self, url, headers=None, params=None):
                path = "/v2" + url.split("/v2", 1)[1]
                params = dict(params or {})
                outer.calls.append(("GET", path, params))
                value = outer.routes.get(path)
                if callable(value):
                    value = value(params)
                if isinstance(value, Response):
                    return value
                return Response(value if value is not None else [])

        self.AsyncClient = Client


def adapter(*, post=None, routes=None):
    http = Httpx(post=post, routes=routes)
    broker = AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
        http_provider=lambda: http)
    return broker, http


def full_order(**changes):
    payload = {
        "id": "order-1",
        "client_order_id": "key-1",
        "symbol": "AAPL",
        "asset_id": "asset-aapl",
        "side": "buy",
        "status": "new",
        "qty": "2",
        "filled_qty": "0",
        "filled_avg_price": None,
        "submitted_at": "2026-08-19T17:00:00Z",
        "type": "market",
        "time_in_force": "day",
        # This is Alpaca's ordinary simple-order wire representation.
        "order_class": "",
        "extended_hours": False,
    }
    payload.update(changes)
    return payload


def test_runtime_exports_hardened_adapter():
    assert AlpacaExecutionBroker.__name__ == "HardenedAlpacaExecutionBroker"


def test_empty_order_class_is_accepted_as_simple_order():
    broker, _ = adapter(post=Response(full_order(), 200))
    outcome = run(broker.submit(
        client_key="key-1", instrument=INSTRUMENT,
        side=Side.BUY, quantity=Decimal(2)))
    assert outcome.state is S.ACKNOWLEDGED
    assert outcome.broker_order_id == "order-1"


def test_nontrade_query_cannot_hide_future_nonzero_cash_activity():
    seen = []

    def page(params):
        seen.append(dict(params))
        return [{
            "id": "future-1",
            "activity_type": "FUTURE_CASH_TYPE",
            "date": "2026-08-19",
            "net_amount": "1.25",
        }]

    broker, _ = adapter(routes={"/v2/account/activities": page})
    with pytest.raises(MalformedBrokerPayload, match="unrecognized non-trade cash"):
        run(broker.account_cash_activities(
            after=datetime(2026, 8, 19, 16, tzinfo=UTC),
            through=datetime(2026, 8, 19, 18, tzinfo=UTC)))
    assert seen[0]["category"] == "non_trade_activity"
    assert "activity_types" not in seen[0]


def test_native_fill_activity_ids_preserve_economic_multiplicity():
    common = dict(
        client_key=None,
        broker_order_id="order-1",
        quantity=Decimal(1),
        price=Decimal("100"),
        filled_at=datetime(2026, 8, 19, 17, tzinfo=UTC),
    )
    first = NativeBrokerFill(activity_id="fill-a", **common)
    second = NativeBrokerFill(activity_id="fill-b", **common)
    assert journal.fill_fingerprint(first) != journal.fill_fingerprint(second)
