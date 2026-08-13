"""Complete open-order evidence for the destructive migration path."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.broker import AlpacaSentinelBroker  # noqa: E402
from stock_strategy_shared.broker import alpaca as alpaca_mod  # noqa: E402
from stock_strategy_shared.broker.alpaca import (  # noqa: E402
    AlpacaBrokerAdapter, IncompleteOrderList)


def run(coro):
    return asyncio.run(coro)


def order(order_id: str | None, symbol: str = "LEGACY") -> dict:
    return {
        "id": order_id,
        "status": "new",
        "symbol": symbol,
        "side": "buy",
        "filled_qty": "0",
    }


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpx:
    """Only the two read endpoints migration observation is allowed to use."""

    def __init__(self, order_pages, positions=()):
        self.order_pages = list(order_pages)
        self.positions = list(positions)
        self.calls: list[tuple[str, dict]] = []
        outer = self

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, *, headers=None, params=None):
                path = "/" + url.split("/", 3)[-1]
                outer.calls.append((path, dict(params or {})))
                if path.endswith("/v2/orders"):
                    if not outer.order_pages:
                        raise AssertionError("unexpected extra order page")
                    return _Response(outer.order_pages.pop(0))
                if path.endswith("/v2/positions"):
                    return _Response(outer.positions)
                raise AssertionError(f"unexpected broker read {path}")

        self.AsyncClient = _Client


def adapter(http: FakeHttpx) -> AlpacaBrokerAdapter:
    return AlpacaBrokerAdapter(
        api_key="paper-key", secret_key="paper-secret",
        base_url="https://paper-api.alpaca.markets",
        http_provider=lambda: http)


def test_migration_pages_by_exclusive_order_id_until_exhausted():
    first_page = [order(f"open-{number}")
                  for number in range(501, 1, -1)]
    http = FakeHttpx([
        first_page,
        [order("open-1")],
    ])

    observation = run(AlpacaSentinelBroker(adapter(http)).observe())

    assert len(observation.open_orders) == 501
    assert observation.open_orders[0].order_id == "open-501"
    assert observation.open_orders[-1].order_id == "open-1"
    order_calls = [params for path, params in http.calls
                   if path.endswith("/v2/orders")]
    assert order_calls == [
        {"status": "open", "limit": 500, "direction": "desc"},
        {"status": "open", "limit": 500, "direction": "desc",
         "before_order_id": "open-2"},
    ]


def test_page_cap_raises_before_positions_can_be_called_flat(monkeypatch):
    monkeypatch.setattr(alpaca_mod, "ORDER_PAGE_CAP", 2)
    http = FakeHttpx([
        [order(f"open-{number}") for number in range(1000, 500, -1)],
        [order(f"open-{number}") for number in range(500, 0, -1)],
    ])

    with pytest.raises(IncompleteOrderList, match="fail-closed cap"):
        run(AlpacaSentinelBroker(adapter(http)).observe())

    assert not any(path.endswith("/v2/positions") for path, _ in http.calls)


def test_duplicate_exclusive_cursor_response_fails_closed():
    http = FakeHttpx([
        [order("open-3"), order("open-2")],
        [order("open-2"), order("open-1")],
    ])

    with pytest.raises(IncompleteOrderList, match="did not make progress"):
        run(adapter(http).list_orders(status="open", limit=2))


def test_full_page_without_boundary_id_fails_closed():
    http = FakeHttpx([[order("open-2"), order(None)]])

    with pytest.raises(IncompleteOrderList, match="omitted an order id"):
        run(adapter(http).list_orders(status="open", limit=2))
