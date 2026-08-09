"""The startup orchestrator driven end-to-end against a fake broker.

`test_ownership.py` proves the RULES. This proves the LOOP: that a real sequence
of observations — orders cancelled, closes submitted, fills arriving one at a
time, a transport error in the middle — converges on a single clean handover and
never submits a duplicate close.

The fake implements `SentinelBroker`'s five methods. That it can is the argument
for the interface being narrow.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.broker import CloseResult, SentinelBroker  # noqa: E402
from sentinel.ownership import AccountObservation, OpenOrder, OwnershipState  # noqa: E402
from sentinel.startup import (  # noqa: E402
    OwnershipNotEstablished,
    establish_ownership,
)
from sentinel.store import InMemoryOwnershipStore, ownership_established, record  # noqa: E402

S = OwnershipState


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
        return AccountObservation(
            positions=dict(self.positions), open_orders=tuple(self.orders)
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


async def _noop_sleep(_seconds):
    return None


def run(coro):
    return asyncio.run(coro)


class TestTheHandover:
    def test_a_legacy_book_is_liquidated_exactly_once_and_ownership_recorded(self):
        broker = FakeBroker({"AAPL": 10, "MSFT": 5, "NVDA": 2})
        store = InMemoryOwnershipStore()
        result = run(establish_ownership(broker=broker, store=store, sleep=_noop_sleep))

        assert result.bootstrap_allowed is True
        assert result.state is S.WEALTH_CORE_BOOTSTRAP_ALLOWED
        # THE duplicate-close check: three positions, three closes. Not four.
        assert sorted(broker.closes) == ["AAPL", "MSFT", "NVDA"]
        assert len(broker.closes) == len(set(broker.closes))
        assert ownership_established(store) is True

        states = [e.state for e in store.events()]
        assert S.FLAT_CONFIRMED in states
        assert states[-1] is S.WEALTH_CORE_BOOTSTRAP_ALLOWED
        # Two distinct events, in order — flatness observed, then ownership decided.
        assert states.index(S.FLAT_CONFIRMED) < states.index(
            S.SENTINEL_OWNERSHIP_ESTABLISHED)

    def test_legacy_orders_are_cancelled_before_any_close(self):
        broker = FakeBroker(
            {"AAPL": 10}, [OpenOrder(order_id="legacy-buy", ticker="NVDA", side="buy")]
        )
        run(establish_ownership(broker=broker, store=InMemoryOwnershipStore(),
                                sleep=_noop_sleep))
        assert broker.cancelled == ["legacy-buy"]

    def test_an_already_flat_account_establishes_ownership_without_trading(self):
        broker = FakeBroker({})
        result = run(establish_ownership(broker=broker, store=InMemoryOwnershipStore(),
                                         sleep=_noop_sleep))
        assert broker.closes == []
        assert result.bootstrap_allowed is True

    def test_slow_fills_do_not_provoke_duplicate_closes(self):
        """Four cycles of a working sell must still produce ONE close."""
        broker = FakeBroker({"AAPL": 10}, fills_after=4)
        run(establish_ownership(broker=broker, store=InMemoryOwnershipStore(),
                                sleep=_noop_sleep))
        assert broker.closes == ["AAPL"]

    def test_a_refused_close_is_retried_and_does_not_abort_the_others(self):
        broker = FakeBroker({"AAPL": 10, "MSFT": 5}, fail_close={"AAPL"})
        with pytest.raises(OwnershipNotEstablished):
            run(establish_ownership(broker=broker, store=InMemoryOwnershipStore(),
                                    max_cycles=3, sleep=_noop_sleep))
        assert "MSFT" in broker.closes          # the healthy one still went
        assert broker.closes.count("AAPL") > 1  # the halted one was retried

    def test_an_unclosable_book_REFUSES_bootstrap(self):
        """Wealth Core must not start onto an account whose ownership is
        unresolved — it could not tell the legacy book from its own."""
        broker = FakeBroker({"AAPL": 10}, fail_close={"AAPL"})
        store = InMemoryOwnershipStore()
        with pytest.raises(OwnershipNotEstablished, match="not flat"):
            run(establish_ownership(broker=broker, store=store, max_cycles=3,
                                    sleep=_noop_sleep))
        assert ownership_established(store) is False


class TestRestartSafety:
    def test_restart_after_ownership_NEVER_touches_the_book(self):
        """The falsifier, at the orchestrator level: a full Wealth Core book, a
        store that already says we own it, and a restart."""
        broker = FakeBroker({"AAPL": 100, "MSFT": 200, "GOOG": 50})
        store = InMemoryOwnershipStore()
        record(store, S.SENTINEL_OWNERSHIP_ESTABLISHED)

        result = run(establish_ownership(broker=broker, store=store, sleep=_noop_sleep))

        assert broker.closes == [], "Sentinel liquidated its OWN book"
        assert broker.cancelled == []
        assert result.bootstrap_allowed is True
        assert result.cycles == 0
        assert broker.positions == {"AAPL": 100, "MSFT": 200, "GOOG": 50}

    def test_restart_mid_liquidation_does_not_duplicate(self):
        """First run dies after submitting; second run resumes against a broker
        that already carries the working sell."""
        broker = FakeBroker({"AAPL": 10, "MSFT": 5}, fills_after=99)
        store = InMemoryOwnershipStore()
        with pytest.raises(OwnershipNotEstablished):
            run(establish_ownership(broker=broker, store=store, max_cycles=2,
                                    sleep=_noop_sleep))
        submitted = list(broker.closes)
        assert submitted, "nothing was submitted, so the test proves nothing"

        broker.fills_after = 1
        run(establish_ownership(broker=broker, store=store, sleep=_noop_sleep))
        for ticker in set(submitted):
            assert broker.closes.count(ticker) == 1, (
                f"{ticker} was closed twice across the restart — a second close "
                f"while the first works sells into a SHORT position")

    def test_a_second_full_run_is_a_no_op(self):
        broker = FakeBroker({"AAPL": 10})
        store = InMemoryOwnershipStore()
        run(establish_ownership(broker=broker, store=store, sleep=_noop_sleep))
        first = list(broker.closes)

        broker.positions = {"NVDA": 42}          # Wealth Core has since bought
        run(establish_ownership(broker=broker, store=store, sleep=_noop_sleep))
        assert broker.closes == first
        assert broker.positions == {"NVDA": 42}
