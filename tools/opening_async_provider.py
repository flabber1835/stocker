"""Private, shared, independently delayed provider for opening qualification.

This fixture has no network fallback. It deliberately separates economic fills,
order counters, positions and activity visibility; a POST only acknowledges.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import multiprocessing
import math
from multiprocessing.managers import BaseManager
import os
from pathlib import Path
from functools import wraps
from threading import RLock
import time
import uuid

from tools.opening_gateway_qualification import LocalAlpaca, Response
from tools.opening_latency_qualification import QualificationRefused


def serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return invoke


class DelayedAlpaca(LocalAlpaca):
    """Zero-fill receipts; two DAY orders rest, other endpoints converge later."""

    def __init__(self, *, account, cash, assets, opened, closed, delay_seconds=40):
        super().__init__(account=account, cash=cash, assets=assets,
                         window=lambda: (opened, closed), forbid_quotes=True)
        if not 0 < delay_seconds <= 60:
            raise QualificationRefused("INVALID_ASYNC_FIXTURE_DELAY")
        self.initial_cash = self.cash
        self._lock = RLock()
        self.opened, self.closed = opened, closed
        self.cutoff = opened + timedelta(seconds=600)
        self.started = time.monotonic() + max(
            0, (opened + timedelta(seconds=60) - datetime.now(timezone.utc)).total_seconds())
        self.delay_seconds = delay_seconds
        self.pending, self.actual_positions = {}, {}
        self.visibility_events = []
        self.late_posts, self.duplicate_posts = 0, 0
        self.last_post_seconds = None
        self.zero_fill_acknowledgements = 0
        self.partial_order_observations = 0
        self.cash_ahead_observations = 0
        self.contention_started_at = None

    def _advance(self):
        now = datetime.now(timezone.utc)
        for order_id, pending in self.pending.items():
            order = self.orders[order_id]
            if pending["resting"]:
                continue
            quantity, price = Decimal(order["qty"]), Decimal(order["limit_price"])
            half = (quantity / 2).to_integral_value(rounding="ROUND_FLOOR")
            stages = [(half, pending["accepted"] + timedelta(seconds=0.01)),
                      (quantity, pending["accepted"] + timedelta(seconds=0.02))]
            for cumulative, instant in stages:
                if instant <= now and cumulative > pending["economic"]:
                    delta = cumulative - pending["economic"]
                    self.cash -= delta * price
                    asset = order["asset_id"]
                    self.actual_positions[asset] = self.actual_positions.get(asset, Decimal(0)) + delta
                    pending["economic"] = cumulative
            age = (now - pending["accepted"]).total_seconds()
            visible = (quantity if age >= self.delay_seconds else
                       half if age >= 0.03 else Decimal(0))
            order.update(filled_qty=str(visible), filled_avg_price=str(price) if visible else None,
                         status="filled" if visible == quantity else
                         "partially_filled" if visible else "new")
            for cumulative, instant in stages:
                visible_at = pending["accepted"] + timedelta(
                    seconds=self.delay_seconds / 2 if cumulative == half else self.delay_seconds)
                if visible_at <= now and cumulative > pending["published"]:
                    delta = cumulative - pending["published"]
                    asset = order["asset_id"]
                    self.positions[asset] = self.positions.get(asset, Decimal(0)) + delta
                    index = len(self.events) + 1
                    stamp = instant.isoformat()
                    self.events.append({"account_id": self.account_uuid, "at": stamp,
                        "event_id": f"01ASYNC{index:020d}",
                        "ref_id": str(uuid.uuid5(uuid.NAMESPACE_URL, order_id + ":" + str(cumulative))),
                        "status": "executed", "executed_at": stamp, "settle_date": stamp[:10],
                        "activity_type": "TRD", "activity_subtype": None, "previous_id": None,
                        "qty": str(delta), "price": str(price), "net_amount": str(-delta * price),
                        "currency": "USD", "details": {"execution_type": "fill", "order_id": order_id,
                            "asset_id": asset, "symbol": order["symbol"], "side": "buy",
                            "client_order_id": order["client_order_id"]}})
                    pending["published"] = cumulative
        if self.cash < 0:
            raise QualificationRefused("ASYNC_FIXTURE_NEGATIVE_CASH")

    @serialized
    def get(self, url, params):
        self._advance()
        response = super().get(url, params)
        path = self.path(url)
        if path == "/v2/account":
            reserved = sum(((Decimal(self.orders[key]["qty"]) - item["economic"])
                            * Decimal(self.orders[key]["limit_price"])
                            for key, item in self.pending.items()), Decimal(0))
            equity = self.cash + sum((quantity * self.by_id[asset]["price"]
                for asset, quantity in self.actual_positions.items()), Decimal(0))
            response.payload.update(cash=str(self.cash), buying_power=str(max(Decimal(0), self.cash-reserved)),
                                    equity=str(equity), last_equity=str(self.initial_cash))
            if any(item["economic"] > item["published"] for item in self.pending.values()):
                self.cash_ahead_observations += 1
        elif path in {"/v2/orders", "/v2/orders:by_client_order_id"} or path.startswith("/v2/orders/"):
            if any(row["status"] == "partially_filled" for row in self.orders.values()):
                self.partial_order_observations += 1
        return response

    @serialized
    def post(self, url, body):
        self._advance()
        now = datetime.now(timezone.utc)
        if now >= self.cutoff:
            self.late_posts += 1
            raise QualificationRefused("ASYNC_FIXTURE_LATE_POST")
        if any(row["client_order_id"] == body.get("client_order_id") for row in self.orders.values()):
            self.duplicate_posts += 1
            raise QualificationRefused("ASYNC_FIXTURE_DUPLICATE_POST")
        # Reuse the strict wire/whole-share/cash validation, forcing a resting
        # response. Only this fixture's subsequent independent clock fills it.
        symbol = body.get("symbol")
        asset = self.by_id.get(symbol)
        if asset is None or body.get("side") != "buy" or body.get("type") != "limit":
            raise QualificationRefused("ASYNC_FIXTURE_REQUIRES_PROTECTED_BUY")
        old_price = asset["price"]
        asset["price"] = Decimal(body["limit_price"]) + Decimal(1)
        try:
            response = super().post(url, body)
        finally:
            asset["price"] = old_price
        order = self.orders[response.payload["id"]]
        self.pending[order["id"]] = {"accepted": now, "economic": Decimal(0),
            "published": Decimal(0), "resting": len(self.orders) in {2, 3}}
        self.zero_fill_acknowledgements += 1
        self.last_post_seconds = time.monotonic() - self.started
        return Response(dict(response.payload), status=201)

    @serialized
    def snapshot(self):
        self._advance()
        reserved = sum(((Decimal(self.orders[key]["qty"]) - item["economic"])
                        * Decimal(self.orders[key]["limit_price"])
                        for key, item in self.pending.items()), Decimal(0))
        return {"cash": str(self.cash), "initial_cash": str(self.initial_cash),
            "buying_power": str(max(Decimal(0), self.cash-reserved)), "reserved_cash": str(reserved),
            "positions": {key: str(value) for key, value in self.positions.items()},
            "orders": list(self.orders.values()), "requests": dict(self.requests),
            "first_order_seconds": self.first_order_seconds, "last_post_seconds": self.last_post_seconds,
            "zero_fill_acknowledgements": self.zero_fill_acknowledgements,
            "partial_order_observations": self.partial_order_observations,
            "cash_ahead_observations": self.cash_ahead_observations,
            "late_posts": self.late_posts, "duplicate_posts": self.duplicate_posts,
            "contention_started_at": self.contention_started_at,
            "pending_visibility": sum(item["economic"] != item["published"] for item in self.pending.values()),
            "resting_client_keys": [self.orders[key]["client_order_id"] for key, item in self.pending.items()
                                    if item["resting"]],
            "cutoff": self.cutoff.isoformat(), "now": datetime.now(timezone.utc).isoformat()}

    @serialized
    def claim_contention(self, expected_count):
        if self.contention_started_at is not None or len(self.orders) != expected_count:
            return False
        self.contention_started_at = datetime.now(timezone.utc).isoformat()
        return True


class SharedProvider:
    """The same provider process serves every forked production callback."""

    def __init__(self, proxy, *, latency_seconds=0.5):
        if (type(latency_seconds) not in {int, float} or not math.isfinite(latency_seconds)
                or not 0.5 <= latency_seconds <= 5):
            raise QualificationRefused("ASYNC_PROVIDER_LATENCY_FLOOR_REQUIRED")
        self.proxy = proxy
        self.latency_seconds = float(latency_seconds)
        owner = self

        class Client:
            def __init__(self, **_kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            async def get(self, url, headers=None, params=None):
                await asyncio.sleep(owner.latency_seconds)
                return owner.proxy.get(url, dict(params or {}))
            async def post(self, url, headers=None, json=None):
                await asyncio.sleep(owner.latency_seconds)
                return owner.proxy.post(url, dict(json or {}))
            async def delete(self, *_args, **_kwargs):
                raise QualificationRefused("ASYNC_FIXTURE_UNEXPECTED_CANCELLATION")

        self.AsyncClient = Client

    @classmethod
    def start(cls, *, latency_seconds=0.5, **kwargs):
        # Validate before starting the shared process or touching a database.
        cls(None, latency_seconds=latency_seconds)
        provider = DelayedAlpaca(**kwargs)
        context = multiprocessing.get_context("fork")

        class Manager(BaseManager): pass

        Manager.register("provider", callable=lambda: provider,
                         exposed=("get", "post", "snapshot", "claim_contention"))
        path = Path("/tmp/opening-latency") / ("provider-" + uuid.uuid4().hex + ".sock")
        path.parent.mkdir(parents=True, exist_ok=True)
        manager = Manager(address=str(path), authkey=os.urandom(32), ctx=context)
        manager.start()
        return cls(manager.provider(), latency_seconds=latency_seconds), manager
