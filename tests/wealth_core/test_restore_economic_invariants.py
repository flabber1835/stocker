"""Restore decoders reject self-consistent but impossible economic payloads."""
from __future__ import annotations

from copy import deepcopy

import pytest

from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState


@pytest.mark.parametrize("cash", [-0.01, float("nan"), float("inf"), True])
def test_portfolio_restore_refuses_invalid_cash(cash):
    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["cash"] = cash

    with pytest.raises(ValueError, match="cash"):
        PortfolioState.from_dict(payload)


@pytest.mark.parametrize("session_index", [-1, 1.5, True])
def test_portfolio_restore_refuses_invalid_session_index(session_index):
    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["session_index"] = session_index

    with pytest.raises(ValueError, match="session_index"):
        PortfolioState.from_dict(payload)


def test_ledger_restore_refuses_cash_arithmetic_contradiction():
    ledger = Ledger()
    ledger.post(
        session="2026-08-25", event_type=EventType.BUY,
        cash_before=1_000.0, cash_delta=-100.0, shares_delta=1.0,
        security_id="SEC-A", ticker="AAA", price=100.0, reason="BUY")
    payload = ledger.to_dict()
    payload["events"][0]["cash_after"] = 950.0

    with pytest.raises(ValueError, match="cash_after = cash_before"):
        Ledger.from_dict(payload)


@pytest.mark.parametrize("field,value", [
    ("amount", -1.0),
    ("amount", float("nan")),
    ("due_in", -1),
    ("due_in", 1.5),
])
def test_ledger_restore_refuses_invalid_receivable(field, value):
    ledger = Ledger()
    ledger.accrue_dividend(
        session="2026-08-25", security_id="SEC-A", ticker="AAA",
        shares=10, per_share=1.0, cash=1_000.0, due_in=2)
    payload = ledger.to_dict()
    payload["receivables"][0][field] = value

    with pytest.raises(ValueError, match="receivable"):
        Ledger.from_dict(payload)


def test_valid_portfolio_and_ledger_round_trip_unchanged():
    state = PortfolioState.fresh(1_000.0, n_slots=2)
    state.session_index = 7
    ledger = Ledger()
    ledger.accrue_dividend(
        session="2026-08-25", security_id="SEC-A", ticker="AAA",
        shares=10, per_share=1.0, cash=1_000.0, due_in=2)

    restored_state = PortfolioState.from_dict(deepcopy(state.to_dict()))
    restored_ledger = Ledger.from_dict(deepcopy(ledger.to_dict()))

    assert restored_state.to_dict() == state.to_dict()
    assert restored_ledger.to_dict() == ledger.to_dict()
