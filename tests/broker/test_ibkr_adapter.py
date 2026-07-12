"""IBKRBrokerAdapter unit tests — transport faked via the http_provider seam.

Lock the IBKR-specific translations: conid resolution, reply-confirmation loop,
synthesized close/cancel-all, Alpaca-shaped get_order normalization, the
order_ref → raw["client_order_id"] injection, hyphen↔space symbology, the CP
status map, and the three-layer dormancy contract.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from stock_strategy_shared.broker import (  # noqa: E402
    ALREADY_CLOSED_STATUS,
    IBKRBrokerAdapter,
    get_broker_adapter,
)


# --------------------------------------------------------------------------
# Fake httpx — like the Alpaca fake, plus LIST routes (sequential responses)
# for the reply-confirmation loop where one URL answers differently per call.
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
    def __init__(self, routes, recorder):
        self._routes = routes
        self._rec = recorder

    @asynccontextmanager
    async def _cm(self):
        yield self

    def __call__(self, *a, **k):
        self._rec.append(("CLIENT", k))
        return self._cm()

    def _match(self, url):
        for frag, resp in self._routes.items():
            if frag in url:
                if isinstance(resp, list):
                    return resp.pop(0) if resp else _Resp({}, 500, "route exhausted")
                return resp
        raise AssertionError(f"no route for {url}")

    async def get(self, url, **k):
        self._rec.append(("GET", url, k))
        return self._match(url)

    async def post(self, url, json=None, **k):
        self._rec.append(("POST", url, json))
        return self._match(url)

    async def delete(self, url, **k):
        self._rec.append(("DELETE", url, None))
        return self._match(url)


class _FakeHttpx:
    def __init__(self, routes, recorder):
        self.AsyncClient = _FakeClient(routes, recorder)


def _adapter(routes, recorder=None):
    rec = recorder if recorder is not None else []
    fake = _FakeHttpx(routes, rec)
    a = IBKRBrokerAdapter(
        gateway_url="https://ibkr-gateway:5000",
        account_id="DU111",
        tls_verify=False,
        http_provider=lambda: fake,
    )
    return a, rec


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# Dormancy / credentials
# --------------------------------------------------------------------------


def test_no_env_means_no_credentials(monkeypatch):
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    monkeypatch.delenv("IBKR_ACCOUNT_ID", raising=False)
    assert IBKRBrokerAdapter().has_credentials() is False


def test_both_env_vars_required(monkeypatch):
    monkeypatch.setenv("IBKR_GATEWAY_URL", "https://gw:5000")
    monkeypatch.delenv("IBKR_ACCOUNT_ID", raising=False)
    assert IBKRBrokerAdapter().has_credentials() is False
    monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU111")
    assert IBKRBrokerAdapter().has_credentials() is True


def test_factory_ibkr_branch(monkeypatch):
    monkeypatch.setenv("BROKER", "ibkr")
    assert get_broker_adapter().name == "ibkr"


def test_factory_default_untouched(monkeypatch):
    monkeypatch.delenv("BROKER", raising=False)
    assert get_broker_adapter().name == "alpaca"


# --------------------------------------------------------------------------
# Status normalization + symbology
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("Filled", "filled"),
    ("Cancelled", "cancelled"),
    ("ApiCancelled", "cancelled"),
    ("Inactive", "failed"),
    ("Submitted", None),
    ("PreSubmitted", None),
    ("PendingSubmit", None),
    ("PendingCancel", None),
])
def test_status_map(raw, expected):
    a, _ = _adapter({})
    assert a.normalize_status(raw) == expected


def test_symbology_hyphen_space_roundtrip():
    a, _ = _adapter({})
    assert a.to_broker_symbol("BRK-B") == "BRK B"
    assert a.from_broker_symbol("BRK B") == "BRK-B"
    assert a.to_broker_symbol("AAPL") == "AAPL"


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def test_account_summary_amount_unwrap():
    a, _ = _adapter({
        "/portfolio/accounts": _Resp([{"id": "DU111"}]),
        "/portfolio/DU111/summary": _Resp({
            "netliquidation": {"amount": 120000.5},
            "buyingpower": {"amount": 240000.0},
            "totalcashvalue": 3000,      # bare numeric also accepted
        }),
    })
    snap = _run(a.get_account())
    assert snap.equity == 120000.5
    assert snap.buying_power == 240000.0
    assert snap.cash == 3000.0


def test_positions_normalized_and_zero_filtered():
    a, _ = _adapter({
        "/portfolio/accounts": _Resp([{"id": "DU111"}]),
        "/positions/0": _Resp([
            {"ticker": "AAPL", "position": 10, "mktPrice": 200.0,
             "mktValue": 2000.0, "avgCost": 150.0, "unrealizedPnl": 500.0},
            {"ticker": "GONE", "position": 0},
            {"ticker": "BRK B", "position": 5, "mktPrice": 400.0,
             "mktValue": 2000.0, "avgCost": 380.0, "unrealizedPnl": 100.0},
        ]),
    })
    positions = _run(a.get_positions())
    assert [p.ticker for p in positions] == ["AAPL", "BRK-B"]   # system form
    aapl = positions[0]
    assert aapl.qty == 10 and aapl.cost_basis == 1500.0
    assert aapl.unrealized_pl == 500.0


def test_list_orders_injects_client_order_id():
    a, _ = _adapter({
        "/iserver/account/orders": _Resp({"orders": [
            {"orderId": 987, "status": "Filled", "filledQuantity": 10,
             "avgPrice": 101.5, "order_ref": "row-uuid-1"},
            {"orderId": 988, "status": "Submitted"},
        ]}),
    })
    orders = _run(a.list_orders())
    assert orders[0].broker_order_id == "987"
    assert orders[0].status == "filled" and orders[0].raw_status == "Filled"
    assert orders[0].filled_qty == 10 and orders[0].avg_fill_price == 101.5
    # the reaper's contract: raw carries the Alpaca-named client_order_id key
    assert orders[0].raw["client_order_id"] == "row-uuid-1"
    assert orders[1].status is None          # working order → not terminal


def test_get_order_alpaca_shaped_for_reconciler():
    a, _ = _adapter({
        "/order/status/987": _Resp({
            "order_status": "Filled", "cum_fill": "10", "avg_price": "101.5"}),
    })
    info = _run(a.get_order("987"))
    # _reconcile_unfilled_sells reads exactly these keys
    assert info["status"] == "filled"
    assert info["filled_qty"] == "10" and info["filled_avg_price"] == "101.5"
    assert "filled_at" in info


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

_SEARCH = _Resp([{"conid": 265598, "symbol": "AAPL",
                  "sections": [{"secType": "STK"}]}])


def test_submit_resolves_conid_and_returns_order_id():
    rec = []
    a, _ = _adapter({
        "/iserver/secdef/search": _SEARCH,
        "/iserver/account/DU111/orders": _Resp(
            [{"order_id": "42", "order_status": "PreSubmitted"}]),
    }, rec)
    oid, status, err = _run(a.submit_order({
        "symbol": "AAPL", "qty": 10, "side": "buy", "type": "market",
        "time_in_force": "day", "client_order_id": "row-1"}))
    assert (oid, status, err) == ("42", "PreSubmitted", None)
    order = next(p for m, u, p in [r for r in rec if r[0] == "POST"]
                 if "DU111/orders" in u)["orders"][0]
    assert order["conid"] == 265598 and order["orderType"] == "MKT"
    assert order["side"] == "BUY" and order["tif"] == "DAY"
    assert order["cOID"] == "row-1" and order["quantity"] == 10.0


def test_submit_auto_confirms_reply_questions():
    a, _ = _adapter({
        "/iserver/secdef/search": _SEARCH,
        "/iserver/account/DU111/orders": _Resp(
            [{"id": "reply-1", "message": ["You are about to..."]}]),
        "/iserver/reply/reply-1": _Resp(
            [{"order_id": "43", "order_status": "Submitted"}]),
    })
    oid, status, err = _run(a.submit_order({
        "symbol": "AAPL", "qty": 5, "side": "buy", "type": "market",
        "time_in_force": "day", "client_order_id": "row-2"}))
    assert (oid, status, err) == ("43", "Submitted", None)


def test_submit_bounded_reply_loop_fails_loudly():
    a, _ = _adapter({
        "/iserver/secdef/search": _SEARCH,
        "/iserver/account/DU111/orders": _Resp(
            [{"id": "reply-x", "message": ["q"]}]),
        "/iserver/reply/reply-x": _Resp([{"id": "reply-x", "message": ["q"]}]),
    })
    oid, status, err = _run(a.submit_order({
        "symbol": "AAPL", "qty": 5, "side": "buy", "type": "market",
        "time_in_force": "day"}))
    assert oid is None and status is None and "confirmation prompts" in err


def test_submit_unresolvable_symbol_is_error_not_order():
    a, _ = _adapter({"/iserver/secdef/search": _Resp([])})
    oid, status, err = _run(a.submit_order({
        "symbol": "NOPE", "qty": 1, "side": "buy", "type": "market",
        "time_in_force": "day"}))
    assert oid is None and "conid" in err


def test_close_position_synthesized_full_qty_sell():
    rec = []
    a, _ = _adapter({
        "/portfolio/accounts": _Resp([{"id": "DU111"}]),
        "/positions/0": _Resp([{"ticker": "AAPL", "position": 7,
                                "mktPrice": 200.0, "mktValue": 1400.0,
                                "avgCost": 150.0, "unrealizedPnl": 350.0}]),
        "/iserver/secdef/search": _SEARCH,
        "/iserver/account/DU111/orders": _Resp(
            [{"order_id": "77", "order_status": "Submitted"}]),
    }, rec)
    oid, status, err = _run(a.close_position("AAPL"))
    assert (oid, status, err) == ("77", "Submitted", None)
    order = next(p for m, u, p in [r for r in rec if r[0] == "POST"]
                 if "DU111/orders" in u)["orders"][0]
    assert order["side"] == "SELL" and order["quantity"] == 7.0


def test_close_position_already_flat_sentinel():
    a, _ = _adapter({
        "/portfolio/accounts": _Resp([{"id": "DU111"}]),
        "/positions/0": _Resp([]),
    })
    oid, status, err = _run(a.close_position("AAPL"))
    assert oid is None and status == ALREADY_CLOSED_STATUS and err is None


def test_cancel_all_synthesizes_multistatus():
    a, rec = _adapter({
        "/iserver/account/orders": _Resp({"orders": [
            {"orderId": 1, "status": "Submitted"},
            {"orderId": 2, "status": "Filled"},          # terminal → not cancelled
            {"orderId": 3, "status": "PreSubmitted"},
        ]}),
        "/order/1": _Resp({}, 200),
        "/order/3": _Resp({}, 500, "boom"),
    })
    status_code, body, _text = _run(a.cancel_all_orders())
    assert status_code == 207
    by_id = {i["id"]: i for i in body}
    assert set(by_id) == {"1", "3"}                       # 2 untouched
    assert by_id["1"]["status"] == 200
    assert by_id["3"]["status"] == 500 and by_id["3"]["body"] == "boom"


def test_conid_cached_after_first_resolution():
    search_routes = [_Resp([{"conid": 265598, "symbol": "AAPL",
                             "sections": [{"secType": "STK"}]}])]
    a, rec = _adapter({
        "/iserver/secdef/search": search_routes,          # LIST: one response only
        "/iserver/account/DU111/orders": _Resp(
            [{"order_id": "42", "order_status": "Submitted"}]),
    })
    payload = {"symbol": "AAPL", "qty": 1, "side": "buy", "type": "market",
               "time_in_force": "day"}
    assert _run(a.submit_order(dict(payload)))[0] == "42"
    # second submit must hit the cache — the exhausted search route would 500
    assert _run(a.submit_order(dict(payload)))[0] == "42"
