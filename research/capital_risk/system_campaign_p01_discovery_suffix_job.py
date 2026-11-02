"""One fenced hosted suffix; proven P01 export implementation is reused."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from full_system_trials_job import command
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from system_campaign_variants import build
from system_campaign_discovery_context import TAINT
from system_campaign_p01_discovery_parent import SPEC as FINANCIAL_SPEC,scope,admit as admit_financial
from system_campaign_p01_discovery_suffix_parent import SPEC,SPEC_SHA,specification,admit
from system_campaign_p01_discovery_export import qualify_export,write_public_receipt,finish_export
from system_campaign_pxd_financial_body import tree
import system_campaign_p02_continue_job as inspector_source
import system_campaign_p01_discovery_job as previous

HERE=Path(__file__).resolve().parent
REQUEST='system-campaign-p01-discovery-suffix-request-001.json'
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,previous.REQUEST,SPEC,
    'system_campaign_p01_discovery_anchors.py','system_campaign_p01_discovery_suffix_parent.py',
    'system_campaign_p01_discovery_suffix_replay.py','system_campaign_p01_discovery_suffix_run.py',
    'system_campaign_p01_discovery_suffix_job.py','system_campaign_p01_discovery_suffix_probe.py')))


def expected_request():
    spec=specification()
    return dict(schema='research.p01-discovery-exact-diagnostic-suffix-request/1',campaign='system-optimization-002',
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),authority=TAINT,
        financial_authority=False,account_performance_computed=False,production_contacted=False,
        original_request_sha256=sha256_file(HERE/previous.REQUEST),diagnostic_predecessor_file=SPEC,
        diagnostic_predecessor_sha256=SPEC_SHA,original_financial_spec_sha256=spec['strict_financial_spec_sha256'],
        execution_mode='EXACT_TAINTED_DIAGNOSTIC_SUFFIX_WITH_SOURCE_VERIFIED_OLD_BASIS_ANCHORS',
        financial_source_changed=False,financial_state_adopted=False,new_origin=False,new_factual_overlay=False,
        reused_original_three_canonical_cases=True,new_actual_first_transition_gate_required=True,
        actual_export_roundtrip_before_parent_or_worker=True,atomic_public_stop_receipts=True,
        predecessor_transitions=356,expected_remaining_sessions=1381,cumulative_expected_sessions=1737,
        next_session=spec['next_session'],target_end=spec['target_end'],owner_candidate_priority='P01',
        concurrent_candidate_limit=1,discovery_wait_seconds=18000,checkpoint_cadence='FIRST_NEW_MONTH_END_NORMAL_SIGNAL_STOP',
        artifact_retention_days=7,initial_min_disk_bytes=12*1024**3,
        sources={name:sha256_file(HERE/name) for name in SOURCES})


def inspect(name,identity=None):
    body=tree('system_campaign_p02_continue_job.py','inspect',{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-discovery-p01-suffix-worker-[0-9]+-1'})
    sets=[n for n in ast.walk(body) if isinstance(n,ast.Set) and all(isinstance(v,ast.Constant) for v in n.elts)
          and {ast.literal_eval(v) for v in n.elts}=={'/variant','/frozen','/driver','/out','/old'}]
    need(len(sets)==1,'P01_SUFFIX_ONE_EXACT_EXTRA_READONLY_PREDECESSOR_MOUNT_SITE')
    sets[0].elts.append(ast.Constant('/previous'))
    namespace=dict(vars(inspector_source));exec(compile(ast.fix_missing_locations(body),
        '<original-worker-fences-plus-diagnostic-predecessor-ro>','exec'),namespace)
    result=namespace['inspect'](name,identity)
    need(result['Config']['Cmd']==entrypoint(),'P01_SUFFIX_EXACT_CANONICAL_DIAGNOSTIC_ENTRYPOINT')
    return result


def entrypoint():
    return ['-B','-u','/driver/system_campaign_p01_discovery_suffix_run.py','--spec','/out/spec.json',
        '--diagnostic-spec','/out/diagnostic-spec.json','--request','/driver/'+REQUEST]


def worker_command(name,source,frozen,out,old,diagnostic):
    value=command(name,source,frozen,out,'discovery')
    i=value.index('--entrypoint')
    value[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly',
                '--mount',f'type=bind,source={diagnostic},target=/previous,readonly']
    value[value.index('-B'):]=entrypoint()
    return value


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','P01_SUFFIX_NO_BLIND_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'P01_SUFFIX_EXACT_REQUEST_SOURCE_CLOSURE')
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'P01_SUFFIX_ORIGINAL_AUTHENTICATED_INPUT_RUNTIME_STAGING')
    temp=Path(os.environ['RUNNER_TEMP'])
    probe=qualify_export(temp/'p01-suffix-export-qualification',args.request)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    probe_path=args.output.parent/'p01-export-qualification.json'
    probe_path.write_text(json.dumps(probe,sort_keys=True,indent=2)+'\n')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'P01_SUFFIX_SEPARATE_KEY')
    spec=specification();financial=scope(json.loads((HERE/FINANCIAL_SPEC).read_bytes()))
    receipt=dict(schema='research.disposable-core-discovery-suffix-receipt/1',authority=TAINT,
        financial_authority=False,account_performance_computed=False,production_contacted=False,
        arm='P01',stage='campaign-disposable-discovery',run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        strict_parent_outer_sha256=financial['outer_sha256'],strict_parent_run_id=financial['run_id'],
        status='EXACT_DIAGNOSTIC_SUFFIX_NOT_STARTED',actual_discovery_started=False,
        checkpoint_cadence=request['checkpoint_cadence'],export_qualification_sha256=sha256_file(probe_path))
    write_public_receipt(args.output,receipt)
    known=False;out=temp/'p01-diagnostic-suffix-output'
    try:
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'P01_SUFFIX_INITIAL_DISK_RESERVE')
        old=admit_financial(financial,temp/'campaign-factual-transfer-p01-suffix-strict-parent',key)
        diagnostic=admit(spec,temp/'p01-diagnostic-suffix-parent',key)
        frozen=temp/'capital-risk-stage-001/inputs';source=temp/'p01-diagnostic-suffix-financial-source'
        binding=json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',source,binding['parameters'])==binding
             and (old/'source-bindings.json').read_bytes()==(diagnostic/'source-bindings.json').read_bytes(),
             'P01_SUFFIX_ALL515_FINANCIAL_SOURCE_BINDINGS_IDENTICAL')
        for root in (source,old,diagnostic):
            for path in root.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(root,0o555)
        os.environ.pop('GH_TOKEN',None)
        need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
             'P01_SUFFIX_PRIVATE_WORKER_RESOURCES')
        out.mkdir(mode=0o700);(out/'lineage').mkdir()
        for src,dest in ((HERE/FINANCIAL_SPEC,out/'spec.json'),(HERE/SPEC,out/'diagnostic-spec.json'),
                         (args.request,out/'request.json'),(old/'source-bindings.json',out/'source-bindings.json'),
                         (diagnostic/'qualification/discovery-canonical-qualification.json',out/'lineage/original-three-case-qualification.json'),
                         (diagnostic/'worker-inspect.json',out/'lineage/original-diagnostic-worker-inspect.json')):
            shutil.copyfile(src,dest)
        name='capital-system-discovery-p01-suffix-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt.update(discovery_launch_attempted=True,actual_discovery_started=None,status='DIAGNOSTIC_SUFFIX_LAUNCH_ATTEMPTED')
        write_public_receipt(args.output,receipt)
        receipt['worker']=stopped_run(worker_command(name,source,frozen,out,old,diagnostic),name,out,
            deadline=request['discovery_wait_seconds'],inspector=inspect)
        known=True;receipt['status']='DIAGNOSTIC_SUFFIX_STOPPED_PENDING_INSPECTION';write_public_receipt(args.output,receipt)
        result=json.loads((out/'discovery-outcome.json').read_bytes())
        receipt['actual_discovery_started']=result['transitions']>spec['transitions']
        receipt['status']='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' if (
            receipt['worker']['exit_code']==0 and not receipt['worker']['oom_killed']
            and result['all_remaining_sessions_covered'] and result['transitions']==1737
            and result['through']=='2026-07-31' and result['authority']==TAINT
            and result['account_performance_computed'] is False) else 'PARTIAL_DIAGNOSTIC_SUFFIX_PRESERVED'
    except StopUnknown:
        known=False;receipt['status']='DIAGNOSTIC_SUFFIX_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    except Exception:
        receipt['status']='DIAGNOSTIC_SUFFIX_REFUSED_KNOWN_STOP' if known else 'DIAGNOSTIC_SUFFIX_REFUSED_BEFORE_STOP_PROOF'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    finish_export(receipt,out,args.output,key,args.request,known=known);key=None
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status']=='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
