"""Positive economic acceptance criteria for existing #399 F2/F9/F10.

These tests assert required economic results. Confirmed defects must produce
ordinary failures; no xfail, exception-as-success, or production patch is used.
Adjacent passing controls distinguish the exact decision boundaries.
"""
from datetime import date
from decimal import Decimal as D
from fractions import Fraction as F
import json

import pytest
from sentinel.authority import RolloutMode, RolloutState
from sentinel.core import decision
from sentinel.core.kernel import advance_session
from sentinel.core.session import PublishedSession, SessionState
from sentinel.execution import opening_sizing
from sentinel.feed import calendar
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core import v5
from stock_strategy_shared.wealth_core.feed import VendorBar
from tests.v5.test_v5 import book, advance, SecurityBar
from tests.v5.test_opening import case, prices, base
from tests.sentinel.test_production_decision import (
    _binding, _publication, _account, _observation, DECISION_SESSION, EFFECTIVE_SESSION)
from audit.economic_399.continuation_20260917.probes.test_rounded_nav import canonical_two_days


@pytest.mark.parametrize('offset', ['-0.0001','0','0.0001'], ids=['below','exact','above'])
def test_f2_intended_budget_matches_independent_decimal_oracle(offset, record_property):
    intended, reason = v5.admission(equity=51641.59, cash=51641.59, price=103.18)
    assert reason == '' and str(intended) == '2582.0795'
    intended = float(D(str(intended)) + D(offset))
    oracle = min(F(str(intended)) // (F('103.18') * F('1.001')),
                 F('51641.59') // (F('103.18') * F('1.001')))
    actual = v5.opening_quantity(intended=intended, cash=51641.59, price=103.18)
    record_property('finding','F2'); record_property('oracle_shares',oracle)
    record_property('actual_shares',actual)
    assert actual == oracle, f'F2: actual {actual}, exact affordable/intended shares {oracle}'


@pytest.mark.parametrize('path', ['canonical-shadow','production-projection'])
def test_f2_real_paths_preserve_exactly_affordable_share(path, record_property):
    equity, price = 51641.59, 103.18
    intended, why = v5.admission(equity=equity, cash=equity, price=price)
    assert why == ''
    oracle = F(str(intended)) // (F(str(price)) * F('1.001'))
    assert oracle == 25
    if path == 'canonical-shadow':
        state, pending = book(), []
        state.cash = equity
        candidate = SecurityBar('A','A','SID:A',[80.,price],price,True,'',(.5,.1,.2,2.))
        advance(state,pending,'0001',opened=price,close=price,candidates=[candidate])
        assert len(pending) == 1 and pending[0].intended_dollars == intended
        filled = advance(state,pending,'0002',opened=price,close=price)
        actual = filled.fills[0]['shares']
        assert state.episodes[0].current_shares == actual
    else:
        env, _ = case(cash=equity)
        env.pending[0]['intended_dollars'] = intended
        env.last_evidence['wealth_core']['estimated_equity'] = equity
        plan = decision.build_execution_plan(env,_binding(),_publication(),
            _account(equity=str(equity)),_observation(),{'SEC-AAA':D(str(price))},
            {'SEC-AAA':'AAA'},DECISION_SESSION,EFFECTIVE_SESSION,defensive_security=None,
            rollout_state=RolloutState(mode=RolloutMode.CONTROLLER,version=1,
                                      certificate_sha256='a'*64)).plan
        before = env.to_dict()
        projected = opening_sizing.resolve(env,plan,base(env,plan),prices(env,plan,price=str(price)))
        actual = projected.target_basket['SEC-AAA']
        assert env.to_dict() == before
    record_property('finding','F2');record_property('economic_path',path)
    record_property('oracle_shares',oracle);record_property('actual_shares',str(actual))
    assert actual == oracle, f'F2/{path}: actual {actual}, exact economic oracle {oracle}'


@pytest.mark.parametrize('adjustment', [0., .0001, -.0001], ids=['exact-cent','rounded-down','rounded-up'])
def test_f9_target_weights_use_economic_nav(adjustment, record_property):
    env, meta, _ = canonical_two_days(adjustment)
    marks = {sid:D(str(100.+(adjustment if sid=='0' else 0))) for sid in meta}
    target = decision.shadow_target(env)
    nav = F(str(env.wealth_core['cash'])) + sum(F(q)*F(marks[sid]) for sid,q in target.shares.items())
    expected = {sid:F(q)*F(marks[sid])/nav for sid,q in target.shares.items()}
    actual = decision._shadow_weights(env, target, marks)
    assert sum(expected.values()) == 1
    # Twenty individually rounded 28-digit Decimal weights have aggregate
    # representation error below this 1e-25 bound. F9's errors are about 5e-8.
    errors = {sid:abs(F(actual[sid])-value) for sid,value in expected.items()}
    record_property('finding','F9');record_property('exact_nav',str(nav))
    record_property('reported_nav',env.last_evidence['wealth_core']['estimated_equity'])
    record_property('actual_total_weight',str(sum(actual.values())))
    record_property('max_weight_error',str(max(errors.values())))
    assert all(error <= F(1,10**25) for error in errors.values()), 'F9: diagnostic cent rounding changed economic target weights'


def _day(env, meta, session, sid_close, sid_open=None):
    cfg,identity = production_strategy()
    all_days = calendar.previous_sessions('2026-08-11',253)[:-1] + calendar.sessions_in_range('2026-08-11',session)
    spy = {d:100+i*.05 for i,d in enumerate(all_days)}
    days = calendar.previous_sessions(session,210)
    bars = [VendorBar(session=session,security_id=sid,ticker=m.ticker,
        raw_open=(sid_open if sid_open is not None else sid_close) if sid=='0' else 100.,
        raw_close=sid_close if sid=='0' else 100.,volume=1e6,
        signal_close=sid_close if sid=='0' else 100.) for sid,m in meta.items()]
    published = PublishedSession(session,7,bars,meta,{s:'Sector' for s in meta},[spy[d] for d in days],
        spy_sessions=days,spy_expected_sessions=days)
    before = json.loads(json.dumps(env.to_dict()))
    result = advance_session(SessionState.from_dict(before),published,controller_config=cfg,strategy_identity=identity)
    assert env.to_dict() == before
    return SessionState.from_dict(json.loads(json.dumps(result.to_dict())))


@pytest.mark.parametrize('close', ['70.69','70.70','70.71'], ids=['below-stop','inclusive-stop','above-stop'])
def test_f10_inclusive_stop_reaches_next_open_economics(close, record_property):
    env,meta,_ = canonical_two_days(0.)
    peak = _day(env,meta,'2026-08-13',101.)
    ep = next(x for x in peak.wealth_core['episodes'].values() if x['security_id']=='0')
    assert ep['episode_peak_split_adjusted_close'] == 101.
    expected_exit = D(close) <= D('101') * D('0.7')
    stopped = _day(peak,meta,'2026-08-14',float(close))
    observed_exit = bool(next(x for x in stopped.wealth_core['episodes'].values() if x['security_id']=='0')['exit_pending'])
    following = _day(stopped,meta,'2026-08-17',60.,60.)
    owned = sum(x['current_shares'] for x in following.wealth_core['episodes'].values() if x['security_id']=='0')
    cash = D(str(following.wealth_core['cash']))
    expected = (expected_exit,0 if expected_exit else 10,D('599.4') if expected_exit else D(0))
    actual = (observed_exit,owned,cash)
    record_property('finding','F10');record_property('oracle_economics',str(expected))
    record_property('actual_economics',str(actual))
    assert actual == expected, f'F10: observed {actual}; exact inclusive-stop oracle {expected}'
