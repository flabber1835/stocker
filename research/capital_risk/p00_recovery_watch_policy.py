"""Fixed RW1 research policy. All decision execution is hosted-only."""
import ast
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import math
import os
from pathlib import Path
import types

import p00_recovery_hold_policy as hold

PARENT_SHA = hold.PARENT_SHA
BASELINE = hold.BASELINE
NO_EXTRA = hold.CANDIDATE
CANDIDATE = 'P00_RECOVERY_WATCH_RW1'
SCHEMA = 'research.p00-recovery-watch-rw1/1'
VECTOR_SHA = '0a4e3a68aa5dcb4069685b965573d54be4f6eefdf4d78006ffa79dc10b228260'
RULE = dict(peak_return=-.05, entry_r20_below=0., entry_damage=.75,
            entry_green=.25, active_ceiling=.55, recovery_r20_above=0.,
            recovery_damage=.63, recovery_green=.20, recovery_closes=8,
            clear_drawdown_above=-.06)
SNAPSHOT_KEYS = {'schema', 'policy_id', 'mode', 'peak', 'active_cap',
                 'healthy_count', 'last_session'}
native_ast = hold.native_ast


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P00_RECOVERY_WATCH_' + code)


def hosted():
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1'
         and Path(__file__).resolve().as_posix().startswith('/driver/'), 'HOSTED_ONLY')


def profiles():
    controls = hold.profiles()
    return controls + [{**deepcopy(controls[1]), 'id': CANDIDATE}]


def source(raw, candidate):
    """DATA/AST only: candidate inherits the already admitted no-hold parent."""
    return hold.source(raw, candidate)


def parent_module(raw, profile, expected_sha):
    hosted()
    need(profile in profiles() and expected_sha == PARENT_SHA, 'EXACT_REGISTERED_PARENT')
    selected = deepcopy(profile)
    if selected['id'] == CANDIDATE:
        selected['id'] = NO_EXTRA
    return hold.parent_module(raw, selected, expected_sha)


def _session(value):
    need(type(value) is str, 'SESSION_TYPE')
    try:
        valid = len(value) == 10 and date.fromisoformat(value).isoformat() == value
    except ValueError:
        valid = False
    need(valid, 'SESSION_FORMAT')
    return value


def _number(value, code):
    need(type(value) in (int, float) and math.isfinite(value), code)
    return float(value)


def _validated_snapshot(payload):
    """Inert structural validation; no decision or canonical implementation."""
    need(type(payload) is dict and set(payload) == SNAPSHOT_KEYS, 'SNAPSHOT_FIELDS')
    need(payload['schema'] == SCHEMA and payload['policy_id'] == CANDIDATE,
         'SNAPSHOT_POLICY_IDENTITY')
    mode, peak, active, count, cursor = (payload[k] for k in
        ('mode', 'peak', 'active_cap', 'healthy_count', 'last_session'))
    need(type(mode) is str and mode in ('NORMAL', 'PENDING', 'WATCH'), 'SNAPSHOT_MODE')
    need(type(active) is bool and type(count) is int and 0 <= count < 8,
         'SNAPSHOT_COUNTER_TYPES')
    if cursor is not None:
        _session(cursor)
    if mode == 'WATCH':
        need(type(peak) is float and math.isfinite(peak) and peak > 0
             and cursor is not None, 'SNAPSHOT_WATCH_PEAK')
        need(active or count == 0, 'SNAPSHOT_INACTIVE_COUNTER')
    else:
        need(peak is None and active is False and count == 0, 'SNAPSHOT_NONWATCH_STATE')
    need(cursor is not None or mode == 'NORMAL', 'SNAPSHOT_INITIAL_STATE')
    return dict(payload)


