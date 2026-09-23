"""Positive production call-chain acceptance on an independently generated book."""
from dataclasses import replace
import json
import math
from types import SimpleNamespace

import pytest

from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.production import warm_session_state
from sentinel.core.session import PublishedSession, SessionState
from sentinel.feed.calendar import sessions_in_range
from sentinel.strategy import owned_impairment_strategy
from sentinel.controller.champion_config import load
from sentinel.core.decision import runtime_strategy_identity

def production_strategy():
    cfg=load()
    return cfg,runtime_strategy_identity(cfg)
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar


@pytest.fixture(scope='module')
def transitions():
    dates=sessions_in_range('2020-01-01','2022-12-31')[:317]
    meta={f'T{i:02d}':SecurityMeta(f'T{i:02d}',f'T{i:02d}','Domestic Common Stock',f'T{i:02d}',first_session=dates[0]) for i in range(30)}
    prices={sid:100.+i for i,sid in enumerate(meta)}
    spy=[100.];published=[]
    for day,session in enumerate(dates):
        spy.append(spy[-1]*(1.0004+.001*math.sin(day*.31)))
        bars=[]
        for i,sid in enumerate(meta):
            previous=prices[sid]
            gross=(1.001+.0005*math.sin(day*.13+i))*(.99 if day>=292 else 1.)
            prices[sid]*=gross
            bars.append(VendorBar(session,sid,sid,prices[sid],previous*math.sqrt(gross),1e6,signal_close=prices[sid]))
        start=max(0,day-40)
        published.append(PublishedSession(session,1,bars,meta,{s:'S' for s in meta},
            spy_closeadj=spy[start+1:day+2],spy_sessions=dates[start:day+1],spy_expected_sessions=dates[start:day+1]))
    warm=published[:252]
    window=SimpleNamespace(sessions=dates[:252],bars_by_session={p.session:p.bars for p in warm},
        meta=meta,median5_spy_closes={s:v for s,v in zip(dates,spy[1:])},median5_terminals={})
    results={}
    for name,factory in [('current',production_strategy),('owned',owned_impairment_strategy)]:
        cfg,identity=factory()
        state=SessionState.fresh(starting_cash=50000.,controller=Controller(cfg),strategy_identity=identity)
        state=warm_session_state(state,window,publication_version=1,prospective_concordance_witness=True)
        rows=[]
        for p in published[252:]:
            prior=state
            state=advance_session(state,p,controller_config=cfg,strategy_identity=identity)
            if len(rows)>=40:
                repeated=advance_session(SessionState.from_dict(json.loads(json.dumps(prior.to_dict()))),
                    replace(p,bars=tuple(reversed(p.bars))),controller_config=cfg,strategy_identity=identity)
                assert state.state_hash==repeated.state_hash
            rows.append(state)
        results[name]=rows
    return results


def test_complete_kernel_enforces_owned_protection_with_same_core(transitions):
    before=transitions['current'];after=transitions['owned']
    assert len(before[39].wealth_core['episodes'])==20
    for old,new in zip(before,after):
        assert old.wealth_core==new.wealth_core
        assert old.ledger==new.ledger
        assert old.last_evidence['observation']==new.last_evidence['observation']
    stress=after[40:]
    first=next(i for i,s in enumerate(stress) if s.owned_impairment['active'])
    assert first>=4
    for s in stress[first-4:first+1]:
        o=s.last_evidence['observation']
        assert o['shadow_drawdown']<=-.10 and o['damaged_breadth']>=.88 and o['green_breadth']<=.20
    assert stress[first].last_decision['owned_impairment']['reason']=='OWNED_IMPAIRMENT_ENTER'
    for s in stress[first:]:
        assert s.last_decision['target_core_exposure'] == min(.55, s.last_decision['champion_target_core_exposure'])
        assert s.last_decision['owned_impairment']['ceiling'] == .55
