"""Independent exact NAV-to-account-quantity acceptance."""
from datetime import date
from decimal import Decimal
from sentinel.core.session import SessionState
from sentinel.core.decision import build_execution_plan, shadow_target
from sentinel.authority import RolloutMode, RolloutState
from tests.sentinel.test_production_decision import _account, _binding, _observation, _publication
from dataclasses import replace
import json
import pytest
from decimal import localcontext


from tests.support.canonical_economic_book import canonical_two_days


@pytest.mark.parametrize('precision', [6, 28])
@pytest.mark.parametrize('nav,expected', [('2999', 9), ('3000', 10), ('3001', 10), ('6000', 20)])
def test_production_share_scaling_does_not_floor_a_rounded_weight(precision, nav, expected):
    from tests.sentinel.test_production_decision import _state, _episode
    state = _state(episodes=[_episode(0, 'sec-a', 'AAA', 10)], equity='3000', exposure='1')
    # Core owns $1,000 of shares and $2,000 cash. At equal NAV/exposure the
    # account must own the same ten shares; 1/3 is not a stored target weight.
    before = state.to_dict()
    with localcontext() as context:
        context.prec = precision
        decision = build_execution_plan(state, _binding(), _publication(),
            _account(equity=nav), _observation(), {'sec-a': Decimal(100)}, {'sec-a': 'AAA'},
            date(2026, 8, 11), date(2026, 8, 12), defensive_security=None,
            rollout_state=RolloutState(RolloutMode.CONTROLLER, 1, certificate_sha256='a'*64))
    assert decision.plan.target_basket == {'sec-a': Decimal(expected)}
    assert state.to_dict() == before


@pytest.mark.parametrize('precision', [6, 28])
def test_opening_share_scaling_floors_once_after_exact_ratio(precision):
    from sentinel.execution import opening_sizing
    from tests.v5.test_opening import case, prices, base
    state, _ = case(cash=3000)
    state.last_evidence['wealth_core']['estimated_equity'] = 3000
    plan = build_execution_plan(state, _binding(), _publication(),
        _account(equity='1000'), _observation(), {'SEC-AAA': Decimal(999)}, {'SEC-AAA': 'AAA'},
        date(2026, 8, 11), date(2026, 8, 12), defensive_security=None,
        rollout_state=RolloutState(RolloutMode.CONTROLLER, 1, certificate_sha256='a'*64)).plan
    with localcontext() as context:
        context.prec = precision
        result = opening_sizing.resolve(state, plan, base(state, plan), prices(state, plan, price='999'))
    # Three Core shares cost 3 * 999 * 1.001 = 2999.997. At one third
    # account scale, exactly one share is intended, with $1 account cash left.
    assert result.opening_sizing['entries'][0]['core_shares'] == '3'
    assert result.target_basket == {'SEC-AAA': Decimal(1)}


@pytest.mark.parametrize('sleeve', [False, True])
def test_projection_never_rounds_unaffordable_fraction_up_to_one_share(sleeve):
    from sentinel.execution.projection import project
    nav = Decimal('0.99999999999999999999999999999')
    result = project(shadow_weights={} if sleeve else {'A': Decimal(1)},
        exposure=Decimal(0 if sleeve else 1), nav=nav, marks={'A': Decimal(1)},
        defensive_security='A' if sleeve else None, defensive_weight=Decimal(1) if sleeve else None)
    assert result.quantities == {}
    assert result.defensive_quantity == 0
    assert result.cash_residual == nav


@pytest.mark.parametrize('denominator', ['0', '-1', 'NaN', 'Infinity'])
def test_projector_refuses_invalid_weight_denominator(denominator):
    from sentinel.execution.projection import project, ProjectionRefused
    with pytest.raises(ProjectionRefused):
        project(shadow_weights={}, exposure=Decimal(0), nav=Decimal(100),
                marks={}, weight_denominator=Decimal(denominator))