class RecoveryWatch:
    def __init__(self):
        hosted()
        self.mode = 'NORMAL'
        self.peak = None
        self.active_cap = False
        self.healthy_count = 0
        self.last_session = None

    def snapshot(self):
        hosted()
        return _validated_snapshot(dict(schema=SCHEMA, policy_id=CANDIDATE,
            mode=self.mode, peak=self.peak, active_cap=self.active_cap,
            healthy_count=self.healthy_count, last_session=self.last_session))

    @classmethod
    def from_snapshot(cls, payload):
        hosted()
        value = _validated_snapshot(payload)
        result = cls()
        for name in ('mode', 'peak', 'active_cap', 'healthy_count', 'last_session'):
            setattr(result, name, value[name])
        return result

    def step(self, *, session, observation, native_stress):
        hosted()
        self.snapshot()
        current = _session(session)
        need(self.last_session is None or current > self.last_session, 'ORDERED_CURSOR')
        need(type(observation) is dict and observation.get('session') == current,
             'OBSERVATION_SESSION')
        need(type(native_stress) is bool, 'NATIVE_STRESS_TYPE')
        nav = _number(observation.get('shadow_nav'), 'POSITIVE_NAV')
        dd = _number(observation.get('shadow_drawdown'), 'GLOBAL_DRAWDOWN')
        need(nav > 0 and -1 < dd <= 0, 'NAV_DRAWDOWN_DOMAIN')
        watching = self.mode == 'WATCH' or (self.mode == 'PENDING' and not native_stress)
        r20 = damage = green = None
        if watching:
            r20 = _number(observation.get('shadow_r20'), 'WATCH_R20')
            damage = _number(observation.get('damaged_breadth'), 'WATCH_DAMAGE')
            green = _number(observation.get('green_breadth'), 'WATCH_GREEN')
            need(r20 >= -1 and 0 <= damage <= 1 and 0 <= green <= 1, 'WATCH_FEATURE_DOMAIN')
        # Validate all required input before mutating even a single state field.
        reason = 'RW1_NORMAL'
        if self.mode == 'NORMAL' and native_stress:
            self.mode = 'PENDING'
            reason = 'RW1_PENDING_NATIVE_STRESS'
        elif self.mode == 'PENDING':
            reason = 'RW1_PENDING_NATIVE_STRESS'
            if not native_stress:
                self.mode, self.peak = 'WATCH', nav
                reason = 'RW1_WATCH_STARTED'
        entry = healthy = False
        local_return = None
        if self.mode == 'WATCH':
            self.peak = max(self.peak, nav)
            local_return = nav / self.peak - 1
            entry = (local_return <= RULE['peak_return'] and r20 < RULE['entry_r20_below']
                     and damage >= RULE['entry_damage'] and green <= RULE['entry_green'])
            healthy = (r20 > RULE['recovery_r20_above']
                       and damage <= RULE['recovery_damage'] and green >= RULE['recovery_green'])
            if self.active_cap:
                self.healthy_count = self.healthy_count + 1 if healthy else 0
                reason = 'RW1_CAP_ACTIVE'
                if self.healthy_count >= RULE['recovery_closes']:
                    self.active_cap, self.healthy_count = False, 0
                    reason = 'RW1_CAP_RELEASED_WATCH_RETAINED'
            elif entry:
                self.active_cap, self.healthy_count = True, 0
                reason = 'RW1_CAP_ENTERED'
            if (not self.active_cap and not native_stress
                    and dd > RULE['clear_drawdown_above']):
                self.mode, self.peak, self.healthy_count = 'NORMAL', None, 0
                reason = 'RW1_EPISODE_CLEARED'
        self.last_session = current
        return dict(ceiling=RULE['active_ceiling'] if self.active_cap else 1.,
            reason=reason, entry_signal=entry, healthy=healthy, local_return=local_return,
            native_stress=native_stress, state=self.snapshot())


