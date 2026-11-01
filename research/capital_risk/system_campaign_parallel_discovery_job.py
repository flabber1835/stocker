"""Independent per-arm GitHub VM orchestration; no financial replay authority."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from alpaca_fit_job import stopped_run,StopUnknown
from full_system_benchmark import need
from full_system_trials_job import command
from probe import check_context,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from stage import SECRET,PROTOCOL,IMAGE
from seal import sha256_file
from system_campaign_facts import digest
from system_campaign_variants import build
from system_campaign_discovery_context import TAINT
from system_campaign_parallel_discovery import (ARMS,HERE,PARENTS,REQUEST,PRIOR,PRIOR_SHA,
    body,literals,compile_body,specification,reference)
from system_campaign_parallel_discovery_parent import admit
from system_campaign_parallel_discovery_export import qualify_export,write_public_receipt,finish_export
import system_campaign_p02_continue_job as inspector_source
import system_campaign_p01_discovery_suffix_job as previous

SOURCES=tuple(dict.fromkeys((*previous.SOURCES,previous.REQUEST,PARENTS,
    'system_campaign_parallel_discovery.py','system_campaign_parallel_discovery_parent.py',
    'system_campaign_parallel_discovery_export.py','system_campaign_parallel_discovery_run.py',
    'system_campaign_parallel_discovery_job.py','system_campaign_parallel_discovery_probe.py')))


def expected_request():
    return dict(schema='research.parallel-disposable-discovery-request/1',campaign='system-optimization-002',
        authority=TAINT,financial_authority=False,account_performance_computed=False,
        production_contacted=False,arms=list(ARMS),concurrent_candidate_limit=8,
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        predecessor_file=PARENTS,predecessor_sha256=sha256_file(HERE/PARENTS),
        prior375_request_sha256=PRIOR_SHA,canonical_financial_source_changed=False,
        new_origin=False,new_factual_overlay=False,formation_replayed=False,
        execution_mode='OWN_STRICT_PARENT_DISPOSABLE_CANONICAL_DISCOVERY',
        prior_financial_performance_certified=False,actual_canonical_three_case_gate_required=True,
        source_bound_historical_basis_anchors_only=True,
        actual_export_roundtrip_before_parent_or_worker=True,atomic_public_stop_receipts=True,
        target_end='2026-07-31',qualify_wait_seconds=900,discovery_wait_seconds=18000,
        checkpoint_cadence='FIRST_NEW_MONTH_END_NORMAL_SIGNAL_STOP',
        artifact_retention_days=7,initial_min_disk_bytes=12*1024**3,
        sources={name:sha256_file(HERE/name) for name in SOURCES})


def entrypoint(arm,mode):
    need(arm in ARMS and mode in ('qualify','discovery'),'PARALLEL_EXACT_ENTRYPOINT_SCOPE')
    return ['-B','-u','/driver/system_campaign_parallel_discovery_run.py',
        '--mode',mode,'--arm',arm,'--spec','/out/spec.json']


def inspect(name,identity=None):
    fn=literals(body('system_campaign_p02_continue_job.py','inspect'),{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-parallel-discovery-p(?:03|04|05|06|07|09|10|11)-(?:qualify|worker)-[0-9]+-1'})
    value=compile_body(fn,vars(inspector_source))(name,identity)
    arm=name.split('-')[4].upper()
    mode='qualify' if '-qualify-' in name else 'discovery'
    need(value['Config']['Cmd']==entrypoint(arm,mode),'PARALLEL_EXACT_CANONICAL_WORKER_ENTRYPOINT')
    return value


def worker_command(name,arm,mode,source,frozen,out,old):
    value=command(name,source,frozen,out,mode)
    index=value.index('--entrypoint')
    value[index:index]=['--mount',f'type=bind,source={old},target=/old,readonly']
    value[value.index('-B'):]=entrypoint(arm,mode)
    return value


def stage_valid(stage):
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'PARALLEL_ORIGINAL_AUTHENTICATED_INPUT_AND_RUNTIME_STAGING')


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','PARALLEL_NO_BLIND_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes())
    need(request==expected_request(),'PARALLEL_EXACT_FROZEN_REQUEST_AND_SOURCE_CLOSURE')
    spec=specification(args.arm);stage_valid(json.loads(args.staging.read_bytes()))
    temp=Path(os.environ['RUNNER_TEMP']);arm=args.arm
    probe=qualify_export(temp/('parallel-export-probe-'+arm),args.request,arm)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    probe_path=args.output.parent/'export-qualification.json'
    probe_path.write_bytes((json.dumps(probe,sort_keys=True,indent=2)+'\n').encode())
    receipt=dict(schema='research.parallel-disposable-discovery-receipt/1',authority=TAINT,
        financial_authority=False,account_performance_computed=False,production_contacted=False,
        arm=arm,stage='campaign-disposable-discovery',run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        strict_parent_outer_sha256=spec['outer_sha256'],strict_parent_run_id=spec['run_id'],
        checkpoint_cadence=request['checkpoint_cadence'],status='EXPORT_PROBE_PASSED_PARENT_NOT_YET_FETCHED',
        actual_discovery_started=False,export_qualification_sha256=sha256_file(probe_path))
    write_public_receipt(args.output,receipt)
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    need(len(key)==32,'PARALLEL_SEPARATE_KEY')
    out=temp/('parallel-discovery-output-'+arm);out.mkdir(mode=0o700)
    qualification=temp/('parallel-discovery-qualification-'+arm);qualification.mkdir(mode=0o700)
    known=False
    try:
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'PARALLEL_INITIAL_DISK_RESERVE')
        old=admit(spec,temp/('campaign-factual-transfer-parallel-'+arm.lower()),key)
        frozen=temp/'capital-risk-stage-001/inputs';source=temp/('parallel-frozen-source-'+arm)
        binding=json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',source,binding['parameters'])==binding,
             'PARALLEL_EXACT_ORIGINAL_CANDIDATE_FINANCIAL_SOURCE_NO_CONVERSION')
        for directory in (source,old):
            for path in directory.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(directory,0o555)
        os.environ.pop('GH_TOKEN',None)
        need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
             'PARALLEL_ONE_WORKER_PER_VM_RESOURCE_GATE')
        for target in (out,qualification):
            (target/'spec.json').write_bytes((json.dumps(spec,sort_keys=True,indent=2)+'\n').encode())
            shutil.copyfile(args.request,target/'request.json')
            shutil.copyfile(old/'source-bindings.json',target/'source-bindings.json')
        (out/'strict-parent-transport-admission.json').write_bytes((json.dumps(reference(spec),sort_keys=True,indent=2)+'\n').encode())
        name=f'capital-system-parallel-discovery-{arm.lower()}-qualify-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['qualification_worker']=stopped_run(worker_command(name,arm,'qualify',source,frozen,qualification,old),
            name,qualification,deadline=request['qualify_wait_seconds'],inspector=inspect)
        known=True;receipt['status']='QUALIFICATION_STOPPED_PENDING_PROOF';write_public_receipt(args.output,receipt)
        shutil.copytree(qualification,out/'qualification')
        stop=receipt['qualification_worker']
        need(stop['exit_code']==0 and not stop['oom_killed'],'PARALLEL_ACTUAL_QUALIFIER_STOPPED_SUCCESSFULLY')
        proof=json.loads((qualification/'discovery-canonical-qualification.json').read_bytes())
        need(proof['status']=='QUALIFIED' and proof['strict_parent_outer_sha256']==spec['outer_sha256']
             and proof['synthetic_canonical_transitions']==3 and proof['actual_strict_checkpoint_rejection']
             and proof['strict_parent_bytes_unchanged'] and proof['original_runtime_hook_restored']
             and not proof['actual_discovery_started'] and not proof['account_performance_computed'],
             'PARALLEL_ACTUAL_HOSTED_CANONICAL_QUALIFICATION_BEFORE_TRAVERSAL')
        name=f'capital-system-parallel-discovery-{arm.lower()}-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        known=False;receipt.update(status='DISCOVERY_LAUNCH_ATTEMPTED',discovery_launch_attempted=True,
                                   actual_discovery_started=None)
        write_public_receipt(args.output,receipt)
        receipt['worker']=stopped_run(worker_command(name,arm,'discovery',source,frozen,out,old),
            name,out,deadline=request['discovery_wait_seconds'],inspector=inspect)
        known=True;receipt['status']='DISCOVERY_STOPPED_PENDING_OUTPUT_INSPECTION';write_public_receipt(args.output,receipt)
        result=json.loads((out/'discovery-outcome.json').read_bytes())
        receipt['actual_discovery_started']=result['transitions']>0
        complete=(receipt['worker']['exit_code']==0 and not receipt['worker']['oom_killed']
            and result['all_remaining_sessions_covered'] and result['transitions']==spec['expected_remaining_sessions']
            and result['through']==request['target_end'] and result['authority']==TAINT
            and result['account_performance_computed'] is False)
        receipt['status']='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' if complete else 'PARTIAL_DISCOVERY_PRESERVED'
    except StopUnknown:
        known=False;receipt['status']='DISCOVERY_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    except Exception:
        receipt['status']='DISCOVERY_REFUSED_KNOWN_STOP' if known else 'DISCOVERY_REFUSED_BEFORE_STOP_PROOF'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    finish_export(receipt,out,args.output,key,args.request,known=known)
    key=None
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status']=='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--arm',choices=ARMS,required=True)
    for name in ('request','staging','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
