"""Synthetic evidence for the proposal; extracts pure classes, never calls run()."""
import ast
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'results/34480037109-1'
RESULTS = json.loads((EVIDENCE / 'SUMMARY.json').read_text())
NAMES = {'finite', 'Native', 'CandidateA', 'ControlLDRC', '_peer_corr',
         '_prior_residuals', 'dynamic_peer_breadth'}
CONSTANTS = {'ORD_DD', 'FAST', 'SLOW', 'LDRC_DD', 'LDRC_R20', 'LDRC_CEIL',
             'LDRC_REC', 'LDRC_V', 'PEER_LOOKBACK', 'PEER_MIN_OBS', 'PEER_COUNT',
             'PEER_CORR_FLOOR', 'PEER_STATS'}


def load(arm='clean_cached', edits=None):
    source = (EVIDENCE / f'sources/{arm}.py').read_text()
    expected = RESULTS['results'][arm]['source']['candidate_sha256']
    assert hashlib.sha256(source.encode()).hexdigest() == expected
    nodes = []
    for node in ast.parse(source).body:
        name = getattr(node, 'name', None)
        if name in NAMES:
            if edits and name in edits:
                body = ast.get_source_segment(source, node)
                for old, new, count in edits[name]:
                    assert body.count(old) == count
                    body = body.replace(old, new)
                node = ast.parse(body).body[0]
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in CONSTANTS
            for target in node.targets
        ):
            nodes.append(node)
    env = {'np': np}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pure-source>', 'exec'), env)
    return env


def snapshot(obj):
    return json.dumps(obj.__dict__, sort_keys=True)


