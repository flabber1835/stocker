"""Audit-only witness: decimal budget and canonical/production share sizing."""
from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction as F
import json
from sentinel.core import decision
from sentinel.execution import opening_sizing
from stock_strategy_shared.wealth_core import v5
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from tests.v5.test_v5 import book, advance, SecurityBar
from tests.v5.test_opening import case, prices, base
from tests.sentinel.test_production_decision import (
    _binding, _publication, _account, _observation, DECISION_SESSION, EFFECTIVE_SESSION)
from sentinel.authority import RolloutState, RolloutMode


def test_decimal_intended_boundary_in_shadow_and_broker_projection():
    equity = 51641.59
    price = 103.18
    intended, why = v5.admission(equity=equity, cash=equity, price=price)
    assert not why
    assert str(intended) == '2582.0795'
    unit = F(str(price)) * F('1.001')
    oracle = F(str(intended)) // unit
    assert oracle == 25
    assert F(str(intended)) == oracle * unit
    actual = v5.opening_quantity(intended=intended,cash=equity,price=price)
    assert actual == 24

    # Canonical prior-close admission binds its own 5% dollar intent.
    state, pending = book(), []
    state.cash = equity
    candidate = SecurityBar('A','A','SID:A',[80.,price],price,True,'',(.5,.1,.2,2.))
    advance(state,pending,'0001',opened=price,close=price,candidates=[candidate])
    assert len(pending)==1 and pending[0].intended_dollars==intended
    filled = advance(state,pending,'0002',opened=price,close=price)
    assert filled.fills[0]['shares'] == actual
    assert state.episodes[0].current_shares == actual

    # Independently exercise the current production opening projection.
    env, original = case(cash=equity)
    env.pending[0]['intended_dollars'] = intended
    env.last_evidence['wealth_core']['estimated_equity'] = equity
    plan = decision.build_execution_plan(env,_binding(),_publication(),
        _account(equity=str(equity)),_observation(),{'SEC-AAA':D(str(price))},
        {'SEC-AAA':'AAA'},DECISION_SESSION,EFFECTIVE_SESSION,defensive_security=None,
        rollout_state=RolloutState(mode=RolloutMode.CONTROLLER,version=1,
                                  certificate_sha256='a'*64)).plan
    before = env.to_dict()
    projected = opening_sizing.resolve(env,plan,base(env,plan),prices(env,plan,price=str(price)))
    assert projected.target_basket['SEC-AAA']==actual
    assert env.to_dict()==before
    print('AUDIT_WITNESS',json.dumps(dict(equity=equity,intended=intended,price=price,
        exact_whole_shares=oracle,canonical_fill=actual,
        broker_target=str(projected.target_basket['SEC-AAA']),
        floating_quotient=intended/(price*1.001),
        exact_total_cost=str(D(25)*D(str(price))*D('1.001')),
        actual_cash=state.cash)))
