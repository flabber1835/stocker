from copy import deepcopy
from decimal import Decimal as D

import pytest

from research.exposure_oracle.accounting import Day
from research.exposure_oracle import target_analysis as T
from research.exposure_oracle.target import Settings, run


def record(*, impaired=False, healthy=False):
    return dict(decision=dict(target_core_exposure=1.,reason='NORMAL',
        fast_severe_active=False,slow_severe_active=False,
        evidence=dict(fast_signal=False,slow_signal=False,native_snapshot=dict(state=dict(
            ordinary=False,base_fast=False,fast_h=0,slow_h=0))),
        owned_impairment=dict(active=False,impaired=impaired,healthy=healthy,
            entry_streak=int(impaired),recovery_streak=0,reason='NORMAL'),
        ldrc=dict(desired_allocation=1.,reason='NORMAL')))


def test_rule_uses_previous_close_and_preserves_fixed_deployment():
    rows=[record(impaired=True),record(impaired=True),record(),record()]
    days=[Day(str(i),*[D(1)]*6,fixed=D(1) if i==0 else None) for i in range(3)]
    actual=[D(1)]*3
    expected=[D(1),D(0),D(1)]
    assert T.rule_path(rows,days,actual,'impaired',1.,D(0))==expected
    future=deepcopy(rows)
    future[3]=record(impaired=True)
    future[2]['future_return']=-1
    assert T.rule_path(future,days,actual,'impaired',1.,D(0))==expected
    future[2]=record(impaired=True)
    assert T.rule_path(future,days,actual,'impaired',1.,D(0))==[D(1),D(0),D(0)]


def test_episode_includes_rejoin_overnight_and_costs_exactly_once():
    daily=[dict(session=f'd{i}',decision_session=f'c{i}',changed=i in (1,3),
        actual_exposure=1.,oracle_exposure=0. if i in (1,3) else 1.,
        gross_log_gap=.02 if i else 0.,cost_log_gap=-.001 if i else 0.,
        net_log_gap=.019 if i else 0.,mechanism='full') for i in range(5)]
    result=T.episodes(daily)
    assert len(result)==2
    assert [r['rejoined'] for r in result]==['d2','d4']
    assert sum(r['net_log_gap'] for r in result)==pytest.approx(.076)
    assert all(r['changed_days']==1 for r in result)


def test_signal_precision_counts_unchanged_days_in_same_exposure():
    daily=[]
    for changed,flag,exposure in ((True,True,1.),(True,False,1.),(False,True,1.),
                                  (False,True,1.),(False,True,0.)):
        daily.append(dict(actual_exposure=exposure,changed=changed,
            signals={k:flag for k in T.FLAGS}))
    row=next(x for x in T.signal_table(daily) if x['actual_exposure']==1. and x['signal']=='impaired')
    assert row['true_positive']==1 and row['label_false_positive']==2
    assert row['precision']==pytest.approx(1/3) and row['recall']==.5
    assert row['eligible']==4


def test_untyped_recorded_signal_refuses():
    row=record()
    row['decision']['evidence']['fast_signal']=1
    with pytest.raises(ValueError,match='boolean'):
        T.signals(row)


def test_output_cannot_overlap_snapshot_before_any_write(tmp_path):
    snapshot=tmp_path/'snapshot'
    snapshot.mkdir()
    with pytest.raises(ValueError,match='separate'):
        run(snapshot,snapshot/'result',Settings())
    assert list(snapshot.iterdir())==[]


def test_target_settings_refuse_reversed_band():
    with pytest.raises(ValueError,match='increasing'):
        Settings(lower_cagr=.30,upper_cagr=.25)


def test_period_blocks_rebase_without_crossing_or_skipping_a_return():
    rows=[dict(session=s) for s in ('2012-12-28','2012-12-31','2013-01-02','2015-12-31','2016-01-04')]
    result=T.period_metrics(rows,dict(nav=['1','2','3','4','5']))
    assert [(r['start'],r['end']) for r in result]==[
        ('2012-12-28','2012-12-31'),('2012-12-31','2015-12-31'),('2015-12-31','2016-01-04')]
    assert [D(r['multiple']) for r in result]==[D(2),D(2),D('1.25')]


def test_independent_exhaustive_audit_never_silently_prunes_for_resources():
    import numpy as np
    from research.exposure_oracle.target_audit import enumerate_bound
    factors=np.array([[[1.,1.04,1.08]]*3])
    with pytest.raises(ValueError,match='resource limit'):
        enumerate_bound(factors,[0],0,1,1.035,1.1,.1,limit=1)
    result=enumerate_bound(factors,[0],0,1,1.035,1.1,.1)
    assert result['feasible_complete_paths']==2
    assert result['minimum_objective']==[1,55,1]


def test_independent_audit_accepts_actual_policy_already_in_target_band():
    import numpy as np
    from research.exposure_oracle.target_audit import enumerate_bound
    result=enumerate_bound(np.ones((2,3,3)),[0,0],0,0,1.,1.1,.1)
    assert result['minimum_objective']==[0,0,0]