def vector_source(raw, no_extra):
    """Instrument hash-bound independent numeric equations, never Native code."""
    need(hashlib.sha256(raw).hexdigest() == VECTOR_SHA, 'INDEPENDENT_VECTOR_BYTES')
    text = hold.transform(raw, hold.VECTOR_CHANGES) if no_extra else raw.decode()
    tree = ast.parse(text)
    original = ast.dump(tree, include_attributes=False)
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'targets']
    loop, = [n for n in function.body if isinstance(n, ast.For)]
    append, = [n for n in loop.body if isinstance(n, ast.Expr)
               and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
               and isinstance(n.value.func.value, ast.Name)
               and n.value.func.value.id == 'paths' and n.value.func.attr == 'append']
    returned = function.body[-1]
    expected = ast.parse('np.asarray(paths, dtype=float).T', mode='eval').body
    need(isinstance(returned, ast.Return)
         and ast.dump(returned.value) == ast.dump(expected), 'INDEPENDENT_EXACT_RETURN')
    initial = ast.parse('native_stress_paths = []').body[0]
    capture = ast.parse('native_stress_paths.append((ordinary | bf | fast | slow).copy())').body[0]
    position, insertion = function.body.index(loop), loop.body.index(append)
    old_return = returned.value
    function.body.insert(position, initial)
    loop.body.insert(insertion, capture)
    returned.value = ast.parse('(np.asarray(paths, dtype=float).T, '
                               'np.asarray(native_stress_paths, dtype=bool).T)', mode='eval').body
    result = ast.unparse(ast.fix_missing_locations(tree)) + '\n'
    function.body.remove(initial)
    loop.body.remove(capture)
    returned.value = old_return
    need(ast.dump(tree, include_attributes=False) == original, 'INDEPENDENT_COMPLETE_INVERSE_AST')
    return result


def independent_watch(rows, stress_flags):
    """Separate scalar equations, with no calls to the worker state machine."""
    hosted()
    need(len(stress_flags) == len(rows), 'INDEPENDENT_STRESS_AXIS')
    phase, high, limited, consecutive, cursor = 'NORMAL', None, False, 0, None
    caps, states = [], []
    for row, stress in zip(rows, stress_flags):
        day = _session(row['session'])
        need(cursor is None or day > cursor, 'INDEPENDENT_ORDERED_AXIS')
        need(type(stress) is bool, 'INDEPENDENT_STRESS_BOOL')
        obs = row['evidence']['observation']
        need(obs.get('session', day) == day, 'INDEPENDENT_OBSERVATION_SESSION')
        value = _number(obs.get('shadow_nav'), 'INDEPENDENT_NAV')
        draw = _number(obs.get('shadow_drawdown'), 'INDEPENDENT_DRAWDOWN')
        need(value > 0 and -1 < draw <= 0, 'INDEPENDENT_DOMAIN')
        next_phase = 'PENDING' if phase == 'NORMAL' and stress else phase
        entering_watch = phase == 'PENDING' and not stress
        if entering_watch:
            next_phase, high = 'WATCH', value
        if next_phase == 'WATCH':
            momentum = _number(obs.get('shadow_r20'), 'INDEPENDENT_R20')
            damaged = _number(obs.get('damaged_breadth'), 'INDEPENDENT_DAMAGE')
            good = _number(obs.get('green_breadth'), 'INDEPENDENT_GREEN')
            need(momentum >= -1 and 0 <= damaged <= 1 and 0 <= good <= 1,
                 'INDEPENDENT_FEATURE_DOMAIN')
            high = value if value > high else high
            recovering = momentum > 0 and damaged <= .63 and good >= .20
            breached = value / high - 1 <= -.05 and momentum < 0 and damaged >= .75 and good <= .25
            was_limited = limited
            consecutive = (consecutive + 1 if recovering else 0) if was_limited else 0
            limited = (consecutive < 8) if was_limited else bool(breached)
            if not limited:
                consecutive = 0
            if not limited and not stress and draw > -.06:
                next_phase, high, consecutive = 'NORMAL', None, 0
        phase, cursor = next_phase, day
        caps.append(.55 if limited else 1.)
        states.append(dict(schema=SCHEMA, policy_id=CANDIDATE, mode=phase, peak=high,
                           active_cap=bool(limited), healthy_count=int(consecutive), last_session=day))
    return caps, states


def independent_targets(rows, registered):
    hosted()
    import numpy as np
    import full_system_controller_vector as equations
    need(registered == profiles(), 'EXACT_THREE_PROFILES')
    raw = Path(equations.__file__).read_bytes()
    paths, flags = [], []
    for index in range(2):
        module = types.ModuleType('_independent_p00_rw1_' + str(index))
        exec(compile(vector_source(raw, bool(index)), '<independent-p00-rw1-native-equations>', 'exec'),
             module.__dict__)
        path, stress = module.targets(rows, registered[index:index+1])
        need(path.shape == stress.shape == (1, len(rows)), 'INDEPENDENT_ARRAY_SHAPE')
        paths.append(path[0])
        flags.append(stress[0])
    need(np.array_equal(flags[0], flags[1]), 'UNCHANGED_NATIVE_STRESS')
    caps, states = independent_watch(rows, [bool(x) for x in flags[1]])
    return np.asarray([paths[0], paths[1], np.minimum(paths[1], caps)], dtype=float), states


