"""Fixed 144-profile DATA/AST class and training-only selection."""
import ast
from copy import deepcopy
from fractions import Fraction as Q
import hashlib
import itertools
import json
import os
from pathlib import Path
import types

from p10_reentry_policy import transform

HERE = Path(__file__).resolve().parent
BASELINE = 'P00_FROZEN_SENTINEL'
NO_EXTRA = 'P00_NO_EXTRA_RECOVERY_HOLD'
PARENT_SHA = 'a67bb21df8df12f1e411bfc9a562eb62180df4e1fd6f9e94c1e845a9f0978fb5'
AXES = dict(extra_hold=[True, False], fast_healthy=[2, 3], slow_healthy=[3, 6],
            owned_entry_sessions=[1, 3, 5], owned_entry_damage=['0.75', '0.88'],
            owned_ceiling=['0.25', '0.55', '0.75'])
NATIVE_CAPS = dict(ordinary_age=20, ordinary_h=3, base_fast_age=10, base_fast_h=3,
                   base_dur=30, fast_age=9, fast_h=3, slow_age=19, slow_h=6)
VECTOR_CHANGES = (
    ('old & ~new & (age + 1 >= 10) & (fh >= 3)',
     "old & ~new & (age + 1 >= 10) & (fh >= p('recovery.fast_healthy'))"),
    ('old & (sa + 1 >= 20) & (sh >= 6)',
     "old & (sa + 1 >= 20) & (sh >= p('recovery.slow_healthy'))"),
    ('np.minimum(fh, 3)', "np.minimum(fh, p('recovery.fast_healthy'))"),
    ('np.minimum(sh, 6)', "np.minimum(sh, p('recovery.slow_healthy'))"),
    ("episode & (native >= 1) & ((full >= par('recovery_sessions')) | concord)",
     "episode & (native >= 1) & ((p('recovery.extra_hold') == 0) | (full >= par('recovery_sessions')) | concord)"),
)


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P00_SENTINEL_GRID_' + code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def profiles():
    from full_system_controller_policy import BASE_PARENT, BASE_OWNED
    protocol = json.loads((HERE/'p00-sentinel-grid-protocol.json').read_bytes())
    need(protocol['axes'] == AXES and protocol['profile_count'] == 144
         and protocol['selection_uses_later_periods'] is protocol['postselection_retuning'] is False,
         'EXACT_FIXED_CLASS')
    result = []
    for values in itertools.product(*(AXES[k] for k in AXES)):
        axis = dict(zip(AXES, values))
        owned = dict(BASE_OWNED)
        owned.update(entry_sessions=axis['owned_entry_sessions'], entry_damage=axis['owned_entry_damage'],
                     active_ceiling=axis['owned_ceiling'])
        config = dict(parent=deepcopy(BASE_PARENT), owned=owned,
                      recovery={k:axis[k] for k in ('extra_hold','fast_healthy','slow_healthy')})
        control = (axis['fast_healthy'],axis['slow_healthy'],owned) == (3,6,BASE_OWNED)
        pid = (BASELINE if axis['extra_hold'] else NO_EXTRA) if control else 'GRID_'+digest(config)[:20]
        result.append(dict(id=pid, **config))
    result.sort(key=lambda p:(p['id'] != BASELINE, p['id'] != NO_EXTRA, p['id']))
    need(len(result) == len({p['id'] for p in result}) == 144
         and [p['id'] for p in result[:2]] == [BASELINE,NO_EXTRA], 'COMPLETE_CLASS_AND_CONTROLS')
    return result