def controller_args(i, rng):
    phase = i % 60
    recovery_r40 = -.03 if (i // 60) % 2 else -.05
    if phase < 8:
        return (0., 0., -.20, -.10, -.08, .07, -.06)
    if phase < 16:
        return (.55, .55, -.05, .06, recovery_r40, .07, .04)
    if phase == 16:
        return (1., .55, -.05, .06, recovery_r40, .07, .04)
    if phase < 25:
        return (1., 1., -.12, -.10, -.06, .07, -.06)
    if phase < 41:
        return (1., 1., -.05, .04, -.03, .07, .02)
    return (rng.choice([0., .55, 1.]), rng.choice([None, 0., .55, 1.]),
            rng.choice([None, -.1, -.099, -.2]),
            rng.choice([None, float('nan'), -.085, 0., .04]),
            rng.choice([None, -.04, -.039, .02]),
            rng.choice([None, -.01, 0., .04, .12]),
            rng.choice([None, -.02, 0., .03]))


def check_redundant_guards():
    edits = {
        'Native': [('dd>-.06 and not fastsig', 'dd>-.06', 2)],
        'CandidateA': [('if not self.latched and not cleared:', 'if not self.latched:', 1)],
    }
    ref = load(); changed = load(edits=edits)
    a = ref['Native'](); b = changed['Native']()
    ca = ref['CandidateA'](); cb = changed['CandidateA']()
    rng = random.Random(350301)
    for i in range(10000):
        healthy = (i // 25) % 4 == 0
        ob = (rng.choice([None, -.155, -.1, -.06, -.059, -.20]), -.07, -.11,
              .04 if healthy else -.06, rng.choice([None, -.09, .02]),
              .3 if healthy else .9, .5 if healthy else .1, .35, -.03, .08,
              0 if healthy else 4, 110. if healthy else 90.)
        assert a.step(ob) == b.step(ob)
        assert snapshot(a) == snapshot(b)
        args = controller_args(i, rng)
        assert ca.step(*args) == cb.step(*args)
        assert snapshot(ca) == snapshot(cb)
    return {'native_steps': 10000, 'candidate_steps': 10000}


def check_reduced_candidate_information():
    env = load(); cls = env['CandidateA']; original = cls()
    state = {'recovery': 'CLEAR', 'latched': False, 'full_streak': 0,
             'recent_positive_streak': 0, 'previous_native_was_full': True}
    audit = {'episodes': 0, 'concordance_releases': 0}
    rng = random.Random(350302); states_seen = set(); reasons_seen = set()
    for i in range(25000):
        args = controller_args(i, rng)
        reconstructed = cls()
        reconstructed.episode = state['recovery'] != 'CLEAR'
        reconstructed.prev_desired = {'CLEAR': 1., 'HOLD_ZERO': 0., 'HOLD_55': .55}[state['recovery']]
        reconstructed.prev_native = 1. if state['previous_native_was_full'] else 0.
        for key in ('latched', 'full_streak', 'recent_positive_streak'):
            setattr(reconstructed, key, state[key])
        expected = original.step(*args)
        observed = reconstructed.step(*args)
        assert expected == observed
        reasons_seen.update(observed[1].split('|'))
        for key in audit:
            audit[key] += getattr(reconstructed, key)
            assert audit[key] == getattr(original, key)
        if reconstructed.episode:
            assert reconstructed.prev_desired in (0., .55)
            recovery = 'HOLD_ZERO' if reconstructed.prev_desired == 0. else 'HOLD_55'
        else:
            recovery = 'CLEAR'
        state = {key: getattr(reconstructed, key) for key in
                 ('latched', 'full_streak', 'recent_positive_streak')}
        state.update(recovery=recovery,
                     previous_native_was_full=reconstructed.prev_native >= 1-1e-12)
        states_seen.add(recovery)
    assert states_seen == {'CLEAR', 'HOLD_ZERO', 'HOLD_55'}
    assert {'DIVERGENCE_CLEAR', 'LD_ENTER_DIVERGENCE', 'FULL_RISK_HELD',
            'FULL_RISK_CERTIFIED_CROSS_SURFACE',
            'FULL_RISK_CERTIFIED_PERSISTENCE'} <= reasons_seen, reasons_seen
    return {'steps': 25000, 'reconstructed_before_every_step': True,
            'recovery_states_seen': sorted(states_seen), 'audit': audit,
            'claim': 'Information-reduction check; enum transition implementation remains proposed.'}


def check_rebound_enabled_counterexample():
    a = load()['ControlLDRC']()
    b = load(edits={'ControlLDRC': [
        ('if not self.latched and not cleared:', 'if not self.latched:', 1)]})['ControlLDRC']()
    a.latched = b.latched = True
    args = (1., 1., -.12, -.10, -.05, .12)
    x = a.step(*args); y = b.step(*args)
    assert x[0] == 1. and y[0] == .55
    return {'rebound_enabled_target': x[0], 'incorrect_guard_removal_target': y[0]}


def check_mandatory_ramp_interaction():
    reference = load(); fixed = load('fixed_ramp10')
    targets = []
    for env in (reference, fixed):
        n = env['Native'](); c = env['CandidateA']()
        n.fast = True; n.fast_age = 9; n.fast_h = 2
        if hasattr(n, 'r40hist'):
            n.r40hist = [-.05, -.04, -.03, -.02, -.01, 0.]
        c.episode = True; c.prev_native = 0.; c.prev_desired = 0.
        native = n.step((-.03, .02, .03, .04, .05, .3, .5, 0., .06, 0., 0, 110.))[0]
        desired = c.step(native, 0., -.03, .06, -.05, .07, .04)[0]
        targets.append({'native': native, 'final': desired})
    assert targets == [{'native': 1., 'final': 0.}, {'native': .55, 'final': .55}]
    return {'reference': targets[0], 'mandatory_ramp': targets[1],
            'claim': 'Synthetic mechanism; historical session attribution remains separate.'}


def check_peer_vote_information():
    combinations = 0
    for count in range(1, 5):
        for votes in itertools.product([False, True], repeat=count):
            assert (sum(votes) / count >= .5) == (2 * sum(votes) >= count)
            if not votes[0]:
                peers = count - 1; red_peers = sum(votes[1:])
                reduced = (peers == 1 and red_peers == 1) or red_peers >= 2
                assert reduced == (sum(votes) / count >= .5)
            combinations += 1
    env = load(); rng = random.Random(350303)
    env['_prior_residuals'] = lambda tid, *_: {0: tid + 1.}
    env['_peer_corr'] = lambda *_: .5
    for _ in range(1000):
        held = [(i, None, -.02, rng.choice([-.04, -.02, .02]), None, None,
                 bool(rng.randrange(2)), False) for i in range(rng.randrange(21))]
        expected = env['dynamic_peer_breadth'](held, 0, None, None, None)
        fast = (sum(bool(z[6]) for z in held) / len(held),
                sum(z[2] <= -.10 or z[3] <= -.03 for z in held) / len(held)) if held else (0., 0.)
        assert expected == fast
    # A red peer changes the answer and must disable the shortcut.
    held = [(0, None, -.02, -.01, None, None, False, False),
            (1, None, -.12, -.04, None, None, False, True)]
    assert env['dynamic_peer_breadth'](held, 0, None, None, None) == (0., 1.)
    assert sum(z[2] <= -.10 or z[3] <= -.03 for z in held) / len(held) == .5
    return {'vote_combinations': combinations, 'zero_red_books': 1000,
            'red_peer_falsifier': 'detected'}


def check_fragility_observation_clock():
    rng = random.Random(350304)
    nav = [100.]
    for _ in range(2000):
        nav.append(nav[-1] * (1 + rng.uniform(-.025, .025)))
    history = []; current_close_mismatches = 0
    for t in range(len(nav)):
        r40 = nav[t] / nav[t-40] - 1 if t >= 40 else None
        expected = (history[-1] - history[-6]) if len(history) >= 6 and history[-6] is not None else None
        derived = ((nav[t-1] / nav[t-41] - 1) - (nav[t-6] / nav[t-46] - 1)) if t >= 46 else None
        assert expected == derived
        if t >= 46:
            wrong = r40 - (nav[t-5] / nav[t-45] - 1)
            current_close_mismatches += wrong != expected
        history = (history + [r40])[-6:]
    assert current_close_mismatches > 0
    return {'observations': len(nav), 'wrong_current_close_mismatches': current_close_mismatches}


def main():
    checks = {name.removeprefix('check_'): fn() for name, fn in sorted(globals().copy().items())
              if name.startswith('check_') and callable(fn)}
    print(json.dumps({'status': 'PASS_SYNTHETIC_REASONING_CHECKS',
                      'python': sys.version.split()[0], 'numpy': np.__version__,
                      'source_sha256': RESULTS['results']['clean_cached']['source']['candidate_sha256'],
                      'full_pit_starts': 0, 'checks': checks}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
