"""No repeated control/FAST9 forward path; actual FAST1, REFERENCE10 and20 restores."""
import ast
from copy import deepcopy
from pathlib import Path
import shutil

from system_campaign_p10_ahl2_contract import need, digest, encoded, AFFECTED, physical_tree
from system_campaign_p10_ahl2_context import frozen_namespace
from system_campaign_p10_ahl2_post_plan import retained_specification
from system_campaign_p10_ahl2_post_plan_parent import validate_retained
from system_campaign_p10_ahl2_post_plan_observe import Observer
from system_campaign_p10_ahl2_post_plan_replay import replay, resume_binding
from system_campaign_p10_ahl2_epoch import prepare_epoch, write_json
from system_campaign_p10_ahl2_gate import (records, parser_falsifiers, actual_v_guard_falsifier,
                                         synthetic_supported_cash)

SCHEMA = 'research.p10-ahl2-post-plan-qualification/1'
STATUS = 'P10_RETAINED_CONTROL_FAST_PREFIX_AND_CHANGED_PATH_QUALIFIED'
COUNTS = dict(reused_control_records=10,reused_fast_committed_records=9,
              old_control_forward_transitions=0,cached_fast_forward_transitions=0,
              new_fast_transitions=1,new_reference_transitions=10,new_full_record_canonical_restores=20)


def validator_namespace():
    _,nodes,scope = frozen_namespace('system_campaign_p10_ahl2_gate.py',('qualification_valid',))
    fn, = nodes
    changes = {'research.p10-ahl2-changed-qualification/1':SCHEMA}
    counts = dict.fromkeys(changes,0)
    for node in ast.walk(fn):
        if isinstance(node,ast.Constant) and type(node.value) is str and node.value in changes:
            counts[node.value] += 1
            node.value = changes[node.value]
    need(all(n == 1 for n in counts.values()), 'P10_POST_PLAN_ONE_VERSIONED_SUMMARY_SCHEMA_SITE')
    scope['STATUS'] = STATUS
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<p10-post-plan-all-original-qualification-predicates>','exec'),scope)
    return scope


def qualification_valid(value,spec):
    validator_namespace()['qualification_valid'](value,spec)
    retained = retained_specification()
    need(value['retained_execution_counts'] == COUNTS
         and all(type(n) is int for n in value['retained_execution_counts'].values())
         and value['root_q_only_admission_sha256'] == retained['root_q_only_admission_sha256']
         and value['retained_artifact_id'] == retained['artifact_id']
         and value['retained_request_sha256'] == retained['request_sha256']
         and value['cached_failed_tenth_adopted'] is False
         and value['source_own1_suffix_origin_preserved'] is True
         and value['correct_actual_post_plan_context_qualified'] is True,
         'P10_POST_PLAN_EXPLICIT_REUSE_COUNTS_ROOT_ADMISSION_AND_REMAINING_ACTUAL_GATES')
    return value


def compare_paths(fast,reference):
    need(len(fast) == len(reference) == 10 and fast == reference and encoded(fast) == encoded(reference),
         'P10_POST_PLAN_ALL10_FULL_RECORD_AND_NUMERIC_TYPE_EQUALITY')
    need(fast[-1]['session'] == AFFECTED and len(fast[-1]['sensors']) == 3
         and all(s['post_plan_context']['actual_code_object_identity'] is True
                 and s['post_plan_context']['engine_return_before_sensor'] is True
                 for s in fast[-1]['sensors']), 'P10_POST_PLAN_ALL3_ACTUAL_TERM_VIEWS_CORRECT_CALLER')