def source_changes(profile):
    r, pid = profile['recovery'], profile['id']
    caps = {**NATIVE_CAPS, 'fast_h':r['fast_healthy'], 'slow_h':r['slow_healthy']}
    gate = 'self.full_streak >= LDRC_REC or concordant'
    return (
        ('self.fast_h >= 3', 'self.fast_h >= '+str(r['fast_healthy'])),
        ('self.slow_h >= 6', 'self.slow_h >= '+str(r['slow_healthy'])),
        ('min(self.fast_h, 3)', 'min(self.fast_h, '+str(r['fast_healthy'])+')'),
        ('min(self.slow_h, 6)', 'min(self.slow_h, '+str(r['slow_healthy'])+')'),
        (repr(NATIVE_CAPS), repr(caps)),
        ("'ramp-free-native/1'", repr('research-p00-sentinel-grid-native/'+pid)),
        ("'ramp-free-ex3-rebound-false/1'", repr('research-p00-sentinel-grid-candidate/'+pid)),
        (gate, gate if r['extra_hold'] else 'True'),
    )


def source(raw, profile):
    need(hashlib.sha256(raw).hexdigest() == PARENT_SHA, 'FROZEN_PARENT_BYTES')
    return transform(raw, source_changes(profile))


def hosted():
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1'
         and Path(__file__).resolve().as_posix().startswith('/driver/'), 'HOSTED_ONLY')


def parent_module(raw, profile, expected_sha):
    hosted()
    need(expected_sha == PARENT_SHA and profile in profiles(), 'EXACT_REGISTERED_PROFILE')
    text = source(raw, profile)
    module = types.ModuleType('_private_p00_sentinel_grid_'+profile['id'])
    exec(compile(text, '<hash-bound-p00-sentinel-grid>', 'exec'), module.__dict__)
    module.compiled_sha256 = hashlib.sha256(text.encode()).hexdigest()
    return module


def targets(rows, registered):
    hosted()
    import full_system_controller_vector as baseline
    need(registered == profiles(), 'EXACT_VECTOR_CLASS')
    raw = Path(baseline.__file__).read_bytes()
    text = transform(raw, VECTOR_CHANGES)
    module = types.ModuleType('_independent_p00_sentinel_grid_equations')
    exec(compile(text, '<independent-p00-grid-vector>', 'exec'), module.__dict__)
    return module.targets(rows, registered)


def select(records, baseline):
    """Exact training-only growth/protection selection; no later metrics accepted."""
    expected = {'id','core_id','group','metrics','turnover'}
    need(records and all(set(r) == expected for r in records), 'TRAINING_ONLY_RECORD_SHAPE')
    by = {r['id']:r for r in records}
    need(set(by) == {p['id'] for p in profiles()} and baseline == BASELINE, 'COMPLETE_TRAINING_CLASS')
    controls = [by[BASELINE],by[NO_EXTRA]]
    axis = lambda r:tuple(r['metrics'][k] for k in ('anchor','start','end','closes'))
    need(all(axis(r) == axis(controls[0]) for r in records)
         and controls[0]['metrics']['end'] in ('2020-12-31','2022-12-30')
         and controls[0]['metrics']['anchor'] == '2018-01-02'
         and len({r['core_id'] for r in records}) == 1, 'COMMON_TRAINING_WINDOW')
    wealth = lambda r:Q(r['metrics']['multiple'])
    dd = lambda r:Q(r['metrics']['maximum_drawdown_magnitude'])
    cost = lambda r:Q(r['turnover'])
    growth_order = lambda r:(-wealth(r),dd(r),cost(r),r['id'])
    protect_order = lambda r:(dd(r),-wealth(r),cost(r),r['id'])
    floor = max(map(wealth,controls))
    ceiling = min(map(dd,controls))
    protection = min((r for r in records if wealth(r) >= floor), key=protect_order)['id']
    growth = min((r for r in records if dd(r) <= ceiling), key=growth_order)['id']
    budgets = []
    selected = [BASELINE,NO_EXTRA,protection,growth]
    for fraction in ('0.50','0.75','1.0'):
        allowed = [r for r in records if dd(r) <= dd(controls[0])*Q(fraction)]
        winner = min(allowed,key=growth_order)['id'] if allowed else None
        budgets.append(dict(relative_budget=fraction,id=winner))
        if winner: selected.append(winner)
    joint = [r for r in records if wealth(r) > wealth(controls[0]) and dd(r) < dd(controls[0])]
    best = min(joint,key=growth_order)['id'] if joint else None
    if best: selected.append(best)
    return dict(status='TRAINING_SELECTION_LOCKED', selected=list(dict.fromkeys(selected)), baseline=BASELINE,
                protection_candidate=protection, growth_candidate=growth,
                budget_choices=budgets, training_joint_improvements=len(joint), best_joint=best,
                growth_floor_multiple=str(floor), drawdown_ceiling=str(ceiling), evaluation_used=False,
                coverage='COMPLETE_144_PROFILE_CLASS_NOT_GLOBAL_OPTIMUM')


