"""Legacy-order cancellation is confirmed by OBSERVATION, never by the API.

THE DEFECT, reproduced 2026-08-09 from a code review before anything changed.
`_execute` called `broker.cancel_orders(...)`, ignored the returned count, and
`establish_ownership` then recorded `LEGACY_ORDERS_CANCELLED` regardless. With a
broker that accepted the call and cancelled nothing, the measured result was:

    cancel attempted exactly ONCE, never retried
    liquidation submitted while the legacy BUY was still working
    LEGACY_ORDERS_CANCELLED recorded after zero cancellations

The trap is structural rather than arithmetic: `LEGACY_ORDERS_CANCELLED` is
deliberately NOT in `_CLEANUP_PHASES` — correctly, because after that point the
open orders are Sentinel's own liquidation sells and cancelling them would fight
its own liquidation forever. So claiming that state prematurely made the cancel
branch permanently unreachable. One optimistic transition disabled the retry.

WHY IT MATTERS ON A PAPER ACCOUNT WITH REAL CONSEQUENCES: cancel-before-sell
exists because a resting legacy BUY can fill AFTER the liquidation has sold
everything, re-creating a position Sentinel has already reported gone — and then
Wealth Core bootstraps onto a book containing a security it never chose.

THE RULE NOW:

    Sentinel may enter LEGACY_ORDERS_CANCELLED only after a FRESH broker
    observation shows zero legacy open orders.

"The broker accepted the cancel" and "the order is gone" are different facts.
Only the second is safe to act on, and only an observation can establish it.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from fakes import FakeBroker  # noqa: E402
from sentinel.ownership import (  # noqa: E402
    AccountObservation, OpenOrder, OwnershipState as S, plan_startup)
from sentinel.startup import (  # noqa: E402
    OwnershipNotEstablished, establish_ownership)
from sentinel.store import InMemoryOwnershipStore  # noqa: E402


def obs(positions=None, orders=()):
    return AccountObservation(positions=dict(positions or {}),
                              open_orders=tuple(orders))


def buy(oid, ticker):
    return OpenOrder(order_id=oid, ticker=ticker, side="buy")


def run(broker, store, *, max_cycles=8):
    async def _go():
        return await establish_ownership(
            broker=broker, store=store, max_cycles=max_cycles,
            poll_seconds=0, sleep=lambda *_: asyncio.sleep(0))
    try:
        return asyncio.run(_go()), None
    except OwnershipNotEstablished as exc:
        return None, exc


def states(store):
    return [e.state.value for e in store.events()]


# ── the planner ──────────────────────────────────────────────────────────────

class TestCancellationIsConfirmedByObservation:

    def test_requesting_a_cancel_does_NOT_claim_it_succeeded(self):
        plan = plan_startup(state=S.UNINITIALIZED,
                            observation=obs({"AAPL": 10}, [buy("o1", "NVDA")]),
                            ownership_established=False)
        assert plan.cancel_order_ids == ("o1",)
        assert plan.next_state is S.LEGACY_CLEANUP_REQUIRED, (
            "advancing here leaves the cancel branch unreachable, because "
            "LEGACY_ORDERS_CANCELLED is not a cleanup phase")

    def test_a_STILL_VISIBLE_order_is_cancelled_AGAIN(self):
        """The retry the old code could not perform."""
        plan = plan_startup(state=S.LEGACY_CLEANUP_REQUIRED,
                            observation=obs({"AAPL": 10}, [buy("o1", "NVDA")]),
                            ownership_established=False)
        assert plan.cancel_order_ids == ("o1",)
        assert plan.next_state is S.LEGACY_CLEANUP_REQUIRED
        assert plan.liquidate_tickers == (), (
            "liquidation started while a legacy order was still working")

    def test_only_an_EMPTY_observation_advances_the_state(self):
        plan = plan_startup(state=S.LEGACY_CLEANUP_REQUIRED,
                            observation=obs({"AAPL": 10}),
                            ownership_established=False)
        assert plan.next_state is S.LEGACY_ORDERS_CANCELLED
        assert "confirmed by observation" in plan.reason

    def test_an_account_with_no_orders_does_not_wait_to_prove_a_negative(self):
        """The confirmation gate applies where a cancel was REQUESTED. An
        account that never had an open order has nothing to confirm, and
        spending a cycle proving the absence of something it never had would
        delay a liquidation for no evidence."""
        plan = plan_startup(state=S.UNINITIALIZED,
                            observation=obs({"AAPL": 10}),
                            ownership_established=False)
        assert plan.liquidate_tickers == ("AAPL",)

    def test_our_OWN_sells_are_still_never_cancelled(self):
        """The property the premature advance was accidentally protecting.
        Past cleanup, open orders are Sentinel's own liquidation sells;
        cancelling them would fight its own liquidation forever."""
        from fakes import FakeBroker as _  # noqa: F401  (import symmetry)
        from sentinel.ownership import OpenOrder as OO
        plan = plan_startup(
            state=S.LIQUIDATION_SUBMITTED,
            observation=obs({"AAPL": 10},
                            [OO(order_id="s1", ticker="AAPL", side="sell")]),
            ownership_established=False)
        assert plan.cancel_order_ids == ()


# ── end to end, against a broker that misbehaves ─────────────────────────────

class _Stubborn(FakeBroker):
    """Accepts every cancel and cancels NOTHING. The exact reported case."""

    async def cancel_orders(self, order_ids):
        self.cancelled.extend(order_ids)
        return 0


class _LiesAboutTheCount(FakeBroker):
    """Reports success for orders it did not touch — the case a count check
    would miss, which is why the count is telemetry and not proof."""

    async def cancel_orders(self, order_ids):
        self.cancelled.extend(order_ids)
        return len(order_ids)


class _CancelsOnTheSecondAsk(FakeBroker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._asks = 0

    async def cancel_orders(self, order_ids):
        self._asks += 1
        self.cancelled.extend(order_ids)
        if self._asks >= 2:
            self.orders = [o for o in self.orders
                           if o.order_id not in set(order_ids)]
        return len(order_ids)


class TestEndToEnd:

    def test_zero_cancellations_never_reaches_liquidation(self):
        b = _Stubborn(positions={"AAPL": 10},
                      orders=[buy("legacy-buy-1", "NVDA")])
        store = InMemoryOwnershipStore()
        res, exc = run(b, store)
        assert res is None and exc is not None, (
            "ownership was established with a live legacy BUY on the book")
        assert b.closes == [], (
            "liquidation ran while a legacy BUY could still refill the account")
        assert b.cancelled.count("legacy-buy-1") > 1, (
            "the cancel was never retried — the defect exactly")
        assert "LEGACY_ORDERS_CANCELLED" not in states(store)

    def test_an_ACCEPTED_cancel_that_did_nothing_is_retried(self):
        """A count check would pass here. Only observation catches it."""
        b = _LiesAboutTheCount(positions={"AAPL": 10},
                               orders=[buy("o1", "NVDA")])
        store = InMemoryOwnershipStore()
        _, exc = run(b, store)
        assert exc is not None
        assert b.cancelled.count("o1") > 1
        assert "LEGACY_ORDERS_CANCELLED" not in states(store)

    def test_PARTIAL_cancellation_keeps_cleaning(self):
        class _OnlyFirst(FakeBroker):
            async def cancel_orders(self, order_ids):
                self.cancelled.extend(order_ids)
                self.orders = [o for o in self.orders if o.order_id != "o1"]
                return len(order_ids)

        b = _OnlyFirst(positions={"AAPL": 10},
                       orders=[buy("o1", "NVDA"), buy("o2", "TSLA")])
        store = InMemoryOwnershipStore()
        _, exc = run(b, store)
        assert exc is not None, "it proceeded with o2 still working"
        assert b.closes == []
        assert b.cancelled.count("o2") > 1

    def test_a_RETRY_that_succeeds_completes_the_handover(self):
        """The control: the gate must not merely block, it must let a genuine
        cleanup through once the orders are actually gone."""
        b = _CancelsOnTheSecondAsk(positions={"AAPL": 10},
                                   orders=[buy("o1", "NVDA")])
        store = InMemoryOwnershipStore()
        res, exc = run(b, store)
        assert exc is None and res is not None and res.bootstrap_allowed
        seq = states(store)
        assert "LEGACY_ORDERS_CANCELLED" in seq
        assert seq.index("LEGACY_ORDERS_CANCELLED") < seq.index("LIQUIDATION_SUBMITTED")
        assert b.closes == ["AAPL"]

    def test_a_legacy_BUY_that_FILLS_during_cleanup_is_liquidated_too(self):
        """The loss mechanism cancel-before-sell exists to prevent. If the buy
        fills anyway, the new position must be treated as legacy and sold — not
        inherited by Wealth Core."""
        class _FillsThenCancels(FakeBroker):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self._asks = 0

            async def cancel_orders(self, order_ids):
                self._asks += 1
                self.cancelled.extend(order_ids)
                if self._asks == 1:
                    # Too late: it filled between the observation and the cancel.
                    self.orders = [o for o in self.orders
                                   if o.order_id not in set(order_ids)]
                    self.positions["NVDA"] = 5
                return len(order_ids)

        b = _FillsThenCancels(positions={"AAPL": 10},
                              orders=[buy("o1", "NVDA")])
        store = InMemoryOwnershipStore()
        res, exc = run(b, store)
        assert exc is None and res.bootstrap_allowed
        assert set(b.closes) == {"AAPL", "NVDA"}, (
            "the position created by the late fill was not liquidated, so "
            "Wealth Core would have inherited it")

    def test_a_RESTART_between_request_and_confirmation_re_cancels(self):
        """State persisted mid-cleanup is LEGACY_CLEANUP_REQUIRED, so a restart
        re-observes and re-cancels rather than resuming as if confirmed."""
        b = _Stubborn(positions={"AAPL": 10}, orders=[buy("o1", "NVDA")])
        store = InMemoryOwnershipStore()
        run(b, store, max_cycles=2)
        assert states(store)[-1] == "LEGACY_CLEANUP_REQUIRED"

        # A new process, same durable store.
        b2 = _CancelsOnTheSecondAsk(positions={"AAPL": 10},
                                    orders=[buy("o1", "NVDA")])
        res, exc = run(b2, store)
        assert exc is None and res.bootstrap_allowed
        assert b2.cancelled, "the restart did not re-attempt the cancellation"

    def test_ownership_is_still_a_NO_OP_once_established(self):
        """The invariant the whole module protects, unchanged by this work: the
        same code path that empties a legacy book will happily empty a live
        one."""
        b = FakeBroker(positions={"AAPL": 10})
        store = InMemoryOwnershipStore()
        res, exc = run(b, store)
        assert exc is None and res.bootstrap_allowed
        b2 = FakeBroker(positions={"WEALTH": 42})
        res2, _ = run(b2, store)
        assert res2.cycles == 0 and b2.closes == []