def targets(rows, registered):
    hosted()
    return independent_targets(rows, registered)[0]


def _watch_canary(cls):
    """Hosted synthetic lifecycle oracle, also run against negative mutants."""
    state = cls()
    index, checked = 0, 0

    def observation(**changes):
        return dict(shadow_nav=100., shadow_drawdown=-.20, shadow_r20=.01,
                    damaged_breadth=.50, green_breadth=.30, **changes)

    def advance(stress=False, **changes):
        nonlocal state, index, checked
        index += 1
        day = (date(2000, 1, 1) + timedelta(days=index)).isoformat()
        ob = observation()
        ob.update(changes)
        ob['session'] = day
        result = state.step(session=day, observation=ob, native_stress=stress)
        payload = state.snapshot()
        state = cls.from_snapshot(payload)
        need(state.snapshot() == payload and result['state'] == payload, 'CANARY_RESTART')
        checked += 1
        return result

    need(advance(shadow_nav=70., shadow_r20=-.20, damaged_breadth=.90,
                 green_breadth=.05)['ceiling'] == 1. and state.mode == 'NORMAL', 'CANARY_NO_PRESTRESS')
    advance(True)
    need(state.mode == 'PENDING' and state.peak is None, 'CANARY_PENDING')
    advance(True, shadow_nav=120.)
    need(state.mode == 'PENDING' and state.peak is None, 'CANARY_PENDING_WAITS')
    advance()
    need(state.mode == 'WATCH' and state.peak == 100., 'CANARY_RECOVERY_PEAK')
    advance(shadow_nav=110.)
    need(state.peak == 110., 'CANARY_PEAK_RATCHET')
    failed_terms = [dict(shadow_nav=106.), dict(shadow_r20=0.),
                    dict(damaged_breadth=.74), dict(green_breadth=.26)]
    for alternative in failed_terms:
        values = dict(shadow_nav=100., shadow_r20=-.01, damaged_breadth=.80, green_breadth=.10)
        values.update(alternative)
        need(advance(**values)['ceiling'] == 1., 'CANARY_EACH_ENTRY_TERM')
    need(advance(shadow_nav=100., shadow_r20=-.01, damaged_breadth=.80,
                 green_breadth=.10)['ceiling'] == .55, 'CANARY_CAP_ENTRY')
    need(advance(True, shadow_nav=115., shadow_r20=-.01, damaged_breadth=.80,
                 green_breadth=.10)['ceiling'] == .55 and state.peak == 115.,
         'CANARY_PEAK_RETAINED_UNDER_NATIVE_STRESS')
    for _ in range(7):
        need(advance()['ceiling'] == .55, 'CANARY_EIGHT_HEALTHY_REQUIRED')
    advance(shadow_r20=0.)
    need(state.healthy_count == 0, 'CANARY_UNHEALTHY_RESET')
    for i in range(8):
        need(advance()['ceiling'] == (1. if i == 7 else .55), 'CANARY_EIGHT_HEALTHY_RELEASE')
    need(state.mode == 'WATCH' and state.peak == 115., 'CANARY_RELEASE_RETAINS_MEMORY')
    need(advance(shadow_nav=107., shadow_r20=-.01, damaged_breadth=.80,
                 green_breadth=.10)['ceiling'] == .55, 'CANARY_SECOND_LEG')
    advance(shadow_drawdown=-.01, shadow_r20=-.01)
    need(state.mode == 'WATCH' and state.active_cap, 'CANARY_NO_UNHEALTHY_CLEAR')
    for _ in range(8):
        advance(True, shadow_drawdown=-.01)
    need(state.mode == 'WATCH' and not state.active_cap, 'CANARY_NATIVE_STRESS_RETAINS_WATCH')
    advance(shadow_drawdown=-.06)
    need(state.mode == 'WATCH', 'CANARY_STRICT_CLEAR_BOUNDARY')
    advance(shadow_drawdown=-.059)
    need(state.mode == 'NORMAL' and state.peak is None, 'CANARY_EPISODE_CLEAR')
    advance(True)
    advance()
    before = state.snapshot()
    current = (date.fromisoformat(before['last_session']) + timedelta(days=1)).isoformat()
    ob = observation()
    ob['session'] = current
    bad_inputs = [dict(shadow_nav=None), dict(shadow_nav=True), dict(shadow_nav=0.),
                  dict(shadow_drawdown=.01), dict(shadow_drawdown=-1.),
                  dict(shadow_r20=None), dict(damaged_breadth=float('nan')),
                  dict(green_breadth=1.01), dict(session='1999-01-01')]
    for changes in bad_inputs:
        try:
            state.step(session=current, observation={**ob, **changes}, native_stress=False)
        except ValueError:
            pass
        else:
            need(False, 'CANARY_INVALID_INPUT_REFUSAL')
        need(state.snapshot() == before, 'CANARY_INVALID_INPUT_NONMUTATION')
    for day in (before['last_session'], '1999-01-01', 'not-a-date'):
        try:
            state.step(session=day, observation={**ob, 'session': day}, native_stress=False)
        except ValueError:
            pass
        else:
            need(False, 'CANARY_ORDERED_CURSOR')
    corruptions = [dict(schema='ramp-free-native/1'), dict(policy_id=NO_EXTRA),
                   dict(mode='UNKNOWN'), dict(peak=None), dict(peak=True),
                   dict(healthy_count=True), dict(healthy_count=8),
                   dict(active_cap=False, healthy_count=1), dict(last_session=None)]
    for changes in corruptions:
        try:
            cls.from_snapshot({**before, **changes})
        except ValueError:
            pass
        else:
            need(False, 'CANARY_SNAPSHOT_REFUSAL')
    return checked


