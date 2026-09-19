"""Independent exact NAV-to-account-quantity acceptance."""
from datetime import date
from decimal import Decimal
from sentinel.core.session import SessionState
from sentinel.core.decision import build_execution_plan, shadow_target
from sentinel.authority import RolloutMode, RolloutState
from tests.sentinel.test_production_decision import _account, _binding, _observation, _publication
from dataclasses import replace
import json


from tests.support.canonical_economic_book import canonical_two_days

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
