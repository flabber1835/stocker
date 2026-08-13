"""Pending intent follows the same corporate-action economics as its episode."""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    step_session,
    tradeability_only_bars,
)
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def bar(sec: str, ticker: str, session: str, *, price: float,
        split: float = 1.0, tradeable: bool = True) -> DailyBar:
    return DailyBar(
        security_id=sec, ticker=ticker, issuer_id=f"I:{sec}",
        session=session, signal_close_split_adj_div_unadj=price,
        raw_open=price, raw_mark_close=price, tradeable=tradeable,
        split_ratio=split, dividend_per_share=0.0,
        unresolved_corporate_action=False)


def held(shares: float, *, cash: float = 1_000.0) -> PortfolioState:
    state = PortfolioState.fresh(cash)
    state.slots[0].occupied_by = "OLD"
    state.episodes[0] = HoldingEpisode(
        "OLD", "OLD", "I:OLD", 0, "d0", "d0", 100.0, 100.0,
        shares, shares, 100.0)
    state.initialized = True
    return state


def pending_close(shares: float) -> list[PendingOrder]:
    return [PendingOrder(
        Operation.CLOSE_POSITION, "OLD", "OLD", 0, shares, "d0", "EXIT")]


def pending_open(shares: float) -> tuple[PortfolioState, list[PendingOrder]]:
    state = PortfolioState.fresh(100_000.0)
    state.initialized = True
    state.reserve_slot(0, "OLD", "OLD", "I:OLD")
    return state, [PendingOrder(
        Operation.OPEN_SLOT_POSITION, "OLD", "OLD", 0, shares, "d0", "ENTRY")]


def step(state: PortfolioState, pending: list[PendingOrder], *, session: str,
         bars: list[DailyBar], ledger: Ledger | None = None,
         terms: list[TerminalTerms] | None = None):
    ledger = ledger if ledger is not None else Ledger()
    result = step_session(
        session=session, state=state, bars=bars, pending=pending,
        ledger=ledger, last_known={}, cfg=CFG, strategy_id=SID,
        strategy_version=VER, security_bars=tradeability_only_bars(bars, None),
        terminal_terms=terms or ())
    return result, ledger


def conversion(session: str, ratio: float, *, lieu: float | None = None):
    return TerminalTerms(
        session=session, security_id="OLD", kind=TerminalKind.CONVERSION,
        delivered_security_id="NEW", delivered_ticker="NEW",
        delivered_issuer_id="I:NEW", exchange_ratio=ratio,
        cash_in_lieu_price_per_delivered_share=lieu,
        reference=f"test/conversion/{ratio}")


@pytest.mark.parametrize("shares,ratio,expected", [
    (10, 2.0, 20),       # forward
    (100, 0.1, 10),      # reverse
    (5, 1.5, 7.5),       # fractional entitlement remains canonical
])
def test_pending_close_is_exactly_split_with_the_episode(shares, ratio, expected):
    state, pending, ledger = held(shares, cash=0.0), pending_close(shares), Ledger()
    result, _ = step(
        state, pending, session="d1",
        bars=[bar("OLD", "OLD", "d1", price=100.0 / ratio, split=ratio)],
        ledger=ledger)

    assert pending == []
    assert result.fills[0]["shares"] == pytest.approx(expected)
    assert result.transformed[0]["shares_before"] == shares
    assert result.transformed[0]["shares_after"] == pytest.approx(expected)
    sell = next(e for e in ledger.events if e.event_type is EventType.SELL)
    assert sell.shares_delta == pytest.approx(-expected)
    assert sell.detail["pending_transformations"] == result.fills[0]["transformations"]


@pytest.mark.parametrize("shares,ratio,expected", [
    (10, 2.0, 20),
    (100, 0.1, 10),
    (10, 1.5, 15),
])
def test_pending_open_is_exactly_split_when_still_whole(shares, ratio, expected):
    state, pending = pending_open(shares)
    result, ledger = step(
        state, pending, session="d1",
        bars=[bar("OLD", "OLD", "d1", price=10.0, split=ratio)])

    assert pending == []
    assert state.episodes[0].current_shares == expected
    assert result.fills[0]["transformations"][0]["shares_after"] == expected
    buy = next(e for e in ledger.events if e.event_type is EventType.BUY)
    assert buy.shares_delta == expected
    assert buy.detail["pending_transformations"] == result.fills[0]["transformations"]


