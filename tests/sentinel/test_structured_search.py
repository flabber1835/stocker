from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json

import numpy as np
import pytest

from research.exposure_oracle.accounting import Day
from research.exposure_oracle import inputs
from research.structured_search import audit, data as D, engine, models, policies, protocol
from research.structured_search import diagnostics


def days(n=350):
    rng=np.random.default_rng(21)
    result=[]
    for i in range(n):
        gap=Decimal(str(1+rng.normal(0,.005))); intra=Decimal(str(1+rng.normal(.0004,.01)))
        result.append(Day((date(2007,1,1)+timedelta(days=i)).isoformat(),
                          gap,intra,gap*intra,Decimal(1),Decimal('1.0001'),Decimal('1.0001')))
    return result


def observations(n=350):
    rng=np.random.default_rng(11); values=rng.normal(0,.01,(n,len(D.FEATURES)))
    values[:D.WARMUP]=np.nan
    return values


def feature_rows(n=100):
    return [dict(session=(date(2007,1,1)+timedelta(days=i)).isoformat(),
        core=dict(nav=str(100+i*.1)),spy=dict(nav=str(100+i*.05)),cash=5,held=19,
        decision=dict(target_core_exposure=1.,native_target_core_exposure=1.,champion_target_core_exposure=1.,
            fast_severe_active=False,slow_severe_active=False,
            owned_impairment=dict(healthy=i%3==0,impaired=i%3==1))) for i in range(n)]


def test_menu_has_576_unique_reproducible_candidates_and_balanced_models():
    menu=protocol.menu()
    assert len(menu)==576 and len({c.id for c in menu})==576
    assert [c.model_dump() for c in menu]==[c.model_dump() for c in protocol.menu()]
    assert all(sum(c.family==f for c in menu)==144 for f in protocol.FAMILIES)
    assert all(sum(c.params.get('model')==m for c in menu)==48 for m in ('ridge','tree','neural'))
    assert menu!=protocol.menu(seed=1730)


def test_chronological_folds_have_past_training_validation_and_future_evaluation():
    start=date(2006,7,31); end=date(2022,8,9)
    dates=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    folds=protocol.folds(dates)
    assert len(folds)==5 and folds[-1]['test_end']=='2022-08-09'
    assert all(f['fit_end']==f['val_left']<f['val_right']==f['left']<f['right'] for f in folds)
    assert all(a['right']==b['left'] for a,b in zip(folds,folds[1:]))


def test_features_are_prefix_causal_and_ignore_account_and_broker():
    rows=feature_rows(); before=D.features(rows)
    changed=deepcopy(rows)
    for r in changed:
        r['strategy']={'nav':'999999999'}; r['broker']={'cash':-1,'shares':1000000}
    changed[-1]['core']['nav']='100000'
    np.testing.assert_array_equal(D.features(changed)[:-1],before[:-1])
    np.testing.assert_array_equal(D.features(rows[:80]),before[:80])


@pytest.mark.parametrize('bad',[1,'false',None])
def test_untyped_boolean_evidence_refuses(bad):
    rows=feature_rows(); rows[70]['decision']['owned_impairment']['healthy']=bad
    with pytest.raises(ValueError): D.features(rows)


def test_labels_exclude_first_overnight_and_purge_every_future_outcome():
    ds=[Day(str(i),Decimal('1.1'),Decimal('1.01'),Decimal('1.111'),
            Decimal(1),Decimal(1),Decimal(1)) for i in range(120)]
    indices,y=D.labels(ds,5,100)
    assert indices[-1]==95
    assert y[-1,0]==pytest.approx((np.log(1.01)+4*np.log(1.111))*252/5)
    assert np.all(y[:,1]==0)
    changed=ds[:100]+[Day(str(i),*[Decimal('2')]*6) for i in range(20)]
    np.testing.assert_array_equal(D.labels(changed,5,100)[1],y)


@pytest.mark.parametrize('kind',['ridge','tree','neural'])
def test_fitted_models_use_only_purged_training_rows_and_reproduce_json(kind):
    p=dict(model=kind,features='all',horizon=5,alpha=.01,depth=3,leaf=25,width=8,rate=.003)
    x=observations(); ds=days(); cutoff=250
    fitted=models.fit(x,ds,p,cutoff)
    changed=x.copy(); changed[cutoff+1:]=1e6
    altered=ds[:cutoff]+[Day(str(i),*[Decimal(2)]*6) for i in range(len(ds)-cutoff)]
    assert models.fit(changed,altered,p,cutoff)==fitted
    np.testing.assert_allclose(fitted['xmean'],x[63:246].mean(axis=0),rtol=1e-12)
    assert fitted['last_example']==245 and fitted['last_outcome']==250
    restored=json.loads(json.dumps(fitted,allow_nan=False))
    np.testing.assert_array_equal(models.predict(fitted,x),models.predict(restored,x))
    audit.check_model(fitted,x,cutoff)
    changed_model=deepcopy(fitted); changed_model['last_outcome']=cutoff+1
    with pytest.raises(ValueError,match='boundary'): audit.check_model(changed_model,x,cutoff)


def test_health_subset_excludes_controller_severe_and_target_features():
    names=[D.FEATURES[i] for i in D.columns('health')]
    assert 'core_healthy' in names and 'healthy_streak' in names
    assert 'native_target' not in names and 'native_fast_severe' not in names and 'champion_target' not in names


