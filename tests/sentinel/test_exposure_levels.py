from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from research.exposure_oracle import accounting as A, levels, levels_policy as P, logic


def row(i, *, impaired=False, healthy=False, native=1., base=1., owned=False):
    if native==0: base=0.
    target=min(base,.55 if owned else 1.)
    return dict(session=(date(2021,1,4)+timedelta(days=i)).isoformat(),decision=dict(
        target_core_exposure=target,native_target_core_exposure=native,champion_target_core_exposure=base,
        ldrc=dict(desired_allocation=base,reason='FULL_RISK_HELD' if native==1 and base==0 else 'NORMAL'),
        owned_impairment=dict(active=owned,impaired=impaired,healthy=healthy,
            entry_streak=1 if impaired and not owned else 0,recovery_streak=0,
            target=target,parent_target=base,reason='TEST')))


def sequence():
    return [row(0),row(1,impaired=True),row(2,impaired=True),row(3,owned=True),
        row(4,native=0),row(5,base=0,healthy=True),row(6,base=0,healthy=True),
        row(7,base=0,healthy=True),row(8,base=0),row(9,base=0,impaired=True),
        row(10),row(11,healthy=True),row(12,healthy=True),row(13,healthy=True)]


@pytest.mark.parametrize('count',[3,5])
def test_prefix_invariance_resume_and_no_future_or_account_feedback(count):
    rows=sequence(); policy=P.Policy()
    expected=P.decisions(rows,policy,count)
    assert P.decisions(rows[:8],policy,count)==expected[:8]
    continued=P.decisions(rows[8:],policy,count,P.State.model_validate(expected[7]['state']))
    assert continued==expected[8:]
    changed=deepcopy(rows)
    for r in changed:
        r['strategy']={'nav':'0.01'}; r['broker']={'shares':999999}
    changed[-1]=row(13,native=0)
    assert P.decisions(changed,policy,count)[:-1]==expected[:-1]


def test_pairs_share_states_and_only_stage_outputs_differ():
    three=P.decisions(sequence(),P.Policy(),3)
    five=P.decisions(sequence(),P.Policy(),5)
    assert [x['state'] for x in three]==[x['state'] for x in five]
    assert [x['reason'] for x in three]==[x['reason'] for x in five]
    assert D(three[1]['target'])==D('.55') and D(five[1]['target'])==D('.75')
    assert D(three[7]['target'])==D('.55') and D(five[7]['target'])==D('.25')
    assert set(D(x['target']) for x in five)==set(P.GRIDS[5])


def test_warning_requires_entry_confirmation_and_stronger_healthy_release():
    trace=P.decisions(sequence(),P.Policy(entry=2,release=3),5)
    assert D(trace[1]['target'])==1 and D(trace[2]['target'])==D('.75')
    assert trace[6]['state']['warning'] and not trace[7]['state']['warning']
    assert D(trace[13]['target'])==1


def test_native_severe_immediately_overrides_existing_recovery_probe():
    rows=[row(i,base=0,healthy=True) for i in range(3)]+[row(3,native=0,healthy=True)]
    trace=P.decisions(rows,P.Policy(),5)
    assert D(trace[2]['target'])==D('.25')
    assert D(trace[3]['target'])==0 and not trace[3]['state']['bridge']


def test_probe_holds_on_neutral_but_resets_on_impairment_and_native_severe():
    trace=P.decisions(sequence(),P.Policy(),5)
    assert D(trace[6]['target'])==0
    assert D(trace[7]['target'])==D(trace[8]['target'])==D('.25')
    assert D(trace[9]['target'])==0 and not trace[9]['state']['bridge']


def test_owned_ceiling_and_divergence_cannot_be_raised_by_warning():
    rows=[row(0,impaired=True),row(1,owned=True),row(2,base=.55)]
    trace=P.decisions(rows,P.Policy(),5)
    assert [D(x['target']) for x in trace]==[D('.75'),D('.55'),D('.55')]


@pytest.mark.parametrize('corruption',['integer','contradictory','composition','reason','duplicate'])
def test_source_or_state_contract_changes_refuse(corruption):
    rows=sequence()
    if corruption=='integer': rows[1]['decision']['owned_impairment']['impaired']=1
    elif corruption=='contradictory': rows[1]['decision']['owned_impairment']['healthy']=True
    elif corruption=='composition': rows[1]['decision']['target_core_exposure']=.55
    elif corruption=='reason': rows[5]['decision']['ldrc']['reason']='UNKNOWN'
    else: rows[1]['session']=rows[0]['session']
    with pytest.raises(ValueError): P.decisions(rows,P.Policy(),5)


def test_new_levels_still_execute_at_next_open_with_fixed_first_funding():
    rows=sequence()[:3]; trace=P.decisions(rows,P.Policy(),5)
    days=[A.Day(rows[1]['session'],*[D(1)]*6,fixed=D('.55')),
          A.Day(rows[2]['session'],*[D(1)]*6)]
    assert logic.apply_at_next_open(days,trace)==[D('.55'),D('.75')]
    trace[2]['target']='0'
    assert logic.apply_at_next_open(days,trace)==[D('.55'),D('.75')]


def test_training_prefix_excludes_later_outcomes():
    rows=[dict(session=s,return_value=x) for s,x in
          (('2015-12-30',0),('2015-12-31',1),('2016-01-04',1000000))]
    before=levels.training_prefix(rows,'2015-12-31')
    changed=deepcopy(rows); changed[-1]['return_value']=-1000000
    assert levels.training_prefix(changed,'2015-12-31')==before==rows[:2]


def test_selection_respects_drawdown_and_keeps_baseline_fallback():
    def record(name,n,cagr,dd,turn=1.,switches=1):
        return dict(id=name,levels=n,metrics=dict(cagr=cagr,maxdd=dd,allocation_turnover=turn,switches=switches))
    baseline=record('baseline',0,.15,.2)
    records=[baseline,record('too-risky',5,.4,.21),record('three',3,.2,.19),
             record('five-a',5,.17,.19,2),record('five-b',5,.17,.19,1)]
    assert P.choose(records,5)['id']=='five-b'
    assert P.choose(records,3)['id']=='three'
    assert P.choose([baseline,record('loser',5,.1,.1)],5)==baseline


def test_predeclared_menu_has_four_early_two_recovery_and_eight_combined():
    choices=P.menu()
    assert len(choices)==len({p.key for p in choices})==14
    assert sum(p.early and not p.recovery for p in choices)==4
    assert sum(p.recovery and not p.early for p in choices)==2
    assert sum(p.early and p.recovery for p in choices)==8


def test_output_overlap_refuses_before_writing(tmp_path):
    snapshot=tmp_path/'snapshot'; snapshot.mkdir()
    with pytest.raises(ValueError,match='separate'):
        levels.run(snapshot,snapshot/'experiment')
    assert list(snapshot.iterdir())==[]
