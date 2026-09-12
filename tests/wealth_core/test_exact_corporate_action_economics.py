"""Exact economic arithmetic at corporate-action boundaries."""
from dataclasses import asdict

import pytest

from stock_strategy_shared.wealth_core.adapter import apply_dividends
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.sharadar_domains import (
    raw_compatible_volume,
    raw_dividend_per_share,
)
from stock_strategy_shared.wealth_core.shares import is_integral, split_shares
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind,
    TerminalTerms,
    _split_entitlement,
    apply_terminal,
)


CFG = WealthCoreConfig()


def _book(*, shares=10, cash=10_000.0):
    state = PortfolioState.fresh(cash)
    state.slots[0].occupied_by = "S1"
    state.episodes[0] = HoldingEpisode(
        security_id="S1", ticker="T1", issuer_id="I1", slot_id=0,
        signal_date="d0", entry_date="d1", entry_raw_open=50.0,
        entry_split_adjusted_price=50.0, initial_shares=shares,
        current_shares=shares, episode_peak_split_adjusted_close=60.0,
        market_sessions_held=40)
    state.initialized = True
    return state


def _conversion(*, ratio, lieu=None):
    return TerminalTerms(
        session="d9", security_id="S1", kind=TerminalKind.CONVERSION,
        delivered_security_id="S2", delivered_ticker="T2",
        delivered_issuer_id="I2", exchange_ratio=ratio,
        cash_in_lieu_price_per_delivered_share=lieu,
        reference="economic-canonicalization")


@pytest.mark.parametrize("adjusted,raw,reported_volume,expected", [
    ("100.01", "100.01", "1234567", 1_234_567.0),
    ("20.002", "100.01", "6172835", 1_234_567.0),
    ("70", "210", "3704400", 1_234_800.0),
    ("30", "210", "8643600", 1_234_800.0),
])
def test_raw_compatible_volume_uses_exact_source_decimal_economics(
        adjusted, raw, reported_volume, expected):
    assert raw_compatible_volume(adjusted, raw, reported_volume) == expected


@pytest.mark.parametrize("adjusted,raw,reported,expected", [
    ("99.99", "99.99", "0.47", 0.47),
    ("19.998", "99.99", "0.094", 0.47),
    ("37.13", "37.13", "1.23", 1.23),
    ("7.426", "37.13", "0.246", 1.23),
])
def test_raw_dividend_uses_exact_source_decimal_economics(
        adjusted, raw, reported, expected):
    assert raw_dividend_per_share(adjusted, raw, reported) == expected


def _dividend_bar(per_share):
    return VendorBar(
        session="d9", security_id="S1", ticker="T1",
        raw_close=50.0, raw_open=50.0, volume=1_000_000.0,
        dividend_per_share=per_share)


def test_equivalent_dividend_rebases_produce_identical_ledger_and_state():
    baseline_dividend = raw_dividend_per_share("99.99", "99.99", "0.47")
    rebased_dividend = raw_dividend_per_share("19.998", "99.99", "0.094")
    assert baseline_dividend == rebased_dividend == 0.47

    states = []
    ledgers = []
    for dividend in (baseline_dividend, rebased_dividend):
        state, ledger = _book(shares=100), Ledger()
        apply_dividends(state, [_dividend_bar(dividend)], ledger, "d9", cfg=CFG)
        states.append(state.to_dict())
        ledgers.append([asdict(event) for event in ledger.events])

    assert states[0] == states[1]
    assert ledgers[0] == ledgers[1]


@pytest.mark.parametrize("shares,ratio,whole,fraction", [
    (10, 0.99999999995, 9, 0.9999999995),
    (10, 1.0, 10, 0.0),
    (10, 1.00000000005, 10, 0.0000000005),
    (100, 0.5, 50, 0.0),
    (50, 2.0, 100, 0.0),
    (1_000_000, 1.0000000000005, 1_000_000, 0.0000005),
])
def test_terminal_entitlement_floors_exactly(shares, ratio, whole, fraction):
    delivered, remainder = _split_entitlement(shares, ratio)
    assert delivered == whole
    assert remainder == pytest.approx(fraction, rel=0, abs=1e-15)


def test_true_near_integer_fraction_requires_cash_in_lieu():
    state = _book(shares=10)
    result = apply_terminal(
        state, _conversion(ratio=0.99999999995, lieu=None),
        ledger=Ledger(), session="d9", cfg=CFG)
    assert result["applied"] is False
    assert result["reason"] == "MISSING_CASH_IN_LIEU_PRICE"
    assert state.episodes[0].security_id == "S1"
    assert state.episodes[0].current_shares == 10


def test_true_near_integer_fraction_delivers_nine_and_pays_fractional_cash():
    state, ledger = _book(shares=10), Ledger()
    result = apply_terminal(
        state, _conversion(ratio=0.99999999995, lieu=100.0),
        ledger=ledger, session="d9", cfg=CFG)

    assert result["applied"] is True
    assert result["shares_delivered"] == 9
    assert state.episodes[0].current_shares == 9
    assert result["cash_in_lieu"] == pytest.approx(99.99999995)
    assert state.cash == pytest.approx(10_099.99999995)
    event = ledger.events[-1]
    assert event.detail["shares_delivered"] == 9
    assert event.detail["fractional_entitlement"] == pytest.approx(0.9999999995)

    restored = PortfolioState.from_dict(state.to_dict())
    assert restored.to_dict() == state.to_dict()


def test_exact_integer_entitlement_needs_no_cash_in_lieu():
    state = _book(shares=10)
    result = apply_terminal(
        state, _conversion(ratio=1.0, lieu=None),
        ledger=Ledger(), session="d9", cfg=CFG)
    assert result["applied"] is True
    assert result["shares_delivered"] == 10
    assert result["cash_in_lieu"] == 0.0


def test_pending_and_held_conversion_arithmetic_agree_on_real_fraction():
    ratio = 0.99999999995
    pending = split_shares(10, ratio)
    delivered, remainder = _split_entitlement(10, ratio)
    assert pending == pytest.approx(9.9999999995)
    assert not is_integral(pending)
    assert delivered == 9
    assert remainder == pytest.approx(0.9999999995)
