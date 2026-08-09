"""Sentinel's startup ownership boundary.

The hard one is `TestOwnershipIsIrreversible`. The same code path that empties a
legacy Stocker book will happily empty a Wealth Core book — they are both "the
positions at the broker" — and the only thing separating them is a persisted
decision. If that decision can be lost, forgotten, or out-voted by an
observation, Sentinel liquidates its own portfolio on a restart.

Every test here drives the PURE planner or a fake broker. None reaches Alpaca.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.ownership import (  # noqa: E402
    AccountObservation,
    LIQUIDATION_REASON,
    OpenOrder,
    OwnershipState,
    plan_startup,
)
from sentinel.store import (  # noqa: E402
    FileOwnershipStore,
    InMemoryOwnershipStore,
    OwnershipEvent,
    current_state,
    ownership_established,
    record,
)

S = OwnershipState


def obs(positions=None, orders=()):
    return AccountObservation(positions=positions or {}, open_orders=tuple(orders))


def sell(oid, ticker):
    return OpenOrder(order_id=oid, ticker=ticker, side="sell")


def buy(oid, ticker):
    return OpenOrder(order_id=oid, ticker=ticker, side="buy")


class TestOwnershipIsIrreversible:
    """THE falsifier. Everything else is secondary to this."""

    @pytest.mark.parametrize("state", list(OwnershipState))
    def test_an_owned_book_is_NEVER_liquidated(self, state):
        """Whatever the recorded state, an established owner does not liquidate.

        Parametrised across every state because the danger is a state field that
        got rolled back, hand-edited or written by an older build. Ownership must
        out-rank it in all of them.
        """
        plan = plan_startup(
            state=state,
            observation=obs({"AAPL": 100, "MSFT": 50}),
            ownership_established=True,
        )
        assert plan.liquidate_tickers == ()
        assert plan.cancel_order_ids == ()
        assert plan.is_liquidating is False
        assert plan.next_state is S.WEALTH_CORE_BOOTSTRAP_ALLOWED

    def test_the_same_book_IS_liquidated_when_ownership_is_not_established(self):
        """The control. Without this the test above could pass on a planner that
        never liquidates anything."""
        plan = plan_startup(
            state=S.UNINITIALIZED,
            observation=obs({"AAPL": 100, "MSFT": 50}),
            ownership_established=False,
        )
        assert set(plan.liquidate_tickers) == {"AAPL", "MSFT"}
        assert LIQUIDATION_REASON in plan.reason

    def test_ownership_established_has_NO_default(self):
        """A default would let a call site inherit the dangerous answer by saying
        nothing — the crash brake's `prior=` lesson."""
        with pytest.raises(TypeError):
            plan_startup(state=S.UNINITIALIZED, observation=obs())  # type: ignore[call-arg]

    def test_ownership_survives_later_events_in_the_log(self):
        """`ownership_established` searches the whole history, not the tail. A
        decision taken cannot become untaken by something recorded afterwards."""
        store = InMemoryOwnershipStore()
        record(store, S.FLAT_CONFIRMED)
        record(store, S.SENTINEL_OWNERSHIP_ESTABLISHED)
        record(store, S.WEALTH_CORE_BOOTSTRAP_ALLOWED)
        record(store, S.ACCOUNT_INSPECTED)  # a later, lower state
        assert current_state(store) is S.ACCOUNT_INSPECTED
        assert ownership_established(store) is True

    def test_a_naturally_flat_wealth_core_book_is_not_a_migration(self):
        """Wealth Core books go flat on their own — a full rotation, a crash
        brake, a last stop. If flatness were the ownership signal, the first such
        day would read as 'migration never completed'."""
        store = InMemoryOwnershipStore()
        record(store, S.SENTINEL_OWNERSHIP_ESTABLISHED)
        assert ownership_established(store) is True
        plan = plan_startup(
            state=S.WEALTH_CORE_BOOTSTRAP_ALLOWED,
            observation=obs(),  # flat, as a rotated book can be
            ownership_established=ownership_established(store),
        )
        assert plan.next_state is S.WEALTH_CORE_BOOTSTRAP_ALLOWED
        assert plan.liquidate_tickers == ()


