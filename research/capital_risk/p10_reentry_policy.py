"""DATA/AST policy compiler; canonical modules execute only on hosted compute."""
import ast
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import types

PARENT_SHA = 'a67bb21df8df12f1e411bfc9a562eb62180df4e1fd6f9e94c1e845a9f0978fb5'
BASELINE = 'P10_FROZEN_SENTINEL'
CANDIDATE = 'P10_CORE_HEALTH_3'
CHANGES = (
    ('self.fast_age + 1 >= 10 and self.fast_h >= 3', 'self.fast_h >= 3'),
    ('self.slow_age + 1 >= 20 and self.slow_h >= 6', 'self.slow_h >= 3'),
    ('self.full_streak >= LDRC_REC or concordant', 'True'),
    ("'ramp-free-native/1'", "'research-p10-health3-native/1'"),
    ("'ramp-free-ex3-rebound-false/1'", "'research-p10-health3-candidate/1'"),
    ("'FULL_RISK_CERTIFIED_PERSISTENCE'", "'P10_CORE_HEALTH_3_RECOVERY'"),
)
VECTOR_CHANGES = (
    ('old & ~new & (age + 1 >= 10) & (fh >= 3)', 'old & ~new & (fh >= 3)'),
    ('old & (sa + 1 >= 20) & (sh >= 6)', 'old & (sh >= 3)'),
    ('episode & (native >= 1) & ((full >= par(\'recovery_sessions\')) | concord)',
     'episode & (native >= 1)'),
)


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P10_REENTRY_' + code)


def expression(text):
    return ast.parse(text, mode='eval').body


def transform(raw, changes):
    tree = ast.parse(raw)
    original = ast.dump(tree, include_attributes=False)
    operations = []
    for before, after in changes:
        pattern = ast.dump(expression(before), include_attributes=False)
        matches = [n for n in ast.walk(tree) if ast.dump(n, include_attributes=False) == pattern]
        need(len(matches) == 1, 'EXACT_SINGLE_AST_SITE:' + before)
        target = matches[0]
        replacement = expression(after)
        for parent in ast.walk(tree):
            for field, child in ast.iter_fields(parent):
                if child is target:
                    setattr(parent, field, replacement)
                    operations.append((parent, field, None, target))
                elif isinstance(child, list):
                    for i, item in enumerate(child):
                        if item is target:
                            child[i] = replacement
                            operations.append((parent, field, i, target))
    result = ast.unparse(ast.fix_missing_locations(tree)) + '\n'
    for parent, field, index, prior in reversed(operations):
        if index is None:
            setattr(parent, field, prior)
        else:
            getattr(parent, field)[index] = prior
    need(ast.dump(tree, include_attributes=False) == original, 'COMPLETE_INVERSE_AST')
    return result


def source(raw, candidate):
    need(hashlib.sha256(raw).hexdigest() == PARENT_SHA, 'FROZEN_PARENT_BYTES')
    return transform(raw, CHANGES) if candidate else raw.decode()


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
    module = types.ModuleType('_research_p10_' + profile['id'])
    exec(compile(text, '<p10-hash-bound-research-policy>', 'exec'), module.__dict__)
    module.compiled_sha256 = hashlib.sha256(text.encode()).hexdigest()
    return module


def targets(rows, registered):
    hosted()
    import numpy as np
    import full_system_controller_vector as baseline
    need(registered == profiles(), 'EXACT_TWO_PROFILES')
    text = transform(Path(baseline.__file__).read_bytes(), VECTOR_CHANGES)
    independent = types.ModuleType('_independent_p10_health3_equations')
    exec(compile(text, '<independent-p10-health3-array-equations>', 'exec'), independent.__dict__)
    return np.concatenate((baseline.targets(rows, registered[:1]),
                           independent.targets(rows, registered[1:])), axis=0)


def canary(raw):
    """Actual canonical signatures and policy differences; hosted synthetic DTOs."""
    hosted()
    old = parent_module(raw, profiles()[0], PARENT_SHA)
    new = parent_module(raw, profiles()[1], PARENT_SHA)
    healthy = (0., .01, .01, .01, .01, .5, .3, 0., .01, 0., 0, 100.)
    checked = 0
    for attr in ('fast', 'slow'):
        baseline, changed = old.Native(), new.Native()
        setattr(baseline, attr, True)
        setattr(changed, attr, True)
        for i in range(3):
            before = baseline.step(healthy)[0]
            after = changed.step(healthy)[0]
            need(before == 0. and after == (1. if i == 2 else 0.), 'THREE_HEALTHY_' + attr)
            checked += 1
        payload = changed.snapshot()
        need(new.Native.from_snapshot(payload).snapshot() == payload, 'NEW_NATIVE_RESTORE')
        try:
            old.Native.from_snapshot(payload)
        except ValueError:
            pass
        else:
            need(False, 'CROSS_POLICY_SNAPSHOT_REFUSAL')
    for cls, expected in ((old.CandidateA, 0.), (new.CandidateA, 1.)):
        state = cls()
        state.episode = True
        need(state.step(1., 1., -.05, -.01, -.10, .01, .01)[0] == expected,
             'ACTUAL_RECOVERY_GATE')
        checked += 1
    state = new.CandidateA()
    state.episode = True
    state.latched = True
    need(state.step(1., 1., -.11, -.09, -.10, .01, .01)[0] == .55, 'DIVERGENCE_CEILING_RETAINED')
    checked += 1
    return dict(actual_synthetic_calls=checked, three_healthy_release=True,
                divergence_ceiling_retained=True, original_snapshot_refused=True)
