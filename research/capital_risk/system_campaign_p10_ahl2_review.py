"""Stopped P10 diagnostic-record review; no account performance or old audits."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

from system_campaign_p10_ahl2_contract import (CHECKPOINT, EPOCH, TAINT, CURSOR, NEXT, AFFECTED,
    HERE, SPEC, digest, sha, need, encoded, physical_tree)
from system_campaign_p10_ahl2_epoch import prepare_epoch, write_json
from system_campaign_p10_ahl2_gate import qualification_valid, records
from system_campaign_p10_ahl2_wire import object_bytes


def checkpoint(path):
    return object_bytes(Path(path).read_bytes(), gzip_declared=True)


def epoch_valid(root, cp, binding):
    raw = (Path(root) / 'diagnostic-input-epochs.jsonl').read_bytes()
    commitment = cp['diagnostic_input_epoch']
    need(commitment == binding.epoch and len(raw) == commitment['bytes']
         and sha(raw) == commitment['prefix_sha256'] and len(raw.splitlines()) == commitment['rows'] == 1,
         'P10_EXACT_SINGLE_DURABLE_ZERO_INPUT_EPOCH')
    row = json.loads(raw)
    body = row['record']
    need(body['schema'] == EPOCH and digest(body) == row['chain_sha256'] == commitment['chain_sha256']
         and body['predecessor_input_sha256'] == binding.spec['input_sha256']
         and body['successor_input_sha256'] == binding.run.input_sha256
         and body['predecessor_descriptors'] == binding.spec['old_descriptors']
         and body['successor_descriptors'] == binding.descriptors
         and body['original_state_sha256'] == binding.spec['state_sha256']
         and body['source_binding_sha256'] == binding.spec['source_binding_sha256']
         and body['cursor'] == CURSOR and body['transitions'] == 1 and body['entire_state_unchanged'] is True,
         'P10_COMPLETE_SOURCE_INPUT_PRIOR_STATE_AND_FOUR_DESCRIPTOR_EPOCH_BINDING')


def carrier_valid(cp, binding):
    need(cp['schema'] == CHECKPOINT and cp['authority'] == TAINT and cp['financial_authority'] is False
         and cp['account_performance_computed'] is False
         and type(cp['discovery_transitions']) is int and cp['discovery_transitions'] >= 1
         and cp['sha256'] == digest({k:v for k,v in cp.items() if k != 'sha256'})
         and cp['input_descriptors'] == binding.descriptors
         and cp['original_diagnostic_checkpoint_sha256'] == binding.spec['diagnostic_checkpoint_sha256']
         and cp['strict_parent_outer_sha256'] == binding.spec['strict_parent_outer_sha256']
         and cp['source_binding_sha256'] == binding.spec['source_binding_sha256'],
         'P10_NEW_VERSIONED_DIAGNOSTIC_CARRIER_NO_FINANCIAL_RELABEL')
    run = cp['runtime_checkpoint']
    need(run['checkpoint_sha256'] == digest({k:v for k,v in run.items() if k != 'checkpoint_sha256'})
         and digest(run['state']) == run['state_sha256']
         and run['state']['last_processed_session'] == cp['source_cursor']
         and run['input_sha256'] == binding.run.input_sha256
         and run['policy'] == binding.run.policy,
         'P10_EVERY_NEW_CANONICAL_RUNTIME_STATE_INPUT_POLICY_CURSOR')


def journal_and_event_prefixes(root, cp, binding, axis):
    from system_campaign_discovery_suffix_parent import verify_prefix, verify_chain
    root = Path(root)
    saved, previous = binding.saved, binding.previous
    tails, streams, suffixes = {}, {}, {}
    for name, commitment in cp['journals'].items():
        original = (previous / 'diagnostic-book' / (name + '.jsonl')).read_bytes()
        old = verify_prefix(original, saved['journals'][name], last=True)
        full = (root / 'diagnostic-book' / (name + '.jsonl')).read_bytes()
        selected = verify_prefix(full, commitment, last=True)
        need(selected.startswith(old), 'P10_EVERY_ORIGINAL_COMMITTED_JOURNAL_PREFIX_BYTE')
        streams[name] = selected
        suffixes[name] = [json.loads(line) for line in selected[len(old):].splitlines()]
        tail = full[len(selected):]
        tails[name] = dict(bytes=len(tail), sha256=sha(tail))
    wanted = axis[axis.index(CURSOR)+1:axis.index(cp['source_cursor'])+1]
    daily = suffixes['daily']
    need([x['session'] for x in daily] == wanted and cp['discovery_transitions'] == 1 + len(daily)
         and not suffixes['formation'], 'P10_EXACT_NEW_ORDERED_AXIS_NO_TAIL_ADOPTION_OR_RESTART')
    events_full = (root / 'discovery-events.jsonl').read_bytes()
    old_full = (previous / 'discovery-events.jsonl').read_bytes()
    old = verify_prefix(old_full, saved['events'])
    selected = verify_prefix(events_full, cp['events'])
    need(selected.startswith(old), 'P10_ALL_ORIGINAL_EVENT_PREFIX_BYTES')
    events = verify_chain(events_full, cp['events'])
    new_events = events[saved['events']['rows']:]
    committed = [x for x in new_events if x['kind'] == 'CORE_TRANSITION_COMMITTED']
    need([e['session'] for e in committed] == wanted,
         'P10_NEW_COMMITTED_CANONICAL_EVENT_AXIS_EXACT')
    chain = saved['transition_chain_sha256']
    ledger = deepcopy(saved['runtime_checkpoint']['state']['ledger']['events'])
    by_day = {e['session']:e for e in committed}
    for row in daily:
        event = by_day[row['session']]
        chain = digest(dict(previous=chain, session=row['session'], next_state_sha256=row['state_sha256'],
                            event_chain_sha256=row['event_chain_sha256']))
        need(chain == row['chain_sha256'] and row['input_sha256'] == binding.run.input_sha256
             and row['state_sha256'] == event['context']['next_state_sha256']
             and event['input_sha256'] == binding.run.input_sha256
             and event['source_sha256'] == digest(binding.parent['base']['sources']),
             'P10_EACH_ACTUAL_NEW_TRANSITION_STATE_EVENT_INPUT_AND_ORIGINAL_CHAIN')
        ledger.extend(event['context']['new_ledger_events'])
    need(chain == cp['transition_chain_sha256']
         and ledger == cp['runtime_checkpoint']['state']['ledger']['events'],
         'P10_ENTIRE_INHERITED_LEDGER_AND_EVERY_LOGGED_NEW_EVENT_EXACT')
    tails['events'] = dict(bytes=len(events_full)-len(selected), sha256=sha(events_full[len(selected):]))
    return dict(daily=daily, tails=tails, event_count=len(new_events), new_ledger_events=len(ledger)-len(
        saved['runtime_checkpoint']['state']['ledger']['events']))


def review(spec, out, evidence, *, root=Path('/old'), previous=Path('/previous'), source_root=Path('/variant')):
    from full_system_core import hosted
    hosted()
    out, evidence, root, previous = map(Path, (out, evidence, root, previous))
    source_binding = json.loads((previous / 'source-bindings.json').read_bytes())
    physical_tree(source_root, source_binding, spec)
    need((evidence / 'spec.json').read_bytes() == (HERE / SPEC).read_bytes()
         and (evidence / 'request.json').read_bytes() == (HERE / 'system-campaign-p10-ahl2-request-001.json').read_bytes()
         and (evidence / 'source-bindings.json').read_bytes() == (previous / 'source-bindings.json').read_bytes()
         and (evidence / 'source-map.json').read_bytes() == (previous / 'source-bindings.json').read_bytes(),
         'P10_ALL_FOUR_EVIDENCE_ROOTS_EXACT_RAW_SOURCE_COPIES')
    from research.pooled_vacancy_funding import runtime
    from research.pooled_input_support import bundle
    from system_campaign_parallel_discovery_run import retained_inputs
    from system_campaign_p10_ahl2_parent import read_checkpoint
    from system_campaign_anchor_proofs import proof_prefix_evidence
    from system_campaign_discovery_suffix_parent import verify_chain
    parent = read_checkpoint(root / spec['financial_strict_predecessor']['selected_checkpoint'])
    zero = out / 'review-zero-epoch'
    zero.mkdir()
    with retained_inputs(root, parent, zero):
        binding = prepare_epoch(root, previous, zero, spec, source_root=source_root)
        current = checkpoint(evidence / 'diagnostic-book/discovery-checkpoint.json.gz')
        paths = sorted((evidence / 'diagnostic-book/retained-checkpoints').glob('*.json.gz'))
        paths.extend(sorted((evidence / 'diagnostic-book/pre-event').glob('*.json.gz')))
        paths.append(evidence / 'diagnostic-book/discovery-checkpoint.json.gz')
        checks = []
        for path in paths:
            cp = checkpoint(path)
            carrier_valid(cp, binding)
            epoch_valid(evidence, cp, binding)
            need(runtime.checkpoint(runtime.restore(cp['runtime_checkpoint'], policy=parent['base']['policy'],
                 input_sha256=binding.run.input_sha256)) == cp['runtime_checkpoint'],
                 'P10_EVERY_NEW_RETAINED_OR_CURRENT_CP_FULL_CANONICAL_RESTORE')
            streams = journal_and_event_prefixes(evidence, cp, binding, bundle.axis())
            anchors = verify_chain((evidence / 'retained-anchor-events.jsonl').read_bytes(),
                                   cp['retained_source_anchors'], anchor=True)
            need(all(r['input_sha256'] == binding.run.input_sha256
                     and r['source_sha256'] == digest(parent['base']['sources']) for r in anchors),
                 'P10_ALL_NEW_COMMITTED_AUXILIARY_ANCHORS_SOURCE_INPUT_BOUND')
            proof_prefix_evidence(evidence, cp['retained_anchor_qualifications'], predecessor=cp['diagnostic_predecessor'])
            checks.append(dict(file=path.relative_to(evidence).as_posix(), source_cursor=cp['source_cursor'],
                transitions=cp['discovery_transitions'], full_canonical_roundtrip=True,
                explicit_input_epoch=True, current_prefixes_and_tails=streams['tails']))
        for name, expected in spec['full_inventory'].items():
            raw = (evidence / 'lineage/diagnostic-predecessor' / name).read_bytes()
            need(len(raw) == expected['bytes'] and sha(raw) == expected['sha256'],
                 'P10_ORIGINAL_FULL_CP_STREAM_PROOF_AND_ALL_NINE_TAIL_BYTES_RETAINED:' + name)
        recovery = json.loads((evidence / 'actual-journal-recovery.json').read_bytes())
        need(recovery['actual_canonical_journal_recover'] is True
             and recovery['committed_journals'] == spec['journals'], 'P10_ACTUAL_NEW_DISJOINT_JOURNAL_RECOVERY')
        old_daily_tail = (previous / 'diagnostic-book/daily.jsonl').read_bytes()[spec['journals']['daily']['bytes']:]
        archived = recovery['recovered_tails']['daily']
        need((evidence / 'diagnostic-book' / archived['filename']).read_bytes() == old_daily_tail
             and archived['bytes'] == spec['old_unsent_tails']['daily']['bytes']
             and archived['sha256'] == spec['old_unsent_tails']['daily']['sha256'],
             'P10_ALL_NINE_OLD_UNSENT_DAILY_ROWS_DURABLY_ARCHIVED_NOT_ADOPTED')
        summary = json.loads((evidence / 'retained-qualification/qualification-summary.json').read_bytes())
        qualification_valid(summary, spec)
        q_records = records(evidence / 'retained-qualification/fast')
        f_records = records(evidence)
        committed = [r for r in f_records if r['session'] <= current['source_cursor'] and 'checkpoint' in r]
        expected = [r for r in q_records if r['session'] <= min(current['source_cursor'], AFFECTED)]
        need(committed == expected and encoded(committed) == encoded(expected),
             'P10_FRESH_OWN_CP1_RECOMPUTATION_FULL_CHANGED_PATH_EQUALS_QUALIFIER')
        need(summary['successor_input_sha256'] == current['runtime_checkpoint']['input_sha256'],
             'P10_QUALIFIED_INPUT4_EQUALS_FRESH_SUFFIX_INPUT')
        final_streams = journal_and_event_prefixes(evidence, current, binding, bundle.axis())
        result = dict(schema='research.p10-own-ahl2-diagnostic-review/1',
            status='P10_OWN_DIAGNOSTIC_SUFFIX_REVIEWED_PENDING_CLIENT', authority=TAINT,
            financial_authority=False, account_performance_computed=False,
            source_cursor=current['source_cursor'], transitions=current['discovery_transitions'],
            new_transitions=current['discovery_transitions']-1, remaining_sessions=spec['cumulative_expected_sessions']-current['discovery_transitions'],
            original_one_transition_checkpoint_and_all_tails_preserved=True,
            original_financial_parent_distinct=True, no_qualifier_or_tail_state_adopted=True,
            physical_source_files=516, canonical_source_files=224, old_inputs=3, current_inputs=4,
            current_input_sha256=current['runtime_checkpoint']['input_sha256'],
            complete_actual_first_changed_path_equal=True, new_checkpoints=checks,
            actual_old_journal_recovery=recovery, current_tails=final_streams['tails'],
            entire_ledger_prefix_and_logged_additions=True, new_ledger_events=final_streams['new_ledger_events'],
            old_accounting_or_strategy_cases_reexecuted=False, production_contacted=False)
        write_json(out / 'p10-ahl2-diagnostic-review.json', result)
        return result
