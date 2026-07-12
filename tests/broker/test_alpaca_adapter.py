"""Phase-1 unit tests for the shared BrokerAdapter / AlpacaBrokerAdapter.

Transport is faked via the `http_provider` seam — no network, no service import.
These lock the broker-agnostic contract and the canonical status normalization
(the boundary that prevents a `partial_fill` vs `partially_filled` split-brain).
"""
from __future__ import annotations

import sys
import os
from contextlib import asynccontextmanager

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from stock_strategy_shared.broker import (  # noqa: E402
    ALREADY_CLOSED_STATUS,
    AlpacaBrokerAdapter,
    get_broker_adapter,
)
from stock_strategy_shared.order_status import OPEN_ORDER_STATUSES, TURNOVER_STATUSES  # noqa: E402


# --------------------------------------------------------------------------
# Fake httpx
# --------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Records requests and returns canned responses keyed by URL substring."""

    def __init__(self, routes, recorder):
        self._routes = routes
        self._rec = recorder

    @asynccontextmanager
    async def _cm(self):
        yield self

    def __call__(self, *a, **k):  # AsyncClient(timeout=...) call
        return self._cm()

    async def get(self, url, headers=None, params=None):
        self._rec.append(("GET", url, headers, params))
        return self._match(url)

    async def post(self, url, headers=None, json=None):
        self._rec.append(("POST", url, headers, json))
        return self._match(url)

    async def delete(self, url, headers=None):
        self._rec.append(("DELETE", url, headers, None))
        return self._match(url)

    def _match(self, url):
        for frag, resp in self._routes.items():
            if frag in url:
                return resp
        raise AssertionError(f"no route for {url}")


class _FakeHttpx:
    def __init__(self, routes, recorder):
        self._client = _FakeClient(routes, recorder)

    def AsyncClient(self, *a, **k):
        return self._client(*a, **k)


def _adapter(routes, recorder):
    fake = _FakeHttpx(routes, recorder)
    return AlpacaBrokerAdapter(
        api_key="k", secret_key="s", base_url="https://paper.test",
        http_provider=lambda: fake,
    )


# --------------------------------------------------------------------------
# Status normalization — the canonical-token boundary
# --------------------------------------------------------------------------


def test_partially_filled_maps_to_canonical_partial_fill():
    a = _adapter({}, [])
    assert a.normalize_status("partially_filled") == "partial_fill"
    # the broker spelling is NEVER a canonical token
    assert "partially_filled" not in OPEN_ORDER_STATUSES
    assert "partially_filled" not in TURNOVER_STATUSES


def test_terminal_status_map_values_are_canonical_or_known():
    a = _adapter({}, [])
    assert a.normalize_status("filled") == "filled"
    assert a.normalize_status("canceled") == "cancelled"
    assert a.normalize_status("rejected") == "failed"
    assert a.normalize_status("expired") == "cancelled"
    # 'partial_fill' is in the canonical open set
    assert "partial_fill" in OPEN_ORDER_STATUSES


def test_open_statuses_return_none():
    a = _adapter({}, [])
    for s in ("new", "accepted", "pending_new", "held", ""):
        assert a.normalize_status(s) is None


# --------------------------------------------------------------------------
# Credentials gate
# --------------------------------------------------------------------------


def test_has_credentials_rejects_empty_and_demo():
    assert AlpacaBrokerAdapter(api_key="", secret_key="s").has_credentials() is False
    assert AlpacaBrokerAdapter(api_key="demo", secret_key="s").has_credentials() is False
    assert AlpacaBrokerAdapter(api_key="k", secret_key="").has_credentials() is False
    assert AlpacaBrokerAdapter(api_key="k", secret_key="s").has_credentials() is True


# --------------------------------------------------------------------------
# Reads → normalized dataclasses
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_normalizes_floats():
    rec = []
    a = _adapter({"/v2/account": _Resp({"equity": "1000.5", "buying_power": "2000", "cash": "50"})}, rec)
    snap = await a.get_account()
    assert snap.equity == 1000.5 and snap.buying_power == 2000.0 and snap.cash == 50.0
    assert snap.raw["equity"] == "1000.5"
    # auth header + URL shape preserved
    method, url, headers, _ = rec[0]
    assert method == "GET" and url == "https://paper.test/v2/account"
    assert headers["APCA-API-KEY-ID"] == "k" and headers["APCA-API-SECRET-KEY"] == "s"