def test_partial_fill_remainder_is_not_rounded_into_an_overlapping_order():
    from sentinel.execution import commands as C
    from tests.sentinel.test_execution_contract import order, obs, pos, ident, INSTR
    from sentinel.execution.contract import Side
    tiny = '0.00000000000000000000000000001'
    expected = Decimal('0.99999999999999999999999999999')
    working = order(qty='1', filled=tiny)
    command = C.Command(ident(), INSTR, Side.SELL, Decimal(1),
                        filled_quantity=Decimal(tiny))
    assert working.remaining == expected
    assert command.remaining == expected
    assert command.signed_remaining == expected.copy_negate()
    # The one-share target is fully allocated between its tiny fill and the
    # exact working remainder. No new order (even dust) is economically due.
    delta = C.compute_delta(security_id=INSTR.security_id, desired=Decimal(1),
        observation=obs(orders=[working], positions=[pos(tiny)]))
    assert delta.remaining == 0
    assert delta.classification is C.DeltaClass.NONE


def test_exact_delta_and_magnitude_preserve_a_fractional_position():
    from sentinel.execution import commands as C
    from tests.sentinel.test_execution_contract import obs, pos, INSTR
    quantity = '1.00000000000000000000000000001'
    delta = C.compute_delta(security_id=INSTR.security_id, desired=Decimal(0),
                            observation=obs(positions=[pos(quantity)]))
    assert delta.remaining == Decimal(quantity).copy_negate()
    assert delta.quantity == Decimal(quantity)


def test_committed_orders_do_not_erase_a_small_excess():
    from sentinel.execution import commands as C
    from tests.sentinel.test_execution_contract import order, obs, INSTR
    working = [order('first', qty='0.6'),
               order('second', qty='0.40000000000000000000000000001')]
    assert C.committed_quantity(working) == Decimal('1.00000000000000000000000000001')
    delta = C.compute_delta(security_id=INSTR.security_id, desired=Decimal(1),
                            observation=obs(orders=working))
    assert delta.remaining == Decimal('-0.00000000000000000000000000001')
    assert delta.classification is C.DeltaClass.DUST

def test_full_precision_nav_preserves_twenty_affordable_target_shares():
    from fractions import Fraction
    from sentinel.execution import opening_sizing
    from sentinel.execution.contract import BrokerInstrument, BrokerPosition
    from tests.v5.test_opening import prices, base
    env, meta, stages = canonical_two_days(-.0001)
    first = stages[0]
    tickers = {sid:m.ticker for sid,m in meta.items()}
    rollout = RolloutState(RolloutMode.CONTROLLER,1,certificate_sha256='a'*64)
    first_plan = build_execution_plan(first,_binding(),_publication(),_account(equity='40000'),
        _observation(),{sid:Decimal(100) for sid in meta},tickers,
        date(2026,8,11),date(2026,8,12),defensive_security=None,rollout_state=rollout).plan
    opened = opening_sizing.resolve(first, first_plan, base(first,first_plan), prices(first,first_plan))
    assert len(opened.target_basket) == 20
    assert set(opened.target_basket.values()) == {Decimal(19)}
    # Controlled broker arithmetic: fills at the actual $100 open, zero explicit fees.
    cash = Decimal(40000) - sum(q*Decimal(100) for q in opened.target_basket.values())
    assert cash == 2000
    marks = {sid:Decimal('99.9999') if sid=='0' else Decimal(100) for sid in meta}
    positions = [BrokerPosition(BrokerInstrument(sid,tickers[sid],f'asset-{sid}'),q)
                 for sid,q in opened.target_basket.items()]
    account_nav = cash + sum(q*marks[sid] for sid,q in opened.target_basket.items())
    assert account_nav == Decimal('39999.9981')
    restored = SessionState.from_dict(json.loads(json.dumps(env.to_dict())))
    decision = build_execution_plan(restored,_binding(),replace(_publication(),window_end='2026-08-12'),
        _account(equity=str(account_nav),cash=str(cash)),_observation(positions=positions),marks,tickers,
        date(2026,8,12),date(2026,8,13),defensive_security=None,rollout_state=rollout)
    core = shadow_target(restored)
    true_core_nav = Decimal(str(restored.wealth_core['cash'])) + sum(q*marks[sid] for sid,q in core.shares.items())
    assert true_core_nav == Decimal('19999.999')
    oracle = {sid:int(Fraction(q)*Fraction(account_nav)/Fraction(true_core_nav)) for sid,q in core.shares.items()}
    assert set(oracle.values()) == {20}
    assert set(decision.plan.target_basket.values()) == {Decimal(20)}
    assert len(decision.plan.target_basket) == 20
    assert sum(Decimal(oracle[sid])-decision.plan.target_basket[sid] for sid in oracle) == 0
