"""Hosted actual canonical parameter boundary/restore/transition admission."""
from copy import deepcopy
from fractions import Fraction
import math
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need

def qualify(p,profile):
    from stock_strategy_shared.wealth_core import v5,signals,median5
    from stock_strategy_shared.wealth_core.state import HoldingEpisode,SlotState,PortfolioState
    from stock_strategy_shared.wealth_core.feed import SecuritySeries
    from stock_strategy_shared.wealth_core.window_signals import feature
    from research.pooled_vacancy_funding import runtime
    cfg=v5.research_config(profile);n=p['slots'];cases=[]
    need(cfg.n_slots==n and cfg.entry_weight==1/n and cfg.max_admissions_per_session==p['admissions']
        and cfg.top_fraction==p['leadership'] and cfg.minimum_leadership_population==p['minimum_leaders']
        and cfg.volatility_profile==p['volatility'] and cfg.transaction_cost_bps==10,'ACTUAL_VARIANT_CONFIG')
    run=runtime.start(starting_cash=50000.,input_sha256='0'*64,policy=profile);cp=runtime.checkpoint(run)
    need(len(run.state.wealth_core['slots'])==n,'ACTUAL_SESSION_SLOT_DOMAIN')
    need(runtime.checkpoint(runtime.restore(cp,policy=profile,input_sha256='0'*64))==cp,'ACTUAL_FRESH_CONFIG_RESTORE');cases.append('runtime_config_and_fresh_roundtrip')
    ep=HoldingEpisode('S','S','SID:S',0,'2025-12-01','2025-12-02',100.,100.,100.,100.,episode_peak_split_adjusted_close=100.)
    boundary=float(Fraction(100)*Fraction(str(p['stop'])))
    need(ep.stop_triggered(boundary) and not ep.stop_triggered(boundary+.01),'ACTUAL_VARIANT_STOP')
    ep.market_sessions_held=p['review']-1;need(not ep.review_due,'VARIANT_REVIEW_EARLY');ep.market_sessions_held+=1;need(ep.review_due,'VARIANT_REVIEW_EXACT');cases.append('stop_review_boundaries')
    slot=SlotState(0,cooldown_sessions_elapsed=p['slot_cooldown']-1);need(slot.in_cooldown,'VARIANT_SLOT_COOLDOWN_EARLY');slot.age_cooldown();need(not slot.in_cooldown,'VARIANT_SLOT_COOLDOWN_RELEASE')
    book=PortfolioState.fresh(50000.,n_slots=n,entry_sizing_profile=profile);book.median5=median5.fresh()
    book.security_cooldowns['S']=p['security_cooldown']-1;need(book.security_in_cooldown('S'),'VARIANT_SECURITY_COOLDOWN_EARLY')
    original=book.to_dict();need(PortfolioState.from_dict(original).to_dict()==original,'VARIANT_COOLDOWN_VALID_RESTORE')
    bad=deepcopy(original);bad['security_cooldowns']['S']=p['security_cooldown']
    try:PortfolioState.from_dict(bad)
    except ValueError:pass
    else:raise ValueError('REFUSED_SECURITY_COOLDOWN_GUARD_ABSENT')
    bad=deepcopy(original);bad['slots']['0']['cooldown_sessions_elapsed']=p['slot_cooldown']
    try:PortfolioState.from_dict(bad)
    except ValueError:pass
    else:raise ValueError('REFUSED_SLOT_COOLDOWN_GUARD_ABSENT')
    cases.append('independent_cooldown_restore_bounds')
    dollars,reason=v5.admission(equity=30000.,cash=50000.,price=100.,cost_bps=10)
    need(not reason and dollars==float(Fraction(30000)/n),'ACTUAL_NAV_N_FUNDING')
    need(v5.opening_quantity(intended=dollars,cash=150.,price=100.,cost_bps=10)==1,'ACTUAL_POSITIVE_PARTIAL_PRESERVED');cases.append('funding_and_positive_partial')
    count=p['lookback']+1;closes=[100.+i*.1+(i%3)*.01 for i in range(count)];index=299
    series=SecuritySeries('S','S','SID:S',session_indices=list(range(index-count+1,index+1)),signal_closes=closes,
        raw_closes=[100.]*p['liquidity'],volumes=[10000000.]*p['liquidity'])
    meta=SimpleNamespace(category='Domestic Common Stock',first_session='2000-01-03',last_session=None)
    bar=feature(series,meta,index=index,session='2026-01-05');need(bar.eligible,'ACTUAL_VARIANT_FEATURE_ELIGIBLE')
    segment=closes[:len(closes)-p['skip']];returns=[math.log(b/a) if p['volatility']=='log_returns_certified_v1' else b/a-1 for a,b in zip(segment,segment[1:])]
    mean=sum(returns)/len(returns);vol=math.sqrt(sum((x-mean)**2 for x in returns)/(len(returns)-1))*math.sqrt(252)
    momentum=closes[-p['skip']-1]/closes[0]-1.;recent=closes[-1]/closes[-p['skip']-1]-1.
    need(bar.certified_signals==(momentum,recent,vol,math.log1p(momentum)/vol),'ACTUAL_ACTIVE_FEATURE_FORMULA')
    series.session_indices[-2]-=1;need(not feature(series,meta,index=index,session='2026-01-05').eligible,'ACTUAL_FEATURE_CAUSAL_AXIS_GUARD');cases.append('active_feature_horizon_formula_and_axis')
    if p['family']!='CORE':cases+=risk_cases(p,profile,cfg)
    return {'status':'ACTUAL_CAMPAIGN_VARIANT_CONFIGURATION_AND_CANONICAL_CASES_PASSED','cases':cases,'parameters':p,
        'profile':profile,'not_economic_performance':True,'local_financial_replay':False}

