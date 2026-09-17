"""Audit-only canonical NAV-to-target precision counterexample."""
from datetime import date
from decimal import Decimal
from sentinel.strategy import production_strategy
from sentinel.controller.machine import Controller
from sentinel.core.session import SessionState, PublishedSession
from sentinel.core.production import warm_session_state
from sentinel.core.kernel import advance_session
from sentinel.core.loader import CorpusWindow
from sentinel.core.decision import build_execution_plan, shadow_target, _shadow_weights
from sentinel.authority import RolloutMode, RolloutState
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from tests.sentinel.test_production_decision import _account, _binding, _observation, _publication
from dataclasses import replace
import json
import pytest


def canonical_two_days(close_adjustment):
    d1, d2 = '2026-08-11', '2026-08-12'
    hist = calendar.previous_sessions(d1, 253)[:-1]
    meta = {str(i): SecurityMeta(str(i), f'T{i}', 'Common Stock', str(i), first_session=hist[0]) for i in range(25)}
    bars = {s: [VendorBar(s, sid, m.ticker, 100-(252-k)*.2, 100-(252-k)*.2, 1e6,
                         signal_close=100-(252-k)*.2) for sid,m in meta.items()] for k,s in enumerate(hist)}
    window = CorpusWindow(hist, bars, meta)
    spy = {s: 100+k*.05 for k,s in enumerate(hist)}
    spy[d1] = 112.6; spy[d2] = 112.65
    window.median5_spy_closes = spy
    window.median5_terminals = {}
    cfg, identity = production_strategy()
    from sentinel.shadow_runtime import _starting_cash
    assert _starting_cash('20020') == Decimal(20020)
    env = SessionState.fresh(starting_cash=20020., controller=Controller(cfg), strategy_identity=identity)
    env = warm_session_state(env, window, publication_version=7, prospective_concordance_witness=True)
    stages = []
    for d in (d1,d2):
        days = calendar.previous_sessions(d, 210)
        p = PublishedSession(session=d, data_version=7,
            bars=[VendorBar(session=d,security_id=sid,ticker=m.ticker,raw_open=100.,
                            raw_close=100.+(close_adjustment if d==d2 and sid=='0' else 0),volume=1e6,
                            signal_close=100.+(close_adjustment if d==d2 and sid=='0' else 0)) for sid,m in meta.items()],
            meta=meta, sectors={sid:'Sector' for sid in meta}, spy_sessions=days,
            spy_expected_sessions=days, spy_closeadj=[spy[s] for s in days])
        prior = env.to_dict()
        env = advance_session(env,p,controller_config=cfg,strategy_identity=identity)
        assert prior == SessionState.from_dict(prior).to_dict()
        env = SessionState.from_dict(json.loads(json.dumps(env.to_dict())))
        stages.append(env)
        print(d, 'cash',env.wealth_core['cash'],'episodes', len(env.wealth_core['episodes']),
              'pending',len(env.pending), 'nav',env.shadow_nav_history[-1],
              'estimated',env.last_evidence['wealth_core']['estimated_equity'],
              'exposure',env.last_decision['target_core_exposure'])
    return env, meta, stages

@pytest.mark.parametrize('adjustment', [0., .0001, -.0001])
def test_canonical_target_rounding( adjustment):
    env, meta, stages = canonical_two_days(adjustment)
    marks = {sid:Decimal(str(100.+(adjustment if sid=='0' else 0))) for sid in meta}
    target = shadow_target(env)
    weights = _shadow_weights(env, target, marks)
    print('shares',target.shares, 'weights_total',sum(weights.values()))
    p = replace(_publication(), window_end='2026-08-12')
    def project():
        return build_execution_plan(env, _binding(), p, _account(equity='20000'), _observation(),
            marks, {sid:m.ticker for sid,m in meta.items()}, date(2026,8,12),date(2026,8,13), defensive_security=None,
            rollout_state=RolloutState(RolloutMode.CONTROLLER,1,certificate_sha256='a'*64))
    if sum(weights.values()) > 1:
        with pytest.raises(ValueError) as exc: project()
        print('REFUSAL',str(exc.value))
    else:
        result=project(); print('BASKET',result.plan.target_basket)


def test_rounding_up_omits_twenty_affordable_target_shares_after_real_opening_projection():
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
    assert set(decision.plan.target_basket.values()) == {Decimal(19)}
    assert len(decision.plan.target_basket) == 20
    assert sum(Decimal(oracle[sid])-decision.plan.target_basket[sid] for sid in oracle) == 20
    print('ROUND-UP ORACLE', {'actual_account_nav':str(account_nav),'cash':str(cash),
        'true_core_nav':str(true_core_nav),'rounded_core_nav':restored.last_evidence['wealth_core']['estimated_equity'],
        'opening_shares_per_name':19, 'oracle_target_per_name':20,'production_target_per_name':19})