class TestLegacyCleanupSequencing:
    def test_orders_are_cancelled_BEFORE_positions_are_sold(self):
        """A resting legacy BUY that fills after we sold re-creates a position we
        already reported gone."""
        plan = plan_startup(
            state=S.UNINITIALIZED,
            observation=obs({"AAPL": 10}, [buy("o1", "NVDA")]),
            ownership_established=False,
        )
        assert plan.cancel_order_ids == ("o1",)
        assert plan.liquidate_tickers == ()
        assert plan.next_state is S.LEGACY_ORDERS_CANCELLED

    def test_our_OWN_sells_are_not_cancelled_once_past_the_cleanup_phase(self):
        """Otherwise each cycle cancels what the previous one submitted, forever."""
        plan = plan_startup(
            state=S.LIQUIDATION_SUBMITTED,
            observation=obs({"AAPL": 10}, [sell("s1", "AAPL")]),
            ownership_established=False,
        )
        assert plan.cancel_order_ids == ()
        assert plan.next_state is S.LIQUIDATION_PENDING

    def test_an_already_flat_account_needs_no_liquidation(self):
        plan = plan_startup(
            state=S.UNINITIALIZED, observation=obs(), ownership_established=False
        )
        assert plan.next_state is S.FLAT_CONFIRMED
        assert plan.liquidate_tickers == ()

    def test_a_working_order_means_NOT_flat_even_with_no_positions(self):
        """A resting buy could still fill and hand Wealth Core a position it did
        not choose."""
        plan = plan_startup(
            state=S.UNINITIALIZED,
            observation=obs({}, [buy("o1", "NVDA")]),
            ownership_established=False,
        )
        assert plan.next_state is not S.FLAT_CONFIRMED

    def test_zero_quantity_is_not_a_position(self):
        """Alpaca can report a closed position transiently; treating it as held
        would keep liquidating something that no longer exists."""
        plan = plan_startup(
            state=S.UNINITIALIZED,
            observation=obs({"AAPL": 0.0}),
            ownership_established=False,
        )
        assert plan.next_state is S.FLAT_CONFIRMED


class TestIdempotencyUnderRestart:
    def test_a_ticker_with_a_working_sell_is_NOT_closed_again(self):
        """A second close while the first is working over-sells into a SHORT."""
        plan = plan_startup(
            state=S.LIQUIDATION_SUBMITTED,
            observation=obs({"AAPL": 10, "MSFT": 5}, [sell("s1", "AAPL")]),
            ownership_established=False,
        )
        assert plan.liquidate_tickers == ("MSFT",)

    def test_submit_then_timeout_resolves_by_ASKING_the_broker(self):
        """The order may or may not have been accepted. Both worlds are handled by
        re-observing rather than by remembering what we tried."""
        accepted = plan_startup(
            state=S.LIQUIDATION_SUBMITTED,
            observation=obs({"AAPL": 10}, [sell("s1", "AAPL")]),
            ownership_established=False,
        )
        assert accepted.liquidate_tickers == ()   # it landed; leave it alone

        lost = plan_startup(
            state=S.LIQUIDATION_SUBMITTED,
            observation=obs({"AAPL": 10}),
            ownership_established=False,
        )
        assert lost.liquidate_tickers == ("AAPL",)  # it never landed; retry

    def test_a_partial_fill_keeps_liquidating_rather_than_declaring_victory(self):
        plan = plan_startup(
            state=S.LIQUIDATION_PENDING,
            observation=obs({"AAPL": 3}),   # 10 -> 3, still held
            ownership_established=False,
        )
        assert plan.liquidate_tickers == ("AAPL",)

    def test_positions_gone_but_orders_still_working_is_PENDING_not_flat(self):
        plan = plan_startup(
            state=S.LIQUIDATION_PENDING,
            observation=obs({}, [sell("s1", "AAPL")]),
            ownership_established=False,
        )
        assert plan.next_state is S.LIQUIDATION_PENDING


class TestTheStore:
    def test_the_ownership_record_survives_a_restart(self, tmp_path):
        path = tmp_path / "ownership.jsonl"
        record(FileOwnershipStore(path), S.SENTINEL_OWNERSHIP_ESTABLISHED)
        assert ownership_established(FileOwnershipStore(path)) is True

    def test_a_torn_FINAL_line_is_survivable(self, tmp_path):
        """A crash mid-append describes an event that never completed."""
        path = tmp_path / "ownership.jsonl"
        store = FileOwnershipStore(path)
        record(store, S.SENTINEL_OWNERSHIP_ESTABLISHED)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"state": "FLAT_CONF')
        assert ownership_established(FileOwnershipStore(path)) is True

    def test_corruption_EARLIER_in_the_log_REFUSES_rather_than_skips(self, tmp_path):
        """Skipping a bad line could silently drop the ownership event and re-arm
        liquidation. Loud beats lossy."""
        path = tmp_path / "ownership.jsonl"
        store = FileOwnershipStore(path)
        record(store, S.ACCOUNT_INSPECTED)
        lines = path.read_text().splitlines()
        path.write_text("{{{not json\n" + "\n".join(lines) + "\n")
        with pytest.raises(ValueError, match="corruption"):
            FileOwnershipStore(path).events()

    def test_an_empty_log_reads_as_UNINITIALIZED(self, tmp_path):
        assert current_state(FileOwnershipStore(tmp_path / "none.jsonl")) is S.UNINITIALIZED

    def test_events_round_trip(self, tmp_path):
        path = tmp_path / "ownership.jsonl"
        store = FileOwnershipStore(path)
        record(store, S.LIQUIDATION_SUBMITTED, liquidated=["AAPL", "MSFT"])
        (e,) = FileOwnershipStore(path).events()
        assert e.state is S.LIQUIDATION_SUBMITTED
        assert e.detail["liquidated"] == ["AAPL", "MSFT"]
        assert isinstance(e, OwnershipEvent)