def _synthetic_panels():
    """Causal close-only panels; account-level gap charging is checked separately."""
    hosted()
    panels = {
        'smooth_recovery': [
            (100., True, .01, .50, .30), (100., False, .01, .50, .30),
            (102., False, .02, .40, .40), (104., False, .03, .35, .45),
            (106., False, .04, .30, .50)],
        'choppy_constructive_recovery': [
            (100., True, .01, .50, .30), (100., False, .01, .50, .30),
            (104., False, .02, .50, .30), (101., False, .01, .80, .10),
            (106., False, .03, .40, .40), (103., False, .01, .80, .10),
            (108., False, .04, .30, .50)],
        'already_held_gap': [
            (100., True, .01, .50, .30), (100., False, .01, .50, .30),
            (110., False, .02, .40, .40), (100., False, -.02, .80, .10)],
    }
    evidence, checked = {}, 0
    for name, observations in panels.items():
        watch, rows, flags, records = RecoveryWatch(), [], [], []
        for index, (nav, stress, r20, damage, green) in enumerate(observations):
            day = (date(2002, 1, 1) + timedelta(days=index)).isoformat()
            ob = dict(session=day, shadow_nav=nav, shadow_drawdown=-.20,
                      shadow_r20=r20, damaged_breadth=damage, green_breadth=green)
            result = watch.step(session=day, observation=ob, native_stress=stress)
            rows.append(dict(session=day, evidence=dict(observation=ob)))
            flags.append(stress)
            records.append(dict(session=day, nav=nav, ceiling=result['ceiling'], state=watch.snapshot()))
            checked += 1
        caps, snapshots = independent_watch(rows, flags)
        need(caps == [r['ceiling'] for r in records]
             and snapshots == [r['state'] for r in records], 'CANARY_SYNTHETIC_PANEL_EQUATIONS')
        if name != 'already_held_gap':
            need(all(r['ceiling'] == 1. for r in records), 'CANARY_CONSTRUCTIVE_RECOVERY_FULL')
        else:
            need(records[-2]['ceiling'] == 1. and records[-1]['ceiling'] == .55,
                 'CANARY_GAP_HAS_NO_PRIOR_CLOSE_PROTECTION')
        evidence[name] = records
    return checked, evidence


