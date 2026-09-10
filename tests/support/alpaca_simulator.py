"""Deterministic Alpaca wire laboratory. Test-only; all HTTP stays in memory.

The ledger models economic truth. Faults alter delivery independently, including
acceptance followed by a lost response. No production transition table is used.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable

import httpx

D = Decimal
PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
EPOCH = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)
ACCOUNT_UUID = "00000000-0000-4000-8000-000000000001"
ASSET_UUID = "00000000-0000-4000-8000-000000000002"


class Profile(str, Enum):
    PAPER = "paper"
    LIVE_CASH = "live_cash"


@dataclass
class DeliveryFault:
    method: str
    path: str
    occurrence: int
    after_effect: bool
    deliver: Callable


class AlpacaSimulator:
    """One account, stable native identities, explicit time and settlement.

    LIVE_CASH is an economic stress profile of this in-memory peer. The real
    adapter still receives PAPER_URL; a live URL never gains trading authority.
    """

    def __init__(self, profile: Profile = Profile.PAPER, cash: str = "100000"):
        self.profile = Profile(profile)
        self.now = EPOCH
        self.account_id = "SIM-ALPACA-1"
        self.native_account_id = ACCOUNT_UUID
        self.initial_cash = D(cash)
        self.cash = D(cash)
        self.unsettled = D(0)
        self.cash_movements: list[Decimal] = []
        self.positions: dict[str, Decimal] = {}
        self.assets = {"AAA": {"id": ASSET_UUID, "symbol": "AAA",
                               "status": "active", "tradable": True}}
        self.prices = {"AAA": D("100")}
        self.orders: dict[str, dict] = {}
        self.fills: list[dict] = []
        self.events: list[dict] = []
        self.account_overrides: dict = {}
        self.clock_overrides: dict = {}
        self.requests: list[dict] = []
        self.counts = Counter()
        self.faults: list[DeliveryFault] = []
        self.cancel_mode = "confirm"
        self.sequence = 0

    def advance(self, seconds: int = 1):
        if seconds < 0:
            raise ValueError("world time advances monotonically")
        self.now += timedelta(seconds=seconds)

    def add_asset(self, symbol: str, price: str = "100"):
        if symbol in self.assets:
            raise ValueError("asset already exists")
        asset_id = f"00000000-0000-4000-8000-{len(self.assets) + 2:012d}"
        self.assets[symbol] = dict(id=asset_id, symbol=symbol,
                                  status="active", tradable=True)
        self.prices[symbol] = D(price)

    def account(self):
        equity = self.cash + sum((q * self.prices[s]
                                 for s, q in self.positions.items()), D(0))
        return dict(id=self.native_account_id, account_number=self.account_id,
                    currency="USD", equity=str(equity), cash=str(self.cash),
                    buying_power=str(self.cash - self.unsettled), multiplier="1",
                    status="ACTIVE", trading_blocked=False,
                    account_blocked=False, trade_suspended_by_user=False) | \
            copy.deepcopy(self.account_overrides)

    def position_rows(self):
        return [dict(symbol=s, asset_id=self.assets[s]["id"], qty=str(q),
                     side="long" if q >= 0 else "short",
                     market_value=str(q * self.prices[s]))
                for s, q in sorted(self.positions.items()) if q]

    def _event(self, activity_type: str, amount: Decimal, *, at=None,
               details=None, **fields):
        self.sequence += 1
        stamp = at or self.now
        event = dict(event_id=f"{self.sequence:026d}",
                     ref_id=f"activity-{self.sequence:08d}",
                     account_id=self.native_account_id, currency="USD",
                     status="executed", activity_type=activity_type,
                     at=stamp.isoformat(), executed_at=stamp.isoformat(),
                     settle_date=stamp.date().isoformat(), net_amount=str(amount),
                     details=details or {}) | fields
        self.events.append(event)
        return event

    def cash_event(self, kind: str, amount: str, *, at=None, adversarial=False):
        value = D(amount)
        if not value.is_finite():
            raise ValueError("ledger cash must be finite")
        if not adversarial:
            if kind == "CSD" and value <= 0:
                raise ValueError("deposit must be positive")
            if kind in {"CSW", "FEE"} and value >= 0:
                raise ValueError("withdrawal/fee must be negative")
            if self.cash + value < 0:
                raise ValueError("insufficient cash")
        if self.profile is Profile.PAPER and not adversarial:
            if kind in {"DIV", "FEE"}:
                return None
            raise ValueError("paper funding is set at account creation")
        self.cash += value
        self.cash_movements.append(value)
        return self._event(kind, value, at=at)

    def replace_paper_account(self, cash: str = "100000"):
        if self.profile is not Profile.PAPER:
            raise ValueError("live account replacement is not a paper reset")
        self.account_id = "SIM-ALPACA-REPLACED"
        self.native_account_id = "00000000-0000-4000-8000-000000000099"
        self.initial_cash = self.cash = D(cash)
        self.unsettled = D(0)
        self.orders.clear()
        self.positions.clear()
        self.fills.clear()
        self.events.clear()
        self.cash_movements.clear()

    def fill(self, order_id: str, quantity: str | None = None,
             price: str | None = None, *, liquidity: str | None = None,
             late: bool = False):
        order = self.orders[order_id]
        if order["status"] in {"filled", "rejected", "expired", "canceled"} and not late:
            raise ValueError("cannot fill a terminal order")
        remaining = D(order["qty"]) - D(order["filled_qty"])
        qty = remaining if quantity is None else D(quantity)
        px = self.prices[order["symbol"]] if price is None else D(price)
        if self.profile is Profile.LIVE_CASH and liquidity is not None:
            qty = min(qty, D(liquidity))
        if (not qty.is_finite() or not px.is_finite() or qty <= 0
                or px <= 0 or qty > remaining):
            raise ValueError("invalid fill")
        sign = D(1) if order["side"] == "buy" else D(-1)
        notional = qty * px
        symbol = order["symbol"]
        if sign > 0 and notional > self.cash - self.unsettled:
            raise ValueError("fill exceeds spendable cash")
        if sign < 0 and qty > self.positions.get(symbol, D(0)):
            raise ValueError("fill would open a short")
        old_qty = D(order["filled_qty"])
        old_notional = old_qty * D(order["filled_avg_price"] or "0")
        order["filled_qty"] = str(old_qty + qty)
        order["filled_avg_price"] = str((old_notional + notional) / (old_qty + qty))
        order["status"] = "filled" if qty == remaining else "partially_filled"
        order["updated_at"] = self.now.isoformat()
        self.positions[symbol] = self.positions.get(symbol, D(0)) + sign * qty
        self.cash -= sign * notional
        if sign < 0 and self.profile is Profile.LIVE_CASH:
            self.unsettled += notional
        self.fills.append(dict(order_id=order_id, symbol=symbol, quantity=qty,
                               price=px, sign=sign))
        return self._event("TRD", -sign * notional,
                           qty=str(qty), price=str(px),
                           details=dict(order_id=order_id, symbol=symbol,
                                        asset_id=order["asset_id"],
                                        client_order_id=order["client_order_id"],
                                        side=order["side"], execution_type="fill"))

    def settle(self):
        self.unsettled = D(0)

    def assert_conservation(self):
        expected_cash = self.initial_cash + sum(self.cash_movements, D(0))
        expected_positions = {}
        for fill in self.fills:
            expected_cash -= fill["sign"] * fill["quantity"] * fill["price"]
            symbol = fill["symbol"]
            expected_positions[symbol] = expected_positions.get(symbol, D(0)) + \
                fill["sign"] * fill["quantity"]
        assert self.cash == expected_cash
        assert {s: q for s, q in self.positions.items() if q} == \
            {s: q for s, q in expected_positions.items() if q}
        assert self.cash >= 0 and all(q >= 0 for q in self.positions.values())
        assert len({o["client_order_id"] for o in self.orders.values()}) == len(self.orders)

    def fault(self, method: str, path: str, deliver: Callable, *,
              occurrence: int = 1, after_effect: bool = False):
        if occurrence < 1:
            raise ValueError("fault occurrence must be positive")
        self.faults.append(DeliveryFault(method, path,
                          self.counts[(method, path)] + occurrence,
                          after_effect, deliver))

    def reply(self, method: str, path: str, payload=None, *, status=200,
              occurrence=1, after_effect=False, content: bytes | None = None,
              headers=None):
        def deliver(world, request, response):
            if content is not None:
                return httpx.Response(status, content=content, headers=headers)
            return httpx.Response(status, content=json.dumps(payload).encode(),
                                  headers=headers)
        self.fault(method, path, deliver, occurrence=occurrence,
                   after_effect=after_effect)

    def timeout(self, method="POST", path="/v2/orders", *, after_effect=False):
        def deliver(world, request, response):
            raise httpx.ReadTimeout("simulated lost response", request=request)
        self.fault(method, path, deliver, after_effect=after_effect)

    def _submit(self, body):
        if any(o["client_order_id"] == body["client_order_id"]
               for o in self.orders.values()):
            return httpx.Response(422, json=dict(message="duplicate client_order_id"),
                                  headers={"X-Request-ID": "sim-duplicate"})
        asset = next((a for a in self.assets.values()
                      if body["symbol"] in {a["id"], a["symbol"]}), None)
        if asset is None:
            return httpx.Response(422, json=dict(message="unknown asset"),
                                  headers={"X-Request-ID": "sim-rejection"})
        qty = D(body["qty"])
        symbol = asset["symbol"]
        reserved = sum((D(o["qty"]) - D(o["filled_qty"])) * self.prices[o["symbol"]]
                       for o in self.orders.values()
                       if o["side"] == "buy" and self._working(o))
        unavailable = (not qty.is_finite() or qty <= 0
                       or not asset["tradable"] or asset["status"] != "active"
                       or self.account()["trading_blocked"]
                       or self.account()["account_blocked"])
        if body["side"] == "buy":
            unavailable |= qty * self.prices[symbol] > self.cash - self.unsettled - reserved
        else:
            selling = sum((D(o["qty"]) - D(o["filled_qty"])) for o in self.orders.values()
                          if o["symbol"] == symbol and o["side"] == "sell" and self._working(o))
            unavailable |= qty > self.positions.get(symbol, D(0)) - selling
        if unavailable:
            return httpx.Response(403, json=dict(message="insufficient available buying power or shares"),
                                  headers={"X-Request-ID": "sim-rejection"})
        order_id = f"order-{len(self.orders) + 1:08d}"
        order = copy.deepcopy(body) | dict(id=order_id, symbol=symbol,
                  asset_id=asset["id"], status="new", filled_qty="0",
                  filled_avg_price=None, submitted_at=self.now.isoformat(),
                  updated_at=self.now.isoformat())
        self.orders[order_id] = order
        return httpx.Response(200, json=order)

    @staticmethod
    def _working(order):
        return order["status"] not in {"filled", "canceled", "expired", "rejected"}

    def _route(self, request: httpx.Request):
        path, method = request.url.path, request.method
        params = dict(request.url.params)
        if method == "GET" and path == "/v2/account":
            return httpx.Response(200, json=self.account())
        if method == "GET" and path == "/v2/positions":
            return httpx.Response(200, json=self.position_rows())
        if method == "GET" and path == "/v2/clock":
            payload = dict(timestamp=self.now.isoformat(), is_open=True,
                           next_open=(self.now + timedelta(days=1)).isoformat(),
                           next_close=self.now.replace(hour=20, minute=0).isoformat())
            return httpx.Response(200, json=payload | self.clock_overrides)
        if method == "GET" and path.startswith("/v2/assets/"):
            key = path.rsplit("/", 1)[-1]
            asset = next((a for a in self.assets.values()
                          if key in {a["id"], a["symbol"]}), None)
            return httpx.Response(200 if asset else 404, json=asset)
        if method == "POST" and path == "/v2/orders":
            return self._submit(json.loads(request.content))
        if method == "GET" and path == "/v2/orders":
            rows = [o for o in self.orders.values() if
                    params.get("status", "open") == "all" or
                    (params.get("status", "open") == "open") == self._working(o)]
            rows.sort(key=lambda o: (o["submitted_at"], o["id"]), reverse=True)
            cursor = params.get("before_order_id")
            if cursor:
                indices = [i for i, o in enumerate(rows) if o["id"] == cursor]
                if not indices:
                    return httpx.Response(422, json=dict(message="unknown cursor"))
                rows = rows[indices[0] + 1:]
            return httpx.Response(200, json=rows[:int(params.get("limit", 50))])
        if method == "GET" and path == "/v2/orders:by_client_order_id":
            row = next((o for o in self.orders.values()
                        if o["client_order_id"] == params.get("client_order_id")), None)
            return httpx.Response(200 if row else 404, json=row)
        if path.startswith("/v2/orders/"):
            row = self.orders.get(path.rsplit("/", 1)[-1])
            if row is None:
                return httpx.Response(404, json=dict(message="order not found"))
            if method == "GET":
                return httpx.Response(200, json=row)
            if method == "DELETE":
                if self.cancel_mode == "fill":
                    self.fill(row["id"])
                elif self.cancel_mode == "confirm" and self._working(row):
                    row["status"] = "canceled"
                return httpx.Response(204)
        if method == "GET" and path == "/v2beta1/events/activities":
            events = self.events
            if "since" in params:
                events = [e for e in events if e["at"] >= params["since"]]
            if "until" in params:
                events = [e for e in events if e["at"] <= params["until"]]
            if "since_id" in params:
                events = [e for e in events if e["event_id"] > params["since_id"]]
            if "until_id" in params:
                events = [e for e in events if e["event_id"] <= params["until_id"]]
            return httpx.Response(200, text="".join(
                "data: " + json.dumps(e) + "\n\n" for e in events),
                headers={"Content-Type": "text/event-stream"})
        raise AssertionError(f"unmodeled Alpaca route: {method} {path}")

    def handle(self, request: httpx.Request):
        assert str(request.url).startswith(PAPER_URL + "/"), "unexpected origin"
        assert request.headers.get("APCA-API-KEY-ID") == "simulation-key"
        assert request.headers.get("APCA-API-SECRET-KEY") == "simulation-secret"
        key = (request.method, request.url.path)
        self.counts[key] += 1
        self.requests.append(dict(method=request.method, path=request.url.path,
                                  params=dict(request.url.params),
                                  body=json.loads(request.content) if request.content else None))
        matches = [f for f in self.faults if (f.method, f.path) == key
                   and f.occurrence == self.counts[key]]
        assert len(matches) <= 1, "ambiguous fault script"
        fault = matches[0] if matches else None
        response = self._route(request) if fault is None or fault.after_effect else None
        if fault is not None:
            self.faults.remove(fault)
            response = fault.deliver(self, request, response)
        return response

    def adapter(self):
        from sentinel.execution.alpaca import AlpacaExecutionBroker

        world = self

        class HTTPProvider:
            @staticmethod
            def AsyncClient(**kwargs):
                return httpx.AsyncClient(transport=httpx.MockTransport(world.handle),
                                         trust_env=False, **kwargs)

        return AlpacaExecutionBroker(
            api_key="simulation-key", secret_key="simulation-secret",
            base_url=PAPER_URL, http_provider=lambda: HTTPProvider,
            clock_provider=lambda: self.now,
            resolve_security_id=lambda s, _as_of=None: f"SEC-{s}" if s in self.assets else None)
