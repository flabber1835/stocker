from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
import gzip
import json

import numpy as np
import pytest

from sentinel.feed.rolling_contract import digest
from research.exposure_oracle import accounting as A, inputs
from research.signal_study import audit, extract, features, opportunities, probes
from research.signal_study.guard import CoreGuard
from research.signal_study import review
from research.structured_search import data


def records(n=100):
    rows=[]; recovered=[]
    for i in range(n):
        day=(date(2010,1,1)+timedelta(days=i)).isoformat()
        nav=100+i*.1+np.sin(i)
        rows.append(dict(session=day,core=dict(nav=str(nav)),spy=dict(nav=str(100+i*.05)),cash=5,held=19,
            economics=dict(parent_core_close_equity=str(nav),parent_core_open_equity=str(nav*.999)),
            decision=dict(target_core_exposure=1.,native_target_core_exposure=1.,champion_target_core_exposure=1.,
                fast_severe_active=False,slow_severe_active=False,
                evidence=dict(native_snapshot=dict(state={k:0 for k in features.MEMORY})),
                owned_impairment=dict(healthy=i%3==0,impaired=i%3==1))))
        recovered.append(dict(session=day,values=dict(leadership_nav=100+i*.2,
            recorded_damaged_breadth=(i%20)/20,recorded_stops_today=0),origins={}))
    return rows,recovered


def packet():
    rows,_=records(80); dates=[r['session'] for r in rows]; last=dates[-1]
    state=dict(last_processed_session=last,shadow_nav_history=[r['core']['nav'] for r in rows[-41:]],
        median5=dict(witness_nav=list(range(100,141))),breadth_history=[None,.1,.2,.3,.4,.5],
        controller_session_history=dates[-20:],trailing_stop_sessions=[dates[-3],dates[-3]],
        last_evidence=dict(observation=dict(session=last,shadow_nav=123,damaged_breadth=.5,green_breadth=None),
                           recent_leadership={},breadth=dict(holdings=[])))
    p=dict(cursor=last,state=state,state_sha256=digest(state),outputs={'daily.jsonl':dict(bytes=1,sha256='prefix')})
    rows[-1]['state_sha256']=p['state_sha256']
    return p,rows


def encoded(p):
    blob=gzip.compress(json.dumps(p).encode())
    return blob,'checkpoint-'+inputs.sha(blob)+'.json.gz'


def test_checkpoint_authentication_requires_file_state_prefix_and_cursor():
    p,rows=packet(); by_date={r['session']:r for r in rows}; pref={p['cursor']:p['outputs']['daily.jsonl']}
    assert extract.validate(*encoded(p),by_date,pref)[1]=='eligible'
    blob,name=encoded(p)
    with pytest.raises(ValueError,match='filename'): extract.validate(blob,name+'x',by_date,pref)
    changed=deepcopy(p); changed['state']['breadth_history'][-1]=.9
    with pytest.raises(ValueError,match='state hash'): extract.validate(*encoded(changed),by_date,pref)
    changed=deepcopy(p); changed['state_sha256']='other'
    assert extract.validate(*encoded(changed),by_date,pref)[1]=='different_canonical_state'
    changed=deepcopy(p); changed['outputs']['daily.jsonl']['bytes']=2
    assert extract.validate(*encoded(changed),by_date,pref)[1]=='different_daily_prefix'
    changed=deepcopy(p); changed['state']['last_evidence']['observation']['session']=rows[-2]['session']
    changed['state_sha256']=digest(changed['state']); by_date[p['cursor']]['state_sha256']=changed['state_sha256']
    with pytest.raises(ValueError,match='date mismatch'): extract.validate(*encoded(changed),by_date,pref)


def test_prefix_hashes_cover_exact_line_bytes():
    blob=b'{"session":"a"}\n{ "session": "b" }\n'
    p=extract.prefixes(blob)
    assert p['b']==dict(bytes=len(blob),sha256=inputs.sha(blob))
    assert p['a']['bytes']==len(blob.splitlines(keepends=True)[0])