def canary(raw):
    hosted()
    retained = hold.canary(raw)
    checked = _watch_canary(RecoveryWatch)
    # These actual state-machine mutations must be rejected by the same oracle.
    mutations = (
        ('local_return <= RULE[\'peak_return\']', 'True'),
        ("r20 < RULE['entry_r20_below']", 'True'),
        ("damage >= RULE['entry_damage']", 'True'),
        ("green <= RULE['entry_green']", 'True'),
        ("self.healthy_count >= RULE['recovery_closes']", 'self.healthy_count >= 7'),
        ('self.peak = max(self.peak, nav)', 'self.peak = nav'),
        ('self.healthy_count + 1 if healthy else 0',
         'self.healthy_count + 1 if healthy else self.healthy_count'),
    )
    class_source = ast.unparse(next(n for n in ast.parse(Path(__file__).read_bytes()).body
                                   if isinstance(n, ast.ClassDef) and n.name == 'RecoveryWatch'))
    import sys
    module_values = sys.modules[__name__].__dict__
    for original, replacement in mutations:
        need(class_source.count(original) == 1, 'CANARY_EXACT_MUTATION_SITE')
        space = dict(module_values)
        exec(compile(class_source.replace(original, replacement), '<hosted-rw1-negative-mutant>', 'exec'), space)
        try:
            _watch_canary(space['RecoveryWatch'])
        except ValueError as error:
            need('CANARY_' in str(error), 'CANARY_MUTANT_FAILED_FOR_EXPECTED_ASSERTION')
        else:
            need(False, 'CANARY_MUTANT_ESCAPED')
    # Native flags for independent equations come from its own state equations.
    rows = []
    for i in range(35):
        day = (date(2001, 1, 1) + timedelta(days=i)).isoformat()
        ob = dict(session=day, shadow_nav=100. if i != 23 else 110., shadow_drawdown=-.20,
                  shadow_r5=.01, shadow_r10=.01, shadow_r20=.01 if i < 24 else -.01,
                  shadow_r40=.01, damaged_breadth=.50 if i < 24 else .80,
                  green_breadth=.30 if i < 24 else .10, damaged_breadth_delta5=0.,
                  spy_r20=.01, spy_vol_ratio=0., stops20=0)
        rows.append(dict(session=day, evidence=dict(observation=ob,
            recent_leadership=dict(recent_r20=.01, recent_r40=.01))))
    paths, expected = independent_targets(rows, profiles())
    actual, native = RecoveryWatch(), parent_module(raw, profiles()[1], PARENT_SHA).Native()
    keys = ('shadow_drawdown', 'shadow_r5', 'shadow_r10', 'shadow_r20', 'shadow_r40',
            'damaged_breadth', 'green_breadth', 'damaged_breadth_delta5', 'spy_r20',
            'spy_vol_ratio', 'stops20', 'shadow_nav')
    for i, row in enumerate(rows):
        ob = row['evidence']['observation']
        native.step(tuple(ob[key] for key in keys))
        stress = any(bool(getattr(native, key)) for key in ('ordinary', 'base_fast', 'fast', 'slow'))
        actual.step(session=row['session'], observation=ob, native_stress=stress)
        need(actual.snapshot() == expected[i], 'CANARY_INDEPENDENT_NATIVE_AND_WATCH')
        prefix, snapshots = independent_targets(rows[:i+1], profiles())
        need((prefix == paths[:, :i+1]).all() and snapshots == expected[:i+1], 'CANARY_PREFIX_CAUSALITY')
        checked += 2
    need(any(state['active_cap'] for state in expected), 'CANARY_INDEPENDENT_HAS_ENTRY')
    panel_checks, panel_evidence = _synthetic_panels()
    checked += panel_checks
    return {**retained, 'actual_synthetic_calls': retained['actual_synthetic_calls'] + checked,
            'rw1_lifecycle_and_strict_restore': True, 'rw1_negative_mutants_rejected': len(mutations),
            'independent_native_stress_and_watch_equal': True, 'rw1_prefix_causality': True,
            'synthetic_close_only_panels': panel_evidence,
            'already_held_gap_requires_separate_account_charge': True}
