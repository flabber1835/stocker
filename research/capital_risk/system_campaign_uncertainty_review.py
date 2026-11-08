"""Hosted certificate replay against committed financial/watch identities."""
import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_uncertainty_context import DAY, SID, SCHEMA, WATCH_SCHEMA, digest, discrete, encoded
from system_campaign_uncertainty_gate import certified_recovery
from system_campaign_uncertainty_input import require_no_financial_position, parse
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth


def committed_rows(book, cp, name):
    with (book / (name + '.jsonl')).open('rb') as stream:
        raw = stream.read(cp['journals'][name]['bytes'])
    need(hashlib.sha256(raw).hexdigest() == cp['journals'][name]['prefix_sha256'],
         'UNCERTAINTY_CANONICAL_JOURNAL_PREFIX')
    return [json.loads(line) for line in raw.splitlines()]


def seed(root, cp):
    """Validate the whole selected certificate prefix and return its exact rows."""
    path = root / 'uncertainty-certificate.jsonl'
    financial = [r for n in ('formation', 'daily') for r in committed_rows(root / 'book', cp, n)
                 if r['session'] >= DAY]
    watches = [r for r in committed_rows(root / 'book', cp, 'watch') if r.get('schema') == WATCH_SCHEMA]
    if not path.exists():
        need(not financial and not watches, 'UNCERTAINTY_MISSING_COMMITTED_CERTIFICATE')
        return []
    raw_rows = path.read_bytes().splitlines(keepends=True)
    rows = []
    chain = digest(SCHEMA)
    for raw in raw_rows:
        row = json.loads(raw)
        if row['session'] > cp['source_cursor']:
            break
        need(raw == encoded(row) + b'\n', 'UNCERTAINTY_EXACT_CANONICAL_CERTIFICATE_BYTES')
        payload = {k: v for k, v in row.items() if k != 'chain_sha256'}
        chain = digest(dict(previous=chain, record=payload))
        need(row['schema'] == SCHEMA and row['chain_sha256'] == chain, 'UNCERTAINTY_ORIGINAL_CERTIFICATE_CHAIN')
        rows.append(row)
    need(len(rows) == len(financial) == len(watches), 'UNCERTAINTY_COMPLETE_COMMITTED_CERTIFICATE_AXIS')
    for row, fin, watch in zip(rows, financial, watches):
        need(row['session'] == fin['session'] == watch['session']
             and row['next_state_sha256'] == fin['state_sha256'] == watch['next_state_sha256']
             and row['input_sha256'] == fin['input_sha256'] == watch['input_sha256']
             and row['chain_sha256'] == watch['certificate_chain_sha256'],
             'UNCERTAINTY_WATCH_AND_FINANCIAL_EXACT_COMMITMENT')
    return rows


def preserve_and_seed(old, out, cp):
    rows = seed(old, cp)
    source = old / 'uncertainty-certificate.jsonl'
    if source.exists():
        raw = source.read_bytes();prefix = b''.join(encoded(r) + b'\n' for r in rows)
        need(raw.startswith(prefix), 'UNCERTAINTY_ORIGINAL_FULL_PREFIX')
        target = out / 'lineage/uncertainty-certificate-original.jsonl'
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        save(out / 'uncertainty-prefix-preservation.json', dict(
            original_bytes=len(raw), original_sha256=hashlib.sha256(raw).hexdigest(),
            committed_prefix_bytes=len(prefix), committed_prefix_sha256=hashlib.sha256(prefix).hexdigest(),
            unsent_tail_bytes=len(raw) - len(prefix), unsent_tail_sha256=hashlib.sha256(raw[len(prefix):]).hexdigest(),
            selected_outer_sha256=cp['sha256'], original_whole_stream_preserved=True))
    return rows


