"""Independent holder, exact-floor and representability witnesses for #373."""
from copy import deepcopy
from dataclasses import replace
from decimal import localcontext
from fractions import Fraction as F
import json

import pytest

from stock_strategy_shared.wealth_core.adapter import PendingOrder, step_session
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.shares import split_shares
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind, TerminalTerms, TermsIncomplete, _split_entitlement, apply_terminal)

CFG = WealthCoreConfig()
DAY = "2026-08-12"


def book(parts):
    state = PortfolioState.fresh(10_000.)
    state.initialized = True
    for slot, quantity in enumerate(parts):
        state.slots[slot].occupied_by = "OLD"
        state.episodes[slot] = HoldingEpisode(
            "OLD", "OLD", "I:OLD", slot, "2026-08-10", "2026-08-11",
            60., 10., quantity, quantity, 10., market_sessions_held=30 + slot,
            source_lots=[{"kind": "ADMISSION", "shares": quantity}])
    return state


def terms(**kwargs):
    return TerminalTerms(DAY, "OLD", TerminalKind.CONVERSION,
                         delivered_security_id="NEW", delivered_ticker="NEW",
                         delivered_issuer_id="I:NEW", exchange_ratio="0.5", **kwargs)


def bars(day=DAY, *, split=1., old_price=60., new_open=120.):
    return [DailyBar("OLD", "OLD", "I:OLD", day,
                    signal_close_split_adj_div_unadj=10.,
                    raw_open=old_price, raw_mark_close=old_price, split_ratio=split),
            DailyBar("NEW", "NEW", "I:NEW", day,
                     signal_close_split_adj_div_unadj=20.,
                     raw_open=new_open, raw_mark_close=120., tradeable=new_open is not None)]


def step(state, ledger, *, day=DAY, pending=None, events=(), daily=None):
    return step_session(session=day, state=state, bars=bars(day) if daily is None else daily,
                        pending=[] if pending is None else pending, ledger=ledger,
                        last_known={}, cfg=CFG, strategy_id="stocker_wealth_core_v1",
                        strategy_version=1, security_bars=[], terminal_terms=events)


@pytest.mark.parametrize("parts", [(202,), (101, 101), (100, 51, 51), (2,), (1, 1)])
def test_holder_integral_delivery_does_not_require_cil(parts):
    state, ledger = book(parts), Ledger()
    result = step(state, ledger, events=[terms()])
    expected = sum(parts) // 2
    assert state.shares_by_security() == {"NEW": expected}
    assert state.cash == 10_000.
    assert result.resolved_equity == 10_000. + expected * 120.
    assert len(state.episodes) == len(parts)
    for slot, ep in state.episodes.items():
        assert ep.current_shares == parts[slot] / 2
        assert ep.market_sessions_held == 31 + slot
        assert ep.episode_peak_split_adjusted_close == 20.
        assert ep.source_lots[0]["shares"] == parts[slot]
        assert ep.source_lots[-1]["from_security_id"] == "OLD"
    restored = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored.to_dict() == state.to_dict()
    next_result = step(restored, Ledger.from_dict(ledger.to_dict()), day="2026-08-13")
    assert next_result.resolved_equity == result.resolved_equity


@pytest.mark.parametrize("parts", [(203,), (101, 102), (51, 51, 101)])
def test_mixed_holder_cash_and_pending_exits_survive_restart(parts):
    state, ledger = book(parts), Ledger()
    pending = [PendingOrder(Operation.CLOSE_POSITION, "OLD", "OLD", slot,
                            quantity, "2026-08-11", "TEST") for slot, quantity in enumerate(parts)]
    event = replace(terms(cash_in_lieu_price_per_delivered_share=100.),
                    kind=TerminalKind.CASH_PLUS_STOCK, cash_per_share=2.)
    # A priced but halted delivered security permits rebase without filling exits.
    daily = bars()
    daily[1] = replace(daily[1], tradeable=False)
    step(state, ledger, pending=pending, events=[event], daily=daily)
    assert state.shares_by_security()["NEW"] == 101
    assert state.cash == pytest.approx(10_456., abs=1e-9)
    assert sum(p.shares for p in pending) == 101
    assert all(p.shares == state.episodes[p.slot_id].current_shares for p in pending)
    restored = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    restored_pending = [PendingOrder.from_dict(p.to_dict()) for p in pending]
    step(restored, Ledger.from_dict(ledger.to_dict()), day="2026-08-13", pending=restored_pending)
    assert restored.cash == pytest.approx(float(F(10_456) + F(101) * 120 * F("0.999")))
    assert not restored.episodes and not restored_pending


