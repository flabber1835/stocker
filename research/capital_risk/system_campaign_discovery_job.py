"""One serial, fenced and encrypted diagnostic workflow from strict own41."""
import argparse
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
from system_campaign_facts import digest
from system_campaign_discovery_context import TAINT
from system_campaign_discovery_parent import SPEC,SPEC_SHA,PATH,scope,reference,admit
from system_campaign_pxd_financial_body import function
import system_campaign_p02_continue_job as inspector_source
import system_campaign_evidence_export as export_source
import system_campaign_p02_winter2025_cash_job as prior

HERE=Path(__file__).resolve().parent
REQUEST='system-campaign-p02-discovery-request.json'
SOURCES=tuple(dict.fromkeys((*prior.SOURCES,prior.REQUEST,SPEC,
    'system_campaign_discovery_context.py','system_campaign_discovery_replay.py',
    'system_campaign_discovery_inputs.py','system_campaign_discovery_gate.py',
    'system_campaign_discovery_parent.py','system_campaign_discovery_run.py',
    'system_campaign_discovery_job.py','system_campaign_discovery_import_probe.py')))


def expected_request():
    spec=scope(json.loads((HERE/SPEC).read_bytes()))
    return dict(schema='research.disposable-core-discovery-request/1',campaign='system-optimization-002',
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        authority=TAINT,financial_authority=False,execution_mode='DISPOSABLE_CANONICAL_CORE_TRADING_DISCOVERY',
        predecessor_file=SPEC,predecessor_sha256=SPEC_SHA,parent_content_reference_sha256=digest(reference(spec)),
        canonical_financial_source_changed=False,new_origin=False,new_overlay=False,production_contacted=False,
        owner_candidate_priority='P02',concurrent_candidate_limit=1,target_end='2026-07-31',
        expected_remaining_sessions=314,qualify_wait_seconds=900,discovery_wait_seconds=12600,
        initial_min_disk_bytes=12*1024**3,source_archive_limit_bytes=512*1024**2,
        artifact_retention_days=7,account_performance_computed=False,
        sources={n:sha256_file(HERE/n) for n in SOURCES})


