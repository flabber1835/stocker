"""A paper account that behaves like Alpaca where it matters: a close creates
a WORKING sell order, and fills are not instantaneous.

Shared by the state-machine and CLI suites so both drive the SAME broker
behaviour — two fakes that drift is how a seam gets tested twice and covered
once.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'shared'))

from sentinel.broker import CloseResult, SentinelBroker  # noqa: E402
from sentinel.execution.contract import CommandOutcome  # noqa: E402
from sentinel.execution.states import CommandState  # noqa: E402
from sentinel.ownership import AccountObservation, OpenOrder  # noqa: E402


class FakeBroker(SentinelBroker):
    """A paper account that behaves like Alpaca in the ways that matter:
    a close creates a WORKING sell order, and fills are not instantaneous."""

    def __init__(self, positions=None, orders=(), *, fills_after=1, fail_close=()):
        self.positions = dict(positions or {})
        self.orders = list(orders)
        self.fills_after = fills_after          # cycles a sell works before filling
        self.fail_close = set(fail_close)       # tickers whose close is refused
        self.closes: list[str] = []             # every close ATTEMPT, in order
        self.cancelled: list[str] = []
        self._age: dict[str, int] = {}
        self._by_key: dict[str, OpenOrder] = {}

    async def account(self):
        return None

    async def observe(self) -> AccountObservation:
        # Age working sells; fill them when they mature. Ordered before the
        # snapshot so a fill is visible on the cycle it happens.
        for o in list(self.orders):
            if o.side == "sell":
                self._age[o.order_id] = self._age.get(o.order_id, 0) + 1
                if self._age[o.order_id] > self.fills_after:
                    self.orders.remove(o)
                    self.positions.pop(o.ticker, None)
                    if o.client_key:
                        self._by_key[o.client_key] = replace(
                            o, state=CommandState.FILLED,
                            filled_quantity=o.quantity,
                            filled_average_price=Decimal("100"))
        return AccountObservation(
            positions=dict(self.positions),
            position_security_ids={
                ticker: f"asset-{ticker}" for ticker in self.positions},
            open_orders=tuple(self.orders)
        )

    async def cancel_orders(self, order_ids):
        for oid in order_ids:
            self.cancelled.append(oid)
            self.orders = [o for o in self.orders if o.order_id != oid]
        return len(order_ids)

    async def close_position(self, ticker) -> CloseResult:
        self.closes.append(ticker)
        if ticker in self.fail_close:
            return CloseResult(ticker, None, None, "halted")
        oid = f"close-{ticker}-{len(self.closes)}"
        self.orders.append(OpenOrder(order_id=oid, ticker=ticker, side="sell"))
        return CloseResult(ticker, oid, "accepted", None)

    async def find_liquidation(self, client_key):
        return self._by_key.get(client_key)

    async def submit_liquidation(self, command):
        ticker = command.instrument.symbol
        self.closes.append(ticker)
        if ticker in self.fail_close:
            return CommandOutcome(
                CommandState.REJECTED, detail="halted")
        oid = f"close-{ticker}-{len(self.closes)}"
        order = OpenOrder(
            order_id=oid, ticker=ticker, side="sell",
            client_key=command.client_key,
            state=CommandState.ACKNOWLEDGED,
            quantity=command.quantity, filled_quantity=Decimal(0),
            broker_instrument_id=command.instrument.broker_id)
        self.orders.append(order)
        self._by_key[command.client_key] = order
        return CommandOutcome(
            CommandState.ACKNOWLEDGED, broker_order_id=oid,
            detail="accepted")
