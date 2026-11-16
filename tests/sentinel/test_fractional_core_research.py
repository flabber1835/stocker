"""Independent cash/share checks on the research-only canonical entry overlay."""
from decimal import Decimal as D
from fractions import Fraction
import json
import math

import pytest

from research.main_cagr.fractional import activate, affordable_quantity, transform, PROFILE
from stock_strategy_shared.wealth_core import adapter, engine, v5
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.v5.test_v5 import bars, book, PendingOrder, Operation
from sentinel.controller import ex3_v6


def advance(state, pending, session, *, opened, close, split=1.):
    return adapter.step_session(session=session, state=state,
        bars=bars(session, opened=opened, close=close, split=split),
        security_bars=[], pending=pending, ledger=Ledger(), last_known={},
        cfg=v5.config(), strategy_id=ex3_v6.STRATEGY_ID, strategy_version=1)


def test_fractional_admission_removes_one_share_cap_but_preserves_cash_and_market_guards():
    assert v5.admission(equity=50000, cash=100, price=300)[0] is None
    with activate():
        assert v5.admission(equity=50000, cash=100, price=300)[0] == 2500
        assert v5.admission(equity=50000, cash=0, price=300)[0] is None
        assert v5.admission(equity=50000, cash=100, price=None)[0] is None
    assert v5.admission(equity=50000, cash=100, price=300)[0] is None


@pytest.mark.parametrize('budget,price', [(2500,300), (2500,3000), (25000,3000), (1,1e6), (123.45,7.13)])
def test_fractional_quantity_is_maximum_bounded_by_exact_costs(budget, price):
    actual = affordable_quantity(budget, price, 10)
    unit = Fraction(str(price))*Fraction(1001,1000)
    exact = Fraction(str(budget))/unit
    assert actual > 0 and Fraction(str(actual))*unit <= Fraction(str(budget))
    assert abs(Fraction(str(actual))-exact) <= Fraction(2,10**12)
    with activate():
        assert v5.opening_quantity(intended=budget*2, cash=budget, price=price) == actual


def test_fractional_entry_split_exit_and_restart_preserve_cash_and_all_share_records():
    from stock_strategy_shared.wealth_core.adapter import PendingOrder
    with activate():
        state = book()
        state.reserve_slot(0, 'A', 'A', 'SID:A')
        pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, 'A', 'A', 0, 0,
                                '0001', 'ENTRY_DURABLE_RANK', intended_dollars=5000.)]
        result = advance(state, pending, '0002', opened=6000., close=6000.)
        quantity = result.fills[0]['shares']
        assert 0 < quantity < 1
        assert state.episodes[0].initial_shares == quantity
        assert state.episodes[0].current_shares == quantity
        assert state.episodes[0].source_lots[0]['shares'] == quantity
        assert state.cash == pytest.approx(100000-float(D(str(quantity))*D(6000)*D('1.001')), abs=1e-9)
        restored = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
        assert restored.to_dict() == state.to_dict()
        for value in (state, restored):
            advance(value, [], '0003', opened=3000., close=3000., split=2.)
        assert restored.to_dict() == state.to_dict()
        assert state.episodes[0].current_shares == pytest.approx(2*quantity, abs=1e-12)
        cash_before = state.cash
        qty = state.episodes[0].current_shares
        order = PendingOrder(Operation.CLOSE_POSITION, 'A', 'A', 0, qty, '0003', 'EXIT_REVIEW_WEAKNESS')
        result = advance(state, [order], '0004', opened=3100., close=3100.)
        assert not state.episodes and result.fills[0]['shares'] == qty
        assert state.cash == pytest.approx(cash_before+float(D(str(qty))*D(3100)*D('.999')), abs=1e-9)


def test_research_state_and_functions_cannot_silently_become_production():
    from sentinel.controller.machine import Controller
    from sentinel.core.session import SessionState
    from sentinel.strategy import production_strategy
    original = (adapter.step_session, engine.apply_entry, v5.PROFILE)
    with activate():
        cfg, identity = production_strategy()
        state = SessionState.fresh(starting_cash=50000, controller=Controller(cfg), strategy_identity=identity)
        raw = state.to_dict()
        assert raw['wealth_core']['entry_sizing_profile'] == PROFILE
        assert SessionState.from_dict(raw).state_hash == state.state_hash
    assert (adapter.step_session, engine.apply_entry, v5.PROFILE) == original
    with pytest.raises(ValueError, match='entry sizing profile'):
        SessionState.from_dict(raw)


def test_unknown_source_seam_refuses():
    with pytest.raises(ValueError, match='source seam changed'):
        transform(v5.admission, [('not-the-reviewed-source', '', 1)])
