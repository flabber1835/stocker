"""Session-effective issuer changes preserve the admission invariant."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    IssuerFamilyCollision,
    PendingOrder,
    step_session,
    tradeability_only_bars,
)
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.hashes import order_hash
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def bar(sec: str, issuer: str, *, session: str = "d1",
        price: float = 10.0) -> DailyBar:
    return DailyBar(
        security_id=sec, ticker=sec, issuer_id=issuer, session=session,
        signal_close_split_adj_div_unadj=price, raw_open=price,
        raw_mark_close=price, tradeable=True)


def hold(state: PortfolioState, slot: int, sec: str, issuer: str) -> None:
    state.slots[slot].occupied_by = sec
    state.episodes[slot] = HoldingEpisode(
        sec, sec, issuer, slot, "d0", "d0", 10.0, 10.0,
        10, 10, 10.0)
    state.initialized = True


def reserve(state: PortfolioState, slot: int, sec: str, issuer: str,
            *, signal: str = "d0") -> PendingOrder:
    state.reserve_slot(slot, sec, sec, issuer)
    return PendingOrder(
        Operation.OPEN_SLOT_POSITION, sec, sec, slot, 10,
        signal, "ENTRY_DURABLE_RANK")


def step(state: PortfolioState, pending: list[PendingOrder], bars,
         *, terminal_terms=()):
    return step_session(
        session="d1", state=state, bars=bars, pending=pending,
        ledger=Ledger(), last_known={}, cfg=CFG,
        strategy_id=SID, strategy_version=VER,
        security_bars=tradeability_only_bars(bars, None),
        terminal_terms=terminal_terms)


def test_pending_entry_rebound_into_held_issuer_is_cancelled_before_fill():
    state = PortfolioState.fresh(100_000.0)
    hold(state, 0, "HELD", "ISSUER_HELD")
    pending = [reserve(state, 1, "BUY", "ISSUER_OLD")]

    result = step(state, pending, [
        bar("HELD", "ISSUER_HELD"), bar("BUY", "ISSUER_HELD")])

    assert pending == []
    assert 1 not in state.episodes
    assert state.slots[1].reserved_for is None
    cancelled, = result.cancelled
    assert cancelled["reason"] == "ISSUER_CONFLICT_BEFORE_FILL"
    assert cancelled["reservation_released"] is True
    assert cancelled["conflict_kind"] == "HELD"
    assert cancelled["conflicting_security_id"] == "HELD"
    transform, = cancelled["transformations"]
    assert transform["kind"] == "ISSUER_REBIND"
    assert transform["from_issuer_id"] == "ISSUER_OLD"
    assert transform["to_issuer_id"] == "ISSUER_HELD"
    assert not result.fills


def test_two_pending_entries_converge_and_only_prior_reservation_fills():
    state = PortfolioState.fresh(100_000.0)
    state.initialized = True
    later = reserve(state, 2, "LATER", "ISSUER_LATER", signal="d0")
    first = reserve(state, 1, "FIRST", "ISSUER_FIRST", signal="d0")
    pending = [later, first]  # reverse queue order must not select the winner

    result = step(state, pending, [
        bar("FIRST", "ISSUER_ONE"), bar("LATER", "ISSUER_ONE")])

    assert [fill["security_id"] for fill in result.fills] == ["FIRST"]
    assert "FIRST" in state.held_security_ids()
    assert "LATER" not in state.held_security_ids()
    cancelled, = result.cancelled
    assert cancelled["security_id"] == "LATER"
    assert cancelled["conflict_kind"] == "PENDING"
    assert cancelled["conflicting_security_id"] == "FIRST"
    assert cancelled["conflicting_slot_id"] == 1
    assert state.slots[2].reserved_for is None


def test_distinct_holdings_that_become_one_issuer_fail_closed_with_evidence():
    state = PortfolioState.fresh(100_000.0)
    hold(state, 0, "AAA", "ISSUER_A")
    hold(state, 1, "BBB", "ISSUER_B")

    with pytest.raises(IssuerFamilyCollision) as caught:
        step(state, [], [bar("AAA", "ISSUER_ONE"),
                         bar("BBB", "ISSUER_ONE")])

    assert caught.value.evidence == {
        "session": "d1",
        "reason": "HELD_ISSUER_COLLISION_AFTER_METADATA_REBIND",
        "collisions": [{
            "issuer_id": "ISSUER_ONE",
            "holdings": [
                {"slot_id": 0, "security_id": "AAA",
                 "prior_issuer_id": "ISSUER_A"},
                {"slot_id": 1, "security_id": "BBB",
                 "prior_issuer_id": "ISSUER_B"},
            ],
        }],
    }
    # Detection precedes mutation and fills.
    assert state.episodes[0].issuer_id == "ISSUER_A"
    assert state.episodes[1].issuer_id == "ISSUER_B"


def test_future_conversion_terms_do_not_waive_a_current_held_collision():
    state = PortfolioState.fresh(100_000.0)
    hold(state, 0, "AAA", "ISSUER_A")
    hold(state, 1, "BBB", "ISSUER_B")
    future = [TerminalTerms(
        session="d2", security_id=security_id,
        kind=TerminalKind.CONVERSION,
        delivered_security_id="ACQUIRER", delivered_ticker="ACQUIRER",
        delivered_issuer_id="ISSUER_ONE", exchange_ratio=1.0)
        for security_id in ("AAA", "BBB")]

    with pytest.raises(IssuerFamilyCollision):
        step(state, [], [bar("AAA", "ISSUER_ONE"),
                         bar("BBB", "ISSUER_ONE")],
             terminal_terms=future)


def test_rebind_cancellation_and_reservation_release_are_hashed():
    def execute():
        state = PortfolioState.fresh(100_000.0)
        hold(state, 0, "HELD", "ISSUER_HELD")
        pending = [reserve(state, 1, "BUY", "ISSUER_OLD")]
        result = step(state, pending, [
            bar("HELD", "ISSUER_HELD"), bar("BUY", "ISSUER_HELD")])
        run = SimpleNamespace(sessions=[result], unfilled_at_end=[])
        return result, order_hash(run)

    result1, digest1 = execute()
    result2, digest2 = execute()
    assert result1.cancelled == result2.cancelled
    assert digest1 == digest2

    changed = deepcopy(result1)
    changed.cancelled[0]["reservation_released"] = False
    assert order_hash(SimpleNamespace(
        sessions=[changed], unfilled_at_end=[])) != digest1


def test_unrelated_issuer_changes_continue_normally():
    state = PortfolioState.fresh(100_000.0)
    hold(state, 0, "HELD", "ISSUER_A")
    pending = [reserve(state, 1, "BUY", "ISSUER_B")]

    result = step(state, pending, [
        bar("HELD", "ISSUER_A_NEW"), bar("BUY", "ISSUER_B_NEW")])

    assert result.cancelled == []
    assert state.episodes[0].issuer_id == "ISSUER_A_NEW"
    assert state.episodes[1].issuer_id == "ISSUER_B_NEW"


def test_same_session_corporate_action_consolidation_remains_valid():
    state = PortfolioState.fresh(100_000.0)
    hold(state, 0, "TARGET_A", "ISSUER_A")
    hold(state, 1, "TARGET_B", "ISSUER_B")
    terms = [TerminalTerms(
        session="d1", security_id=security_id,
        kind=TerminalKind.CONVERSION,
        delivered_security_id="ACQUIRER", delivered_ticker="ACQUIRER",
        delivered_issuer_id="ISSUER_ACQUIRER", exchange_ratio=1.0,
        reference=f"test/{security_id}/to-acquirer")
        for security_id in ("TARGET_A", "TARGET_B")]

    result = step(
        state, [], [bar("TARGET_A", "ISSUER_ACQUIRER"),
                    bar("TARGET_B", "ISSUER_ACQUIRER")],
        terminal_terms=terms)

    assert result.cancelled == []
    assert len(state.episodes) == 2
    assert state.shares_by_security()["ACQUIRER"] == 20
    assert [row["applied"] for row in result.terminal_results] == [True, True]


def test_conversion_into_an_already_held_issuer_refuses_before_fills():
    """The regression: only the pre-conversion held state was validated."""
    state = PortfolioState.fresh(100_000.0)
    hold(state, 0, "TARGET", "ISSUER_TARGET")
    hold(state, 1, "EXISTING_CLASS", "ISSUER_ACQUIRER")
    pending = [reserve(state, 2, "BUY", "ISSUER_OTHER")]
    terms = [TerminalTerms(
        session="d1", security_id="TARGET",
        kind=TerminalKind.CONVERSION,
        delivered_security_id="DELIVERED_CLASS",
        delivered_ticker="DELIVERED_CLASS",
        delivered_issuer_id="ISSUER_ACQUIRER", exchange_ratio=1.0,
        reference="test/target/to-held-issuer")]

    with pytest.raises(IssuerFamilyCollision) as caught:
        step(state, pending, [
            bar("TARGET", "ISSUER_TARGET"),
            bar("EXISTING_CLASS", "ISSUER_ACQUIRER"),
            bar("BUY", "ISSUER_OTHER")], terminal_terms=terms)

    collision, = caught.value.evidence["collisions"]
    assert collision["issuer_id"] == "ISSUER_ACQUIRER"
    assert {row["security_id"] for row in collision["holdings"]} == {
        "DELIVERED_CLASS", "EXISTING_CLASS"}
    # No pending admission reached its broker-model fill boundary.
    assert 2 not in state.episodes
    assert pending[0].security_id == "BUY"
