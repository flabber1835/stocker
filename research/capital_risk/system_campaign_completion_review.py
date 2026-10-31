"""Independently continue the exact authenticated post-ZGNX certificate prefix."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha
from system_campaign_uncertainty_context import discrete
from system_campaign_uncertainty_review import committed_rows, seed
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth
from system_campaign_uncertainty_gate import certified_recovery
from system_campaign_completion_scope import review_guards, require_absent
from system_campaign_completion_facts import contract, PRIVATE
from system_campaign_completion_basis import validate


def parent_review(old, cp, spec):
    raw = (old / 'uncertainty-certificate-review.json').read_bytes(); proof = json.loads(raw)
    need(cp['sha256'] == spec['outer_sha256'] and cp['source_cursor'] == '2022-09-30'
         and cp['completed'] == 1196 and len(cp['repairs']) == 27,
         'COMPLETION_EXACT_ACTUAL_SEPTEMBER_PARENT')
    need(sha(raw) == spec['interval_review_sha256'] and proof['checkpoint_sha256'] == cp['sha256']
         and proof['rows'] == 742 and proof['comparisons'] == 1375
         and proof['every_actual_comparison_invariant'] is True
         and proof['every_committed_watch_and_financial_row_bound'] is True
         and proof['every_discrete_controller_state_equal'] is True
         and proof['no_owned_cvr_accounting_supported'] is True
         and proof['event_resolution'] is not None,
         'COMPLETION_EXACT_AUTHENTICATED_TWO_EVENT_PARENT_PROOF')
    return raw, proof


def preserve_parent_event(old, out, cp, spec):
    """Reuse the reviewed event proof and retain its actual original checkpoint."""
    from research.pooled_vacancy_funding import journal
    raw, proof = parent_review(old, cp, spec); event = proof['event_resolution']
    path = Path(event['path'])
    need(not path.is_absolute() and '..' not in path.parts and path.parts[:2] == ('book', 'pre-event'),
         'COMPLETION_PARENT_EVENT_SAFE_ORIGINAL_PATH')
    source = old / path; value = journal.read_checkpoint(source)
    need(sha(source.read_bytes()) == event['file_sha256'] and value['sha256'] == event['outer_sha256']
         and value['source_cursor'] == '2022-03-04', 'COMPLETION_PARENT_EVENT_EXACT_ORIGINAL_BYTES')
    target = out / path; target.parent.mkdir(parents=True, exist_ok=True)
    need(not target.exists(), 'COMPLETION_PARENT_EVENT_DISJOINT_COPY')
    shutil.copyfile(source, target)
    (out / 'parent-joint-certificate-review.json').write_bytes(raw)
    need(json.loads(raw) == proof, 'COMPLETION_PARENT_PROOF_UNCHANGED')
    return proof


def guarded_event(root, event, row):
    from research.pooled_vacancy_funding import backtest, journal, runtime
    from research.pooled_vacancy_funding.repair import AddedTerm
    from sentinel.controller import terminal_returns
    matches = []
    for path in (root / 'book/pre-event').glob(event['session'] + '-*.json.gz'):
        value = journal.read_checkpoint(path)
        need(path.name == event['session'] + '-' + value['sha256'] + '.json.gz',
             'COMPLETION_ACTUAL_EVENT_ARCHIVE_NAME')
        if value['run']['state_sha256'] == row['prior_state_sha256'] and value['run']['input_sha256'] == row['input_sha256']:
            matches.append((path, value))
    need(len(matches) == 1, 'COMPLETION_UNIQUE_ACTUAL_PRE_EVENT_CHECKPOINT')
    path, cp = matches[0]
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'],
                               input_sha256=backtest.input_hash(cp['base'], cp['repairs']))
    need(runtime.checkpoint(restored) == cp['run'] and cp['source_cursor'] == event['native_session'],
         'COMPLETION_ACTUAL_EVENT_CANONICAL_RESTORE_AND_PRICE_DATE')
    prior = restored.state; sid = event['security_id']
    require_absent(prior.wealth_core, prior.pending, [sid])
    material = row['material']['rows']; names = [v['security_id'] for v in material]
    need(names == prior.median5['selected'] and all(v['prior'] == prior.median5['selected_closes'][v['security_id']]
         for v in material), 'COMPLETION_ACTUAL_EVENT_SELECTED_SET_AND_PRIOR_CLOSES')
    term = AddedTerm.model_validate(event['added']).terms()
    result = terminal_returns.values(prior=prior,
             published=SimpleNamespace(session=event['session'], terminal_events=(term,), bars=()))
    if sid in names:
        anchor = prior.feed['series'][sid]['signal_basis_anchor']
        need(anchor[0] == event['native_session'], 'COMPLETION_ACTUAL_EVENT_ADJACENT_RAW_SIGNAL_ANCHOR')
        value, = [v for v in material if v['security_id'] == sid]
        need(value['current'] == [result[sid], result[sid]], 'COMPLETION_ACTUAL_CANONICAL_POINT_OBSERVATION')
    else:
        need(sid not in result, 'COMPLETION_UNSELECTED_NAME_HAS_NO_POINT_OBSERVATION')
    return dict(session=event['session'], security_id=sid, selected=sid in names,
                actual_predecessor=path.relative_to(root).as_posix(), file_sha256=sha(path.read_bytes()),
                outer_sha256=cp['sha256'], canonical_notional=result.get(sid),
                unowned_and_unordered=True, no_morning_settlement_claim=True)


def review(root, old, spec, output):
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5, champion_config
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    parent = journal.read_checkpoint(old / spec['selected_checkpoint'])
    raw, proof = parent_review(old, parent, spec)
    inherited = seed(old, parent); rows = seed(root, cp); n = len(inherited)
    need(n == 742 and rows[:n] == inherited, 'COMPLETION_ALL_COMMITTED_PARENT_CERTIFICATES_IDENTICAL')
    need((root / 'lineage/uncertainty-certificate-original.jsonl').read_bytes()
         == (old / 'uncertainty-certificate.jsonl').read_bytes(), 'COMPLETION_ENTIRE_PARENT_CERTIFICATE_AND_TAIL_PRESERVED')
    model = validate(root, cp)
    need(model or len(rows) == n, 'COMPLETION_NEW_ROWS_REQUIRE_ACTUAL_GUARDED_INPUT')
    math = RollingWitnessBounds.restore(inherited[-1]['math']); previous = deepcopy(inherited[-1]['after'])
    financial = [r for name in ('formation', 'daily') for r in committed_rows(root / 'book', cp, name)]
    financial_by_day = {r['session']: r for r in financial}; comparisons = proof['comparisons']; events = []
    event_map = {e['session']: e for e in contract()['scoped_events']}
    for row in rows[n:]:
        need(row['before'] == previous and row['representative_is_not_a_valuation'] is True
             and row['owned_position'] is False and row['pending_order'] is False,
             'COMPLETION_ACTUAL_INDUCTIVE_CONTROLLER_SCOPE')
        material = row['material']['rows']; names = [v['security_id'] for v in material]
        need(len(names) == len(set(names)) and 'additional_event_basis' not in row,
             'COMPLETION_POST_PARENT_NO_NEW_INTERVAL_EVENT')
        returns = []
        for item in material:
            bound = Interval(*item['current'])
            need(bound.lo == bound.hi, 'COMPLETION_ONLY_NEW_POINT_FACTORS_NO_REVALUATION')
            returns.append(bound.div(Interval.point(item['prior'])).sub(Interval.point(1.)))
        factor = growth(returns)
        need(factor.pair() == row['material']['factor'], 'COMPLETION_EVERY_NEW_INDEPENDENT_FACTOR')
        math.advance(factor, row['material']['representative_nav'])
        need(math.snapshot() == row['math'], 'COMPLETION_EVERY_NEW_PERSISTED_INTERVAL_CONTINUATION')
        bounds = {f'recent_r{k}': math.period(k) for k in (20, 40)}
        need({k: v.pair() if v is not None else None for k, v in bounds.items()} == row['intervals'],
             'COMPLETION_EVERY_NEW_ROUNDING_AWARE_BOUND')
        state = median5.fresh(champion=True); state.update(row['before']); state['last_session'] = row['session']
        kwargs = dict(row['scalar_inputs'], state=state)
        need(all(kwargs[k] == row['material']['observed'][k] for k in bounds),
             'COMPLETION_ACTUAL_OBSERVED_CONTROLLER_SCALARS')
        (after, decision), checks = certified_recovery(champion_config.recover, kwargs, bounds)
        need(checks == row['comparisons'] and discrete(after) == row['after'] and decision == row['decision'],
             'COMPLETION_EVERY_ACTUAL_CANONICAL_COMPARISON_AND_DISCRETE_STATE')
        actual = financial_by_day[row['session']]
        need(actual['decision']['ldrc'] == decision and actual['decision']['native_target_core_exposure'] == kwargs['native'],
             'COMPLETION_EVERY_ACTUAL_FINANCIAL_CONTROLLER_DECISION')
        if row['session'] in event_map:
            events.append(guarded_event(root, event_map[row['session']], row))
        previous = discrete(after); comparisons += len(checks)
    need(previous == discrete(cp['run']['state']['median5'])
         and math.absolute.contains(cp['run']['state']['median5']['witness_nav'][-1]),
         'COMPLETION_CURRENT_ACTUAL_CONTROLLER_STATE')
    need([v['session'] for v in events] == [day for day in sorted(event_map) if day <= cp['source_cursor']],
         'COMPLETION_EVERY_REACHED_GUARDED_EVENT_REVIEWED')
    watches = committed_rows(root / 'book', cp, 'watch')
    guard_proof = review_guards(financial, watches, guarded_input_sha256=model[0].sha256 if model else '')
    save(output.parent / 'completion-position-guard-review.json', guard_proof)
    save(output, dict(schema='research.joint-leadership-uncertainty-independent-review/1',
        status='COMMITTED_PREFIX_JOINT_INTERVAL_INVARIANT', rows=len(rows), comparisons=comparisons,
        through=cp['source_cursor'], checkpoint_sha256=cp['sha256'], inherited_rows=n,
        exact_parent_interval_proof_sha256=sha(raw), event_resolution=proof['event_resolution'],
        guarded_completion_events=events, original_certificate_and_entire_tail_preserved=True,
        every_actual_comparison_invariant=True, every_committed_watch_and_financial_row_bound=True,
        every_discrete_controller_state_equal=True, financial_path_invariant_over_declared_sensor_interval=True,
        independent_uncertainty_assumption=False, witness_valuation_unique=False,
        representative_is_not_a_valuation=True, no_owned_cvr_accounting_supported=True,
        full_period_complete=cp['completed'] == 2156, production_contacted=False))
