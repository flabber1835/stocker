"""One DATA/AST recovery change; canonical execution remains hosted only."""
import ast
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import types

from p10_reentry_policy import transform

PARENT_SHA = 'a67bb21df8df12f1e411bfc9a562eb62180df4e1fd6f9e94c1e845a9f0978fb5'
BASELINE = 'P00_FROZEN_SENTINEL'
CANDIDATE = 'P00_NO_EXTRA_RECOVERY_HOLD'
CHANGES = (
    ('self.full_streak >= LDRC_REC or concordant', 'True'),
    ("'ramp-free-ex3-rebound-false/1'", "'research-p00-no-extra-recovery-hold/1'"),
    ("'FULL_RISK_CERTIFIED_PERSISTENCE'", "'P00_NATIVE_RECOVERED_NO_EXTRA_HOLD'"),
)
VECTOR_CHANGES = (
    ('episode & (native >= 1) & ((full >= par(\'recovery_sessions\')) | concord)',
     'episode & (native >= 1)'),
)


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P00_RECOVERY_HOLD_' + code)


def native_ast(raw):
    node, = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'Native']
    return ast.dump(node, include_attributes=False)


def source(raw, candidate):
    need(hashlib.sha256(raw).hexdigest() == PARENT_SHA, 'FROZEN_PARENT_BYTES')
    if not candidate:
        return raw.decode()
    result = transform(raw, CHANGES)
    need(native_ast(raw) == native_ast(result), 'NATIVE_AST_UNCHANGED')
    return result


def hosted():
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1'
         and Path(__file__).resolve().as_posix().startswith('/driver/'), 'HOSTED_ONLY')


def profiles():
    from full_system_controller_policy import BASE_PARENT, BASE_OWNED
    return [dict(id=name, parent=deepcopy(BASE_PARENT), owned=dict(BASE_OWNED))
            for name in (BASELINE, CANDIDATE)]


def parent_module(raw, profile, expected_sha):
    hosted()
    need(expected_sha == PARENT_SHA and profile['id'] in (BASELINE, CANDIDATE), 'REGISTERED_PARENT')
    text = source(raw, profile['id'] == CANDIDATE)
    module = types.ModuleType('_research_p00_' + profile['id'])
    exec(compile(text, '<p00-hash-bound-extra-hold-policy>', 'exec'), module.__dict__)
    module.compiled_sha256 = hashlib.sha256(text.encode()).hexdigest()
    return module


def targets(rows, registered):
    hosted()
    import numpy as np
    import full_system_controller_vector as baseline
    need(registered == profiles(), 'EXACT_TWO_PROFILES')
    text = transform(Path(baseline.__file__).read_bytes(), VECTOR_CHANGES)
    independent = types.ModuleType('_independent_p00_extra_hold_equations')
    exec(compile(text, '<independent-p00-extra-hold-array-equations>', 'exec'), independent.__dict__)
    return np.concatenate((baseline.targets(rows, registered[:1]),
                           independent.targets(rows, registered[1:])), axis=0)


def canary(raw):
    """Actual frozen controller signatures and transitions, hosted synthetic input."""
    hosted()
    old = parent_module(raw, profiles()[0], PARENT_SHA)
    new = parent_module(raw, profiles()[1], PARENT_SHA)
    healthy = (0., .01, .01, .01, .01, .5, .3, 0., .01, 0., 0, 100.)
    checked = 0
    releases = {}
    for attr, first_full in (('fast', 9), ('slow', 19)):
        before, after = old.Native(), new.Native()
        setattr(before, attr, True)
        setattr(after, attr, True)
        observed = None
        for i in range(24):
            left, right = before.step(healthy), after.step(healthy)
            need(left == right and before.snapshot() == after.snapshot(), 'ALL_NATIVE_TRANSITIONS_UNCHANGED')
            if observed is None and right[0] == 1.:
                observed = i + 1
            checked += 2
        need(observed == first_full, 'ORIGINAL_MINIMUM_AGE_' + attr)
        releases[attr] = observed
    for cls in (old.Native, new.Native):
        state = cls()
        state.fast, state.fast_age, state.fast_h = True, 9, 2
        unhealthy = list(healthy)
        unhealthy[3] = -.01
        need(state.step(unhealthy)[0] == 0. and state.fast_h == 0, 'UNHEALTHY_RESETS_NATIVE_STREAK')
        for i in range(3):
            need(state.step(healthy)[0] == (1. if i == 2 else 0.), 'ORIGINAL_THREE_HEALTHY_AFTER_RESET')
        checked += 4
    for cls, expected in ((old.CandidateA, 0.), (new.CandidateA, 1.)):
        state = cls()
        state.episode = True
        need(state.step(1., 1., -.05, -.01, -.10, .01, .01)[0] == expected, 'ONLY_EXTRA_HOLD_REMOVED')
        checked += 1
    for cls in (old.CandidateA, new.CandidateA):
        state = cls()
        state.episode, state.latched = True, True
        need(state.step(1., 1., -.11, -.09, -.10, .01, .01)[0] == (0. if cls is old.CandidateA else .55),
             'LEADERSHIP_CEILING_RETAINED')
        checked += 1
    for source_cls, other_cls in ((old.CandidateA, new.CandidateA), (new.CandidateA, old.CandidateA)):
        payload = source_cls().snapshot()
        need(source_cls.from_snapshot(payload).snapshot() == payload, 'SAME_POLICY_CANDIDATE_RESTORE')
        try:
            other_cls.from_snapshot(payload)
        except ValueError:
            pass
        else:
            need(False, 'CROSS_POLICY_CANDIDATE_SNAPSHOT_REFUSAL')
    from owned_grid import canonical_leaf, configure
    from types import SimpleNamespace
    leaf = canonical_leaf('/variant/sentinel/controller/owned_impairment.py',
        '699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b',
        name='_private_sharadar_owned_grid_p00_hold_canary')
    configure(leaf, profiles()[0]['owned'])
    state = leaf.fresh()
    for i in range(13):
        ob = SimpleNamespace(session=f'2000-01-{i+3:02}', shadow_drawdown=-.11,
                             shadow_r20=-.01 if i < 5 else .01,
                             damaged_breadth=.90 if i < 5 else .50, green_breadth=.05 if i < 5 else .30)
        state, evidence = leaf.step(observation=ob, base_target=1., state=state)
        need(evidence['target'] == (.55 if 4 <= i < 12 else 1.), 'OWNED55_UNCHANGED')
        checked += 1
    return dict(actual_synthetic_calls=checked, native_timing_unchanged=releases,
                native_unhealthy_streak_reset_retained=True, only_extra_hold_removed=True,
                leadership_ceiling_retained=True, owned55_retained=True,
                cross_policy_candidate_snapshot_refused=True)
