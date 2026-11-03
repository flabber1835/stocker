"""One independently exportable hosted VM per exact diagnostic suffix."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from alpaca_fit_job import stopped_run, StopUnknown
from full_system_benchmark import need
from full_system_trials_job import command
from probe import check_context, memory_bytes
from seal import sha256_file
from stage import SECRET
from system_campaign_variants import build
from system_campaign_discovery_context import TAINT, digest
from system_campaign_parallel_discovery import compile_body, body, literals, check_parent
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_parallel_discovery_parent import admit as admit_strict
from system_campaign_parallel_discovery_export import qualify_export, write_public_receipt, finish_export
from system_campaign_discovery_suffix_parent import (ARMS, ANCHOR_SPEC, SPINOFF_SPEC, specification,
                                                   admit as admit_diagnostic, HERE)
import system_campaign_p02_continue_job as inspector_source

PRIOR = 'system-campaign-volatility-admission-recovery-request-001.json'
PRIOR_SHA = 'b8a5349cdcd8f9017af4d1338f5b8a5fbf88ef049ddc28cba32f9083ba4d12bf'
REQUEST = 'system-campaign-discovery-suffix-request-001.json'
SELECTED_ARMS = ('P03', 'P05')
SOURCES = tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'], PRIOR,
    ANCHOR_SPEC, 'system_campaign_anchor_proofs.py',
    'system_campaign_discovery_suffix_parent.py', 'system_campaign_discovery_suffix_replay.py',
    'system_campaign_discovery_suffix_run.py', 'system_campaign_discovery_suffix_job.py',
    'system_campaign_discovery_suffix_probe.py')))


def expected_request():
    need(sha256_file(HERE/PRIOR) == PRIOR_SHA, 'SUFFIX_EXACT418_PREDECESSOR_REQUEST')
    old = json.loads((HERE/PRIOR).read_bytes())
    need(len(old['sources']) == 418 and all(sha256_file(HERE/n) == h for n,h in old['sources'].items()),
         'SUFFIX_ALL418_PRIOR_DRIVER_BYTES_RETAINED_UNCHANGED')
    specs = {arm: specification(arm) for arm in SELECTED_ARMS}
    return dict(schema='research.exact-diagnostic-suffix-request/1', campaign='system-optimization-002',
        authority=TAINT, financial_authority=False, account_performance_computed=False, production_contacted=False,
        arms=list(SELECTED_ARMS), concurrent_candidate_limit=2, prior418_request_sha256=PRIOR_SHA,
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        predecessor_files={ANCHOR_SPEC:sha256_file(HERE/ANCHOR_SPEC)},
        diagnostic_predecessors={a:dict(artifact_id=s['artifact_id'], checkpoint_sha256=s['diagnostic_checkpoint_sha256'],
            transitions=s['transitions'], source_cursor=s['selected_session']) for a,s in specs.items()},
        execution_mode='EXACT_OWN_DIAGNOSTIC_SUFFIX_ONLY', canonical_financial_source_changed=False,
        financial_state_adopted=False, new_origin=False, formation_replayed=False, new_factual_overlay=False,
        reused_original_three_case_gate=True, committed_only_events_and_anchors=True,
        complete_old_cp_journals_and_unsent_tails_preserved=True, actual_journal_recover_required=True,
        immutable_versioned_anchor_proofs=True, source_bound_spinoff_deferral_selected=False,
        actual_export_roundtrip_before_parent_or_worker=True, atomic_public_stop_receipts=True,
        discovery_wait_seconds=18000, target_end='2026-07-31', artifact_retention_days=7,
        checkpoint_cadence='FIRST_NEW_MONTH_END_NORMAL_SIGNAL_STOP', initial_min_disk_bytes=12*1024**3,
        sources={n:sha256_file(HERE/n) for n in SOURCES})


def entrypoint(arm):
    need(arm in SELECTED_ARMS, 'SUFFIX_EXACT_SELECTED_ENTRYPOINT_ARM')
    return ['-B','-u','/driver/system_campaign_discovery_suffix_run.py','--arm',arm,
            '--spec','/out/spec.json','--request','/driver/'+REQUEST]


def inspect(name, identity=None):
    fn = literals(body('system_campaign_p02_continue_job.py','inspect'), {
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-diagnostic-suffix-p(?:03|05|06|07)-worker-[0-9]+-1'})
    sets = [n for n in ast.walk(fn) if isinstance(n,ast.Set) and all(isinstance(v,ast.Constant) for v in n.elts)
            and {ast.literal_eval(v) for v in n.elts} == {'/variant','/frozen','/driver','/out','/old'}]
    need(len(sets) == 1, 'SUFFIX_ONE_EXTRA_READONLY_PREVIOUS_MOUNT_SET')
    sets[0].elts.append(ast.Constant('/previous'))
    value = compile_body(fn,vars(inspector_source))(name,identity)
    arm = name.split('-')[4].upper()
    need(value['Config']['Cmd'] == entrypoint(arm), 'SUFFIX_EXACT_CANONICAL_DIAGNOSTIC_WORKER_ENTRYPOINT')
    return value


def worker_command(name, arm, source, frozen, out, old, previous):
    value = command(name,source,frozen,out,'discovery'); i = value.index('--entrypoint')
    value[i:i] = ['--mount',f'type=bind,source={old},target=/old,readonly',
                  '--mount',f'type=bind,source={previous},target=/previous,readonly']
    value[value.index('-B'):] = entrypoint(arm)
    return value


PHASES = {'MARKER_PASSED','BEFORE_DISK_GATE','BEFORE_STRICT_PARENT_FETCH','STRICT_PARENT_ADMITTED',
          'BEFORE_DIAGNOSTIC_FETCH','DIAGNOSTIC_ADMITTED','SOURCE_VERIFIED','BEFORE_WORKER_RESOURCE_GATE',
          'WORKER_LAUNCH_ATTEMPTED','WORKER_STOPPED','FAILURE','UNKNOWN_NO_SNAPSHOT'}


def phase(path, arm, stage, error=None):
    need(arm in ARMS and stage in PHASES, 'SUFFIX_PUBLIC_PHASE_EXACT_ALLOWLIST')
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    prior = json.loads(path.read_bytes()) if path.exists() else None
    value = dict(schema='research.diagnostic-suffix-nonfinancial-phase/1', arm=arm,
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], phase=stage,
        previous_phase=prior['phase'] if prior else None,
        free_disk_bytes=shutil.disk_usage(Path(os.environ['RUNNER_TEMP'])).free,
        available_memory_bytes=memory_bytes()['MemAvailable'],
        exception_class=type(error).__name__ if error is not None else None,
        code_locations=[dict(file=Path(f.filename).name, function=f.name, line=f.lineno)
                        for f in traceback.extract_tb(error.__traceback__)] if error is not None else [],
        exception_values_included=False, financial_or_market_payload_included=False,
        financial_authority=False, production_contacted=False)
    pending = path.with_suffix('.pending')
    with pending.open('wb') as stream:
        stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode()); stream.flush(); os.fsync(stream.fileno())
    os.replace(pending,path)


def main(args):
    check_context(os.environ)
    need(args.arm in SELECTED_ARMS, 'SUFFIX_ONLY_SELECTED_P03_P05_RECOVERY')
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'SUFFIX_NO_BLIND_WORKFLOW_RERUN')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(), 'SUFFIX_EXACT_REQUEST_AND_COMPLETE_SOURCE_CLOSURE')
    spec = specification(args.arm); financial = spec['financial_strict_predecessor']; arm = args.arm
    stage_valid(json.loads(args.staging.read_bytes()))
    temp = Path(os.environ['RUNNER_TEMP']); args.output.parent.mkdir(parents=True,exist_ok=True)
    probe = qualify_export(temp/('diagnostic-suffix-marker-'+arm),args.request,arm)
    probe_path = args.output.parent/'export-qualification.json'
    with probe_path.open('xb') as stream:
        stream.write((json.dumps(probe,sort_keys=True,indent=2)+'\n').encode()); stream.flush(); os.fsync(stream.fileno())
    phase_path = args.output.parent/'phase.json'; phase(phase_path,arm,'MARKER_PASSED')
    receipt = dict(schema='research.exact-diagnostic-suffix-receipt/1', authority=TAINT,
        financial_authority=False, account_performance_computed=False, production_contacted=False,
        arm=arm, stage='campaign-disposable-discovery', run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request), protocol_sha256=request['protocol_sha256'],
        strict_parent_outer_sha256=financial['outer_sha256'], strict_parent_run_id=financial['run_id'],
        checkpoint_cadence=request['checkpoint_cadence'], status='EXPORT_PROBE_PASSED_PARENT_NOT_YET_FETCHED',
        actual_discovery_started=False, export_qualification_sha256=sha256_file(probe_path))
    write_public_receipt(args.output,receipt)
    key = base64.b64decode(os.environ.pop(SECRET,''),validate=True); need(len(key)==32,'SUFFIX_SEPARATE_KEY')
    out = temp/('diagnostic-suffix-output-'+arm); out.mkdir(mode=0o700); known = False
    try:
        phase(phase_path,arm,'BEFORE_DISK_GATE')
        need(shutil.disk_usage(temp).free >= request['initial_min_disk_bytes'], 'SUFFIX_INITIAL_DISK_RESERVE')
        phase(phase_path,arm,'BEFORE_STRICT_PARENT_FETCH')
        old = admit_strict(financial,temp/('campaign-factual-transfer-suffix-strict-'+arm.lower()),key)
        phase(phase_path,arm,'STRICT_PARENT_ADMITTED'); phase(phase_path,arm,'BEFORE_DIAGNOSTIC_FETCH')
        previous = admit_diagnostic(spec,temp/('campaign-factual-transfer-suffix-diagnostic-'+arm.lower()),key)
        phase(phase_path,arm,'DIAGNOSTIC_ADMITTED')
        frozen = temp/'capital-risk-stage-001/inputs'; source = temp/('diagnostic-suffix-source-'+arm)
        binding = json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',source,binding['parameters']) == binding
             and (old/'source-bindings.json').read_bytes() == (previous/'source-bindings.json').read_bytes(),
             'SUFFIX_EXACT_ORIGINAL_FINANCIAL_SOURCE_NO_CONVERSION')
        for directory in (source,old,previous):
            for path in directory.rglob('*'): os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(directory,0o555)
        phase(phase_path,arm,'SOURCE_VERIFIED'); os.environ.pop('GH_TOKEN',None)
        phase(phase_path,arm,'BEFORE_WORKER_RESOURCE_GATE')
        need(memory_bytes()['MemAvailable'] >= 10*1024**3 and shutil.disk_usage(temp).free >= 10*1024**3,
             'SUFFIX_ONE_OFFLINE_WORKER_RESOURCE_AND_EXPORT_RESERVE')
        for target,value in ((out/'spec.json',spec),(out/'request.json',request)):
            with target.open('xb') as stream:
                stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode()); stream.flush(); os.fsync(stream.fileno())
        shutil.copyfile(old/'source-bindings.json',out/'source-bindings.json')
        shutil.copyfile(old/financial['selected_checkpoint'],out/'strict-parent.json.gz')
        shutil.copyfile(previous/'strict-parent-reference.json',out/'strict-parent-reference.json')
        name = f'capital-system-diagnostic-suffix-{arm.lower()}-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt.update(status='DIAGNOSTIC_SUFFIX_LAUNCH_ATTEMPTED',discovery_launch_attempted=True,actual_discovery_started=None)
        write_public_receipt(args.output,receipt); phase(phase_path,arm,'WORKER_LAUNCH_ATTEMPTED')
        receipt['worker'] = stopped_run(worker_command(name,arm,source,frozen,out,old,previous),name,out,
            deadline=request['discovery_wait_seconds'],inspector=inspect)
        known = True; receipt['status'] = 'DIAGNOSTIC_SUFFIX_STOPPED_PENDING_INSPECTION'
        write_public_receipt(args.output,receipt); phase(phase_path,arm,'WORKER_STOPPED')
        result = json.loads((out/'discovery-outcome.json').read_bytes())
        receipt['actual_discovery_started'] = result['transitions'] > spec['transitions']
        complete = (receipt['worker']['exit_code'] == 0 and not receipt['worker']['oom_killed']
            and result['all_remaining_sessions_covered'] and result['transitions'] == spec['cumulative_expected_sessions']
            and result['through'] == request['target_end'] and result['authority'] == TAINT
            and result['account_performance_computed'] is False)
        receipt['status'] = 'COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' if complete else 'PARTIAL_DIAGNOSTIC_SUFFIX_PRESERVED'
    except StopUnknown:
        known = False; receipt['status'] = 'DIAGNOSTIC_SUFFIX_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
        phase(phase_path,arm,'UNKNOWN_NO_SNAPSHOT')
    except Exception as error:
        receipt['status'] = 'DIAGNOSTIC_SUFFIX_REFUSED_KNOWN_STOP' if known else 'DIAGNOSTIC_SUFFIX_REFUSED_BEFORE_STOP_PROOF'
        phase(phase_path,arm,'FAILURE',error)
        if known: (out/'driver-failure.txt').write_text(traceback.format_exc())
    finish_export(receipt,out,args.output,key,args.request,known=known); key=None
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status'] == 'COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' else 2)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--arm',choices=SELECTED_ARMS,required=True)
    for name in ('request','staging','output'): parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
