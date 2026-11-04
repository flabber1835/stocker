"""Exhaustive canonical recovery partitions; never choose an uncertain branch."""
import ast
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import hashlib
import json
import math
import operator
from pathlib import Path
from typing import Literal

from pydantic import Field
from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth
from system_campaign_uncertainty_input import LeadershipUncertaintyInput, InputCodec
from system_campaign_uncertainty_context import (
    SensorCertificate, SID, DAY, DISCRETE, discrete, encoded, digest,
)
from system_campaign_uncertainty_review import committed_rows

HERE = Path(__file__).parent
SCHEMA = 'research.leadership-branch-uncertainty-certificate/1'
WATCH = 'research.leadership-branch-uncertainty-commitment/1'
INPUT = 'research.leadership-branch-uncertainty-input/1'
TREATMENT = 'ALL_REACHABLE_CANONICAL_DECISIONS_MUST_BE_IDENTICAL'
CONTRACT = 'system-campaign-financial-branch-contract.json'
MAX_STATES, MAX_PARTITIONS = 256, 64


class Split(Exception):
    def __init__(self, key, threshold, relation):
        self.key, self.threshold, self.relation = key, threshold, relation


class Scalar(float):
    def __new__(cls, value, interval, key, checks):
        need(interval.contains(value), 'BRANCH_REPRESENTATIVE_IN_SUBDOMAIN')
        obj = float.__new__(cls, value)
        obj.interval, obj.key, obj.checks = interval, key, checks
        return obj

    def compare(self, other, relation):
        need(type(other) in (int, float) and math.isfinite(other), 'BRANCH_FINITE_POINT_THRESHOLD')
        fn = {'gt': operator.gt, 'ge': operator.ge, 'lt': operator.lt, 'le': operator.le}[relation]
        lo, hi = fn(self.interval.lo, other), fn(self.interval.hi, other)
        if lo != hi:
            raise Split(self.key, other, relation)
        self.checks.append(dict(key=self.key, interval=self.interval.pair(), relation=relation, threshold=other, result=lo))
        return lo

    def __gt__(self, other): return self.compare(other, 'gt')
    def __ge__(self, other): return self.compare(other, 'ge')
    def __lt__(self, other): return self.compare(other, 'lt')
    def __le__(self, other): return self.compare(other, 'le')


def split_domain(interval, threshold, relation):
    # Domains cover every finite binary64 value, including the exact threshold.
    converted = float(threshold)
    need(math.isfinite(converted) and converted == threshold, 'BRANCH_EXACT_BINARY64_POINT_THRESHOLD')
    threshold = converted
    low = threshold if relation in ('gt', 'le') else math.nextafter(threshold, -math.inf)
    high = math.nextafter(threshold, math.inf) if relation in ('gt', 'le') else threshold
    rows = [(interval.lo, min(interval.hi, low)), (max(interval.lo, high), interval.hi)]
    result = [Interval(a, b) for a, b in rows if a <= b]
    need(len(result) == 2 and result[0].lo == interval.lo and result[-1].hi == interval.hi
         and math.nextafter(result[0].hi, math.inf) == result[1].lo,
         'BRANCH_EXHAUSTIVE_DISJOINT_BINARY64_SPLIT')
    return result


def partitions(function, kwargs, bounds):
    queue, leaves = [dict(bounds)], []
    while queue:
        need(len(queue) + len(leaves) <= MAX_PARTITIONS, 'BRANCH_PARTITION_BOUND_NO_TRUNCATION')
        domain = queue.pop(0)
        supplied, plain, checks = deepcopy(kwargs), deepcopy(kwargs), []
        for key, interval in domain.items():
            need((kwargs[key] is None) == (interval is None), 'BRANCH_INPUT_AVAILABILITY')
            if interval is not None:
                value = min(max(float(kwargs[key]), interval.lo), interval.hi)
                supplied[key] = Scalar(value, interval, key, checks)
                plain[key] = value
        before = encoded(supplied['state'])
        try:
            result = function(**supplied)
        except Split as split:
            need(encoded(supplied['state']) == before, 'BRANCH_ALTERNATIVE_INPUT_NOT_MUTATED')
            pieces = split_domain(domain[split.key], split.threshold, split.relation)
            queue[:0] = [{**domain, split.key: piece} for piece in pieces]
            continue
        need(encoded(supplied['state']) == before, 'BRANCH_ALTERNATIVE_INPUT_NOT_MUTATED')
        ordinary = function(**plain)
        need(encoded(plain['state']) == before and encoded(result) == encoded(ordinary),
             'BRANCH_COMPLETE_SUBDOMAIN_CANONICAL_EQUALITY')
        leaves.append(dict(domains={k: v.pair() if v is not None else None for k, v in domain.items()},
                           comparisons=checks, state=ordinary[0], decision=ordinary[1]))
    need(leaves, 'BRANCH_NONEMPTY_COMPLETE_PARTITION')
    return leaves


