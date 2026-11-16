from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from research.exposure_oracle import accounting as A, logic
from sentinel.controller import owned_impairment


def records():
    state = owned_impairment.OwnedImpairmentState().model_dump()
    rows = []
    for i in range(45):
        day = (date(2021,1,4)+timedelta(days=i)).isoformat()
        impaired = i < 7 or 24 <= i < 30
        healthy = 12 <= i < 24 or i >= 32
        ob = SimpleNamespace(session=day,shadow_drawdown=-.2 if impaired else -.03,
            damaged_breadth=.95 if impaired else (.2 if healthy else .5),
            green_breadth=.1 if not healthy else .8,shadow_r20=.1 if healthy else -.1)
        native = 0. if 6 <= i < 12 else 1.
        base = 0. if native == 0 or 12 <= i < 20 else 1.
        state,evidence = owned_impairment.step(observation=ob,base_target=base,state=state)
        rows.append(dict(session=day,decision=dict(native_target_core_exposure=native,
            champion_target_core_exposure=base,target_core_exposure=evidence['target'],
            owned_impairment=evidence,ldrc=dict(desired_allocation=base,
                reason='FULL_RISK_HELD' if native == 1 and base == 0 else 'NORMAL'))))
    return rows


def test_baseline_reproduces_canonical_latch_and_final_targets():
    rows = records()
    trace = logic.decisions(rows,verify_baseline=True)
    for row,decision in zip(rows,trace):
        actual = row['decision']['owned_impairment']
        for key in ('active','entry_streak','recovery_streak','reason'):
            assert decision[key] == actual[key]
        assert D(decision['target']) == D(str(actual['target']))


@pytest.mark.parametrize('entry,bridge',logic.CASES.values())
def test_decisions_are_prefix_invariant_and_future_independent(entry,bridge):
    rows = records()
    full = logic.decisions(rows,entry_sessions=entry,bridge=bridge)
    assert logic.decisions(rows[:17],entry_sessions=entry,bridge=bridge) == full[:17]
    changed = deepcopy(rows)
    changed[-1]['decision']['owned_impairment']['healthy'] = False
    assert logic.decisions(changed,entry_sessions=entry,bridge=bridge)[:-1] == full[:-1]


def test_earlier_exit_uses_existing_predicate_and_preserves_eight_close_release():
    rows = records()
    early = logic.decisions(rows,entry_sessions=1)
    base = logic.decisions(rows)
    assert early[1]['active'] and not base[1]['active']
    assert D(early[3]['target']) == D('.55') and D(base[3]['target']) == 1
    assert early[18]['active'] and not early[19]['active']
    assert early[19]['reason'] == 'OWNED_RECOVERED'


def test_bridge_only_changes_native_full_recovery_wait():
    rows = records()
    base = logic.decisions(rows)
    bridge = logic.decisions(rows,bridge=True)
    for i,(b,c) in enumerate(zip(base,bridge)):
        if 12 <= i < 20:
            assert b['target'] == '0.0' and c['target'] == '0.55'
        else:
            assert D(c['target']) == D(b['target'])
        if rows[i]['decision']['native_target_core_exposure'] == 0:
            assert D(c['target']) == 0


def test_bridge_refuses_unknown_zero_reason():
    rows = records()
    rows[12]['decision']['ldrc']['reason'] = 'UNREVIEWED_ZERO'
    with pytest.raises(ValueError,match='unrecognized'):
        logic.decisions(rows,bridge=True)


def test_baseline_state_mismatch_cannot_be_hidden():
    rows = records()
    rows[13]['decision']['owned_impairment']['recovery_streak'] += 1
    with pytest.raises(ValueError,match='baseline owned state mismatch'):
        logic.decisions(rows,verify_baseline=True)


@pytest.mark.parametrize('impaired,healthy',[(1,False),(False,'true'),(True,True)])
def test_source_predicates_are_strict_and_coherent(impaired,healthy):
    seed = logic.Latch(active=False,entry_streak=0,recovery_streak=0,session='2021-01-04')
    with pytest.raises(ValueError,match='boolean predicates'):
        logic.advance(seed,session='2021-01-05',impaired=impaired,healthy=healthy,entry_sessions=1)


def test_close_decision_can_only_affect_following_open():
    days = [A.Day('2021-01-05',*[D(1)]*6),A.Day('2021-01-06',*[D(1)]*6)]
    trace = [dict(session='2021-01-04',target='0'),dict(session='2021-01-05',target='.55'),
             dict(session='2021-01-06',target='1')]
    assert logic.apply_at_next_open(days,trace) == [D(0),D('.55')]
    trace[1]['session'] = '2021-01-04'
    with pytest.raises(ValueError,match='alignment'):
        logic.apply_at_next_open(days,trace)


def test_later_window_retains_candidate_history_and_overnight_position():
    days = [A.Day('2021-01-05',D(1),D('1.1'),D('1.1'),D(1),D(1),D(1)),
            A.Day('2021-01-06',D('.9'),D(1),D('.9'),D(1),D(1),D(1))]
    full = A.replay(days,D(0),[D(1),D('.55')],'2021-01-04')
    rows = [dict(session=d,economics=dict(held_allocation='0')) for d in
            ('2021-01-04','2021-01-05','2021-01-06')]
    selected = logic.window(full,rows,1,2)
    assert selected['switches'] == 1
    assert selected['allocation_turnover'] == pytest.approx(.45)
    assert D(selected['multiple']) == D(full['nav'][2])/D(full['nav'][1])
    assert selected['cost_log'] == full['cost_log'][1:]


def test_initial_tbill_funding_counts_as_turnover_but_not_exposure_switch():
    day = A.Day('2021-01-05',*[D(1)]*6,fixed=D(0),fixed_net=D('.999'),
                fixed_cost=D('.999'),fixed_turnover=D(1))
    full = A.replay([day],D(0),[D(0)],'2021-01-04')
    rows = [dict(session='2021-01-04',economics=dict(held_allocation=None)),
            dict(session='2021-01-05',economics=dict(held_allocation='0',turnover='1'))]
    selected = logic.window(full,rows,0,1)
    assert selected['allocation_turnover'] == 1
    assert selected['switches'] == 0
    assert selected['overlay_cost_drag'] == pytest.approx(.001)
