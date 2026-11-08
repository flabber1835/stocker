"""One hosted reconstruction qualification; no economic continuation selected."""
import argparse,base64,json,os,shutil,traceback
from pathlib import Path
from full_system_benchmark import need
from full_system_trials_job import command
from system_campaign_evidence_export import seal
from system_campaign_p02_uncertainty_job import SOURCES as PRIOR
from system_campaign_p02_continue_job import inspect as prior_inspect
from system_campaign_factual_admit import admit
from system_campaign_variants import build
from system_campaign_ancestor import preserve as preserve_ancestor
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE=Path(__file__).resolve().parent
SOURCES=tuple(dict.fromkeys((*PRIOR,'system_campaign_resume_window.py',
    'system_campaign_resume_qualification.py','system_campaign_reconstruction_job.py')))


def expected_request():
    name='system-campaign-reconstruction-predecessor.json';spec=json.loads((HERE/name).read_bytes())
    need(spec['arm']=='P02' and spec['run_id']==41134805155 and spec['selected_session']=='2021-11-30'
         and spec['outer_sha256']=='022fed7f8ae09a726da64c52e9ad54aaa21dc3edb087528005be0992bf5c9faf'
         and not spec.get('review_refusal') and not spec.get('unadvanced_qualification_failure'),
         'RECONSTRUCTION_LATEST_ADMITTED_OWN_FINANCIAL_PREDECESSOR')
    qualification=json.loads((HERE/'system-campaign-uncertainty-qualification.json').read_bytes())
    return dict(schema='research.exact-reconstruction-request/1',campaign='system-optimization-002',
        only_candidate='P02',concurrent_candidate_limit=1,predecessor_file=name,predecessor_sha256=sha256_file(HERE/name),
        predecessor_common_basis_sha256='a48ee3117782a26df3c7f03f42e99489e1dfbbd42c52a9cf88fe23285336d249',
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        canonical_controller_sources=qualification['canonical_controller_sources'],
        sources={n:sha256_file(HERE/n) for n in SOURCES},source_archive_limit_bytes=1024**3,
        export_expanded_limit_bytes=2*1024**3,initial_min_disk_bytes=12*1024**3,
        qualification_wait_seconds=1200,artifact_retention_days=7,probe_modes=['COLD','BOUNDED'],
        probe_measured_transitions_each=1,probe_next_session='2021-12-01',
        new_origin=False,new_overlay=False,source_conversion=False,economic_suffix_started=False,production_contacted=False)


def inspect(name,identity=None):
    v=prior_inspect(name,identity)
    need(v['Config']['Cmd']==['-B','-u','/driver/system_campaign_resume_qualification.py',
        '--spec','/out/spec.json','--request','/driver/system-campaign-reconstruction-request.json'],
        'RECONSTRUCTION_EXACT_QUALIFICATION_ENTRYPOINT')
    return v


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','RECONSTRUCTION_NO_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'RECONSTRUCTION_EXACT_REQUEST')
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'RECONSTRUCTION_EXACT_AUTHENTICATED_FROZEN_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'RECONSTRUCTION_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'RECONSTRUCTION_INITIAL_DISK')
    spec=json.loads((HERE/request['predecessor_file']).read_bytes())
    old=admit(spec,temp/'campaign-factual-transfer-reconstruction',key,max_zip_bytes=request['source_archive_limit_bytes'])
    review=json.loads((old/'core-review.json').read_bytes());basis=json.loads((old/'common-factual-and-uncertainty-basis.json').read_bytes())
    need(review['counts']==dict(formation=126,daily=986) and review['all_prefixes_verified']
         and review['all_daily_factors_and_chains_verified'] and review['checkpoint_sha256']==spec['outer_sha256']
         and basis['sha256']==request['predecessor_common_basis_sha256'],'RECONSTRUCTION_ACTUAL_ADMITTED_OLD_PREFIX')
    source=temp/'reconstruction-immutable-source';frozen=temp/'capital-risk-stage-001/inputs'
    binding=build(frozen/'source-fixed',source,json.loads((old/'source-bindings.json').read_bytes())['parameters'])
    need(binding==json.loads((old/'source-bindings.json').read_bytes()),'RECONSTRUCTION_ALL_FINANCIAL_SOURCE_BYTES_UNCHANGED')
    out=temp/'reconstruction-output';out.mkdir(mode=0o700)
    for name,raw in (('spec.json',(HERE/request['predecessor_file']).read_bytes()),('request.json',args.request.read_bytes()),
                     ('source-bindings.json',(old/'source-bindings.json').read_bytes())):(out/name).write_bytes(raw)
    for root in (source,old):
        for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
        os.chmod(root,0o555)
    os.environ.pop('GH_TOKEN',None)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,'RECONSTRUCTION_PROBE_RESOURCES')
    name='capital-system-factual-p02-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
    cmd=command(name,source,frozen,out,'economic');i=cmd.index('--entrypoint')
    cmd[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly']
    cmd[cmd.index('/driver/full_system_core.py'):]=['/driver/system_campaign_resume_qualification.py',
        '--spec','/out/spec.json','--request','/driver/system-campaign-reconstruction-request.json']
    receipt=dict(schema='research.exact-reconstruction-qualification-receipt/1',arm='P02',run_id=os.environ['GITHUB_RUN_ID'],
        head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        predecessor_run_id=spec['run_id'],predecessor_outer_sha256=spec['outer_sha256'],
        new_origin=False,new_overlay=False,source_conversion=False,economic_suffix_started=False,production_contacted=False,status='NOT_STARTED')
    known=False
    try:
        worker=stopped_run(cmd,name,out,deadline=request['qualification_wait_seconds'],inspector=inspect)
        known=True;receipt['worker']=worker;receipt['status']='STOPPED_QUALIFICATION_FAILED_EVIDENCE_PRESERVED'
        if worker['exit_code']==0 and not worker['oom_killed']:
            proof=json.loads((out/'reconstruction-qualification.json').read_bytes())
            need(proof['status']=='EXACT_NEXT_TRANSITION_EQUAL' and not proof['selected_for_economic_use']
                 and proof['predecessor']==spec['outer_sha256'],'RECONSTRUCTION_ACTUAL_COMPLETED_PROOF')
            receipt['status']='STOPPED_RECONSTRUCTION_QUALIFICATION_PASSED'
    except StopUnknown:receipt['status']='QUALIFICATION_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    except Exception:
        receipt['status']='STOPPED_QUALIFICATION_REFUSED' if known else 'QUALIFICATION_STOP_NOT_PROVEN'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        receipt['encrypted_ancestor']=preserve_ancestor(old,out,spec)
        receipt['encrypted_output']=seal(out,args.output.parent/'reconstruction.tar.crseal',key,args.request,'P02',
            stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='STOPPED_RECONSTRUCTION_QUALIFICATION_PASSED' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