def test_same_session_pending_ticker_change_is_dated_and_durable_on_fill():
    state, pending, ledger = held(10, cash=0.0), pending_close(10), Ledger()
    result, _ = step(
        state, pending, session="d1",
        bars=[bar("OLD", "NEW_LABEL", "d1", price=90.0)], ledger=ledger)

    transform, = result.transformed
    assert transform == {
        "session": "d1", "kind": "TICKER_CHANGE",
        "from_security_id": "OLD", "to_security_id": "OLD",
        "from_ticker": "OLD", "to_ticker": "NEW_LABEL",
        "shares_before": 10, "shares_after": 10,
    }
    sell = next(e for e in ledger.events if e.event_type is EventType.SELL)
    assert sell.ticker == "NEW_LABEL"
    assert sell.detail["pending_transformations"] == [transform]


def test_fractional_pending_open_is_explicitly_cancelled_and_releases_slot():
    state, pending = pending_open(5)
    result, _ = step(
        state, pending, session="d1",
        bars=[bar("OLD", "OLD", "d1", price=100.0, split=0.3)])

    assert pending == [] and 0 not in state.episodes
    assert state.slots[0].reserved_for is None
    cancelled, = result.cancelled
    assert cancelled["reason"] == "INEXPRESSIBLE_FRACTIONAL_ENTRY"
    assert cancelled["reservation_released"] is True
    assert cancelled["transformations"][0]["shares_after"] == pytest.approx(1.5)


@pytest.mark.parametrize("shares,ratio,lieu,expected", [
    (10, 2.0, None, 20),
    (100, 0.1, None, 10),
    (5, 0.3, 50.0, 1),  # the 0.5 entitlement is settled by the conversion
])
def test_pending_close_follows_forward_reverse_and_fractional_conversion(
        shares, ratio, lieu, expected):
    state, pending, ledger = held(shares, cash=0.0), pending_close(shares), Ledger()
    result, _ = step(
        state, pending, session="d1",
        bars=[bar("NEW", "NEW", "d1", price=50.0)], ledger=ledger,
        terms=[conversion("d1", ratio, lieu=lieu)])

    assert pending == [] and 0 not in state.episodes
    assert result.fills[0]["security_id"] == "NEW"
    assert result.fills[0]["shares"] == expected
    transform, = result.fills[0]["transformations"]
    assert transform["from_security_id"] == "OLD"
    assert transform["to_security_id"] == "NEW"
    assert transform["shares_after"] == expected
    assert next(e for e in ledger.events if e.event_type is EventType.SELL).shares_delta == -expected


def test_pending_open_follows_an_exact_pure_stock_conversion_and_reservation():
    state, pending = pending_open(10)
    result, _ = step(
        state, pending, session="d1",
        bars=[bar("NEW", "NEW", "d1", price=20.0)],
        terms=[conversion("d1", 1.5)])

    assert pending == []
    assert state.episodes[0].security_id == "NEW"
    assert state.episodes[0].current_shares == 15
    assert result.fills[0]["transformations"][0]["shares_after"] == 15
    assert state.slots[0].reserved_for is None


def test_fractional_pending_open_conversion_is_cancelled_and_releases_slot():
    state, pending = pending_open(5)
    result, _ = step(
        state, pending, session="d1",
        bars=[bar("NEW", "NEW", "d1", price=20.0)],
        terms=[conversion("d1", 0.3, lieu=50.0)])

    assert pending == [] and state.slots[0].reserved_for is None
    cancelled, = result.cancelled
    assert cancelled["reason"] == "TERMINAL_INTENT_INEXPRESSIBLE"
    assert cancelled["reservation_released"] is True
    assert cancelled["transformed_shares"] == pytest.approx(1.5)
    assert PortfolioState.from_dict(state.to_dict()).slots[0].reserved_for is None


def test_mixed_consideration_never_retargets_a_pending_open_or_loses_cash_leg():
    state, pending = pending_open(10)
    # A separate held episode makes apply_terminal report a real conversion;
    # the queued BUY still owned no predecessor and therefore no cash leg.
    state.slots[1].occupied_by = "OLD"
    state.episodes[1] = HoldingEpisode(
        "OLD", "OLD", "I:OLD", 1, "d0", "d0", 100.0, 100.0,
        10, 10, 100.0)
    terms = TerminalTerms(
        session="d1", security_id="OLD", kind=TerminalKind.CASH_PLUS_STOCK,
        cash_per_share=12.0, delivered_security_id="NEW",
        delivered_ticker="NEW", delivered_issuer_id="I:NEW",
        exchange_ratio=1.5, reference="test/mixed")

    result, _ = step(
        state, pending, session="d1",
        bars=[bar("NEW", "NEW", "d1", price=20.0)], terms=[terms])

    assert pending == []
    assert state.slots[0].reserved_for is None
    cancelled, = result.cancelled
    assert cancelled["reason"] == "TERMINAL_INTENT_INEXPRESSIBLE"
    assert cancelled["terms_reason"] == \
        "MIXED_CONSIDERATION_ENTRY_HAS_NO_ENTITLEMENT"
    assert not [f for f in result.fills if f["operation"] == "OPEN_SLOT_POSITION"]