def inspect(name,identity=None):
    value=function('system_campaign_p02_continue_job.py','inspect',{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-discovery-p02-(?:qualify|worker)-[0-9]+-1'},vars(inspector_source))(name,identity)
    mode='qualify' if '-qualify-' in name else 'discovery'
    need(value['Config']['Cmd']==['-B','-u','/driver/system_campaign_discovery_run.py',
        '--mode',mode,'--spec','/out/spec.json','--request','/driver/'+REQUEST],
        'DISCOVERY_EXACT_QUALIFICATION_OR_DIAGNOSTIC_ENTRYPOINT')
    return value


def sealed(root,target,key,request):
    return function('system_campaign_evidence_export.py','seal',{
        'campaign-factual-suffix':'campaign-disposable-discovery'},vars(export_source))(
        root,target,key,request,'P02',stage='campaign-disposable-discovery',
        protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','DISCOVERY_NO_BLIND_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes())
    need(request==expected_request(),'DISCOVERY_EXACT_FROZEN_REQUEST')
    spec=scope(json.loads((HERE/SPEC).read_bytes()))
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'DISCOVERY_ORIGINAL_AUTHENTICATED_INPUT_AND_RUNTIME_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    need(len(key)==32,'DISCOVERY_SEPARATE_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'DISCOVERY_INITIAL_DISK_BUDGET')
    old=admit(spec,temp/'p02-discovery-strict-parent',key)
    source=temp/'p02-discovery-frozen-source'
    oldbinding=json.loads((old/'source-bindings.json').read_bytes())
    need(build(frozen/'source-fixed',source,oldbinding['parameters'])==oldbinding,
         'DISCOVERY_EXACT_FROZEN_P02_FINANCIAL_SOURCE_NO_CONVERSION')
    for root in (source,old):
        for path in root.rglob('*'):
            os.chmod(path,0o555 if path.is_dir() else 0o444)
        os.chmod(root,0o555)
    os.environ.pop('GH_TOKEN',None)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
         'DISCOVERY_WORKER_RESOURCE_GATE')
    out=temp/'p02-discovery-output';out.mkdir(mode=0o700)
    qualify=temp/'p02-discovery-qualification';qualify.mkdir(mode=0o700)
    for target in (out,qualify):
        shutil.copyfile(HERE/SPEC,target/'spec.json')
        shutil.copyfile(args.request,target/'request.json')
        shutil.copyfile(old/'source-bindings.json',target/'source-bindings.json')
    ref=reference(spec);(out/'lineage').mkdir()
    (out/PATH).write_text(json.dumps(ref,sort_keys=True,indent=2)+'\n')
    receipt=dict(schema='research.disposable-core-discovery-receipt/1',authority=TAINT,
        financial_authority=False,account_performance_computed=False,production_contacted=False,
        arm='P02',stage='campaign-disposable-discovery',run_id=os.environ['GITHUB_RUN_ID'],
        head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),
        protocol_sha256=request['protocol_sha256'],strict_parent_outer_sha256=spec['outer_sha256'],
        strict_parent_run_id=spec['run_id'],status='NOT_STARTED',actual_discovery_started=False)

    def cmd(name,mode,target):
        value=command(name,source,frozen,target,mode)
        i=value.index('--entrypoint')
        value[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly']
        value[value.index('/driver/full_system_core.py'):]=['/driver/system_campaign_discovery_run.py',
            '--mode',mode,'--spec','/out/spec.json','--request','/driver/'+REQUEST]
        return value

    known=False
    try:
        name='capital-system-discovery-p02-qualify-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['qualification_worker']=stopped_run(cmd(name,'qualify',qualify),name,qualify,
            deadline=request['qualify_wait_seconds'],inspector=inspect)
        known=True
        shutil.copytree(qualify,out/'qualification')
        stop=receipt['qualification_worker']
        need(stop['exit_code']==0 and not stop['oom_killed'],'DISCOVERY_ACTUAL_QUALIFIER_STOPPED_SUCCESSFULLY')
        proof=json.loads((qualify/'discovery-canonical-qualification.json').read_bytes())
        need(proof['status']=='QUALIFIED' and proof['strict_parent_outer_sha256']==spec['outer_sha256']
             and proof['synthetic_canonical_transitions']==3 and proof['actual_strict_checkpoint_rejection']
             and proof['strict_parent_bytes_unchanged'] and proof['original_runtime_hook_restored']
             and not proof['actual_discovery_started'] and not proof['account_performance_computed'],
             'DISCOVERY_ACTUAL_HOSTED_QUALIFICATION_BEFORE_REMAINDER')
        name='capital-system-discovery-p02-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        known=False;receipt['discovery_launch_attempted']=True
        receipt['actual_discovery_started']=None
        receipt['worker']=stopped_run(cmd(name,'discovery',out),name,out,
            deadline=request['discovery_wait_seconds'],inspector=inspect)
        known=True
        result=json.loads((out/'discovery-outcome.json').read_bytes())
        receipt['actual_discovery_started']=result['transitions']>0
        receipt['status']='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' if (
            receipt['worker']['exit_code']==0 and not receipt['worker']['oom_killed']
            and result['all_remaining_sessions_covered'] and result['transitions']==314
            and result['through']=='2026-07-31' and result['authority']==TAINT
            and result['account_performance_computed'] is False) else 'PARTIAL_DISCOVERY_PRESERVED'
    except StopUnknown:
        known=False;receipt['status']='DISCOVERY_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    except Exception:
        receipt['status']='DISCOVERY_REFUSED_KNOWN_STOP' if known else 'DISCOVERY_REFUSED_BEFORE_STOP_PROOF'
        if known:
            (out/'driver-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        receipt['encrypted_output']=sealed(out,args.output.parent/'p02-discovery.tar.crseal',key,args.request)
    key=None
    args.output.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status']=='COMPLETE_DISCOVERY_PENDING_INDEPENDENT_REVIEW' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
