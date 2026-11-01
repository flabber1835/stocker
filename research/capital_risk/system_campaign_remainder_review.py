"""Stopped-source review of the exact new input and every new range-proof row."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha, digest
from system_campaign_remainder_input import InputCodec, PRIVATE, ORDINARY, require_no_position
from system_campaign_remainder_facts import prepare
from system_campaign_remainder_parent import PATH, reference
from system_campaign_discovery_inputs import retained_inputs
from system_campaign_outcome_archive import seed
from system_campaign_outcome_review import recovery_inputs
from system_campaign_outcome_proof import certified_recovery
from system_campaign_uncertainty_context import discrete, WATCH_SCHEMA
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth
from system_campaign_uncertainty_review import committed_rows
import system_campaign_p02_unconsumed_cash_run as retained
import system_campaign_p02_winter2025_cash_run as previous


def event_checkpoint(root, row):
    from research.pooled_vacancy_funding import journal
    matches = []
    for path in (root / 'book/pre-event').glob(row['session'] + '-*.json.gz'):
        cp = journal.read_checkpoint(path)
        need(path.name == row['session'] + '-' + cp['sha256'] + '.json.gz',
             'REMAINDER_EXACT_EVENT_ARCHIVE_NAME')
        if cp['run']['state_sha256'] == row['prior_state_sha256'] and cp['run']['input_sha256'] == row['input_sha256']:
            matches.append((path, cp))
    need(len(matches) == 1, 'REMAINDER_UNIQUE_ACTUAL_EVENT_PREDECESSOR')
    return matches[0][1]


def guard_snapshot(snapshot, cash_evidence, sid):
    require_no_position(SimpleNamespace(wealth_core=snapshot['wealth_core'],
        pending=snapshot['pending'], ledger=snapshot['ledger'],
        last_evidence=dict(cash_distributions=cash_evidence)), sid)


def retained_scope_reviews(root, old, cp, parent, out):
    import system_campaign_completion_scope as completion
    import system_campaign_close_scope as closing
    import system_campaign_pxd_scope as pxd
    from system_campaign_abiomed_input import require_no_position as no_abiomed
    from system_campaign_chinook_input import require_no_position as no_chinook
    financial = [*committed_rows(root / 'book', cp, 'formation'),
                 *committed_rows(root / 'book', cp, 'daily')]
    watches = committed_rows(root / 'book', cp, 'watch')
    for module, filename in ((completion, 'completion-position-guard-review.json'),
        (closing, 'retained-close-position-guard-review.json'), (pxd, 'retained-pxd-position-guard-review.json')):
        descriptor, = [v for v in parent['repairs'] if json.loads(
            (root / 'book/repairs' / v['filename']).read_bytes())['schema'] == module.SCHEMA]
        proof = module.review_guards(financial, watches, guarded_input_sha256=descriptor['sha256'])
        save(out / filename, proof)
    new = [v for v in financial if v['session'] > parent['source_cursor']]
    for row in new:
        audit = row['evidence']['research_entry_audit']
        for snap in (audit['opening_accounting'], audit['closing_accounting']):
            state = SimpleNamespace(wealth_core=snap['wealth_core'], pending=snap['pending'])
            no_abiomed(state); no_chinook(state)
    save(out / 'retained-sensor-position-guard-review.json', dict(
        actual_new_financial_rows=len(new), every_new_abiomed_and_chinook_open_close_checked=True,
        old_guard_sources_and_typed_inputs_unchanged=True, production_contacted=False))


def certificate_review(root, old, cp, parent, facts, loaded, out):
    from sentinel.controller import champion_config
    inherited = seed(old, parent)
    rows = seed(root, cp)
    need(rows[:len(inherited)] == inherited and len(inherited) == 1388,
         'REMAINDER_EXACT_ORIGINAL_COMMITTED_CERTIFICATE_PREFIX')
    old_prefix = b''.join(line for line in (old / 'uncertainty-certificate.jsonl').read_bytes().splitlines(keepends=True)
                         if json.loads(line)['session'] <= parent['source_cursor'])
    need((root / 'uncertainty-certificate.jsonl').read_bytes().startswith(old_prefix),
         'REMAINDER_ORIGINAL_CERTIFICATE_BYTES_NOT_REENCODED')
    financial = {v['session']: v for v in committed_rows(root / 'book', cp, 'daily')}
    watches = committed_rows(root / 'book', cp, 'watch')
    math = RollingWitnessBounds.restore(inherited[-1]['math'])
    previous_discrete = inherited[-1]['after']
    cases = [v for v in facts.catalog['cases'] if v['treatment'] != 'CANONICAL_ORDINARY']
    resolutions, comparison_count = {}, 0
    for row in rows[len(inherited):]:
        need(row['remainder_input_sha256'] == loaded.sha256 and row['before'] == previous_discrete,
             'REMAINDER_EACH_ACTUAL_INPUT_AND_COMPLETE_DISCRETE_CHAIN')
        event = [v for v in cases if v['sensor_session'] == row['session']]
        need(len(event) <= 1, 'REMAINDER_DECLARED_SINGLE_SENSOR_EVENT')
        selected_sid = None
        if event:
            case, = event; sid = case['security_id']
            before = event_checkpoint(root, row); state = before['run']['state']
            require_no_position(SimpleNamespace(**state), sid)
            basis = row['remainder_event_basis']; selected = sid in state['median5']['selected']
            need(basis['selected'] is selected and basis['session'] == row['session']
                 and basis['security_id'] == sid and basis['phase'] == case['phase']
                 and basis['input_sha256'] == loaded.sha256,
                 'REMAINDER_ACTUAL_SELECTED_EVENT_AND_PHASE')
            need([v['security_id'] for v in row['material']['rows']] == state['median5']['selected'],
                 'REMAINDER_EVENT_ACTUAL_PRIOR_WITNESS_MEMBERSHIP')
            if selected:
                anchor = state['feed']['series'][sid]['signal_basis_anchor']
                need([basis['prior_session'], basis['raw_anchor'], basis['signal_anchor']] ==
                     [anchor[0], str(anchor[1]), str(anchor[2])]
                     and anchor[0] == before['source_cursor'], 'REMAINDER_ACTUAL_EVENT_RAW_SIGNAL_PREIMAGE')
                raw, signal, split = (Fraction(basis[k]) for k in ('raw_anchor', 'signal_anchor', 'split'))
                need(raw > 0 and signal > 0 and split > 0
                     and basis['source_event_sha256'] == digest(facts.payload['event_quotes'][case['ticker']]),
                     'REMAINDER_EXACT_EVENT_SOURCE_AND_POSITIVE_BASIS')
                expected = [float(Fraction(v) * split * signal / raw) for v in case['consideration_bounds']]
                item, = [v for v in row['material']['rows'] if v['security_id'] == sid]
                need(item['prior'] == state['median5']['selected_closes'][sid]
                     and item['current'] == basis['signal_consideration_interval'] == expected,
                     'REMAINDER_FULL_CONSIDERATION_RANGE_WITHOUT_POINT_SUBSTITUTION')
                selected_sid = sid
            resolutions[case['ticker']] = dict(session=row['session'], selected=selected,
                predecessor_outer_sha256=before['sha256'], event_basis=deepcopy(basis))
        else:
            need('remainder_event_basis' not in row, 'REMAINDER_NO_UNDECLARED_SENSOR_EVENT')
        material = row['material']['rows']; returns = []
        need(len(material) == len({v['security_id'] for v in material}), 'REMAINDER_UNIQUE_WITNESS_MEMBERS')
        for item in material:
            bound = Interval(*item['current'])
            need(item['security_id'] == selected_sid or bound.lo == bound.hi,
                 'REMAINDER_ONLY_EXPLICIT_DECLARED_EVENT_MAY_VARY')
            returns.append(bound.div(Interval.point(item['prior'])).sub(Interval.point(1.)))
        factor = growth(returns)
        need(factor.pair() == row['material']['factor'], 'REMAINDER_EVERY_INDEPENDENT_WITNESS_FACTOR')
        math.advance(factor, row['material']['representative_nav'])
        need(math.snapshot() == row['math'], 'REMAINDER_JOINT_OLD_AND_NEW_UNCERTAINTY_NOT_RESET')
        bounds = {f'recent_r{k}': math.period(k) for k in (20, 40)}
        need({k: v.pair() if v is not None else None for k, v in bounds.items()} == row['intervals'],
             'REMAINDER_EVERY_ROUNDING_AWARE_RETURN_BOUND')
        kwargs = recovery_inputs(row)
        need(all(kwargs[k] == row['material']['observed'][k] for k in bounds),
             'REMAINDER_ACTUAL_RECOVERY_OBSERVATIONS')
        (after, decision), proof = certified_recovery(champion_config.recover, kwargs, bounds)
        need(proof == row['comparisons'] and discrete(after) == row['after'] and decision == row['decision'],
             'REMAINDER_EVERY_COMPLETE_CANONICAL_CONTROLLER_OUTCOME')
        actual = financial[row['session']]
        need(actual['decision']['ldrc'] == decision
             and actual['decision']['native_target_core_exposure'] == kwargs['native']
             and actual['state_sha256'] == row['next_state_sha256']
             and actual['input_sha256'] == row['input_sha256'], 'REMAINDER_EVERY_FINANCIAL_DECISION_BINDING')
        guard_cases = [v for v in cases if row['session'] >= v['native_session']]
        need(row['remainder_unowned_unordered_unentitled'] == [v['security_id'] for v in guard_cases],
             'REMAINDER_ACTUAL_ALL_ACTIVE_SCOPE_GUARDS')
        audit = actual['evidence']['research_entry_audit']
        for case in guard_cases:
            for snap in (audit['opening_accounting'], audit['closing_accounting']):
                guard_snapshot(snap, actual['evidence']['cash_distributions'], case['security_id'])
            need(all(v['security_id'] != case['security_id'] for v in actual['evidence']['wealth_core']['intents']),
                 'REMAINDER_NO_NEW_UNVALUED_FINANCIAL_INTENT')
        previous_discrete = discrete(after)
        comparison_count += sum(len(v['comparisons']) for v in proof['leaves'])
    expected_new = [day for day in sorted(financial) if parent['source_cursor'] < day <= cp['source_cursor']]
    need([v['session'] for v in rows[len(inherited):]] == expected_new
         and previous_discrete == discrete(cp['run']['state']['median5'])
         and math.absolute.contains(cp['run']['state']['median5']['witness_nav'][-1]),
         'REMAINDER_COMPLETE_NEW_AXIS_AND_FINAL_CANONICAL_WITNESS')
    summary = json.loads((old / 'uncertainty-certificate-review.json').read_bytes())
    summary.update(status='COMMITTED_PREFIX_COMPLETE_CONTROLLER_OUTCOME_INVARIANT',
        rows=len(rows), through=cp['source_cursor'], checkpoint_sha256=cp['sha256'],
        inherited_rows=len(inherited), comparisons=summary['comparisons'] + comparison_count,
        every_actual_comparison_invariant=summary['every_actual_comparison_invariant'] and all(
            r['comparisons']['all_individual_comparisons_invariant'] for r in rows[len(inherited):]),
        every_complete_controller_result_equal=True, remainder_input_sha256=loaded.sha256,
        remainder_event_resolutions=resolutions, every_new_remainder_scope_checked=True,
        representative_is_not_a_valuation=True)
    save(out / 'uncertainty-certificate-review.json', summary)
    return summary


def review(out, root, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as financial_review
    from system_campaign_pxd_basis import basis
    parent = journal.read_checkpoint(old / spec['selected_checkpoint'])
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    need(cp['base'] == parent['base'] and cp['repairs'][:-1] == parent['repairs'],
         'REMAINDER_ALL41_ORIGINAL_DESCRIPTORS_AND_FINANCIAL_SOURCE_UNCHANGED')
    facts, bound, refs, path = timing.call('independent_remainder_full_hydration', prepare, parent, old, out, spec)
    for name in (PRIVATE, ORDINARY, 'remainder-terminal-input.json'):
        need((out / name).read_bytes() == (root / name).read_bytes(), 'REMAINDER_INDEPENDENT_EXACT_NEW_INPUT_BYTES')
    codec = InputCodec(root, bound, refs, facts.catalog, facts.natives)
    need(json.loads((root / PATH).read_bytes()) == reference(spec), 'REMAINDER_EXACT_STRICT_PARENT_REFERENCE')
    with codec, retained_inputs(old, parent, out):
        from research.pooled_vacancy_funding import backtest
        loaded = backtest.load_repair(root / 'remainder-terminal-input.json',
            resume_session=parent['source_cursor'], predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
        need(cp['repairs'][-1]['sha256'] == loaded.sha256, 'REMAINDER_EXACT_NINTH_TYPED_SUCCESSOR_INPUT')
        timing.call('canonical_complete_history_financial_review', financial_review, out, root, old, spec)
        timing.call('remainder_complete_certificate_review', certificate_review, root, old, cp, parent, facts, loaded, out)
        timing.call('all_retained_guarded_scopes', retained_scope_reviews, root, old, cp, parent, out)
        timing.call('all_archived_original_checkpoints', retained.review_archived_checkpoints, root, old, out)
        # The original eight-model semantics are evaluated at their actual own41
        # parent, whose exact descriptors remain the prefix of the successor.
        prior = previous.namespace()['prior']
        boundary = journal.read_checkpoint(root / 'book/predecessor-checkpoints' / (prior.OUTER + '.json.gz'))
        amendment = prior.FutureProjection(root, boundary)
        old_hash, value = basis(root, parent, amendment=amendment)
        need(old_hash == request['predecessor_common_basis_sha256'],
             'REMAINDER_EIGHT_ORIGINAL_MODEL_SEMANTICS_EXACT_NOT_REBOUND')
    value = deepcopy(value)
    value['schema'] = 'research.system-campaign-common-remainder-terminal-basis/1'
    value['model_semantics'].append(dict(schema='research.p02-remainder-terminal-input/1',
        cases=facts.catalog['cases'], all_original_models_retained=True,
        source_implementation={v['reference']: v['sha256'] for v in refs},
        contingent_rights_not_owned_or_point_valued=True))
    save(out / 'common-factual-and-uncertainty-basis.json', dict(sha256=digest(value), value=value))
    need(journal.read_checkpoint(root / 'book/checkpoint.json.gz') == cp, 'REMAINDER_REVIEW_NEVER_MUTATES_STOPPED_BOOK')
    save(out / 'remainder-lineage-review.json', dict(status='EXACT_OWN41_REMAINDER_REVIEWED',
        all41_old_descriptors_preserved=True, all_eight_original_models_unchanged=True,
        old_scope_summary_reused_only_at_original_parent=True,
        every_new_input_and_complete_outcome_checked=True, production_contacted=False))
