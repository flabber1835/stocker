"""Existing Alpaca simulator hosted outside the application process."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
import asyncio
import multiprocessing
from functools import partial
import os
import signal

import httpx

from tests.support.alpaca_simulator import AlpacaSimulator, PAPER_URL
from .market import SECURITIES, SYMBOLS, SEED


class BrokerService:
    def __init__(self, profile):
        self.world = AlpacaSimulator(profile)
        self.world.now = datetime.fromisoformat(SEED + "T22:00:00+00:00")
        for symbol in (*SYMBOLS, "BIL"):
            self.world.add_asset(symbol)

    def request(self, method, url, headers, body):
        request = httpx.Request(method, url, headers=headers, content=body)
        try:
            response = self.world.handle(request)
        except httpx.TimeoutException:
            return {"timeout": True}
        return {"status": response.status_code, "headers": dict(response.headers), "body": response.content}

    def move(self, at):
        target = datetime.fromisoformat(at)
        self.world.advance(int((target - self.world.now).total_seconds()))

    def now(self):
        return self.world.now.isoformat()

    def prices(self, prices):
        self.world.prices.update({symbol: Decimal(value) for symbol, value in prices.items()})

    def timeout(self):
        self.world.timeout(after_effect=True)

    def cash(self, amount):
        self.world.cash_event("CSD" if amount > 0 else "CSW", str(amount), adversarial=True)

    def fill(self, partial=False):
        count = 0
        for key, order in list(self.world.orders.items()):
            if self.world._working(order):
                remaining = Decimal(order["qty"]) - Decimal(order["filled_qty"])
                if remaining > 0:
                    self.world.fill(key, str(remaining / 2) if partial else str(remaining))
                    count += 1
        return count

    def set_cancel_pending(self):
        self.world.cancel_mode = "pending"

    def snapshot(self):
        w = self.world
        return json.loads(json.dumps({"now": w.now.isoformat(), "cash": str(w.cash),
            "initial_cash": str(w.initial_cash), "positions": w.positions, "prices": w.prices,
            "movements": w.cash_movements, "fills": w.fills, "orders": w.orders,
            "assets": w.assets, "requests": w.requests, "remaining_faults": len(w.faults)}, default=str))


_METHODS = frozenset({"request", "move", "now", "prices", "timeout", "cash", "fill",
                      "set_cancel_pending", "snapshot"})


def _serve(connection, profile):
    service = BrokerService(profile)
    connection.send({"ready": True})
    while True:
        try:
            method, args, kwargs = connection.recv()
        except EOFError:
            return
        if method == "shutdown":
            return
        try:
            if method not in _METHODS:
                raise ValueError("unknown simulator operation")
            connection.send({"result": getattr(service, method)(*args, **kwargs)})
        except Exception as exc:
            connection.send({"error": f"{type(exc).__name__}: {exc}"})


class RemoteWorld:
    """An inherited private pipe, serialized across application workers."""
    def __init__(self, connection, lock):
        self.connection, self.lock = connection, lock

    def _call(self, method, *args, **kwargs):
        with self.lock:
            self.connection.send((method, args, kwargs))
            if not self.connection.poll(30):
                raise TimeoutError("simulator response exceeded 30 seconds")
            result = self.connection.recv()
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def __getattr__(self, name):
        if name in _METHODS:
            return partial(self._call, name)
        raise AttributeError(name)


class BrokerProcess:
    def __init__(self, process, connection):
        self.process, self.connection = process, connection

    def shutdown(self):
        if self.process.is_alive():
            self.connection.send(("shutdown", (), {}))
            self.process.join(5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(5)
        self.connection.close()


def manager(profile):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_serve, args=(child, profile))
    process.start()
    child.close()
    manager = BrokerProcess(process, parent)
    if not parent.poll(10) or parent.recv() != {"ready": True}:
        manager.shutdown()
        raise RuntimeError("simulator startup failed")
    return manager, RemoteWorld(parent, context.Lock())


def adapter(service, *, kill_after_accept=False):
    from sentinel.execution.alpaca import AlpacaExecutionBroker

    def transport(request):
        result = service.request(request.method, str(request.url), dict(request.headers), request.content)
        if result.get("timeout"):
            raise httpx.ReadTimeout("scheduled loss after broker effect", request=request)
        if kill_after_accept and request.method == "POST" and request.url.path == "/v2/orders" and result["status"] < 300:
            os.kill(os.getpid(), signal.SIGKILL)
        return httpx.Response(result["status"], headers=result["headers"], content=result["body"], request=request)

    class HTTPProvider:
        @staticmethod
        def AsyncClient(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False, **kwargs)

    return AlpacaExecutionBroker(api_key="simulation-key", secret_key="simulation-secret",
        base_url=PAPER_URL, http_provider=lambda: HTTPProvider,
        clock_provider=lambda: datetime.fromisoformat(service.now()),
        resolve_security_id=lambda symbol, _as_of=None: SECURITIES.get(symbol))


def killed_submitter(service):
    """Small child entrypoint proving SIGKILL ordering even before SQL tests."""
    from sentinel.execution.contract import Side
    client = adapter(service, kill_after_accept=True)
    instrument = asyncio.run(client.resolve_instrument(security_id="STATE-S000", symbol="S000"))
    asyncio.run(client.submit(client_key="synthetic-kill-key", instrument=instrument,
                              side=Side.BUY, quantity=Decimal(3)))