def test_recovery_maps_dates_without_backfilling_terminal_values():
    p,rows=packet(); table={r['session']:dict(values={},origins={}) for r in rows}
    extract.recover(p,'checkpoint',rows,table)
    assert table[rows[-41]['session']]['values']['leadership_nav']==100
    assert 'leadership_nav' not in table[rows[-42]['session']]['values']
    assert 'recorded_damaged_breadth' not in table[rows[-6]['session']]['values']
    assert table[rows[-5]['session']]['values']['recorded_damaged_breadth']==.1
    assert 'recorded_green_breadth' not in table[rows[-1]['session']]['values']
    assert table[rows[-3]['session']]['values']['recorded_stops_today']==2
    assert table[rows[-20]['session']]['values']['recorded_stops_today']==0
    assert table[rows[-41]['session']]['origins']['leadership_nav']['preserved_through']==rows[-1]['session']


@pytest.mark.parametrize('corrupt',['core','stop_window','stop_date','overlap'])
def test_recovery_rejects_misalignment_and_conflicts(corrupt):
    p,rows=packet(); table={r['session']:dict(values={},origins={}) for r in rows}
    if corrupt=='core': p['state']['shadow_nav_history'][0]='999'
    if corrupt=='stop_window': p['state']['controller_session_history'].pop(0)
    if corrupt=='stop_date': p['state']['trailing_stop_sessions'].append(rows[0]['session'])
    if corrupt=='overlap':
        table[rows[-1]['session']]['values']['recorded_damaged_breadth']=.9
    with pytest.raises(ValueError): extract.recover(p,'checkpoint',rows,table)


def test_feature_prefix_causality_and_exclusion_of_account_state():
    rows,recovered=records(); x,names,_=features.build(rows,recovered)
    np.testing.assert_array_equal(features.build(rows[:80],recovered[:80])[0],x[:80])
    changed=deepcopy(rows); obs=deepcopy(recovered)
    for row in changed:
        row['broker']={'cash':-123}; row['strategy']={'nav':999999}
        row['economics']['held_allocation']='0'
    for row,r in zip(changed[80:],obs[80:]):
        row['core']['nav']='99999'; row['economics']['parent_core_close_equity']='99999'
        r['values']['leadership_nav']=999999; r['values']['recorded_damaged_breadth']=.99
    np.testing.assert_array_equal(features.build(changed,obs)[0][:80],x[:80])
    assert 'leadership_nav' not in names and len(names)==len(set(names))


def test_missing_damage_stays_missing_and_tiers_have_matched_dates():
    rows,rec=records(); del rec[75]['values']['recorded_damaged_breadth']
    x,names,tiers=features.build(rows,rec)
    assert np.isnan(x[75,names.index('damaged_breadth')])
    assert np.isnan(x[76,names.index('damaged_breadth_change1')])
    assert np.isfinite(x[75,tiers['leadership']]).all()
    assert not np.isfinite(x[75,tiers['breadth']]).all()


def synthetic_days(n=110):
    return [A.Day(str(i),D('.98'),D('1.01'),D('.9898'),D(1),D('1.0001'),D('1.0001')) for i in range(n)]


def test_local_labels_own_intraday_then_rejoin_overnight_and_both_costs():
    ds=synthetic_days(); matrix=data.matrices(ds); actual=np.full(len(ds),2)
    r=opportunities.local_labels(matrix,actual,2,(1,))[0]
    expected=D('1.0001')/(D('1.01')*D('.98'))*D('.999')**2-1
    assert r['t']==63 and r['end']==65 and r['gain']==pytest.approx(float(expected))
    assert r['gains'][2]==pytest.approx(0)
    assert len(r['gains'])==3
    changed=ds.copy(); changed[63]=A.Day('63',D('.5'),D('1.01'),D('.505'),D(1),D('1.0001'),D('1.0001'))
    assert opportunities.local_labels(data.matrices(changed),actual,2,(1,))[0]['gain']==pytest.approx(r['gain'])
    changed=ds.copy(); changed[64]=A.Day('64',D('.5'),D('1.01'),D('.505'),D(1),D('1.0001'),D('1.0001'))
    assert opportunities.local_labels(data.matrices(changed),actual,2,(1,))[0]['gain']>r['gain']+.5


