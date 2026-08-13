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

Administrative positions are read with a stable broker asset id and exact
Decimal quantity, then closed by a named SELL persisted before send. The old
broker-native close method remains only for compatibility with retired component
tests; the production handover never calls it because it cannot carry a client
key and cannot resolve an accept-then-timeout outcome.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from stock_strategy_shared.broker.base import AccountSnapshot, BrokerAdapter

from sentinel.ownership import AccountObservation, OpenOrder
from sentinel.execution.commands import Command
from sentinel.execution.contract import CommandOutcome
from sentinel.execution.states import CommandState

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
    "pending_cancel",
    "replaced",
    "calculated",
    "stopped",
    "suspended",
})

TERMINAL_ORDER_STATES = frozenset({
    "filled", "canceled", "cancelled", "expired", "rejected",
})


class AdministrativeObservationRefused(RuntimeError):
    """Malformed or self-contradictory evidence cannot drive migration."""


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

    async def find_liquidation(self, client_key: str) -> Optional[OpenOrder]:
        """Resolve a migration order by its exact durable client key."""
        raise NotImplementedError(
            "this administrative adapter has no exact client-key lookup")

    async def submit_liquidation(self, command: Command) -> CommandOutcome:
        """Submit one exact-sized SELL carrying ``command.client_key``."""
        raise NotImplementedError(
            "this administrative adapter cannot submit named liquidations")


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
        # The administrative adapter's contract is COMPLETE OR RAISE. Alpaca
        # pages this read by stable order id; deliberately let an incomplete
        # response propagate so migration cannot convert a capped prefix into
        # an empty/flat account.
        orders = await self._adapter.list_orders(status="open", limit=500)
        positions = await self._adapter.get_positions()
        orders_after = await self._adapter.list_orders(
            status="open", limit=500)
        first = tuple(self._admin_order(order) for order in orders)
        second = tuple(self._admin_order(order) for order in orders_after)
        if first != second:
            raise AdministrativeObservationRefused(
                "open orders changed across the orders/positions/orders read; "
                "the account observation is not a coherent instant")

        held: dict[str, Decimal] = {}
        identities: dict[str, str] = {}
        for position in positions:
            ticker = str(position.ticker or "").strip()
            asset_id = str(position.broker_instrument_id or "").strip()
            side = str(position.side or "").strip().lower()
            quantity = position.qty
            if (not ticker or not asset_id or side != "long"
                    or not isinstance(quantity, Decimal)
                    or not quantity.is_finite() or quantity <= 0):
                raise AdministrativeObservationRefused(
                    f"malformed legacy position: ticker={ticker!r}, "
                    f"asset_id={asset_id!r}, side={side!r}, "
                    f"quantity={quantity!r}; migration accepts long "
                    "positions only")
            if ticker in held or asset_id in identities.values():
                raise AdministrativeObservationRefused(
                    f"duplicate legacy position identity {ticker}/{asset_id}")
            held[ticker] = quantity
            identities[ticker] = asset_id
        return AccountObservation(
            positions=held, position_security_ids=identities,
            open_orders=first)

    def _admin_order(self, order) -> OpenOrder:
        raw_status = str(order.raw_status or "").strip().lower()
        if not raw_status:
            raise AdministrativeObservationRefused(
                f"order {order.broker_order_id!r} omitted status")
        if raw_status in TERMINAL_ORDER_STATES:
            raise AdministrativeObservationRefused(
                f"status=open returned terminal order "
                f"{order.broker_order_id}/{raw_status}")
        order_id = str(order.broker_order_id or "").strip()
        ticker = str(order.symbol or "").strip()
        side = str(order.side or "").strip().lower()
        quantity = order.quantity
        filled = order.filled_qty
        average = order.avg_fill_price
        broker_instrument_id = str(
            order.broker_instrument_id or "").strip()
        if (not order_id or not ticker or side not in {"buy", "sell"}
                or not broker_instrument_id
                or not isinstance(quantity, Decimal)
                or not quantity.is_finite() or quantity <= 0
                or not isinstance(filled, Decimal)
                or not filled.is_finite() or filled < 0 or filled > quantity
                or (average is not None and (
                    not isinstance(average, Decimal)
                    or not average.is_finite() or average <= 0))
                or (filled > 0 and average is None)):
            raise AdministrativeObservationRefused(
                f"malformed open order {order_id!r}: symbol={ticker!r}, "
                f"side={side!r}, qty={quantity!r}, filled={filled!r}, "
                f"average={average!r}")
        return OpenOrder(
            order_id=order_id, ticker=ticker, side=side,
            client_key=order.client_order_id,
            state=_migration_state(raw_status), quantity=quantity,
            filled_quantity=filled,
            filled_average_price=average,
            broker_instrument_id=broker_instrument_id)

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
        # Exact-id cancellation is required. Expanding one approved id into
        # cancel-all would mutate orders that arrived after the observation.
        raise NotImplementedError(
            "migration requires exact single-order cancellation; cancel-all "
            "is not a safe fallback")

    async def close_position(self, ticker: str) -> CloseResult:
        order_id, status, error = await self._adapter.close_position(ticker)
        return CloseResult(
            ticker=ticker, broker_order_id=order_id, status=status, error=error
        )

    async def find_liquidation(self, client_key: str) -> Optional[OpenOrder]:
        order = await self._adapter.get_order_by_client_order_id(client_key)
        if order is None:
            return None
        raw_status = str(order.raw_status or "").strip().lower()
        order_id = str(order.broker_order_id or "").strip()
        ticker = str(order.symbol or "").strip()
        side = str(order.side or "").strip().lower()
        quantity = order.quantity
        filled = order.filled_qty
        average = order.avg_fill_price
        broker_instrument_id = str(
            order.broker_instrument_id or "").strip()
        if (not raw_status or not order_id or not ticker
                or side not in {"buy", "sell"}
                or not broker_instrument_id
                or not isinstance(quantity, Decimal) or quantity <= 0
                or not quantity.is_finite()
                or not isinstance(filled, Decimal) or filled < 0
                or not filled.is_finite() or filled > quantity
                or (average is not None and (
                    not isinstance(average, Decimal)
                    or not average.is_finite() or average <= 0))
                or (filled > 0 and average is None)):
            raise AdministrativeObservationRefused(
                f"malformed exact-order response for {client_key}")
        return OpenOrder(
            order_id=order_id, ticker=ticker, side=side,
            client_key=order.client_order_id,
            state=_migration_state(raw_status), quantity=quantity,
            filled_quantity=filled,
            filled_average_price=average,
            broker_instrument_id=broker_instrument_id)

    async def submit_liquidation(self, command: Command) -> CommandOutcome:
        if command.side.value != "SELL":
            raise ValueError("legacy liquidation commands must be SELLs")
        order_id, raw_status, error = await self._adapter.submit_order({
            "symbol": command.instrument.symbol,
            "qty": str(command.quantity),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": command.client_key,
        })
        if error is not None:
            # The carried-forward adapter's legacy triple does not include the
            # HTTP status, so its free-form error cannot prove whether the
            # broker rejected the request before acceptance or accepted it and
            # lost the response behind a 5xx/proxy. Treat the outcome as
            # UNKNOWN and resolve the durable key exactly; guessing REJECTED
            # here would license a second SELL.
            return CommandOutcome(
                state=CommandState.UNKNOWN, detail=str(error))
        if not order_id:
            return CommandOutcome(
                state=CommandState.UNKNOWN,
                detail="broker accepted migration submit without an order id")
        return CommandOutcome(
            state=CommandState.ACKNOWLEDGED,
            broker_order_id=str(order_id), detail=str(raw_status or "accepted"))


def _migration_state(raw_status: str) -> CommandState:
    raw = str(raw_status).strip().lower()
    if raw == "filled":
        return CommandState.FILLED
    if raw == "partially_filled":
        return CommandState.PARTIALLY_FILLED
    if raw in {"canceled", "cancelled", "expired"}:
        return CommandState.CANCELLED
    if raw == "rejected":
        return CommandState.REJECTED
    if raw == "pending_cancel":
        return CommandState.CANCEL_PENDING
    if not raw:
        raise AdministrativeObservationRefused("order status is empty")
    # A future status returned by status=open remains conservatively working.
    return CommandState.ACKNOWLEDGED