def test_forecasts_and_all_rule_families_are_prefix_causal():
    x=observations(100); x[63:]=0
    x[:,D.FEATURES.index('native_target')]=1
    x[:,D.FEATURES.index('champion_target')]=1
    base=np.ones(100)
    p=dict(entry=1,release=3,expiry=5,recovery=3,timeout=10)
    np.testing.assert_array_equal(policies.state_path(x[:80],base[:80],p),policies.state_path(x,base,p)[:80])
    np.testing.assert_array_equal(policies.trend_path(x[:80],base[:80],policies.SIMPLE_TREND),
                                  policies.trend_path(x,base,policies.SIMPLE_TREND)[:80])
    pred=np.column_stack((np.linspace(-.1,.1,100),np.ones(100)*.1))
    p=dict(risk=.1,low=-.02,high=.05,down=2,up=3,hold=3)
    np.testing.assert_array_equal(policies.forecast_path(pred[:80],base[:80],p),
                                  policies.forecast_path(pred,base,p)[:80])


def state_inputs():
    x=np.zeros((90,len(D.FEATURES))); base=np.ones(90)
    x[:,D.FEATURES.index('native_target')]=1
    x[:,D.FEATURES.index('champion_target')]=1
    return x,base


def test_warning_expiration_clears_sticky_defense_without_future_health():
    x,base=state_inputs(); x[63,D.FEATURES.index('core_impaired')]=1
    p=dict(entry=1,release=8,expiry=3,recovery=3,timeout=0)
    out=policies.state_path(x,base,p)
    assert out[63]==out[64]==.55 and out[65]==1
    p['expiry']=0
    assert policies.state_path(x,base,p)[-1]==.55


def test_state_family_native_zero_overrides_positive_recovery_signals():
    x,base=state_inputs()
    x[65,D.FEATURES.index('native_target')]=0
    x[:,D.FEATURES.index('core_healthy')]=1
    p=dict(entry=1,release=1,expiry=5,recovery=1,timeout=5)
    assert policies.state_path(x,base,p)[65]==0


def test_recovery_partial_then_full_requires_present_health_and_positive_momentum():
    x,base=state_inputs(); x[:,D.FEATURES.index('champion_target')]=0
    x[:,D.FEATURES.index('core_healthy')]=1
    x[:,D.FEATURES.index('core_momentum_20')]=.01
    p=dict(entry=1,release=1,expiry=0,recovery=2,timeout=0)
    out=policies.state_path(x,base,p)
    assert out[63]==0 and out[64]==out[65]==.55 and out[66]==1


def test_confirmation_and_minimum_state_duration_avoid_single_close_reversal():
    base=np.ones(75); raw=base.copy(); raw[63:]=0; raw[66:]=1
    out=policies.smooth(raw,base,down=2,up=3,hold=5)
    assert out[63]==1 and out[64]==0 and out[68]==0 and out[69]==1


def test_next_open_alignment_and_first_funding_are_fixed():
    ds=days(3)
    ds[0]=Day(ds[0].session,*[Decimal(1)]*6,fixed=Decimal(0))
    actions=D.apply([1.,.55,0.,1.],ds)
    assert actions.tolist()==[0,1,0]
    assert np.array_equal(actions,D.apply([1.,.55,0.,0.],ds))


def test_return_owns_old_overnight_and_preserves_fold_continuity():
    ds=[Day('2020-01-02',Decimal('.8'),Decimal('1.2'),Decimal('.96'),
            Decimal(1),Decimal(1),Decimal(1)) for _ in range(3)]
    matrix=D.matrices(ds)
    actions=np.array([2,0,2]); whole=D.returns(matrix,actions,0)
    assert np.exp(whole[0])==pytest.approx(1.2*.999)
    assert np.exp(whole[1])==pytest.approx(.8*.999)
    joined=np.r_[D.returns(matrix[:1],actions[:1],0),D.returns(matrix[1:],actions[1:],actions[0])]
    np.testing.assert_array_equal(whole,joined)
    assert not np.allclose(whole[1:],D.returns(matrix[1:],actions[1:],0))


@pytest.mark.parametrize('value',[-.1,.25,1.01,float('nan')])
def test_action_grid_rejects_unpermitted_values(value):
    with pytest.raises(ValueError): D.action_indices([value])


def test_selection_rejects_high_cagr_above_drawdown_cap_and_keeps_fallback():
    def record(name,cagr,dd):
        return dict(id=name,family='trend',metrics=dict(cagr=cagr,maxdd=dd,turnover=1.,switches=1))
    baseline=record('baseline',.15,.2)
    assert protocol.choose([record('tempting',.30,.201)],baseline)['id']=='baseline'
    assert protocol.choose([record('safe',.16,.19)],baseline)['id']=='safe'


def test_outer_selection_file_mutation_is_detected(tmp_path):
    path=tmp_path/'selection.json'; path.write_text('{"choice":"a"}')
    sha=inputs.sha(path.read_bytes()); engine.assert_frozen(path,sha)
    path.write_text('{"choice":"b"}')
    with pytest.raises(ValueError,match='mutated'): engine.assert_frozen(path,sha)


def test_difference_episode_includes_rejoin_overnight():
    candidate=np.array([2,0,0,2,2]); baseline=np.full(5,2)
    delta=np.array([0.,.01,.02,-.005,0.])
    dates=[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(6)]
    ep=diagnostics.episodes(dates,candidate,baseline,2,delta,delta)
    assert len(ep)==1 and ep[0]['sessions']==3 and ep[0]['changed_opens']==2
    assert ep[0]['last_return']==dates[4] and ep[0]['net_log_gain']==pytest.approx(.025)


def test_bootstrap_is_deterministic_and_zero_gain_is_not_significant():
    rng=np.random.default_rng(9); panel=rng.normal(0,.01,(8,100))
    panel=np.vstack((panel,np.zeros(100)))
    a=diagnostics.bootstrap_max(panel,dict(zero=0.),50)
    assert a==diagnostics.bootstrap_max(panel,dict(zero=0.),50)
    assert a['corrected_p']['zero']==1.
