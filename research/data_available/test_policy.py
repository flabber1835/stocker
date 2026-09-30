from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import math

import pytest

from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.median5 import fresh
from stock_strategy_shared.wealth_core.run import run_sessions
from stock_strategy_shared.wealth_core.state import HoldingEpisode
from stock_strategy_shared.wealth_core.v5 import config
from research.data_available.policy import (
    RollingState, apply_corrections, rebase, snapshot_bars, trim)
from research.data_available.run import Arm


def day(i):
    return str(date(2020,1,1)+timedelta(days=i))


def meta(n=1):
    return {str(i):SecurityMeta(str(i),'S'+str(i),category='Domestic Common Stock',
                permaticker=str(i),first_session=day(0)) for i in range(n)}


def bars(i,n=1):
    return [VendorBar(day(i),str(k),'S'+str(k),
        p:=50*math.exp(.001*i+.025*math.sin(i*.37+k)),p,1_000_000.,signal_close=p) for k in range(n)]


def filled_feed(count=150):
    feed=Feed(meta())
    feed.median5_state=fresh()
    for i in range(count):
        norm=feed.advance(day(i),bars(i))
    return feed,norm


def test_current_snapshot_recomputes_corrections_without_mutating_book():
    feed,norm=filled_feed()
    arm=Arm('snapshot')
    before=deepcopy(arm.state.to_dict())
    old=snapshot_bars(feed,norm.security_bars)[0].certified_signals
    s=feed.series['0']
    apply_corrections(feed,[dict(security_id='0',session=s.sessions[-40],
        signal_close=s.signal_closes[-40]*1.1,raw_close=s.raw_closes[-40],volume=s.volumes[-40])])
    new=snapshot_bars(feed,norm.security_bars)[0].certified_signals
    assert new!=old
    assert arm.state.to_dict()==before


@pytest.mark.parametrize('fault',['future','old','duplicate','invalid'])
def test_corrections_are_atomic_and_window_bounded(fault):
    feed,norm=filled_feed(320)
    s=feed.series['0']
    good=dict(security_id='0',session=s.sessions[-40],signal_close=60.,raw_close=60.,volume=1_000_000.)
    bad={**good,'session':{'future':day(321),'old':day(0)}.get(fault,good['session'])}
    if fault=='invalid':
        bad['signal_close']=float('nan')
    before=deepcopy(s)
    with pytest.raises(ValueError):
        apply_corrections(feed,[good,bad])
    assert s==before


def test_missing_candidate_is_excluded_and_readmitted():
    feed,norm=filled_feed()
    assert snapshot_bars(feed,norm.security_bars)[0].eligible
    feed.advance(day(150),[])
    for i in range(151,277):
        norm=feed.advance(day(i),bars(i))
        assert not snapshot_bars(feed,norm.security_bars)[0].eligible
    norm=feed.advance(day(277),bars(277))
    assert snapshot_bars(feed,norm.security_bars)[0].eligible


def test_trim_uses_market_sessions_and_preserves_gaps():
    feed,norm=filled_feed(350)
    trim(feed)
    assert len(feed.series['0'].sessions)==300
    assert feed.series['0'].session_indices[0]==50
    assert len(feed._seen_sessions)==300


def episode():
    return HoldingEpisode('0','S0','SID:0',0,day(0),day(1),100.,100.,10.,10.,100.)


def rolling():
    state=RollingState.fresh(1000.,20).initialize_research()
    state.episodes[0]=episode()
    state.slots[0].occupied_by='0'
    state.initialized=True
    state.owned_closes={'0':dict(entry_date=day(1),observations=[[0,100.]],peak=100.)}
    return state


def test_rolling_peak_expires_on_market_session_300():
    state=rolling()
    for i in range(1,300):
        state.session_index=i
        state.age_one_session({'0':80.})
        assert state.episodes[0].episode_peak_split_adjusted_close==100.
    state.session_index=300
    state.age_one_session({'0':80.})
    assert state.episodes[0].episode_peak_split_adjusted_close==80.
    assert len(state.owned_closes['0']['observations'])==300


