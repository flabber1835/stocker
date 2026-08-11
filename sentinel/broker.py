"""Sentinel's broker/execution seam.

Deliberately NOT a direct dependency on `AlpacaBrokerAdapter`. The startup
liquidation is the first piece of Sentinel's execution layer, not throwaway
migration code — item I (share-level execution projection) sits behind this same
interface, so today's work is load-bearing later.

The interface is narrower than `BrokerAdapter` on purpose. Sentinel needs to
read the account, cancel, close, and reconcile; it does not need the twelve-method
surface Stocker's executor grew. A small seam is also a testable one: the fake in
`tests/sentinel/` implements five methods, not twelve, so the state machine can be
driven through timeouts and partial fills without HTTP.

```text
sentinel/startup.py         the ownership state machine's executor
      |
      v
SentinelBroker              this interface
      |
      v
AlpacaSentinelBroker        wraps the PROVEN AlpacaBrokerAdapter
      |
      v
Alpaca PAPER account
```

**Positions are closed with `close_position`, not a sized sell.** Alpaca computes
the exact held quantity at execution, so it cannot over-sell a fractional
position or race a quantity that drifted since the last read — and a 404 maps to
"already closed" rather than an error. Idempotency does not come from that call
being safe to repeat (it is not: a second close while the first is working would
submit a second sell). It comes from the state machine refusing to close a ticker
that already has a working sell.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional

from stock_strategy_shared.broker.base import AccountSnapshot, BrokerAdapter

from sentinel.ownership import AccountObservation, OpenOrder

#: Broker order states that mean "still working, could still fill". Anything
#: outside this is terminal and no longer claims a position. Kept here rather than
#: imported from Stocker's `order_status` because Sentinel reads the BROKER's
#: vocabulary directly; it has no `alpaca_orders` table to normalise into.
OPEN_ORDER_STATES = frozenset({
    "new",
    "accepted",
    "pending_new",
    "accepted_for_bidding",
    "partially_filled",
    "done_for_day",
    "held",
    "pending_replace",
    "replaced",
    "calculated",
    "suspended",
})


@dataclass(frozen=True)
class CloseResult:
    ticker: str
    broker_order_id: Optional[str]
    status: Optional[str]
    error: Optional[str]

    @property
    def accepted(self) -> bool:
        return self.error is None


class SentinelBroker(abc.ABC):
    """Transport only. It never decides what to trade — the state machine does."""

    @abc.abstractmethod
    async def account(self) -> Optional[AccountSnapshot]:
        """Equity, cash, buying power. Audit context for the handover record."""

    @abc.abstractmethod
    async def observe(self) -> AccountObservation:
        """Read working orders AND positions as one observation.

        One method rather than two because the state machine must never reason
        across a gap: positions read at T and orders read at T+2s can describe a
        world that never existed, and the conclusion "held with no working sell"
        drawn from it would submit a duplicate close.

        **NO BROKER OFFERS AN ATOMIC SNAPSHOT OF BOTH**, so this method's job is
        not to pretend otherwise — it is to order the two reads so that a fill
        landing between them cannot make an object DISAPPEAR. See
        `AlpacaSentinelBroker.observe` for why the order is orders-then-positions
        and not the reverse; the contract is
        docs/sentinel-execution-contract.md §5.3, invariant 21.
        """

    @abc.abstractmethod
    async def cancel_orders(self, order_ids: tuple[str, ...]) -> int:
        """Cancel the named orders. Returns how many the broker accepted."""

    @abc.abstractmethod
    async def close_position(self, ticker: str) -> CloseResult:
        """Close 100% of `ticker`."""


class AlpacaSentinelBroker(SentinelBroker):
    """`SentinelBroker` backed by Stocker's proven `AlpacaBrokerAdapter`.

    This is the retirement's distinction made concrete: the adapter is a
    COMPONENT carried forward, not a SERVICE brought back up. No Stocker
    container runs for any of this.
    """

    def __init__(self, adapter: BrokerAdapter) -> None:
        self._adapter = adapter

    @property
    def adapter(self) -> BrokerAdapter:
        return self._adapter

    def has_credentials(self) -> bool:
        return self._adapter.has_credentials()

    async def account(self) -> Optional[AccountSnapshot]:
        return await self._adapter.get_account()

    async def observe(self) -> AccountObservation:
        """ORDERS FIRST, THEN POSITIONS. The order is the correctness property.

        The two reads cannot be atomic, so something can move between them. The
        question is which direction it moves, and only one ordering is safe:

        ```text
        positions, then orders            orders, then positions
        ─────────────────────             ──────────────────────
        t0 positions -> empty             t0 orders    -> [BUY]     seen
           (a resting BUY has not filled)    ...or -> empty (already filled)
        t1 the BUY FILLS                  t1 the BUY FILLS
        t2 orders -> empty                t2 positions -> [POSITION] seen
           (it is no longer OPEN)
           => concluded FLAT while             => never flat. Costs one cycle.
              holding a position
        ```

        Under positions-first the object is missed by BOTH reads: it left the
        set that was already read and entered the set that was read too early.
        Under orders-first a fill can only move evidence from the not-yet-read
        set into the about-to-be-read set, so it cannot vanish.

        The asymmetry is what matters. A false NOT-flat costs one poll interval.
        A false FLAT is irreversible: `plan_startup` returns FLAT_CONFIRMED and
        `establish_ownership` immediately records SENTINEL_OWNERSHIP_ESTABLISHED,
        so one bad observation ends the migration permanently and Wealth Core
        bootstraps onto an inherited position wearing Sentinel's colours.

        This does NOT make the observation atomic, and it does not cover a third
        party acting between the reads. Irreversible conclusions additionally
        require two consecutive agreeing observations — see
        docs/sentinel-execution-contract.md §5.3.
        """
        orders = await self._adapter.list_orders(status="open")
        positions = await self._adapter.get_positions()
        held = {p.ticker: float(p.qty or 0.0) for p in positions}
        open_orders: list[OpenOrder] = []
        for o in orders:
            raw = o.raw or {}
            raw_status = str(raw.get("status") or o.raw_status or "").lower()
            # `status="open"` is the broker's filter and we trust it, but a
            # terminal row slipping through would make a filled sell look like a
            # working one and stall the machine at LIQUIDATION_PENDING forever.
            if raw_status and raw_status not in OPEN_ORDER_STATES:
                continue
            symbol = raw.get("symbol")
            ticker = (
                self._adapter.from_broker_symbol(str(symbol)) if symbol else ""
            )
            open_orders.append(
                OpenOrder(
                    order_id=o.broker_order_id,
                    ticker=ticker,
                    side=str(raw.get("side") or ""),
                )
            )
        return AccountObservation(
            positions=held, open_orders=tuple(open_orders)
        )

    async def cancel_orders(self, order_ids: tuple[str, ...]) -> int:
        """Cancels by ID, one at a time, rather than via `cancel_all_orders`.

        `DELETE /v2/orders` would be one round trip, but it cancels EVERYTHING —
        including orders this machine has already submitted, if the caller's view
        of the phase were ever wrong. Naming the IDs makes the blast radius
        exactly the set the state machine decided on.
        """
        cancelled = 0
        for oid in order_ids:
            if await self._cancel_one(oid):
                cancelled += 1
        return cancelled

    async def _cancel_one(self, order_id: str) -> bool:
        cancel = getattr(self._adapter, "cancel_order", None)
        if cancel is not None:
            return bool(await cancel(order_id))
        # The adapter interface does not require a single-order cancel. Falling
        # back to cancel-all is acceptable ONLY in the cleanup phase, where by
        # construction every working order is legacy — which is why the state
        # machine restricts cancellation to that phase.
        status, _body, _text = await self._adapter.cancel_all_orders()
        return 200 <= int(status) < 300

    async def close_position(self, ticker: str) -> CloseResult:
        order_id, status, error = await self._adapter.close_position(ticker)
        return CloseResult(
            ticker=ticker, broker_order_id=order_id, status=status, error=error
        )