def test_unsupported_holder_convention_refuses_before_economic_mutation():
    state, ledger = book([101, 101]), Ledger()
    before = deepcopy(state.to_dict())
    with pytest.raises(TermsIncomplete, match="UNSUPPORTED_ENTITLEMENT_AGGREGATION"):
        apply_terminal(state, terms(entitlement_aggregation="PER_EPISODE"),
                       ledger=ledger, session=DAY, cfg=CFG)
    assert state.to_dict() == before and not ledger.events


def test_conflicting_holder_conventions_cannot_coalesce():
    from stock_strategy_shared.terminal_coalescing import (
        TerminalCandidate, coalesce_terminal_terms)
    outcome, = coalesce_terminal_terms([
        TerminalCandidate(terms(), "a"),
        TerminalCandidate(terms(entitlement_aggregation="PER_EPISODE"), "b")])
    assert outcome.selected is None and len(outcome.conflicting) == 2


@pytest.mark.parametrize("precision", [6, 28, 50])
@pytest.mark.parametrize("ratio", ["0.99999999999999999999999999995", "1",
                                  "1.00000000000000000000000000005"])
def test_contractual_floor_is_independent_of_decimal_context(precision, ratio):
    exact = F(10) * F(ratio)
    expected_whole, numerator = divmod(exact.numerator, exact.denominator)
    with localcontext() as context:
        context.prec = precision
        whole, fraction = _split_entitlement(10, ratio)
        event = replace(terms(), exchange_ratio=ratio)
        assert whole == expected_whole
        assert fraction == F(numerator, exact.denominator)
        assert event.completeness(10)[0] == (numerator == 0)
        state, ledger = book([10]), Ledger()
        applied = apply_terminal(state, event, ledger=ledger, session=DAY, cfg=CFG,
                                 source_signal_to_raw_scale=1., delivered_signal_to_raw_scale=1.)
        if numerator:
            assert not applied["applied"] and state.episodes[0].security_id == "OLD"
            applied = apply_terminal(state, replace(event, cash_in_lieu_price_per_delivered_share=1.),
                                     ledger=ledger, session=DAY, cfg=CFG,
                                     source_signal_to_raw_scale=1., delivered_signal_to_raw_scale=1.,
                                     delivered_raw_open=1.)
        assert applied["shares_delivered"] == expected_whole
        assert PortfolioState.from_dict(json.loads(json.dumps(state.to_dict()))).to_dict() == state.to_dict()


def test_extreme_reverse_split_refuses_before_the_first_material_loss():
    from sentinel.feed.calendar import sessions_in_range
    state, ledger = book([13]), Ledger()
    state.cash = 1_000.
    price = 10.
    sessions = sessions_in_range(DAY, "2026-09-03")
    for day in sessions[:12]:
        price *= 10
        step(state, ledger, day=day, daily=bars(day, old_price=price, split=.1))
        assert state.episodes[0].current_shares * price == pytest.approx(130., abs=1e-8)
        state = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
    before, recorded = deepcopy(state.to_dict()), deepcopy(ledger.to_dict())
    pending = [PendingOrder(Operation.CLOSE_POSITION, "OLD", "OLD", 0,
                            state.episodes[0].current_shares, "2026-08-11", "TEST")]
    intent = deepcopy(pending[0].to_dict())
    with pytest.raises(ValueError, match="supported .* precision"):
        step(state, ledger, day=sessions[12],
             daily=bars(sessions[12], old_price=price * 10, split=.1), pending=pending)
    assert state.to_dict() == before and ledger.to_dict() == recorded
    assert pending[0].to_dict() == intent


@pytest.mark.parametrize("quantity,ratio,price", [
    (1e-12, .5, 1e14), (1e-12, .1, 1e15), (1., 1.0000000000005, 1e12)])
def test_split_precision_guard_covers_half_quantum_zero_and_material_mark(quantity, ratio, price):
    with pytest.raises(ValueError, match="supported .* precision"):
        split_shares(quantity, ratio, raw_price=price)


def test_split_preflight_refuses_the_whole_batch_before_partial_mutation():
    from stock_strategy_shared.wealth_core.adapter import apply_splits
    state, ledger = book([10., 1e-12]), Ledger()
    before = deepcopy(state.to_dict())
    with pytest.raises(ValueError, match='supported .* precision'):
        apply_splits(state, bars(old_price=600., split=.1), ledger, DAY)
    assert state.to_dict() == before and not ledger.events
