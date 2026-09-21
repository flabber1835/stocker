"""Contract tests for the owned-book protection cause, independent of returns."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import json

import pytest

from sentinel.controller import owned_impairment as owned
from sentinel.controller.machine import Controller, Observation
from sentinel.core.session import SessionState
from sentinel.strategy import controller_for_identity, owned_impairment_strategy, production_strategy


def ob(day, **changes):
    values = dict(session=str(date(2020,1,1)+timedelta(days=day)), shadow_nav=80000.,
        shadow_drawdown=-.20, damaged_breadth=1., green_breadth=0., shadow_r20=-.10,
        shadow_r5=0., shadow_r10=0., damaged_breadth_delta5=0., spy_r20=.10, spy_vol_ratio=0.)
    return Observation(**(values | changes))


def advance(state, day, parent=1., **changes):
    return owned.step(state=state,observation=ob(day,**changes),base_target=parent)


def impaired_state():
    state=owned.fresh()
    for day in range(5):
        state,_=advance(state,day)
    return state


def healthy():
    return dict(shadow_r20=.01,damaged_breadth=.63,green_breadth=.20)


def test_saturated_damage_enters_on_fifth_close_without_new_shock():
    state=owned.fresh()
    for day in range(5):
        state,result=advance(state,day)
        assert result['target']==(1. if day<4 else 0.)
        state=json.loads(json.dumps(state))
    assert state['active'] and result['reason']=='OWNED_IMPAIRMENT_ENTER'


def test_entry_is_consecutive_and_rearms_after_recovery():
    state=owned.fresh()
    for day in range(4): state,_=advance(state,day)
    state,_=advance(state,4,damaged_breadth=.87)
    for day in range(5,9):
        state,r=advance(state,day);assert r['target']==1.
    state,r=advance(state,9);assert r['target']==0.
    for day in range(10,18): state,r=advance(state,day,**healthy())
    assert r['reason']=='OWNED_RECOVERED'
    for day in range(18,23): state,r=advance(state,day)
    assert r['reason']=='OWNED_IMPAIRMENT_ENTER'


def test_recovery_needs_eight_owned_healthy_closes_and_preserves_parent_ceiling():
    state=impaired_state()
    for day in range(5,13):
        state,r=advance(state,day,parent=.55,**healthy())
        assert r['target']==(0. if day<12 else .55)
    assert not state['active']


@pytest.mark.parametrize('missing', ['shadow_r20','damaged_breadth','green_breadth'])
def test_missing_or_cash_only_book_does_not_clear_protection(missing):
    state=impaired_state()
    for day in range(5,12): state,_=advance(state,day,**healthy())
    fields=healthy() | {missing:None}
    state,r=advance(state,12,**fields)
    assert r['target']==0. and state['recovery_streak']==0
    for day in range(13,23):
        state,r=advance(state,day,shadow_r20=0.,damaged_breadth=0.,green_breadth=0.)
        assert r['target']==0.


@pytest.mark.parametrize('changes', [dict(shadow_drawdown=-.099),dict(damaged_breadth=.879),dict(green_breadth=.201)])
def test_below_severity_never_enters(changes):
    state=owned.fresh()
    for day in range(20): state,r=advance(state,day,**changes)
    assert not state['active'] and r['target']==1.


def test_positive_core_return_is_required_not_just_healthier_membership():
    state=impaired_state()
    for day in range(5,25): state,r=advance(state,day,**(healthy() | {'shadow_r20':0.}))
    assert r['target']==0.


def test_duplicate_or_older_session_is_rejected_without_mutation():
    state=impaired_state();before=deepcopy(state)
    for day in (3,4):
        with pytest.raises(ValueError,match='strictly once'): advance(state,day)
    assert state==before


@pytest.mark.parametrize('field,value', [('active',1),('entry_streak',True),('entry_streak',5),
    ('recovery_streak',8),('version',2),('version',True),('last_session','invalid')])
def test_snapshot_corruption_is_rejected(field,value):
    raw=owned.fresh();raw[field]=value
    with pytest.raises(ValueError): owned.validate({'strategy':owned.STRATEGY_ID},raw)


def test_new_identity_requires_complete_memory_and_old_identity_rejects_it():
    cfg,identity=owned_impairment_strategy()
    state=SessionState.fresh(starting_cash=100000.,controller=Controller(cfg),strategy_identity=identity)
    assert controller_for_identity(identity)==cfg
    assert SessionState.from_dict(json.loads(json.dumps(state.to_dict()))).state_hash==state.state_hash
    raw=state.to_dict();del raw['owned_impairment']
    with pytest.raises(ValueError,match='state required'): SessionState.from_dict(raw)
    old_cfg,old_identity=production_strategy()
    assert old_cfg.digest!=cfg.digest
    old=SessionState.fresh(starting_cash=100000.,controller=Controller(old_cfg),strategy_identity=old_identity)
    assert 'owned_impairment' not in old.to_dict()
    raw=old.to_dict();raw['owned_impairment']=owned.fresh()
    with pytest.raises(ValueError,match='another strategy'): SessionState.from_dict(raw)


def test_owned_rule_is_in_runtime_source_identity_and_cfg_drift_refuses():
    from sentinel.core.decision import data_semantics_source_identity
    assert 'sentinel.controller.owned_impairment' in {x['module'] for x in data_semantics_source_identity()['files']}
    cfg,_=owned_impairment_strategy()
    wrong=Controller(replace(cfg,digest='wrong'))
    with pytest.raises(ValueError,match='configuration differs'):
        wrong.step(observation=ob(0),state=wrong.initial_state())


def test_snapshot_cannot_detach_protection_from_canonical_cursor():
    cfg,identity=owned_impairment_strategy()
    state=SessionState.fresh(starting_cash=100000.,controller=Controller(cfg),strategy_identity=identity)
    raw=state.to_dict();raw['owned_impairment']['last_session']='2020-01-01'
    with pytest.raises(ValueError,match='cursor differs'): SessionState.from_dict(raw)
    state.owned_impairment=raw['owned_impairment']
    with pytest.raises(ValueError,match='cursor differs'): state.to_dict()