def risk_cases(p,profile,cfg):
    from stock_strategy_shared.wealth_core import median5,capital_risk
    from stock_strategy_shared.wealth_core.state import PortfolioState,HoldingEpisode
    from stock_strategy_shared.wealth_core.adapter import step_session
    from stock_strategy_shared.wealth_core.engine import SecurityBar,Operation
    from stock_strategy_shared.wealth_core.prices import DailyBar
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from sentinel.feed.calendar import previous_sessions
    book=PortfolioState.fresh(5000.,n_slots=p['slots'],entry_sizing_profile=profile);book.median5=median5.fresh();book.median5['formation_started']=True;book.initialized=True
    ep=HoldingEpisode('S','S','SID:S',0,'2025-12-01','2025-12-02',100.,100.,100.,100.,episode_peak_split_adjusted_close=100.,market_sessions_held=17,review_completed=True)
    book.episodes[0]=ep;book.slots[0].occupied_by='S';pending=[];ledger=Ledger();last={'S':100.};day='2026-01-05'
    if p['family']=='V':ep.research_stop_floor=90.;ep.research_stop_cursor='2026-01-02'
    h=p['v_horizon'] if p['family']=='V' else 21;price=85. if p['family']=='V' else 100.
    b=DailyBar('S','S','SID:S',day,price,price,price)
    security=SecurityBar('S','S','SID:S',[100.]*(h-1)+[price],raw_close=price,eligible=False,signal_sessions=previous_sessions(day,h))
    result=step_session(session=day,state=book,pending=pending,ledger=ledger,last_known=last,cfg=cfg,
        strategy_id='RESEARCH_SYNTHETIC',strategy_version=1,bars=[b],security_bars=[security])
    if p['family']=='V':
        need(any(o.operation is Operation.CLOSE_POSITION for o in result.decision.operations),'ACTUAL_OLD_VOLATILITY_FLOOR_FIRST')
        need(ep.research_stop_cursor==day,'ACTUAL_VOLATILITY_CURSOR')
        need(PortfolioState.from_dict(book.to_dict()).to_dict()==book.to_dict(),'ACTUAL_VOLATILITY_STATE_RESTORE')
        return ['canonical_old_floor_first_close_and_restore']
    trim,=[o for o in result.decision.operations if o.operation is Operation.REDUCE_POSITION]
    wanted=int((Fraction(15000)*Fraction(str(p['c_target'])))//100)
    need(trim.shares==100-wanted and len(pending)==1,'ACTUAL_CONCENTRATION_INTENT')
    day='2026-01-06';b=DailyBar('S','S','SID:S',day,100.,100.,100.)
    security=SecurityBar('S','S','SID:S',[100.]*21,raw_close=100.,eligible=False,signal_sessions=previous_sessions(day,21))
    result=step_session(session=day,state=book,pending=pending,ledger=ledger,last_known=last,cfg=cfg,
        strategy_id='RESEARCH_SYNTHETIC',strategy_version=1,bars=[b],security_bars=[security])
    need(ep.current_shares==wanted and book.cash==5000.+(100-wanted)*100*.999,'ACTUAL_CONCENTRATION_FILL_AND_FEES')
    need(PortfolioState.from_dict(book.to_dict()).to_dict()==book.to_dict(),'ACTUAL_CONCENTRATION_RESTORE')
    try:capital_risk.exact_float(Fraction(1,3))
    except ValueError:pass
    else:raise ValueError('REFUSED_TRIM_EXACT_REPRESENTATION_GUARD_ABSENT')
    return ['canonical_trim_intent_next_open_fill_fees_restore','nonrepresentable_trim_refused']