@pytest.mark.asyncio
async def test_get_positions_maps_fields_and_skips_nondict():
    rec = []
    routes = {"/v2/positions": _Resp([
        {"symbol": "AAPL", "qty": "10", "avg_entry_price": "100", "current_price": "110",
         "market_value": "1100", "side": "long", "lastday_price": "105", "change_today": "0.01"},
        "garbage",
    ])}
    a = _adapter(routes, rec)
    pos = await a.get_positions()
    assert len(pos) == 1
    p = pos[0]
    assert p.ticker == "AAPL" and p.qty == 10.0 and p.current_price == 110.0
    assert p.side == "long" and p.lastday_price == 105.0


@pytest.mark.asyncio
async def test_list_orders_normalizes_status_and_partial_fill():
    rec = []
    routes = {"/v2/orders": _Resp([
        {"id": "o1", "status": "filled", "filled_qty": "5", "filled_avg_price": "10",
         "filled_at": "2026-06-01T09:30:00Z"},
        {"id": "o2", "status": "partially_filled", "filled_qty": "2"},
        {"id": "o3", "status": "new"},
    ])}
    a = _adapter(routes, rec)
    orders = await a.list_orders()
    by_id = {o.broker_order_id: o for o in orders}
    assert by_id["o1"].status == "filled" and by_id["o1"].filled_at is not None
    assert by_id["o2"].status == "partial_fill" and by_id["o2"].raw_status == "partially_filled"
    assert by_id["o3"].status is None  # still open
    # request used status=all & direction desc
    _, url, _, params = rec[0]
    assert params["status"] == "all" and params["direction"] == "desc"


@pytest.mark.asyncio
async def test_get_order_returns_none_on_non_200():
    a = _adapter({"/v2/orders/": _Resp({}, status_code=404)}, [])
    assert await a.get_order("missing") is None


@pytest.mark.asyncio
async def test_get_clock_parses_and_handles_non_200():
    ok = _adapter({"/v2/clock": _Resp({"is_open": True, "next_open": "2026-06-01T09:30:00Z",
                                       "next_close": "2026-06-01T16:00:00Z"})}, [])
    clock = await ok.get_clock()
    assert clock["is_open"] is True and clock["next_open"] is not None
    bad = _adapter({"/v2/clock": _Resp({}, status_code=500)}, [])
    assert await bad.get_clock() is None


@pytest.mark.asyncio
async def test_submit_order_passes_payload_through_and_returns_tuple():
    rec = []
    a = _adapter({"/v2/orders": _Resp({"id": "abc", "status": "accepted"})}, rec)
    payload = {"symbol": "MSFT", "qty": "3", "side": "buy", "type": "market",
               "time_in_force": "day", "client_order_id": "row-1"}
    oid, status, err = await a.submit_order(payload)
    assert (oid, status, err) == ("abc", "accepted", None)
    method, url, _, body = rec[0]
    assert method == "POST" and url == "https://paper.test/v2/orders"
    # exact payload (incl. client_order_id idempotency key) reaches the broker
    assert body == payload


@pytest.mark.asyncio
async def test_submit_order_non_2xx_returns_error_text():
    a = _adapter({"/v2/orders": _Resp({}, status_code=422, text="insufficient buying power")}, [])
    oid, status, err = await a.submit_order({"symbol": "X"})
    assert oid is None and status is None and err == "insufficient buying power"


@pytest.mark.asyncio
async def test_close_position_success_and_404_sentinel():
    ok = _adapter({"/v2/positions/AAPL": _Resp({"id": "c1", "status": "accepted"})}, [])
    assert await ok.close_position("AAPL") == ("c1", "accepted", None)

    flat = _adapter({"/v2/positions/AAPL": _Resp({}, status_code=404)}, [])
    oid, status, err = await flat.close_position("AAPL")
    assert oid is None and err is None
    assert status == ALREADY_CLOSED_STATUS == "position_already_closed"


@pytest.mark.asyncio
async def test_cancel_all_orders_returns_status_body_text():
    items = [{"id": "o1", "status": 200}, {"id": "o2", "status": 500}]
    a = _adapter({"/v2/orders": _Resp(items, status_code=207)}, [])
    status_code, body, _text = await a.cancel_all_orders()
    assert status_code == 207 and body == items


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


def test_factory_default_is_alpaca(monkeypatch):
    monkeypatch.delenv("BROKER", raising=False)
    assert get_broker_adapter().name == "alpaca"


def test_factory_rejects_unknown(monkeypatch):
    monkeypatch.setenv("BROKER", "robinhood")
    with pytest.raises(ValueError):
        get_broker_adapter()