def canary(raw):
    hosted()
    from owned_grid import canonical_leaf, configure
    from types import SimpleNamespace
    healthy = (0., .01, .01, .01, .01, .50, .30, 0., .01, 0., 0, 100.)
    previous = None
    checked = 0
    for index, profile in enumerate(profiles()):
        module = parent_module(raw, profile, PARENT_SHA)
        for attr,key,age in (('fast','fast_healthy',9),('slow','slow_healthy',19)):
            state = module.Native()
            setattr(state,attr,True)
            setattr(state,attr+'_age',age)
            setattr(state,attr+'_h',profile['recovery'][key]-1)
            bad = list(healthy);bad[3] = -.01
            need(state.step(bad)[0] == 0. and getattr(state,attr+'_h') == 0, 'UNHEALTHY_STREAK_RESET')
            checked += 1
            for i in range(profile['recovery'][key]):
                need(state.step(healthy)[0] == (1. if i+1 == profile['recovery'][key] else 0.), 'PARAMETERIZED_HEALTHY_RELEASE')
                payload = state.snapshot()
                need(module.Native.from_snapshot(payload).snapshot() == payload, 'PARAMETERIZED_NATIVE_RESTORE')
                checked += 1
            state = module.Native();setattr(state,attr,True)
            need(state.step(healthy)[0] == 0., 'MINIMUM_AGE_RETAINED')
            checked += 1
        for latched in (False,True):
            state = module.CandidateA();state.episode=True;state.latched=latched
            wanted = 0. if profile['recovery']['extra_hold'] else (.55 if latched else 1.)
            need(state.step(1.,1.,-.11 if latched else -.05,-.09,-.10,.01,.01)[0] == wanted,
                 'EXTRA_HOLD_AND_LEADERSHIP_CAP')
            payload = state.snapshot()
            need(module.CandidateA.from_snapshot(payload).snapshot() == payload, 'CANDIDATE_RESTORE')
            checked += 1
        if previous is not None:
            for cls,other in ((module.Native,previous.Native),(module.CandidateA,previous.CandidateA)):
                try: cls.from_snapshot(other().snapshot())
                except ValueError: pass
                else: need(False,'CROSS_PROFILE_SNAPSHOT_REFUSAL')
        leaf = canonical_leaf('/variant/sentinel/controller/owned_impairment.py',
            '699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b',
            name='_private_sharadar_owned_grid_p00_grid_canary_'+str(index))
        configure(leaf,profile['owned']);state=leaf.fresh();entry=profile['owned']['entry_sessions']
        for i in range(entry+8):
            ob=SimpleNamespace(session=f'2000-01-{i+3:02}',shadow_drawdown=-.11,
                               shadow_r20=-.01 if i<entry else .01,
                               damaged_breadth=1. if i<entry else .50,green_breadth=0. if i<entry else .30)
            state,evidence=leaf.step(observation=ob,base_target=1.,state=state)
            wanted=float(profile['owned']['active_ceiling']) if entry-1 <= i < entry+7 else 1.
            need(evidence['target'] == wanted,'DECLARED_OWNED_ENTRY_CEILING_AND_RECOVERY')
            checked += 1
        previous=module
    return dict(profiles=144, actual_synthetic_calls=checked, counter_caps_and_restores_verified=True,
                native_minimum_ages_retained=True, leadership_ceiling_retained=True,
                owned_entry_ceiling_and_recovery_verified=True, cross_profile_snapshots_refused=True)
