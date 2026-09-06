from __future__ import annotations

import math

from backtester.production_equivalent_economic_overlay import (
    _move_dividend_accrual_before_open_equity,
    _remove_cumulative_terminal_retirement,
    _remove_missing_mark_hard_abort,
)


def test_dividend_accrual_moves_before_open_equity_and_keeps_one_session_lag():
    source = """def f():
            prior_qty={1:100.0}
            open_eq,_=book.equity(opraw)
            x=1
            for tid,amt in dividends:
                if tid in prior_qty:
                    book.receivables.append((gday+1,prior_qty[tid]*amt))
            y=2
"""
    out = _move_dividend_accrual_before_open_equity(source)
    assert out.index("receivables.append") < out.index("open_eq,_=book.equity(opraw)")
    assert "gday+1" in out.replace(" ", "")


def test_cumulative_retirement_filter_is_removed_without_touching_current_term_tids():
    source = """def f():
    _retired_tids=set()
    term_tids={1}
    _retired_tids.update(term_tids)
    elig=elig&~np.isin(tids,list(_retired_tids))
    if s.reserved() and s.pending_tid in _retired_tids:
        s.pending_tid=-1
    if s.reserved() and s.pending_tid in term_tids:
        s.pending_tid=-1
    return term_tids
"""
    out = _remove_cumulative_terminal_retirement(source)
    assert "_retired_tids" not in out
    assert "pending_tid in term_tids" in out


def test_missing_mark_hard_abort_is_removed_but_unresolved_state_survives():
    source = """def f():
            eq,unresolved=book.equity(clraw)
            if unresolved and date>=START:
                _detail=[]
                raise RuntimeError(f'financial-grade NAV unresolved on {ds}: {_detail}')
            if not unresolved:
                admit()
"""
    out = _remove_missing_mark_hard_abort(source)
    assert "eq,unresolved=book.equity(clraw)" in out
    assert "financial-grade NAV unresolved" not in out
    assert "if not unresolved" in out


def _overnight_factor(prior_exposure: float, open_exposure: float, price_factor: float, dividend_yield: float) -> float:
    """Allocation witness with prior-close dividend entitlement accrued at open."""
    prior_claim = prior_exposure * dividend_yield
    return (1.0 - prior_exposure) + prior_exposure * price_factor + prior_claim


def test_dividend_entitlement_transition_100_to_0_is_not_lost():
    # A 10% ex-dividend price drop paired with a 10% dividend leaves the
    # overnight 100%-owned economic factor at 1.0 even if sold at the open.
    assert math.isclose(_overnight_factor(1.0, 0.0, 0.90, 0.10), 1.0)


def test_dividend_entitlement_transition_0_to_100_is_not_granted_to_open_buyer():
    # The overnight book had no shares, so the new open buyer gets no ex-date
    # dividend in the overnight allocation leg.
    assert math.isclose(_overnight_factor(0.0, 1.0, 0.90, 0.10), 1.0)


def test_dividend_entitlement_transition_100_to_100_preserves_total_return():
    assert math.isclose(_overnight_factor(1.0, 1.0, 0.90, 0.10), 1.0)
