"""Independent financial witnesses for terminal proceeds availability."""
from copy import deepcopy
import json

import pytest

from stock_strategy_shared.wealth_core import median5, v5
from stock_strategy_shared.wealth_core.adapter import PendingOrder, step_session
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.settlement import (
    SettlementPhase, SettlementSource, resolve_settlement,
)
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind, TerminalTerms, _apply_proxy, apply_terminal,
)
from tests.wealth_core.test_adapter import db, seated


def terminal_book(stale=11, *, v5_intent=False):
    state = seated(cash=100., sec="S1", shares=100, entry=10.)
    state.slots[1].occupied_by = "S2"
    state.episodes[1] = HoldingEpisode(
        "S2", "T2", "I2", 1, "d0", "d0", 100., 100., 89, 89, 100.)
    state.sessions_since_valid_mark["S1"] = stale
    state.slots[2].reserve("S3", "T3", "I3")
    cfg = WealthCoreConfig()
    if v5_intent:
        cfg = v5.config()
        state.entry_sizing_profile = v5.PROFILE
        state.median5 = median5.fresh()
    pending = [PendingOrder(
        Operation.OPEN_SLOT_POSITION, "S3", "T3", 2,
        0 if v5_intent else 49, "d0", "ENTRY",
        intended_dollars=500. if v5_intent else None)]
    return state, pending, Ledger(), cfg


def terminal_step(state, pending, ledger, cfg, close, *, day="d1", terms=True,
                  entry_open=10., terminal_open=5.):
    return step_session(
        session=day, state=state, pending=pending, ledger=ledger,
        bars=[db("S1", session=day, open_=terminal_open, mark=close, signal=close),
              db("S2", session=day, open_=100., mark=100., signal=100.),
              db("S3", session=day, open_=entry_open, mark=10., signal=10.)],
        last_known={"S1": 10., "S2": 100.}, cfg=cfg,
        strategy_id="terminal-causality-witness", strategy_version=1,
        security_bars=[],
        terminal_terms=([TerminalTerms(day, "S1", TerminalKind.CASH_MERGER)]
                        if terms else []))


@pytest.mark.parametrize("stale", [10, 11])
@pytest.mark.parametrize("pending_exit", [False, True])
def test_later_terminal_close_cannot_change_opening_cash_nav_or_fixed_share_fills(
        stale, pending_exit):
    witnesses = []
    for close in (1., 10.):
        state, pending, ledger, cfg = terminal_book(stale)
        if pending_exit:
            pending.insert(0, PendingOrder(
                Operation.CLOSE_POSITION, "S1", "T1", 0, 100, "d0", "EXIT"))
        result = terminal_step(state, pending, ledger, cfg, close)
        buys = [event for event in ledger.events if event.event_type is EventType.BUY]
        witnesses.append((result.resolved_open_equity, buys[0].cash_before,
                          buys[0].shares_delta, result.fills))
        assert result.resolved_open_equity == 9500.
        expected_cash = (599.5 if pending_exit and stale == 10 else
                         600. if stale == 11 else 100.)
        assert buys[0].cash_before == expected_cash
        assert buys[0].shares_delta == (49 if expected_cash > 100 else 9)
        if stale == 11:
            assert result.terminal_results[0]["settlement_available_phase"] == "OPEN"
            assert result.terminal_results[0]["proceeds"] == 500.
            assert not any(e.event_type is EventType.SELL and e.security_id == "S1"
                           for e in ledger.events)
    assert witnesses[0] == witnesses[1]


def test_closing_print_is_unavailable_until_the_closing_phase():
    terms = TerminalTerms("d1", "S1", TerminalKind.CASH_MERGER)
    decision = resolve_settlement(
        terms=terms, shares=100, last_valid_mark=10., sessions_since_last_valid_print=11,
        executable_price=10., executable_price_phase="CLOSE", phase="OPEN")
    assert not decision.settles
    state, pending, ledger, cfg = terminal_book()
    opening = apply_terminal(
        state, terms, ledger=ledger, session="d1", cfg=cfg,
        last_valid_mark=10., sessions_since_last_valid_print=11,
        executable_price=10., executable_price_phase="CLOSE", phase="OPEN")
    assert opening["blocked"] and state.cash == 100.
    assert not ledger.events and state.episodes[0].current_shares == 100
    # A phase cut retains both ownership and the unresolved claim.
    state = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    ledger = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    closing = apply_terminal(
        state, terms, ledger=ledger, session="d1", cfg=cfg,
        last_valid_mark=10., sessions_since_last_valid_print=11,
        executable_price=10., executable_price_phase="CLOSE", phase="CLOSE")
    assert closing["proceeds"] == 1000. and state.cash == 1100.
    assert closing["settlement_available_phase"] == "CLOSE"
    assert ledger.events[-1].detail["settlement_available_phase"] == "CLOSE"
    again = apply_terminal(state, terms, ledger=ledger, session="d1", cfg=cfg,
                           phase="CLOSE", executable_price=10., executable_price_phase="CLOSE")
    assert again["reason"] == "NOT_HELD" and state.cash == 1100.