def test_label_end_purging_excludes_incomplete_training_and_test_outcomes():
    ds=synthetic_days(); labels=opportunities.local_labels(data.matrices(ds),np.full(len(ds),2),2,(5,))
    train,test=probes.eligible(labels,np.ones(len(ds)+1,dtype=bool),90,109)
    assert max(r['t'] for r in train)==84 and max(r['end'] for r in train)==90
    assert min(r['t'] for r in test)==90 and max(r['end'] for r in test)==109
    changed=ds[:90]+[A.Day(str(i),*[D(2)]*6) for i in range(20)]
    other=opportunities.local_labels(data.matrices(changed),np.full(len(ds),2),2,(5,))
    assert probes.eligible(other,np.ones(111,dtype=bool),90,109)[0]==train


@pytest.mark.parametrize('kind',['logistic','tree'])
def test_frozen_models_reproduce_and_scaler_only_uses_supplied_training(kind):
    rng=np.random.default_rng(17); x=rng.normal(size=(320,3)); y=x[:,0]+rng.normal(size=320)>.3
    model,scaler,saved=probes.fit(x[:250],y[:250],kind,['a','b','c'])
    np.testing.assert_allclose(saved['mean'],x[:250].mean(axis=0))
    np.testing.assert_allclose(audit.scores(saved,x[250:]),model.predict_proba(scaler.transform(x[250:]))[:,1],atol=1e-12)
    assert saved['threshold']==pytest.approx(float(np.quantile(model.predict_proba(scaler.transform(x[:250]))[:,1],.9)))
    assert probes.fit(x[:199],y[:199],kind,['a','b','c']) is None
    assert probes.fit(x,np.zeros(320,dtype=bool),kind,['a','b','c']) is None


def test_attribution_residual_reconciles_unchanged_partial_convention():
    day=synthetic_days()[0]
    for old in (D(0),D('.55'),D(1)):
        for new in (D(0),D('.55'),D(1)):
            assert sum(opportunities.decompose(day,old,new))==pytest.approx(np.log(float(day.factors(old,new)[0])))
    assert opportunities.decompose(day,D('.55'),D('.55'))[2]!=0


def test_core_guard_blocks_a_transition_before_its_body(monkeypatch):
    import sentinel.core.kernel as kernel
    ran=[]
    def forbidden(): ran.append(True)
    monkeypatch.setattr(kernel,'advance_session',forbidden)
    with pytest.raises(RuntimeError,match='cannot advance'):
        with CoreGuard() as guard: forbidden()
    assert ran==[] and guard.receipt()['canonical_core_transition_calls']==1


def test_metrics_use_fixed_action_gain_and_count_false_alarms():
    rows=[dict(positive=True,score=.8,flag=True,gain=.02,oracle_change=True),
          dict(positive=False,score=.9,flag=True,gain=-.04,oracle_change=False),
          dict(positive=True,score=.2,flag=False,gain=.03,oracle_change=False)]
    m=probes.metrics(rows)
    assert m['precision']==.5 and m['false_alarms']==1 and m['mean_flagged_gain']==pytest.approx(-.01)


def test_review_scaler_falsifier_rejects_changed_scale():
    rng=np.random.default_rng(8); x=rng.normal(size=(250,3)); x[:,2]=1
    _,_,m=probes.fit(x,x[:,0]>0,'logistic',['a','b','c'])
    m['train_indices']=list(range(250))
    assert review.check_scalers([m],x,['a','b','c'])==1
    m['scale'][0]*=1.1
    with pytest.raises(ValueError,match='scale'): review.check_scalers([m],x,['a','b','c'])


def test_overlapping_events_are_counted_as_clusters():
    rows=[dict(t=t,end_index=end,session=str(t)) for t,end in ((1,7),(3,9),(8,14),(14,20))]
    groups=review.clusters(rows)
    assert len(groups)==2 and groups[0]['events']==3 and groups[0]['end_index']==14