def test_corporate_reference_rebase_does_not_create_stop():
    state=rolling()
    state.episodes[0].episode_peak_split_adjusted_close=50.
    state.session_index=1
    state.age_one_session({'0':45.})
    assert state.episodes[0].episode_peak_split_adjusted_close==50.
    assert not state.episodes[0].stop_triggered(45.)
    assert state.owned_closes['0']['observations']==[[0,50.],[1,45.]]


def test_rolling_restart_preserves_future_stop():
    original=rolling()
    original.session_index=120
    original.age_one_session({'0':80.})
    restored=RollingState.from_dict(original.to_dict()).initialize_research(deepcopy(original.owned_closes))
    for i in range(121,305):
        for s in (original,restored):
            s.session_index=i
            s.age_one_session({'0':80.})
    assert original.to_dict()==restored.to_dict()
    assert original.owned_closes==restored.owned_closes


def test_explicit_rebase_keeps_owned_reference_and_price_comparable():
    feed,norm=filled_feed()
    state=rolling()
    old=feed.series['0'].signal_closes[-1]
    rebase(feed,state,'0',.5)
    assert feed.series['0'].signal_closes[-1]==old*.5
    assert state.episodes[0].episode_peak_split_adjusted_close==50.
    assert state.episodes[0].current_shares==10.
    with pytest.raises(ValueError):
        rebase(feed,state,'0',0.)


def test_baseline_driver_matches_canonical_runner_and_next_open_fills():
    sessions=[day(i) for i in range(150)]
    by_day={day(i):bars(i,30) for i in range(150)}
    reference=run_sessions(sessions=sessions,bars_by_session=by_day,meta=meta(30),
        starting_cash=50_000,cfg=config())
    arm=Arm('baseline')
    feed=Feed(meta(30)); feed.median5_state=arm.state.median5
    for d in sessions:
        norm=feed.advance(d,by_day[d])
        row=arm.step(d,norm,norm.security_bars)
    assert arm.state.to_dict()==reference.state.to_dict()
    assert arm.ledger.to_dict()==reference.ledger.to_dict()
    assert [r['equity'] for r in arm.rows]==[s.resolved_equity for s in reference.sessions]
    first_order=next(r for r in arm.rows if r['queued'])
    first_fill=next(r for r in arm.rows if r['fills'])
    assert first_fill['session']>first_order['session']


@pytest.mark.parametrize('variant',['baseline','snapshot','rolling300'])
def test_missing_owned_mark_blocks_admissions_and_split_preserves_value(variant):
    arm=Arm(variant)
    feed=Feed(meta(30)); feed.median5_state=arm.state.median5
    for i in range(135):
        norm=feed.advance(day(i),bars(i,30))
        arm.step(day(i),norm,norm.security_bars if variant=='baseline' else snapshot_bars(feed,norm.security_bars))
    held=next(iter(arm.state.held_security_ids()))
    quantity=sum(e.current_shares for e in arm.state.episodes.values() if e.security_id==held)
    todays=bars(135,30)
    todays=[replace(b,raw_close=b.raw_close/2,raw_open=b.raw_open/2,split_ratio=2.) if b.security_id==held else b for b in todays]
    norm=feed.advance(day(135),todays)
    arm.step(day(135),norm,norm.security_bars if variant=='baseline' else snapshot_bars(feed,norm.security_bars))
    assert sum(e.current_shares for e in arm.state.episodes.values() if e.security_id==held)==quantity*2
    missing=[b for b in bars(136,30) if b.security_id!=held]
    norm=feed.advance(day(136),missing)
    result=arm.step(day(136),norm,norm.security_bars if variant=='baseline' else snapshot_bars(feed,norm.security_bars))
    assert result['blocked'] and result['equity'] is None
    assert held in arm.state.held_security_ids()
    assert not arm.report()['performance_available']
