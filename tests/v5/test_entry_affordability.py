"""The canonical close must not queue an intent that already sizes to zero."""
from fractions import Fraction
import json
import math

import pytest

from sentinel.controller import ex3_v6
from stock_strategy_shared.wealth_core import v5
from stock_strategy_shared.wealth_core.adapter import PendingOrder, step_session
from stock_strategy_shared.wealth_core.engine import Operation, SecurityBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.median5 import fresh
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState

BUDGET_REASON = "INTENDED_BUDGET_ONE_SHARE_UNAFFORDABLE_AT_CLOSE"


def book(cash=100_000.):
    state = PortfolioState.fresh(cash, 20, entry_sizing_profile=v5.PROFILE)
    state.initialized = True
    state.median5 = fresh()
    state.median5["formation_started"] = True
    return state


def session(state, pending, day, *, opened=6000., close=6000., other=False,
            candidates=True):
    market = [DailyBar("AMZN", "AMZN", "ISSUER:AMZN", day,
                       close, opened, close)]
    ranked = ([SecurityBar("AMZN", "AMZN", "ISSUER:AMZN",
                           [close * .8, close], close, True, "",
                           (.5, .1, .2, 2.))] if candidates else [])
    if other:
        market.append(DailyBar("B", "B", "ISSUER:B", day, 100., 100., 100.))
        ranked.append(SecurityBar("B", "B", "ISSUER:B", [80., 100.],
                                  100., True, "", (.4, .1, .2, 1.)))
    return step_session(session=day, state=state, bars=market,
                        security_bars=ranked, pending=pending, ledger=Ledger(),
                        last_known={}, cfg=v5.config(),
                        strategy_id=ex3_v6.STRATEGY_ID, strategy_version=1)


def assert_no_known_zero_retry():
    state, pending = book(), []
    for day in ("0001", "0002", "0003", "0004"):
        result = session(state, pending, day)
        assert not pending
        assert not result.fills and not result.cancelled
        assert not state.reserved_security_ids() and not state.episodes
        assert state.cash == 100_000.
        assert not state.security_cooldowns
        assert all(slot.cooldown_sessions_elapsed is None
                   for slot in state.slots.values())
        rejected = [item for item in result.decision.admission_rejections
                    if item["security_id"] == "AMZN"]
        assert len(rejected) == 1
        assert rejected[0]["affordability_reason"] == BUDGET_REASON
        state = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))


def test_repeated_unaffordable_budget_never_reserves_or_attempts_an_open():
    assert_no_known_zero_retry()


def test_removed_budget_guard_reproduces_zero_cancel_requeue_and_fails_regression(
        monkeypatch):
    admission = v5.admission

    def without_budget_guard(**kwargs):
        intended, reason = admission(**kwargs)
        if reason == BUDGET_REASON:
            return float(Fraction(str(kwargs["equity"])) / 20), ""
        return intended, reason

    with monkeypatch.context() as patch:
        patch.setattr(v5, "admission", without_budget_guard)
        state, pending, cancellations = book(), [], 0
        for day in ("0001", "0002", "0003", "0004"):
            result = session(state, pending, day)
            assert len(pending) == 1 and pending[0].shares == 0
            assert not result.fills
            cancellations += len(result.cancelled)
        assert cancellations == 3
        with pytest.raises(AssertionError):
            assert_no_known_zero_retry()
    assert_no_known_zero_retry()


def test_unaffordable_candidate_does_not_consume_admission_or_slot():
    state, pending = book(), []
    result = session(state, pending, "0001", other=True)
    assert [p.security_id for p in pending] == ["B"]
    assert state.reserved_security_ids() == {"B"}
    amzn = next(s for s in result.decision.candidates
                if s.security_id == "AMZN")
    assert amzn.in_top_decile  # Feasibility did not remove it from leadership.


def test_price_becomes_affordable_without_new_cooldown_or_retry_state():
    state, pending = book(), []
    session(state, pending, "0001")
    assert not pending
    session(state, pending, "0002", opened=4000., close=4000.)
    assert len(pending) == 1 and pending[0].intended_dollars == 5000.
    result = session(state, pending, "0003", opened=4000., close=4000.)
    assert [(f["security_id"], f["shares"]) for f in result.fills] == [("AMZN", 1)]
    assert state.cash == 95_996.


def test_gap_zero_cancels_safely_and_changed_close_prevents_requeue():
    state, pending = book(), []
    session(state, pending, "0001", opened=4000., close=4000.)
    assert len(pending) == 1
    result = session(state, pending, "0002")
    assert len(result.cancelled) == 1
    assert result.cancelled[0]["reason"] == "UNAFFORDABLE_AT_OPEN"
    assert not result.fills and not pending and not state.reserved_security_ids()
    result = session(state, pending, "0003")
    assert not result.cancelled and not pending


def test_positive_cash_clipped_agn1_entry_still_fills_one_share():
    intended, reason = v5.admission(equity=214_460., cash=232.45, price=166.92)
    assert (intended, reason) == (10_723., "")
    state = book(232.45)
    state.reserve_slot(0, "AMZN", "AMZN", "ISSUER:AMZN")
    pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "AMZN", "AMZN", 0, 0,
                            "0001", "ENTRY_DURABLE_RANK",
                            intended_dollars=intended)]
    result = session(state, pending, "0002", opened=166.92, close=166.92,
                     candidates=False)
    assert result.fills[0]["shares"] == 1
    assert not result.cancelled and not pending
    assert state.cash == pytest.approx(232.45 - 166.92 * 1.001)


@pytest.mark.parametrize("price", [
    math.nextafter(100., 0.), 100., math.nextafter(100., math.inf),
])
def test_one_share_intended_budget_boundary_matches_opening(price):
    intended, reason = v5.admission(equity=2002., cash=2002., price=price)
    quantity = v5.opening_quantity(intended=100.1, cash=2002., price=price)
    assert (intended is not None) == (quantity >= 1)
    assert reason == ("" if quantity else BUDGET_REASON)


@pytest.mark.parametrize("cash", [
    math.nextafter(100.1, 0.), 100.1, math.nextafter(100.1, math.inf),
])
def test_one_share_total_cash_boundary_matches_opening(cash):
    intended, reason = v5.admission(equity=2002., cash=cash, price=100.)
    quantity = v5.opening_quantity(intended=100.1, cash=cash, price=100.)
    assert (intended is not None) == (quantity >= 1)
    assert reason == ("" if quantity else
                      "TOTAL_CASH_ONE_SHARE_UNAFFORDABLE_AT_CLOSE")


def test_transaction_cost_is_part_of_intended_budget():
    assert v5.admission(equity=100_000., cash=100_000., price=5000.,
                        cost_bps=0.) == (5000., "")
    assert v5.admission(equity=100_000., cash=100_000., price=5000.,
                        cost_bps=10.) == (None, BUDGET_REASON)