def cloud(function, kwargs, bounds, possible=None):
    need(all((kwargs[k] is None) == (v is None) and (v is None or v.contains(kwargs[k]))
             for k, v in bounds.items()), 'BRANCH_ACTUAL_INPUT_IN_COMPLETE_ADMITTED_DOMAIN')
    actual_before = discrete(kwargs['state'])
    states = deepcopy(possible) if possible is not None else [actual_before]
    need(0 < len(states) <= MAX_STATES and digest(actual_before) in {digest(v) for v in states}
         and len({digest(v) for v in states}) == len(states), 'BRANCH_COMPLETE_PRIOR_SET_INCLUDES_ACTUAL')
    actual_args = deepcopy(kwargs)
    actual = function(**actual_args)
    need(encoded(actual_args['state']) == encoded(kwargs['state']), 'BRANCH_ACTUAL_PRIOR_UNCHANGED')
    outside = {k: v for k, v in actual[0].items() if k not in DISCRETE}
    need(encoded(outside) == encoded({k: v for k, v in kwargs['state'].items() if k not in DISCRETE}),
         'BRANCH_CANONICAL_RECOVERY_ONLY_DECLARED_FIELDS')
    next_states, evidence = {}, []
    for prior in states:
        need(set(prior) == set(DISCRETE), 'BRANCH_EXACT_POSSIBLE_RECOVERY_FIELDS')
        args = deepcopy(kwargs)
        args['state'].update(prior)
        for leaf in partitions(function, args, bounds):
            need(encoded(leaf['decision']) == encoded(actual[1]), 'BRANCH_FINANCIAL_DECISION_DIFFERS')
            need(encoded({k: v for k, v in leaf['state'].items() if k not in DISCRETE}) == encoded(outside),
                 'BRANCH_ALL_OTHER_STATE_FIELDS_IDENTICAL')
            after = discrete(leaf['state'])
            next_states[digest(after)] = after
            need(len(next_states) <= MAX_STATES, 'BRANCH_STATE_BOUND_NO_TRUNCATION')
            evidence.append(dict(before=prior, after=after, domains=leaf['domains'],
                                 comparisons=leaf['comparisons'], decision=leaf['decision']))
    following = [next_states[k] for k in sorted(next_states)]
    need(digest(discrete(actual[0])) in next_states, 'BRANCH_COMPLETE_NEXT_SET_INCLUDES_ACTUAL')
    return actual, following, evidence


