"""The account must never be classified FLAT while it holds a position.

THE DEFECT, from a code review of `AlpacaSentinelBroker.observe`. The two broker
reads cannot be atomic, and the implementation performed them in the one order
that lets an object disappear from BOTH:

    t0  get_positions()          -> empty      a resting legacy BUY has not filled
    t1  the BUY FILLS
    t2  list_orders(open)        -> empty      it is no longer OPEN
        => AccountObservation.is_flat() is True, holding a position

The object left the set that had already been read and entered the set that was
read too early. Reversing the order makes that impossible: a fill can only move
evidence from the not-yet-read set into the about-to-be-read set.

WHY IT IS NOT MERELY A RACE. `plan_startup` maps `is_flat()` straight to
FLAT_CONFIRMED, and `establish_ownership` then records
SENTINEL_OWNERSHIP_ESTABLISHED in the same breath — an IRREVERSIBLE decision.
So one bad observation ends the migration permanently, and Wealth Core boots
onto an inherited legacy position wearing Sentinel's colours. That is precisely
the ambiguity the whole ownership state machine exists to remove.

The asymmetry is the argument for the fix:

    false FLAT       irreversible, and hands Wealth Core a book it did not choose
    false NOT-flat   costs one poll interval

NOTE ON THE INTERLEAVING. It is tempting to write this test as "an open BUY is
observed, then it fills". That version passes against the BROKEN code, because
the BUY was seen. The failure requires the BUY to be invisible as an order at
every moment it is looked for — pre-fill it is not yet a position, post-fill it
is not an open order. The fake below flips state exactly once, on the first read,
whichever read that is, so the same fixture reproduces the bug under the old
ordering and cannot under the new one.

Contract: docs/sentinel-execution-contract.md §5.3, invariant 21.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from decimal import Decimal

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.broker import (  # noqa: E402
    AdministrativeObservationRefused, AlpacaSentinelBroker)
from sentinel.ownership import (  # noqa: E402
    AccountObservation, OwnershipState as S, plan_startup)
from stock_strategy_shared.broker.base import (  # noqa: E402
    BrokerAdapter, BrokerOrder, BrokerPosition)


class FillsBetweenReadsAdapter(BrokerAdapter):
    """A broker whose resting BUY fills between the observation's two reads.

    The fill is triggered by the FIRST read to arrive, not by a clock, so the
    fixture is ordering-agnostic: it reproduces whatever hazard the ordering
    under test actually has, rather than encoding one ordering's assumptions.
    """

    name = "fills-between-reads"

    def __init__(self, ticker: str = "LEGACY", qty: float = 10.0) -> None:
        super().__init__()
        self.ticker = ticker
        self.qty = qty
        self.filled = False
        self.reads: list[str] = []

    def _tick(self, which: str) -> None:
        self.reads.append(which)
        if len(self.reads) == 1:
            # The BUY fills the instant the first read is taken. Before this it
            # is a working order and no position; after it, a position and no
            # working order. It is never both, and never neither.
            self.filled = True

    def has_credentials(self) -> bool:
        return True

    async def get_account(self):
        return None

    async def get_positions(self) -> list[BrokerPosition]:
        pre = not self.filled
        self._tick("positions")
        return [] if pre else [BrokerPosition(
            ticker=self.ticker, qty=Decimal(str(self.qty)),
            side="long",
            broker_instrument_id="asset-legacy")]

    async def list_orders(self, *, status: str = "all", limit: int = 500):
        pre = not self.filled
        self._tick("orders")
        if not pre:
            return []
        return [BrokerOrder(
            broker_order_id="legacy-buy-1", status=None, raw_status="new",
            symbol=self.ticker, side="buy", quantity=Decimal("10"),
            filled_qty=Decimal(0), broker_instrument_id="asset-legacy",
            raw={"status": "new", "symbol": self.ticker, "side": "buy"})]

    async def get_order(self, broker_order_id: str):
        return None

    async def get_clock(self):
        return None

    def normalize_status(self, raw_status: str):
        return None

    async def submit_order(self, payload: dict):
        raise AssertionError("observation must not submit")

    async def close_position(self, symbol: str):
        raise AssertionError("observation must not close")

    async def cancel_all_orders(self):
        raise AssertionError("observation must not cancel")


async def _observe_positions_first(adapter) -> AccountObservation:
    """The ORIGINAL, REJECTED ordering — kept only so the test can prove it is
    the thing that breaks. Mirrors the shipped code before the fix."""
    positions = await adapter.get_positions()
    orders = await adapter.list_orders(status="open")
    held = {p.ticker: float(p.qty or 0.0) for p in positions}
    open_orders = tuple(
        __import__("sentinel.ownership", fromlist=["OpenOrder"]).OpenOrder(
            order_id=o.broker_order_id,
            ticker=str((o.raw or {}).get("symbol") or ""),
            side=str((o.raw or {}).get("side") or ""))
        for o in orders)
    return AccountObservation(positions=held, open_orders=open_orders)


def test_the_rejected_ordering_really_does_lose_the_position():
    """The fixture is only meaningful if it reproduces the bug. Prove it does.

    Without this the test could pass for the wrong reason — a fake that never
    reproduced the hazard would make the fix look verified when nothing was.
    """
    adapter = FillsBetweenReadsAdapter()
    observation = asyncio.run(_observe_positions_first(adapter))

    assert adapter.reads == ["positions", "orders"]
    assert observation.held_tickers() == ()
    assert observation.open_orders == ()
    assert observation.is_flat() is True, (
        "the rejected ordering is supposed to produce the false flat; if it no "
        "longer does, this fixture has stopped exercising the defect")


def test_orders_before_positions_cannot_conclude_flat():
    """The three-read observation detects the fill crossing its boundary."""
    adapter = FillsBetweenReadsAdapter()
    with pytest.raises(AdministrativeObservationRefused, match="changed across"):
        asyncio.run(AlpacaSentinelBroker(adapter).observe())

    assert adapter.reads == ["orders", "positions", "orders"]


def test_the_false_flat_would_have_established_ownership_irreversibly():
    """Why the ordering matters: `is_flat` feeds a decision that never un-happens."""
    flat = asyncio.run(_observe_positions_first(FillsBetweenReadsAdapter()))
    plan = plan_startup(state=S.UNINITIALIZED, observation=flat,
                        ownership_established=False)
    assert plan.next_state is S.FLAT_CONFIRMED, (
        "this is the blast radius: FLAT_CONFIRMED is followed immediately by "
        "SENTINEL_OWNERSHIP_ESTABLISHED, so a single bad observation ends the "
        "migration permanently")

    with pytest.raises(AdministrativeObservationRefused):
        asyncio.run(AlpacaSentinelBroker(FillsBetweenReadsAdapter()).observe())


def test_source_reads_orders_before_positions():
    """A structural guard, because the behavioural test above can be satisfied
    by a fake while the real call order regresses under a refactor."""
    src = inspect.getsource(AlpacaSentinelBroker.observe)
    body = src.split('"""')[-1]          # strip the docstring, which names both
    assert body.index("list_orders") < body.index("get_positions"), (
        "AlpacaSentinelBroker.observe must call list_orders before "
        "get_positions — see docs/sentinel-execution-contract.md invariant 21")
