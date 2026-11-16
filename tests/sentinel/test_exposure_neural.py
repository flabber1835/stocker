from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal as D
import json
import math
from pathlib import Path

import numpy as np
import pytest

from research.exposure_oracle import accounting as A, inputs, neural, neural_data as data, neural_model as model


def records(n=140, actual=D(1)):
    rows=[]
    core,spy,strategy=D(100),D(100),D(100)
    for i in range(n):
        session=(date(2010,1,1)+timedelta(days=i)).isoformat()
        prior_core,prior_strategy=core,strategy
        opening=core*(1+D(str(math.cos(i)*.002))) if i else core
        core=opening*(1+D(str(math.sin(i/4)*.015))) if i else core
        spy=spy*(1+D(str(math.sin(i/7)*.008))) if i else spy
        factor=actual*core/prior_core+(1-actual)
        strategy=prior_strategy*factor
        rows.append(dict(session=session,cash=3.,held=19,core=dict(nav=str(core)),spy=dict(nav=str(spy)),
            strategy=dict(nav=str(strategy)),decision=dict(fast_severe_active=i%11==0,slow_severe_active=False,
                owned_impairment=dict(healthy=i%3==0,impaired=i%3==1)),
            valuation=dict(blocked=False,open_unresolved_security_ids=[],resolved_equity=float(core)),
            economics=dict(held_allocation=str(actual),pending_allocation=str(actual),initial_deployment=False,
                parent_core_open_equity=str(opening),parent_core_close_equity=str(core),
                bil_open_adjusted='1',bil_close_adjusted='1',bil_previous_close_adjusted_current_publication='1',
                bil_previous_session=rows[-1]['session'] if rows else session,last_session=session,
                gross_factor=str(factor),net_factor=str(factor),transaction_cost_factor='1',turnover='0')))
    return rows


def test_features_only_use_completed_prefix_and_ignore_future_and_account_economics():
    rows=records()
    full=data.feature_matrix(rows)
    prefix=data.feature_matrix(rows[:100])
    np.testing.assert_array_equal(full[:100],prefix)
    changed=deepcopy(rows)
    for row in changed[100:]:
        row['core']['nav']=str(D(row['core']['nav'])*D(5))
        row['spy']['nav']=str(D(row['spy']['nav'])*D('.3'))
        row['decision']['owned_impairment']['healthy']=False
    for row in changed:
        row['strategy']['nav']='999999999'
        row['economics']['held_allocation']='0.55'
    np.testing.assert_array_equal(full[:100],data.feature_matrix(changed)[:100])
    assert full.shape==(140,38)


@pytest.mark.parametrize('corruption',['nan','negative','flag','duplicate'])
def test_features_refuse_nonfinite_prices_untyped_flags_and_duplicate_sessions(corruption):
    rows=records()
    if corruption=='nan': rows[80]['core']['nav']='NaN'
    if corruption=='negative': rows[80]['spy']['nav']='-1'
    if corruption=='flag': rows[80]['decision']['fast_severe_active']=1
    if corruption=='duplicate': rows[80]['session']=rows[79]['session']
    with pytest.raises(ValueError): data.feature_matrix(rows)


def test_temporal_partitions_have_disjoint_next_session_outcomes():
    rows=records(180)
    scopes=data.partitions(rows,rows[100]['session'],rows[140]['session'])
    outcomes=[set(range(a+1,b+1)) for a,b in scopes.values()]
    assert not (outcomes[0]&outcomes[1] or outcomes[1]&outcomes[2] or outcomes[0]&outcomes[2])
    assert set.union(*outcomes)==set(range(1,180))
    with pytest.raises(ValueError,match='short or overlap'):
        data.partitions(rows,rows[140]['session'],rows[100]['session'])


def test_teacher_is_bounded_before_future_outcomes():
    rows=records()
    expected=data.teacher(rows,0,99)
    changed=deepcopy(rows)
    for row in changed[100:]:
        row['core']['nav']='9999'
        row['economics']['parent_core_close_equity']='9999'
    assert data.teacher(changed,0,99)==expected
    assert expected['path']['maxdd'] <= expected['cap']+1e-10


def test_supervised_features_precede_their_action_outcomes_by_one_session():
    rows=records()
    features=data.feature_matrix(rows)
    ideal=data.teacher(rows,0,99)
    indices,x,y=data.supervised(rows,features,ideal)
    assert indices.tolist()==list(range(63,99))
    np.testing.assert_array_equal(x,features[63:99])
    np.testing.assert_array_equal(y,ideal['labels'][63:99])
    assert rows[int(indices[-1])+1]['session']==ideal['end']
    assert not np.array_equal(x[-1],features[99])