def qualify(root, previous, out, spec, *, retained=Path('/previous/retained-qualification'),source_root=Path('/variant')):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import runtime,backtest
    from system_campaign_parallel_discovery_run import retained_inputs
    from system_campaign_p10_ahl2_parent import read_checkpoint
    import json
    root,previous,out,retained = map(Path,(root,previous,out,retained))
    physical_tree(source_root,json.loads((previous/'source-bindings.json').read_bytes()),spec)
    cached = validate_retained(retained,spec)
    # Preserve all20 raw records, both CPs, complete original journals/lineage,
    # tails and actual old inspections once. No captured member is rewritten.
    shutil.copytree(retained,out/'retained-parent-evidence')
    parent = read_checkpoint(root/spec['financial_strict_predecessor']['selected_checkpoint'])
    paths,bindings,observers = {},{},{}
    for label,mode in (('fast','FAST'),('reference','REFERENCE')):
        target = out/label; target.mkdir()
        with retained_inputs(root,parent,target):
            binding = prepare_epoch(root,previous,target,spec,source_root=source_root)
            if label == 'fast':
                resume_binding(binding,retained)
            observer = Observer(binding)
            replay(binding,mode=mode,processing_end=AFFECTED,observer=observer,resume=label == 'fast')
        paths[label],bindings[label],observers[label] = records(target),binding,observer
    fast,reference = paths['fast'],paths['reference']
    need(fast[:9] == cached['fast']['records'][:9]
         and encoded(fast[:9]) == encoded(cached['fast']['records'][:9]),
         'P10_POST_PLAN_CACHED_FAST9_BYTES_AND_OBJECTS_REUSED_WITHOUT_FORWARD_REPLAY')
    need([r['session'] for r in observers['fast'].records] == [AFFECTED]
         and len(observers['reference'].records) == 10,
         'P10_POST_PLAN_ONLY_MISSING_FAST1_AND_FRESH_REFERENCE10_EXECUTED')
    compare_paths(fast,reference)
    for name in ('discovery-events.jsonl','retained-anchor-events.jsonl','anchor-qualifications/index.jsonl',
                 'diagnostic-book/daily.jsonl','diagnostic-input-epochs.jsonl','zero-input-epoch.json'):
        need((out/'fast'/name).read_bytes() == (out/'reference'/name).read_bytes(),
             'P10_POST_PLAN_FULL_EVENT_DAILY_PROOF_INPUT_EPOCH_BYTES_EQUAL:'+name)
    need({p.name:p.read_bytes() for p in (out/'fast/anchor-qualifications').glob('*.json')}
         == {p.name:p.read_bytes() for p in (out/'reference/anchor-qualifications').glob('*.json')},
         'P10_POST_PLAN_ALL_IMMUTABLE_ANCHOR_PROOF_BYTES_EQUAL')
    roundtrips = []
    for label in ('fast','reference'):
        target = out/('roundtrip-'+label);target.mkdir()
        binding = bindings[label]
        with retained_inputs(root,parent,target):
            for d in binding.descriptors:
                obj = backtest.load_repair(binding.out/'book/repairs'/d['filename'],
                    resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
                need(obj.sha256 == d['sha256'],'P10_POST_PLAN_ALL4_CODECS_BEFORE_EACH_RESTORE_GROUP')
            for record in paths[label]:
                cp = record['checkpoint']
                restored = runtime.checkpoint(runtime.restore(cp,policy=parent['base']['policy'],input_sha256=binding.run.input_sha256))
                need(restored == cp and encoded(restored) == encoded(cp),'P10_POST_PLAN_EVERY20_NEW_FULL_RECORD_CANONICAL_RESTORE')
                roundtrips.append(dict(mode=label.upper(),session=record['session'],checkpoint_sha256=cp['checkpoint_sha256'],
                                       state_sha256=cp['state_sha256'],full_state_equal=True))
    negative = out/'negative-proofs';negative.mkdir()
    binding,observer = bindings['fast'],observers['fast']
    falsifiers = parser_falsifiers(binding,observer,negative)
    falsifiers.append(actual_v_guard_falsifier(observer,source_root,binding))
    write_json(out/'supported-cash-component.json',synthetic_supported_cash(binding))
    retained_spec = retained_specification()
    summary = dict(schema=SCHEMA,status=STATUS,authority=spec['authority'],financial_authority=False,
        qualifier_state_adopted=False,original_diagnostic_file_sha256=spec['diagnostic_checkpoint_sha256'],
        predecessor_input_sha256=spec['input_sha256'],successor_input_sha256=binding.run.input_sha256,
        candidate_transitions=10,qualified_through=AFFECTED,first_session=spec['next_session'],
        full_FAST_REFERENCE_publication_runtime_event_proof_equal=True,actual_old_refusal_reproduced=True,
        all21_guard_preserved=True,actual_first_affected_state=fast[-1]['checkpoint']['state_sha256'],
        changed_full_path_sha256=digest(fast),falsifiers=falsifiers,actual_new_canonical_roundtrips=roundtrips,
        source_contract=binding.source_contract,actual_held_roles_and_quantities_from_hosted_path=True,
        old_crypto_native_qualification_or_accounting_reexecuted=False,retained_execution_counts=deepcopy(COUNTS),
        root_q_only_admission_sha256=retained_spec['root_q_only_admission_sha256'],
        retained_artifact_id=retained_spec['artifact_id'],retained_request_sha256=retained_spec['request_sha256'],
        cached_failed_tenth_adopted=False,source_own1_suffix_origin_preserved=True,
        correct_actual_post_plan_context_qualified=True)
    qualification_valid(summary,spec)
    write_json(out/'qualification-summary.json',summary)
    return summary
