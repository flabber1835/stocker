"""Complete open-order evidence for the destructive migration path."""
from __future__ import annotations

import asyncio
from decimal import Decimal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.broker import (  # noqa: E402
    AdministrativeObservationRefused, AlpacaSentinelBroker)
from stock_strategy_shared.broker import alpaca as alpaca_mod  # noqa: E402
from stock_strategy_shared.broker.alpaca import (  # noqa: E402
    AlpacaBrokerAdapter, IncompleteOrderList, MalformedBrokerPayload)
from stock_strategy_shared.broker.base import BrokerPosition  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def order(order_id: str | None, symbol: str = "LEGACY", **over) -> dict:
    result = {
        "id": order_id,
        "status": "new",
        "symbol": symbol,
        "side": "buy",
        "qty": "10",
        "filled_qty": "0",
        "asset_id": f"asset-{symbol}",
    }
    result.update(over)
    return result


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
        self.positions = positions if not isinstance(positions, tuple) \
            else list(positions)
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

            async def delete(self, url, *, headers=None):
                path = "/" + url.split("/", 3)[-1]
                outer.calls.append((path, {}))
                return _Response(None)

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


@pytest.mark.parametrize("positions", [
    {"not": "an array"},
    ["not-an-object"],
    [{"symbol": "LEGACY", "asset_id": "asset-1", "side": "long"}],
    [{"symbol": "LEGACY", "asset_id": "asset-1", "qty": "NaN",
      "side": "long"}],
    [{"symbol": "LEGACY", "qty": "10", "side": "long"}],
    [{"symbol": "LEGACY", "asset_id": "asset-1", "qty": "10"}],
    [{"symbol": "LEGACY", "asset_id": "asset-1", "qty": "10",
      "side": "short"}],
])
def test_malformed_positions_are_never_filtered_into_a_flat_account(positions):
    http = FakeHttpx([[]], positions=positions)
    with pytest.raises(MalformedBrokerPayload):
        run(AlpacaSentinelBroker(adapter(http)).observe())


@pytest.mark.parametrize("side", ["", "short", "SHORT", "sideways"])
def test_normalized_nonlong_position_refuses_before_any_mutation(side):
    class DefensiveAdapter:
        mutations = 0

        async def list_orders(self, *, status="open", limit=500):
            assert status == "open"
            assert limit == 500
            return []

        async def get_positions(self):
            return [BrokerPosition(
                ticker="LEGACY", qty=Decimal("10"), side=side,
                broker_instrument_id="asset-1")]

        async def cancel_order(self, _order_id):
            self.mutations += 1
            raise AssertionError("malformed position authorized cancellation")

        async def submit_order(self, _payload):
            self.mutations += 1
            raise AssertionError("malformed position authorized submission")

    raw = DefensiveAdapter()
    with pytest.raises(AdministrativeObservationRefused, match="long positions"):
        run(AlpacaSentinelBroker(raw).observe())
    assert raw.mutations == 0


@pytest.mark.parametrize("bad", [
    order("o1", qty=None),
    order("o1", side="hold"),
    order("o1", asset_id=None),
    order("o1", status="partially_filled", filled_qty="1"),
    order("o1", status="partially_filled", filled_qty="1",
          filled_avg_price="NaN"),
    order("o1", status="filled", filled_qty="10"),
    order("o1", filled_qty="11"),
])
def test_malformed_or_terminal_open_rows_refuse_the_whole_read(bad):
    http = FakeHttpx([[bad]])
    with pytest.raises(MalformedBrokerPayload):
        run(AlpacaSentinelBroker(adapter(http)).observe())


@pytest.mark.parametrize("status", ["pending_cancel", "future_open_status"])
def test_every_nonterminal_row_from_status_open_is_conservatively_working(status):
    row = order("o1", status=status)
    http = FakeHttpx([[row], [row]])
    observed = run(AlpacaSentinelBroker(adapter(http)).observe())
    assert [item.order_id for item in observed.open_orders] == ["o1"]


def test_cancellation_names_only_the_approved_id_when_a_new_order_arrives():
    class RaceAdapter:
        def __init__(self):
            self.orders = {"approved", "arrived-after-observation"}
            self.exact = []

        async def cancel_order(self, order_id):
            self.exact.append(order_id)
            self.orders.discard(order_id)
            return True

        async def cancel_all_orders(self):
            raise AssertionError("cancel-all fallback expanded the blast radius")

    race = RaceAdapter()
    assert run(AlpacaSentinelBroker(race).cancel_orders(("approved",))) == 1
    assert race.exact == ["approved"]
    assert race.orders == {"arrived-after-observation"}