def test_supervised_refuses_labels_claiming_a_different_horizon():
    rows=records()
    ideal=data.teacher(rows,0,99)
    ideal['end']=rows[120]['session']
    with pytest.raises(ValueError,match='label horizon'):
        data.supervised(rows,data.feature_matrix(rows),ideal)


def training_sample():
    x=np.random.default_rng(123).normal(size=(192,4))
    y=np.where(x[:,0]+x[:,1]>0,2,0)
    return x[:128],y[:128],x[128:],y[128:]


def test_selected_scaler_uses_training_only_and_training_is_deterministic():
    x,y,v,w=training_sample()
    v=v+20
    settings=model.Settings(epochs=8,patience=3)
    first,history=model.select(x,y,v,w,['a','b','c','d'],settings,{'role':'test'})
    second,other=model.select(x,y,v,w,['a','b','c','d'],settings,{'role':'test'})
    np.testing.assert_allclose(first.mean,x.mean(axis=0),rtol=0,atol=0)
    np.testing.assert_allclose(first.scale,x.std(axis=0),rtol=0,atol=0)
    assert first.model_dump()==second.model_dump() and history==other
    assert data.counts(y)['0.55']==0
    assert first.actions==[0,.55,1]  # Output contract does not create training examples.


def test_safe_model_roundtrip_and_full_refit_leave_evaluation_unchanged(tmp_path):
    x,y,v,w=training_sample()
    settings=model.Settings(epochs=6,patience=3)
    fitted,_=model.select(x,y,v,w,['a','b','c','d'],settings,{'role':'evaluation'})
    loaded,digest=neural.export(tmp_path/'model.json',fitted,v)
    before=loaded.model_dump_json()
    forward=model.refit(np.vstack((x,v)),np.r_[y,w],['a','b','c','d'],settings,
                        fitted.metadata['selected_epoch'],{'role':'refit'})
    assert loaded.model_dump_json()==before
    assert inputs.sha((tmp_path/'model.json').read_bytes())==digest
    np.testing.assert_array_equal(loaded.probabilities(v),fitted.probabilities(v))
    assert forward.metadata['role']=='refit'
    assert forward.mean!=loaded.mean


@pytest.mark.parametrize('corruption',['scale','weight','action','dimension'])
def test_model_refuses_invalid_serialized_economics(corruption):
    values=dict(features=['x'],mean=[0.],scale=[1.],weights=[[[1.]],[[1.]],[[0.,0.,0.]]],
                biases=[[0.],[0.],[0.,0.,0.]],metadata={})
    if corruption=='scale': values['scale']=[0.]
    if corruption=='weight': values['weights'][0][0][0]=float('nan')
    if corruption=='action': values['actions']=[0,.65,1]
    if corruption=='dimension': values['biases'][0]=[0.,0.]
    with pytest.raises(ValueError): model.FrozenModel(**values)


def test_probabilities_tie_to_zero_and_require_finite_features():
    fitted=model.FrozenModel(features=['x'],mean=[0.],scale=[1.],
        weights=[[[0.]],[[0.]],[[0.,0.,0.]]],biases=[[0.],[0.],[0.,0.,0.]],metadata={})
    assert fitted.predict(np.array([[1.]])).tolist()==[0]
    with pytest.raises(ValueError,match='finite'):
        fitted.probabilities(np.array([[np.inf]]))


def test_test_returns_retain_the_common_overnight_holding():
    rows=records()
    ideal=data.teacher(rows,100,120)
    paths=neural.score_paths(rows,ideal,np.zeros(20,dtype=int),0)
    days,initial,_=A.tape(rows[100:121],canonical=False)
    assert initial==1
    expected=days[0].factors(initial,D(0))[0]
    assert D(paths['neural']['nav'][1])==expected
    assert paths['neural']['exposure']==[0.]*20
    assert paths['neural']['turnover']==1


def test_original_teacher_identity_must_match_snapshot(tmp_path):
    snapshot,oracle=tmp_path/'snapshot',tmp_path/'oracle'
    snapshot.mkdir(); oracle.mkdir()
    pointer=dict(file='original',session='2019-04-16')
    inputs.write_json(snapshot/'latest-checkpoint.json',pointer)
    inputs.write_json(oracle/'summary.json',dict(schema='fractional-exposure-oracle/1',
        source_binding='wrong',checkpoint=pointer,actions=['0','0.55','1'],
        harness={name:inputs.sha((Path(neural.__file__).parent/name).read_bytes())
                 for name in ('accounting.py','search.py','inputs.py')}))
    inputs.write_json(oracle/'paths.json',{})
    with pytest.raises(ValueError,match='does not match'):
        neural.authenticate_oracle(snapshot,oracle,dict(source='original'))