@pytest.mark.parametrize("kind,kw", [
    (TerminalKind.WRITE_OFF, {}),
    (TerminalKind.CASH_MERGER, {"cash_per_share": 12.0}),
])
def test_extinguished_pending_open_is_recorded_and_releases_slot(kind, kw):
    state, pending = pending_open(10)
    terms = TerminalTerms(
        session="d1", security_id="OLD", kind=kind,
        reference=f"test/{kind.value}", **kw)
    result, _ = step(
        state, pending, session="d1", bars=[], terms=[terms])

    assert pending == [] and state.slots[0].reserved_for is None
    cancelled, = result.cancelled
    assert cancelled["reason"] == "TERMINAL_INTENT_EXTINGUISHED"
    assert cancelled["reservation_released"] is True


def test_restart_after_split_transform_is_identical_to_uninterrupted_fill():
    state, pending, ledger = held(5, cash=0.0), pending_close(5), Ledger()
    first, _ = step(
        state, pending, session="d1",
        bars=[bar("OLD", "OLD", "d1", price=100.0 / 1.5,
                  split=1.5, tradeable=False)], ledger=ledger)
    assert first.transformed[0]["shares_after"] == pytest.approx(7.5)

    restored_state = PortfolioState.from_dict(state.to_dict())
    restored_pending = [PendingOrder.from_dict(p.to_dict()) for p in pending]
    restored_ledger = Ledger.from_dict(ledger.to_dict())
    next_bar = [bar("OLD", "OLD", "d2", price=70.0)]
    uninterrupted, _ = step(
        state, pending, session="d2", bars=next_bar, ledger=ledger)
    restarted, _ = step(
        restored_state, restored_pending, session="d2", bars=next_bar,
        ledger=restored_ledger)

    assert uninterrupted.fills == restarted.fills
    assert state.to_dict() == restored_state.to_dict()
    assert ledger.to_dict() == restored_ledger.to_dict()


def test_restart_after_conversion_transform_is_identical_to_uninterrupted_fill():
    state, pending, ledger = held(10, cash=0.0), pending_close(10), Ledger()
    first, _ = step(
        state, pending, session="d1", bars=[], ledger=ledger,
        terms=[conversion("d1", 1.5)])
    assert first.transformed[0]["to_security_id"] == "NEW"
    assert pending[0].to_dict()["transformations"]

    restored_state = PortfolioState.from_dict(state.to_dict())
    restored_pending = [PendingOrder.from_dict(p.to_dict()) for p in pending]
    restored_ledger = Ledger.from_dict(ledger.to_dict())
    next_bar = [bar("NEW", "NEW", "d2", price=70.0)]
    uninterrupted, _ = step(
        state, pending, session="d2", bars=next_bar, ledger=ledger)
    restarted, _ = step(
        restored_state, restored_pending, session="d2", bars=next_bar,
        ledger=restored_ledger)

    assert uninterrupted.fills == restarted.fills
    assert state.to_dict() == restored_state.to_dict()
    assert ledger.to_dict() == restored_ledger.to_dict()


def test_restart_after_not_held_open_conversion_preserves_retargeted_reservation():
    state, pending = pending_open(10)
    first, ledger = step(
        state, pending, session="d1", bars=[],
        terms=[conversion("d1", 1.5)])
    assert first.transformed[0]["to_security_id"] == "NEW"
    assert state.slots[0].reserved_for == "NEW"
    assert pending[0].security_id == "NEW" and pending[0].shares == 15

    restored_state = PortfolioState.from_dict(state.to_dict())
    restored_pending = [PendingOrder.from_dict(p.to_dict()) for p in pending]
    restored_ledger = Ledger.from_dict(ledger.to_dict())
    next_bar = [bar("NEW", "NEW", "d2", price=20.0)]
    uninterrupted, _ = step(
        state, pending, session="d2", bars=next_bar, ledger=ledger)
    restarted, _ = step(
        restored_state, restored_pending, session="d2", bars=next_bar,
        ledger=restored_ledger)

    assert uninterrupted.fills == restarted.fills
    assert state.to_dict() == restored_state.to_dict()
    assert ledger.to_dict() == restored_ledger.to_dict()
