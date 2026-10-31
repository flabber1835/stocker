"""One exact-prefix P02 qualification VM; no economic continuation launcher."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from full_system_trials_job import command, seal
from system_campaign_p02_continue_job import SOURCES as PRIOR, inspect as prior_inspect
from system_campaign_factual_admit import admit
from system_campaign_own_origin import capture as capture_origin
from system_campaign_ancestor import preserve as preserve_ancestor
from system_campaign_variants import build
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes
from stage import SECRET, PROTOCOL, IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE = Path(__file__).resolve().parent
SOURCES = tuple(dict.fromkeys((*PRIOR,
    'system_campaign_uncertainty_input.py','system_campaign_uncertainty_math.py',
    'system_campaign_uncertainty_context.py','system_campaign_uncertainty_review.py',
    'system_campaign_uncertainty_gate.py','system_campaign_uncertainty_facts.py',
    'system_campaign_uncertainty_support.py','system_campaign_uncertainty_integration.py',
    'system_campaign_uncertainty_integration_job.py','system-campaign-uncertainty-contract.json',
    'system-campaign-uncertainty-qualification.json')))


def expected_request():
    proof = json.loads((HERE/'system-campaign-uncertainty-qualification.json').read_bytes())
    need(proof['run_id']==41061791611 and proof['head']=='e5226e142ba825d128009cfbf2a4241e59a39b1b'
         and proof['status']=='PASSED_SYNTHETIC_CANONICAL_QUALIFICATION_ONLY'
         and proof['actual_stopped_exit0_no_oom_and_all_fences']
         and not proof['financial_successor_integration_admitted'], 'UNCERTAINTY_PRIOR_ACTUAL_PROOF_SCOPE')
    for name, digest in proof['qualified_source_files'].items():
        need(sha256_file(HERE/name)==digest,'UNCERTAINTY_PRIOR_QUALIFIED_FUNCTIONS_UNCHANGED')
    return dict(schema='research.system-uncertainty-integration-request/1',
        request_id='uncertainty-own-successor-001',campaign='system-optimization-002',arm='P02',
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        predecessor_file='system-campaign-uncertainty-predecessor.json',
        predecessor_sha256=sha256_file(HERE/'system-campaign-uncertainty-predecessor.json'),
        source_archive_limit_bytes=1024**3,sources={n:sha256_file(HERE/n) for n in SOURCES},
        canonical_controller_sources=proof['canonical_controller_sources'],
        financial_sessions_allowed=0,worker_wait_seconds=1200,artifact_retention_days=7,
        source_conversion=False,new_origin=False,production_contacted=False)


def inspect(name,identity=None):
    result = prior_inspect(name,identity)
    need(result['Config']['Cmd']==['-B','-u','/driver/system_campaign_uncertainty_integration.py',
        '--spec','/out/spec.json','--request','/driver/system-campaign-uncertainty-integration-request.json'],
        'UNCERTAINTY_EXACT_ZERO_SESSION_GATE_ENTRYPOINT')
    return result


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','UNCERTAINTY_NO_FRESH_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'UNCERTAINTY_EXACT_INTEGRATION_REQUEST')
    spec=json.loads((HERE/request['predecessor_file']).read_bytes())
    need(spec['arm']=='P02' and spec['run_id']==41056373429 and spec['selected_session']=='2019-09-30',
         'UNCERTAINTY_EXACT_OWN_ADMITTED_BRANCH')
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'UNCERTAINTY_EXACT_STAGE_AND_RUNTIME')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'UNCERTAINTY_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    old=admit(spec,temp/'campaign-factual-transfer-p02-uncertainty-integration',key,
              max_zip_bytes=request['source_archive_limit_bytes'])
    os.environ.pop('GH_TOKEN',None)
    source=temp/'uncertainty-integration-source'
    binding=build(frozen/'source-fixed',source,json.loads((old/'source-bindings.json').read_bytes())['parameters'])
    need(binding==json.loads((old/'source-bindings.json').read_bytes()),'UNCERTAINTY_ALL_515_SOURCE_BYTES_UNCHANGED')
    for name,digest in request['canonical_controller_sources'].items():
        need(binding['all_sources'][name]==digest,'UNCERTAINTY_ACTUAL_CONTROLLER_IDENTITY')
    out=temp/'uncertainty-integration-output';out.mkdir(mode=0o700)
    capture_origin(old,old,out)
    for name,raw in [('source-bindings.json',(old/'source-bindings.json').read_bytes()),
                     ('request.json',args.request.read_bytes()),('spec.json',(HERE/request['predecessor_file']).read_bytes())]:
        (out/name).write_bytes(raw)
    for root in (old,source):
        for path in root.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
        os.chmod(root,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
         'UNCERTAINTY_INTEGRATION_RESOURCE_GATE')
    receipt=dict(schema='research.system-uncertainty-integration-receipt/1',arm='P02',
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        predecessor_run_id=spec['run_id'],selected_predecessor_outer_sha256=spec['outer_sha256'],
        financial_replay_started=False,production_contacted=False,status='NOT_STARTED')
    known=False
    try:
        name='capital-system-factual-p02-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        cmd=command(name,source,frozen,out,'economic')
        i=cmd.index('--entrypoint');cmd[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly']
        cmd[cmd.index('/driver/full_system_core.py'):]=['/driver/system_campaign_uncertainty_integration.py',
            '--spec','/out/spec.json','--request','/driver/system-campaign-uncertainty-integration-request.json']
        result=stopped_run(cmd,name,out,deadline=request['worker_wait_seconds'],inspector=inspect)
        known=True;receipt['worker']=result
        need(result['exit_code']==0 and not result['oom_killed'],'UNCERTAINTY_ACTUAL_INTEGRATION_STOP')
        proof=json.loads((out/'uncertainty-successor-qualification.json').read_bytes())
        need(proof['status']=='OWN_INPUT_SUCCESSOR_QUALIFIED_ZERO_SESSIONS'
             and proof['actual_runtime_advance_calls']==0,'UNCERTAINTY_ACTUAL_NO_FINANCIAL_REPLAY_PROOF')
        receipt['status']=proof['status']
        receipt['candidate_outer_sha256']=proof['candidate_outer_sha256']
    except StopUnknown:
        receipt['status']='UNCERTAINTY_GATE_STOP_UNKNOWN'
    except Exception:
        receipt['status']='UNCERTAINTY_GATE_REFUSED_KNOWN_STOP' if known else 'UNCERTAINTY_GATE_REFUSED_NO_STOP_PROOF'
        if known:(out/'integration-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        receipt['encrypted_ancestor']=preserve_ancestor(old,out,spec)
        receipt['encrypted_output']=seal(out,args.output.parent/'uncertainty-integration.tar.crseal',key,args.request,'P02',
            stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='OWN_INPUT_SUCCESSOR_QUALIFIED_ZERO_SESSIONS' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
