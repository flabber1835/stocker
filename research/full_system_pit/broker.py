"""Process-external historical Alpaca peer; production uses its real adapter."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
import multiprocessing
from functools import partial
import uuid

import httpx

from tests.support.alpaca_simulator import AlpacaSimulator, Profile, PAPER_URL
from tests.internal_state.broker import BrokerProcess


class Service:
    def __init__(self, start):
        self.world = AlpacaSimulator(Profile.LIVE_CASH)
        self.world.now = datetime.fromisoformat(start)
        self.world.assets.clear()
        self.world.prices.clear()
        self.identities, self.openings, self.wire = {}, {}, []

    def request(self, method, url, headers, body):
        request = httpx.Request(method, url, headers=headers, content=body)
        if request.url.host == "data.alpaca.markets" and request.url.path == "/v2/stocks/bars":
            symbols = request.url.params["symbols"].split(",")
            response = httpx.Response(200, json={"bars": {s: [self.openings[s]]
                for s in symbols if s in self.openings}, "next_page_token": None})
        elif request.url.host == "paper-api.alpaca.markets":
            response = self.world.handle(request)
            if method == "POST" and request.url.path == "/v2/orders" and response.status_code < 300:
                order = response.json()
                if self.world._working(order):
                    self.world.fill(order["id"])
        else:
            raise ValueError("request left simulated Alpaca")
        self.wire.append(dict(method=method, url=url, body=body.decode(), status=response.status_code,
                              response=response.content.decode()))
        return dict(status=response.status_code, headers=dict(response.headers), body=response.content)

    def market(self, at, opening_at, rows, *, opened):
        at = datetime.fromisoformat(at)
        self.world.advance(int((at-self.world.now).total_seconds()))
        for row in rows:
            symbol, sid = row["ticker"], row["sid"]
            self.identities[symbol] = sid
            if symbol not in self.world.assets:
                self.world.add_asset(symbol)
                self.world.assets[symbol]["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "pit:"+sid))
            if opened:
                qty = self.world.positions.get(symbol, Decimal(0))
                split = Decimal(str(row.get("split", 1)))
                if qty and split != 1:
                    self.world.positions[symbol] = qty*split
                    self.world._event("SPLIT", Decimal(0), details={"symbol": symbol, "ratio": str(split)})
                dividend = Decimal(str(row.get("dividend", 0)))
                entitlement = self.world.positions.get(symbol, Decimal(0))*dividend
                if entitlement:
                    self.world.cash_event("DIV", str(entitlement))
                if row.get("op") and row.get("raw_volume"):
                    self.openings[symbol] = dict(t=opening_at, o=row["op"], v=row["raw_volume"])
                else:
                    self.openings.pop(symbol, None)
            price = row.get("op" if opened else "raw")
            if price:
                self.world.prices[symbol] = Decimal(str(price))

    def resolve(self, symbol):
        return self.identities.get(symbol)

    def now(self):
        return self.world.now.isoformat()

    def drain(self):
        wire, self.wire = self.wire, []
        return wire

    def snapshot(self):
        w = self.world
        return json.loads(json.dumps(dict(now=w.now.isoformat(), account=w.account(),
            positions=w.positions, prices={s:w.prices[s] for s in w.positions},
            orders=w.orders, fills=w.fills, cash_movements=w.cash_movements,
            initial_cash=w.initial_cash, identities=self.identities), default=str))


METHODS = {"request", "market", "resolve", "now", "snapshot", "drain"}


def serve(connection, start):
    service = Service(start)
    connection.send({"ready": True})
    while True:
        try:
            method, args, kwargs = connection.recv()
        except EOFError:
            return
        if method == "shutdown":
            return
        try:
            if method not in METHODS:
                raise ValueError("invalid broker operation")
            connection.send({"result": getattr(service, method)(*args, **kwargs)})
        except Exception as exc:
            connection.send({"error": f"{type(exc).__name__}: {exc}"})


class Remote:
    def __init__(self, connection):
        self.connection = connection

    def call(self, method, *args, **kwargs):
        self.connection.send((method, args, kwargs))
        if not self.connection.poll(45):
            raise TimeoutError("broker response deadline")
        result = self.connection.recv()
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def __getattr__(self, name):
        if name in METHODS:
            return partial(self.call, name)
        raise AttributeError(name)


def manager(start):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=serve, args=(child, start))
    process.start()
    child.close()
    lifecycle = BrokerProcess(process, parent)
    if not parent.poll(15) or parent.recv() != {"ready": True}:
        lifecycle.shutdown()
        raise RuntimeError("broker startup failed")
    return lifecycle, Remote(parent)


def adapter(service):
    from sentinel.execution.alpaca import AlpacaExecutionBroker

    def transport(request):
        result = service.request(request.method, str(request.url), dict(request.headers), request.content)
        return httpx.Response(result["status"], headers=result["headers"], content=result["body"], request=request)

    class HTTP:
        @staticmethod
        def AsyncClient(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False, **kwargs)

    return AlpacaExecutionBroker(api_key="simulation-key", secret_key="simulation-secret",
        base_url=PAPER_URL, http_provider=lambda: HTTP,
        clock_provider=lambda: datetime.fromisoformat(service.now()),
        resolve_security_id=lambda symbol, _as_of=None: service.resolve(symbol))