def validate_input_commitment(root, cp):
    from system_campaign_uncertainty_facts import evidence
    matches = []
    for descriptor in cp['repairs']:
        path = root / 'book/repairs' / descriptor['filename']
        raw = path.read_bytes()
        need(hashlib.sha256(raw).hexdigest() == descriptor['sha256'], 'UNCERTAINTY_ALL_RETAINED_INPUT_BYTES')
        if json.loads(raw)['schema'] != 'research.leadership-uncertainty-input/1':
            continue
        obj = parse(path, resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'], expected_evidence=evidence(root))
        need(obj.sha256 == descriptor['sha256'] and descriptor['filename'] == obj.sha256 + '.json',
             'UNCERTAINTY_RETAINED_EXACT_MODEL_INPUT_DESCRIPTOR')
        matches.append(obj.sha256)
    need(len(matches) == 1, 'UNCERTAINTY_ONE_COMMITTED_MODEL_CONTRACT')
    return matches[0]


def review(root, output):
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5, champion_config
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    validate_input_commitment(root, cp)
    rows = seed(root, cp)
    if not rows:
        need(cp['source_cursor'] < DAY, 'UNCERTAINTY_UNPROVED_EVENT_NOT_ADMITTED')
        save(output, dict(status='PRE_EVENT_PREFIX_ONLY', rows=0, economic_invariance_established=False))
        return
    before_event = journal.read_checkpoint(root / 'book/pre-event/2019-10-22.json.gz')
    need(before_event['source_cursor'] == '2019-10-21', 'UNCERTAINTY_ACTUAL_PRE_EVENT_CHECKPOINT')
    original_state = before_event['run']['state']
    event_source = json.loads((root / 'hydrated-uncertainty-event.json').read_bytes())
    native = json.loads((root / 'hydrated-alder-unresolved-date.json').read_bytes())['actual_native']
    moved = {**native, 'session': DAY}
    require_no_financial_position(SimpleNamespace(wealth_core=original_state['wealth_core'], pending=original_state['pending']))
    math_state = RollingWitnessBounds(original_state['median5']['witness_nav'])
    previous = discrete(original_state['median5'])
    financial = {r['session']: r for n in ('formation', 'daily') for r in committed_rows(root / 'book', cp, n)}
    comparisons = 0
    for index, row in enumerate(rows):
        need(row['before'] == previous and row['representative_is_not_a_valuation']
             and row['owned_position'] is False and row['pending_order'] is False,
             'UNCERTAINTY_INDUCTIVE_SAME_DISCRETE_STATE')
        material = row['material']['rows'];names = [r['security_id'] for r in material]
        need(len(names) == len(set(names)), 'UNCERTAINTY_UNIQUE_PRIOR_WITNESS_MEMBERS')
        if index == 0:
            need(row['session'] == DAY and names == original_state['median5']['selected']
                 and all(r['prior'] == original_state['median5']['selected_closes'][r['security_id']] for r in material),
                 'UNCERTAINTY_ACTUAL_EVENT_WITNESS_PREIMAGE')
            event = row['event_basis']
            need(event['source_term_sha256'] == digest(moved)
                 and event['source_event_sha256'] == digest(event_source)
                 and Fraction(event['split']) == Fraction(event_source['split_ratio']),
                 'UNCERTAINTY_EXACT_ADMITTED_NATIVE_AND_FROZEN_SPLIT')
            anchor = original_state['feed']['series'][SID]['signal_basis_anchor']
            need([event['prior_session'], event['raw_anchor'], event['signal_anchor']] ==
                 [anchor[0], str(anchor[1]), str(anchor[2])], 'UNCERTAINTY_EXACT_EVENT_PRICE_BASIS')
            raw, signal, split = map(Fraction, (event['raw_anchor'], event['signal_anchor'], event['split']))
            need(raw > 0 and signal > 0 and split > 0, 'UNCERTAINTY_EVENT_PRICE_BASIS_POSITIVE')
            expected = [float(18 * split * signal / raw), float(20 * split * signal / raw)]
            actual_event, = [r for r in material if r['security_id'] == SID]
            need(actual_event['current'] == event['signal_consideration_interval'] == expected,
                 'UNCERTAINTY_ENTIRE_CONTRACTUAL_RANGE_ENCLOSED')
        returns = []
        for item in material:
            bound = Interval(*item['current'])
            need(row['session'] == DAY and item['security_id'] == SID or bound.lo == bound.hi,
                 'UNCERTAINTY_ONLY_DECLARED_EVENT_CAN_VARY')
            returns.append(bound.div(Interval.point(item['prior'])).sub(Interval.point(1.)))
        factor = growth(returns)
        need(factor.pair() == row['material']['factor'], 'UNCERTAINTY_INDEPENDENT_ACTUAL_OPERATION_ORDER')
        math_state.advance(factor, row['material']['representative_nav'])
        need(math_state.snapshot() == row['math'], 'UNCERTAINTY_EVERY_PERSISTED_MATH_CONTINUATION')
        bounds = {f'recent_r{n}': math_state.period(n) for n in (20, 40)}
        need({k: v.pair() if v is not None else None for k, v in bounds.items()} == row['intervals'],
             'UNCERTAINTY_EVERY_ROUNDING_AWARE_RETURN_INTERVAL')
        state = median5.fresh(champion=True)
        state.update(row['before']);state['last_session'] = row['session']
        kwargs = dict(row['scalar_inputs'], state=state)
        for key in bounds:
            need(kwargs[key] == row['material']['observed'][key], 'UNCERTAINTY_ACTUAL_OBSERVED_SCALAR')
        (after, decision), checks = certified_recovery(champion_config.recover, kwargs, bounds)
        need(checks == row['comparisons'] and discrete(after) == row['after'] and decision == row['decision'],
             'UNCERTAINTY_ACTUAL_CANONICAL_DISCRETE_TRANSITION_AND_ALL_COMPARISONS')
        actual = financial[row['session']]
        need(actual['decision']['ldrc'] == decision
             and actual['decision']['native_target_core_exposure'] == kwargs['native'],
             'UNCERTAINTY_ACTUAL_FINANCIAL_CONTROLLER_DECISION')
        comparisons += len(checks)
        previous = discrete(after)
    need(previous == discrete(cp['run']['state']['median5'])
         and math_state.absolute.contains(cp['run']['state']['median5']['witness_nav'][-1]),
         'UNCERTAINTY_EXACT_CURRENT_CANONICAL_STATE')
    save(output, dict(schema='research.leadership-uncertainty-independent-review/1',
        status='COMMITTED_PREFIX_INTERVAL_INVARIANT', rows=len(rows), comparisons=comparisons,
        through=cp['source_cursor'], checkpoint_sha256=cp['sha256'],
        every_committed_watch_and_financial_row_bound=True, every_actual_comparison_invariant=True,
        every_discrete_controller_state_equal=True, witness_valuation_unique=False,
        financial_path_invariant_over_declared_sensor_interval=True, full_period_complete=cp['completed'] == 2156,
        no_owned_cvr_accounting_supported=True, representative_is_not_a_valuation=True))