def qualify_surface(frozen_source, champion_source):
    tree = ast.parse(frozen_source)
    limit, = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'LDRC_R20' for t in n.targets)]
    need(type(limit) is float and limit == -.085, 'BRANCH_EXACT_FROZEN_POINT_THRESHOLD')
    step, = [n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'CandidateA'
             for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'step']
    parents = {child: parent for parent in ast.walk(step) for child in ast.iter_child_nodes(parent)}
    uses = 0
    for node in ast.walk(step):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load) or node.id not in ('recent_r20', 'recent_r40'):
            continue
        parent = parents[node]
        allowed = (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
                   and parent.func.id == 'finite' and parent.args == [node] and not parent.keywords)
        allowed |= (isinstance(parent, ast.Compare) and parent.left is node and len(parent.ops) == 1
                    and isinstance(parent.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE))
                    and (isinstance(parent.comparators[0], ast.Constant)
                         or isinstance(parent.comparators[0], ast.Name) and parent.comparators[0].id in ('wc_r20', 'LDRC_R20')
                         or isinstance(parent.comparators[0], ast.UnaryOp) and isinstance(parent.comparators[0].op, ast.USub)
                            and isinstance(parent.comparators[0].operand, ast.Constant)))
        need(allowed, 'BRANCH_ONLY_QUALIFIED_FINITE_CHECKS_AND_POINT_COMPARISONS')
        uses += 1
    recover, = [n for n in ast.parse(champion_source).body if isinstance(n, ast.FunctionDef) and n.name == 'recover']
    wrapper_parents = {child: parent for parent in ast.walk(recover) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(recover):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in ('recent_r20', 'recent_r40'):
            parent = wrapper_parents[node]
            index = 3 if node.id == 'recent_r20' else 4
            need(isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                 and isinstance(parent.func.value, ast.Name) and parent.func.value.id == 'candidate'
                 and parent.func.attr == 'step' and len(parent.args) == 7 and parent.args[index] is node,
                 'BRANCH_RECOVERY_ONLY_FORWARDS_UNCERTAIN_INPUTS')
    updates = [n for n in ast.walk(recover) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == 'result' and n.func.attr == 'update']
    need(uses == 10 and len(updates) == 1 and not updates[0].args
         and {k.arg for k in updates[0].keywords} == set(DISCRETE) - {'version'},
         'BRANCH_EXACT_FROZEN_COMPARISON_AND_RECOVERY_WRITE_SURFACE')


class BranchInput(LeadershipUncertaintyInput):
    schema_id: Literal['research.leadership-branch-uncertainty-input/1'] = Field(alias='schema')
    treatment: Literal['ALL_REACHABLE_CANONICAL_DECISIONS_MUST_BE_IDENTICAL']


def evidence(root):
    from system_campaign_uncertainty_facts import evidence as strict_evidence
    result = strict_evidence(root)
    result.append(dict(reference='research:system-optimization-002/branch-uncertainty/contract/1',
        description='Distinct exhaustive financial-invariance contract; original strict comparison contract is retained separately.',
        sha256=hashlib.sha256((HERE / CONTRACT).read_bytes()).hexdigest()))
    result.append(dict(reference='research:system-optimization-002/branch-uncertainty/implementation/1',
        description='Complete canonical branch partitions and possible-state propagation, with independent review.',
        sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    return result


def parse(path, *, resume_session, predecessor_checkpoint_sha256, expected_evidence):
    raw = Path(path).read_bytes()
    need(len(raw) <= 65536, 'BRANCH_TYPED_INPUT_SIZE')
    obj = BranchInput.model_validate_json(raw)
    need(type(resume_session) is str and date.fromisoformat(resume_session).isoformat() == resume_session
         and resume_session < obj.session and obj.predecessor_checkpoint_sha256 == predecessor_checkpoint_sha256,
         'BRANCH_EXACT_UNCONSUMED_OWN_TYPED_PREDECESSOR')
    actual = [v.model_dump() for v in obj.source_evidence]
    need(actual == expected_evidence and len({v['reference'] for v in actual}) == len(actual),
         'BRANCH_EXACT_BOUND_EVIDENCE')
    obj._file_sha256 = hashlib.sha256(raw).hexdigest()
    obj._resume_session = resume_session
    return obj


class Codec(InputCodec):
    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes()).get('schema') != INPUT:
            return super().load(path, resume_session=resume_session, predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj = parse(path, resume_session=resume_session, predecessor_checkpoint_sha256=predecessor_checkpoint_sha256,
                    expected_evidence=self.evidence)
        self.objects.append(obj)
        return obj


def overlay(cp, root):
    need(cp['source_cursor'] < DAY, 'BRANCH_UNCONSUMED_OWN_INPUT_BOUNDARY')
    value = dict(schema=INPUT, predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'], session=DAY,
        security_id=SID, sensor_only=True, require_unowned_and_unordered=True,
        consideration_range='18<=cash_plus_nontransferable_right<=20', treatment=TREATMENT, source_evidence=evidence(root))
    path = root / 'branch-uncertainty-input.json'
    save(path, value)
    return path


class Certificate(SensorCertificate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chain, self.possible = digest(SCHEMA), None

    def __enter__(self):
        qualify_surface(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes(),
                        Path('/variant/sentinel/controller/champion.py').read_bytes())
        value = super().__enter__()
        if self.seed:
            self.possible = deepcopy(self.seed[-1]['possible_after'])
        return value

    def recover(self, **kwargs):
        if self.math is None:
            return self.original_recover(**kwargs)
        prior = deepcopy(self.possible) if self.possible is not None else [discrete(kwargs['state'])]
        try:
            (state, decision), following, leaves = cloud(self.original_recover, kwargs, self.bounds, prior)
        except ValueError as error:
            save(self.out / 'branch-uncertainty-refusal.json', dict(session=kwargs['state']['last_session'],
                error=str(error), financial_session_committed=False, possible_before=prior,
                intervals={k: v.pair() if v is not None else None for k, v in self.bounds.items()}))
            raise
        self.possible = following
        self.pending = dict(schema=SCHEMA, session=kwargs['state']['last_session'], material=self.material,
            math=self.math.snapshot(), intervals={k: v.pair() if v is not None else None for k, v in self.bounds.items()},
            before=discrete(kwargs['state']), after=discrete(state), possible_before=prior, possible_after=following,
            branches=leaves, decision=decision,
            scalar_inputs={k: kwargs[k] for k in ('native', 'wc_drawdown', 'spy_r20', 'wc_r20', 'recent_r20', 'recent_r40')},
            every_reachable_canonical_decision_identical=True, representative_is_not_a_valuation=True,
            owned_position=False, pending_order=False)
        if self.pending['session'] == DAY:
            self.pending['event_basis'] = deepcopy(self.event_basis)
        return state, decision

    def append(self, journal, name, record):
        if name in ('formation', 'daily') and record['session'] >= DAY:
            need(self.pending is not None and record['session'] == self.pending['session']
                 and record['state_sha256'] == self.pending['next_state_sha256']
                 and record['input_sha256'] == self.pending['input_sha256'], 'BRANCH_EXACT_FINANCIAL_ROW')
            need(self.last_session is None or self.last_session < record['session'], 'BRANCH_STRICT_CERTIFICATE_AXIS')
            self.chain = digest(dict(previous=self.chain, record=self.pending))
            self.stream.write(encoded({**self.pending, 'chain_sha256': self.chain}) + b'\n')
            import os
            self.stream.flush(); os.fsync(self.stream.fileno())
            self.original_append(journal, 'watch', dict(schema=WATCH, session=record['session'], input_sha256=record['input_sha256'],
                next_state_sha256=record['state_sha256'], certificate_chain_sha256=self.chain))
            self.rows += 1
            self.last_session, self.pending = record['session'], None
        return self.original_append(journal, name, record)


def qualify(out, hashes):
    hosted()
    from sentinel.controller import median5, champion_config
    for n, h in hashes.items():
        need(hashlib.sha256((Path('/variant') / n).read_bytes()).hexdigest() == h, 'BRANCH_EXACT_QUALIFIED_CONTROLLER_SOURCE')
    qualify_surface(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes(),
                    Path('/variant/sentinel/controller/champion.py').read_bytes())
    state = median5.fresh(champion=True)
    state.update(full_streak=1)
    args = dict(state=state, native=1., wc_drawdown=-.05, recent_r20=-.0007, recent_r40=-.03, spy_r20=.02, wc_r20=.01)
    bounds = dict(recent_r20=Interval(-.001, .001), recent_r40=Interval.point(-.03))
    (actual, decision), possible, _ = cloud(champion_config.recover, args, bounds)
    need(len(possible) == 2 and decision == dict(desired_allocation=1., reason='NORMAL'), 'BRANCH_ACTUAL_AMBIGUOUS_BUT_IDENTICAL_DECISIONS')
    args['state'] = actual
    args['recent_r20'] = -.02
    (_, _), merged, _ = cloud(champion_config.recover, args,
        dict(recent_r20=Interval.point(-.02), recent_r40=Interval.point(-.03)), possible)
    need(len(merged) == 1, 'BRANCH_ACTUAL_COMPLETE_COUNTER_STATE_MERGE')
    bad = median5.fresh(champion=True)
    bad.update(episode=True, full_streak=7)
    try:
        cloud(champion_config.recover, dict(args, state=bad, recent_r20=-.0007), bounds)
    except ValueError as error:
        need('BRANCH_FINANCIAL_DECISION_DIFFERS' in str(error), 'BRANCH_ACTUAL_DIVERGENT_DECISION_REFUSAL_REASON')
    else:
        raise ValueError('REFUSED_BRANCH_ACTUAL_DIVERGENT_DECISION_ACCEPTED')
    save(out / 'branch-controller-qualification.json', dict(passed=True, exact_controller_sources=hashes,
        ambiguous_comparisons_exhaustively_partitioned=True, all_possible_counters_retained_and_later_merged=True,
        actual_divergent_decisions_refused=True, historical_financial_sessions_advanced=0))


def validate_input(root, cp):
    found = []
    for descriptor in cp['repairs']:
        path = root / 'book/repairs' / descriptor['filename']
        raw = path.read_bytes()
        need(hashlib.sha256(raw).hexdigest() == descriptor['sha256'], 'BRANCH_ALL_RETAINED_INPUT_BYTES')
        schema = json.loads(raw)['schema']
        need(schema in ('terminal-repair/1', INPUT), 'BRANCH_NO_UNSELECTED_MODEL_SCHEMA')
        if schema != INPUT:
            continue
        obj = parse(path, resume_session=descriptor['resume_session'],
                    predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'], expected_evidence=evidence(root))
        need(obj.sha256 == descriptor['sha256'] and descriptor['filename'] == obj.sha256 + '.json',
             'BRANCH_EXACT_ACTUALLY_COMMITTED_TYPED_INPUT')
        found.append(obj.sha256)
    need(len(found) == 1, 'BRANCH_EXACTLY_ONE_SELECTED_MODEL')
    return found[0]


def seed(root, cp):
    financial = [r for n in ('formation', 'daily') for r in committed_rows(root / 'book', cp, n) if r['session'] >= DAY]
    watches = [r for r in committed_rows(root / 'book', cp, 'watch') if r.get('schema') == WATCH]
    chain, rows = digest(SCHEMA), []
    path = root / 'uncertainty-certificate.jsonl'
    if path.exists():
        for raw in path.read_bytes().splitlines(keepends=True):
            row = json.loads(raw)
            if row['session'] > cp['source_cursor']:
                break
            need(raw == encoded(row) + b'\n', 'BRANCH_EXACT_CANONICAL_CERTIFICATE_BYTES')
            payload = {k: v for k, v in row.items() if k != 'chain_sha256'}
            chain = digest(dict(previous=chain, record=payload))
            need(row['schema'] == SCHEMA and row['chain_sha256'] == chain, 'BRANCH_COMPLETE_CERTIFICATE_CHAIN')
            rows.append(row)
    need(len(rows) == len(financial) == len(watches), 'BRANCH_COMPLETE_COMMITTED_PROOF_AXIS')
    for row, fin, watch in zip(rows, financial, watches):
        need(row['session'] == fin['session'] == watch['session']
             and row['next_state_sha256'] == fin['state_sha256'] == watch['next_state_sha256']
             and row['input_sha256'] == fin['input_sha256'] == watch['input_sha256']
             and row['chain_sha256'] == watch['certificate_chain_sha256'], 'BRANCH_EXACT_FINANCIAL_WATCH_AND_PROOF_IDENTITY')
    return rows


def review(root, output):
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5, champion_config
    from system_campaign_uncertainty_archive import resolve
    from system_campaign_uncertainty_input import require_no_financial_position
    from fractions import Fraction
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    qualified = json.loads((root / 'branch-controller-qualification.json').read_bytes())
    hashes = qualified['exact_controller_sources']
    need(qualified['passed'] is True and len(hashes) == 6
         and all(cp['base']['sources'].get(n) == h
                 and hashlib.sha256((Path('/variant') / n).read_bytes()).hexdigest() == h for n, h in hashes.items()),
         'BRANCH_REVIEW_EXACT_QUALIFIED_PHYSICAL_CONTROLLER_SOURCES')
    qualify_surface(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes(),
                    Path('/variant/sentinel/controller/champion.py').read_bytes())
    validate_input(root, cp)
    rows = seed(root, cp)
    if not rows:
        need(cp['source_cursor'] < DAY, 'BRANCH_UNPROVED_EVENT_NOT_ADMITTED')
        save(output, dict(status='PRE_EVENT_PREFIX_ONLY', rows=0, economic_invariance_established=False))
        return
    path, resolution = resolve(root)
    before = journal.read_checkpoint(path)['run']['state']
    from types import SimpleNamespace
    require_no_financial_position(SimpleNamespace(wealth_core=before['wealth_core'], pending=before['pending']))
    event_source = json.loads((root / 'hydrated-uncertainty-event.json').read_bytes())
    native = json.loads((root / 'hydrated-alder-unresolved-date.json').read_bytes())['actual_native']
    math_state = RollingWitnessBounds(before['median5']['witness_nav'])
    possible, representative = [discrete(before['median5'])], discrete(before['median5'])
    financial = {r['session']: r for n in ('formation', 'daily') for r in committed_rows(root / 'book', cp, n)}
    total, maximum = 0, 1
    for index, row in enumerate(rows):
        need(row['before'] == representative and row['possible_before'] == possible
             and row['every_reachable_canonical_decision_identical'] is True
             and row['representative_is_not_a_valuation'] is True
             and row['owned_position'] is row['pending_order'] is False, 'BRANCH_INDUCTIVE_COMPLETE_PRIOR_SET')
        material = row['material']['rows']
        names = [r['security_id'] for r in material]
        need(len(names) == len(set(names)), 'BRANCH_UNIQUE_PRIOR_WITNESS_MEMBERS')
        if index == 0:
            need(row['session'] == DAY and names == before['median5']['selected']
                 and all(r['prior'] == before['median5']['selected_closes'][r['security_id']] for r in material),
                 'BRANCH_EXACT_ACTUAL_EVENT_WITNESS_PREIMAGE')
            event = row['event_basis']
            anchor = before['feed']['series'][SID]['signal_basis_anchor']
            need(event['source_term_sha256'] == digest({**native, 'session': DAY})
                 and event['source_event_sha256'] == digest(event_source)
                 and [event['prior_session'], event['raw_anchor'], event['signal_anchor']] == [anchor[0], str(anchor[1]), str(anchor[2])]
                 and Fraction(event['split']) == Fraction(event_source['split_ratio']), 'BRANCH_EXACT_FROZEN_EVENT_AND_PRIOR_BASIS')
            raw, signal, split = map(Fraction, (event['raw_anchor'], event['signal_anchor'], event['split']))
            need(raw > 0 and signal > 0 and split > 0, 'BRANCH_POSITIVE_EVENT_PRICE_BASIS')
            actual, = [r for r in material if r['security_id'] == SID]
            need(actual['current'] == event['signal_consideration_interval'] == [float(18 * split * signal / raw), float(20 * split * signal / raw)],
                 'BRANCH_ENTIRE_FACTUAL_CONSIDERATION_RANGE_ENCLOSED')
        returns = []
        for item in material:
            bound = Interval(*item['current'])
            need(row['session'] == DAY and item['security_id'] == SID or bound.lo == bound.hi,
                 'BRANCH_ONLY_DECLARED_EVENT_MAY_VARY')
            returns.append(bound.div(Interval.point(item['prior'])).sub(Interval.point(1.)))
        factor = growth(returns)
        need(factor.pair() == row['material']['factor'], 'BRANCH_INDEPENDENT_ACTUAL_OPERATION_ORDER')
        math_state.advance(factor, row['material']['representative_nav'])
        bounds = {f'recent_r{n}': math_state.period(n) for n in (20, 40)}
        need(math_state.snapshot() == row['math']
             and {k: v.pair() if v is not None else None for k, v in bounds.items()} == row['intervals'],
             'BRANCH_EVERY_ROUNDING_AWARE_MATH_CONTINUATION')
        state = median5.fresh(champion=True)
        state.update(row['before']); state['last_session'] = row['session']
        kwargs = dict(row['scalar_inputs'], state=state)
        need(all(kwargs[k] == row['material']['observed'][k] for k in bounds), 'BRANCH_ACTUAL_OBSERVED_SCALARS')
        (after, decision), following, leaves = cloud(champion_config.recover, kwargs, bounds, possible)
        need(discrete(after) == row['after'] and following == row['possible_after'] and leaves == row['branches']
             and decision == row['decision'], 'BRANCH_INDEPENDENT_EXHAUSTIVE_STATES_AND_DECISIONS')
        fin = financial[row['session']]
        need(fin['decision']['ldrc'] == decision and fin['decision']['native_target_core_exposure'] == kwargs['native'],
             'BRANCH_EXACT_ACTUAL_FINANCIAL_CONTROLLER_DECISION')
        possible, representative = following, discrete(after)
        total += len(leaves); maximum = max(maximum, len(possible))
    need(representative == discrete(cp['run']['state']['median5'])
         and math_state.absolute.contains(cp['run']['state']['median5']['witness_nav'][-1]), 'BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE')
    save(output, dict(schema='research.leadership-branch-uncertainty-independent-review/1',
        status='COMMITTED_PREFIX_ALL_REACHABLE_DECISIONS_IDENTICAL', rows=len(rows), exhaustive_leaves=total,
        maximum_possible_states=maximum, checkpoint_sha256=cp['sha256'], through=cp['source_cursor'],
        every_actual_financial_watch_and_proof_identity_bound=True, every_reachable_decision_identical=True,
        all_possible_controller_states_retained=True, representative_is_not_a_valuation=True,
        full_period_complete=cp['completed'] == 2156))
    save(output.parent / 'branch-uncertainty-archive-resolution.json', resolution)
