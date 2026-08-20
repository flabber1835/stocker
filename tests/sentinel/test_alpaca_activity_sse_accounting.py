"""Accounting-specific falsifiers for Alpaca Activity SSE."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

from sentinel.execution.alpaca import AlpacaExecutionBroker

UTC = timezone.utc
PAPER = "https://paper-api.alpaca.markets"
ACCOUNT_UUID = "11111111-1111-1111-1111-111111111111"
ACCOUNT_NUMBER = "PA-ALPACA-1"


def run(coro):
    return asyncio.run(coro)


class Response:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Httpx:
    def __init__(self, event):
        self.event = event
        outer = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, headers=None, params=None):
                if url.endswith("/v2/account"):
                    return Response(payload={
                        "id": ACCOUNT_UUID,
                        "account_number": ACCOUNT_NUMBER,
                    })
                if url.endswith("/v2beta1/events/activities"):
                    return Response(text=(
                        "data: " + json.dumps(outer.event, sort_keys=True)
                        + "\n\n"))
                raise AssertionError(url)

        self.AsyncClient = Client


def broker_for(event):
    http = Httpx(event)
    return AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
        http_provider=lambda: http)


def trade_event():
    return {
        "account_id": ACCOUNT_UUID,
        "at": "2026-08-19T17:00:00Z",
        "event_id": "01J5R000000000000000000001",
        "activity_type": "TRD",
        "activity_subtype": None,
        "ref_id": "22222222-2222-2222-2222-222222222222",
        "status": "executed",
        "executed_at": "2026-08-19T17:00:00Z",
        "settle_date": "2026-08-20",
        "qty": "2",
        "price": "100",
        "net_amount": "-200",
        "currency": "USD",
        "previous_id": None,
        "details": {
            "execution_type": "fill",
            "order_id": "order-1",
            "client_order_id": "sntl-0123456789abcdef0123",
        },
    }


def test_trade_event_is_fill_evidence_not_second_cash_flow():
    broker = broker_for(trade_event())
    start = datetime(2026, 8, 19, 16, tzinfo=UTC)
    end = datetime(2026, 8, 19, 18, tzinfo=UTC)

    cash = run(broker.account_cash_activities(after=start, through=end))
    fills = run(broker.recent_fills(start))

    assert cash.activities == ()
    assert cash.last_activity_id is None
    assert cash.last_event_id == "01J5R000000000000000000001"
    assert len(fills) == 1
    assert fills[0].activity_id == "22222222-2222-2222-2222-222222222222"
    assert fills[0].quantity == Decimal("2")
    assert fills[0].price == Decimal("100")