def test_cash_posting_boundary_rejects_a_future_phase_decision():
    state, pending, ledger, cfg = terminal_book()
    terms = TerminalTerms("d1", "S1", TerminalKind.CASH_MERGER)
    decision = resolve_settlement(
        terms=terms, shares=100, executable_price=10., phase="CLOSE",
        executable_price_phase="CLOSE")
    before = deepcopy(state.to_dict())
    with pytest.raises(ValueError, match="unavailable"):
        _apply_proxy(state, 0, state.episodes[0], ledger, "d1", decision,
                     terms, phase="OPEN")
    assert state.to_dict() == before and not ledger.events


def test_exact_terms_remain_available_at_open_even_with_a_later_print():
    decision = resolve_settlement(
        terms=TerminalTerms("d1", "S1", TerminalKind.CASH_MERGER, cash_per_share=7.),
        shares=100, executable_price=10., phase="OPEN", executable_price_phase="CLOSE")
    assert decision.source is SettlementSource.EXACT_TERMS
    assert decision.price_per_share == 7.
    assert decision.availability_phase is SettlementPhase.OPEN


def test_v5_invalid_open_cancellation_survives_restart_and_later_terminal_cash():
    state, pending, ledger, cfg = terminal_book(v5_intent=True)
    first = terminal_step(state, pending, ledger, cfg, 10., terms=False,
                          entry_open=None, terminal_open=None)
    assert first.fills == [] and not pending
    assert any(r["reason"] == "INVALID_OPEN_MARKET" for r in first.cancelled)
    state = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    ledger = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    state.sessions_since_valid_mark["S1"] = 11
    second = terminal_step(state, pending, ledger, cfg, 1., day="d2")
    assert not second.fills and state.cash == 600.
    assert "S3" not in state.held_security_ids()


def test_terminal_opening_outcome_is_identical_after_restart():
    state, pending, ledger, cfg = terminal_book()
    resumed = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    resumed_pending = [PendingOrder.from_dict(p.to_dict()) for p in pending]
    resumed_ledger = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    a = terminal_step(state, pending, ledger, cfg, 1.)
    b = terminal_step(resumed, resumed_pending, resumed_ledger, cfg, 1.)
    assert a == b
    assert state.to_dict() == resumed.to_dict()
    assert ledger.to_dict() == resumed_ledger.to_dict()


def test_missing_terminal_open_defers_closing_print_cash_until_after_fills():
    closing_cash = []
    for close in (1., 10.):
        state, pending, ledger, cfg = terminal_book()
        result = terminal_step(state, pending, ledger, cfg, close, terminal_open=None)
        assert result.resolved_open_equity is None
        assert result.open_unresolved_security_ids == ("S1",)
        buy = next(e for e in ledger.events if e.event_type is EventType.BUY)
        settlement = next(e for e in ledger.events if e.event_type is EventType.CASH_MERGER)
        assert buy.cash_before == 100. and buy.shares_delta == 9
        assert ledger.events.index(buy) < ledger.events.index(settlement)
        assert settlement.detail["settlement_available_phase"] == "CLOSE"
        assert result.terminal_results[-1]["settlement_available_phase"] == "CLOSE"
        assert "S1" not in state.held_security_ids()
        closing_cash.append(state.cash)
    assert closing_cash[1] - closing_cash[0] == pytest.approx(900.)


def test_grace_expiry_cash_is_available_at_close_and_survives_restart():
    state, pending, ledger, cfg = terminal_book(stale=0)
    terminal_step(state, pending, ledger, cfg, None, day="d01",
                  terminal_open=None, entry_open=None)
    for number in range(2, 12):
        state = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
        ledger = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
        result = terminal_step(state, pending, ledger, cfg, None, day=f"d{number:02d}",
            terms=False, terminal_open=None, entry_open=10. if number == 11 else None)
    buy = next(e for e in ledger.events if e.event_type is EventType.BUY)
    assert buy.cash_before == 100. and buy.shares_delta == 9
    settlement = next(e for e in ledger.events if e.event_type is EventType.CASH_MERGER)
    assert settlement.cash_delta == 1000.
    assert settlement.detail["settlement_available_phase"] == "CLOSE"
    assert result.terminal_results[-1]["settlement_available_phase"] == "CLOSE"
    assert not state.terminal_pending_sessions
