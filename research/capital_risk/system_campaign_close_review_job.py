"""One private hosted reviewer of the exact failed output; never a writer."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from full_system_trials_job import command
from system_campaign_evidence_export import seal
from system_campaign_p02_close_job import SOURCES as PRIOR, expected_request as original_request
from system_campaign_close_reference import admit as admit_parent
from system_campaign_close_review_admit import admit as admit_target, require_review_only
from system_campaign_p02_continue_job import inspect as prior_inspect
from system_campaign_variants import build
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from seal import sha256_file
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE

HERE=Path(__file__).parent
SOURCES=tuple((*PRIOR,'system_campaign_close_review_materialization.py',
    'system_campaign_close_review_admit.py','system_campaign_close_review_run.py',
    'system_campaign_close_review_job.py','system_campaign_close_review_import_probe.py'))


def expected_request():
    old=original_request();name='system-campaign-p02-close-review-target.json'
    target=json.loads((HERE/name).read_bytes());require_review_only(target)
    original='system-campaign-p02-close-request.json'
    need(sha256_file(HERE/original)=='bf01f5d065c4a00b006f59f70138cc8ad3ea716a91c35b3cd5a75a3ad0bc91a0',
         'CLOSE_REVIEW_JOB_UNCHANGED_ACTUAL_FINANCIAL_REQUEST')
    return dict(schema='research.p02-stopped-close-review-request/1',
        protocol_sha256=old['protocol_sha256'],original_request_file=original,
        original_request_sha256=sha256_file(HERE/original),
        original_predecessor_file=old['predecessor_file'],
        original_predecessor_sha256=old['predecessor_sha256'],
        review_target_file=name,review_target_sha256=sha256_file(HERE/name),
        financial_replay_authorized=False,original_financial_run_id=41214327942,
        review_wait_seconds=2700,source_archive_limit_bytes=512*1024**2,
        initial_min_disk_bytes=old['initial_min_disk_bytes'],
        export_expanded_limit_bytes=old['export_expanded_limit_bytes'],
        metadata_dependencies_sha256=old['metadata_dependencies_sha256'],
        sources={n:sha256_file(HERE/n) for n in SOURCES},production_contacted=False)


def inspect(name,identity=None):
    value=prior_inspect(name,identity)
    need(value['Config']['Cmd']==['-B','-u','/driver/system_campaign_close_review_run.py',
        '--request','/driver/system-campaign-p02-close-review-request.json'],
        'CLOSE_REVIEW_JOB_ONLY_EXACT_REVIEW_ENTRYPOINT')
    return value


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','CLOSE_REVIEW_JOB_NO_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'CLOSE_REVIEW_JOB_EXACT_REQUEST')
    staging=json.loads(args.staging.read_bytes())
    need(staging['status']=='STAGING_PASSED' and staging['run_id']==os.environ['GITHUB_RUN_ID']
         and staging['source_commit']==os.environ['GITHUB_SHA'] and staging['protocol_sha256']==PROTOCOL
         and staging['runtime_image']==IMAGE and staging['execution_image']==EXECUTION_IMAGE
         and staging['source_files_verified']==514 and staging['members_verified']==591
         and staging['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and staging['authenticated_before_parsing'] and staging['offline_image_source_verified']
         and staging['runtime_index_config_layer_chain_verified'] and not staging['replay_started'],
         'CLOSE_REVIEW_JOB_EXACT_OFFLINE_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'CLOSE_REVIEW_JOB_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'CLOSE_REVIEW_JOB_INITIAL_CAPACITY')
    target_spec=json.loads((HERE/request['review_target_file']).read_bytes())
    old_spec=json.loads((HERE/request['original_predecessor_file']).read_bytes())
    old=admit_parent(old_spec,temp/'campaign-factual-transfer-close-review-parent',key,
                     max_zip_bytes=request['source_archive_limit_bytes'])
    target=admit_target(target_spec,temp/'campaign-factual-transfer-close-review-target',key)
    need((target/'request.json').read_bytes()==(HERE/request['original_request_file']).read_bytes()
         and (target/'spec.json').read_bytes()==(HERE/request['original_predecessor_file']).read_bytes()
         and (target/'source-bindings.json').read_bytes()==(old/'source-bindings.json').read_bytes(),
         'CLOSE_REVIEW_JOB_ACTUAL_BOTH_ARTIFACTS_AND_ORIGINAL_PARENT')
    source=temp/'p02-close-review-source'
    binding=build(frozen/'source-fixed',source,json.loads((target/'source-bindings.json').read_bytes())['parameters'])
    need(binding==json.loads((target/'source-bindings.json').read_bytes()),'CLOSE_REVIEW_JOB_IDENTICAL_FINANCIAL_SOURCE')
    out=temp/'p02-close-review-output';out.mkdir(mode=0o700)
    for name,path in (('request.json',args.request),('review-target.json',HERE/request['review_target_file']),
        ('original-financial-request.json',HERE/request['original_request_file'])):
        shutil.copyfile(path,out/name)
    os.environ.pop('GH_TOKEN',None)
    for root in (source,old,target):
        for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
        os.chmod(root,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
         'CLOSE_REVIEW_JOB_PRIVATE_RESOURCE_GATE')
    name='capital-system-factual-p02-review-'+os.environ['GITHUB_RUN_ID']+'-1'
    cmd=command(name,source,frozen,out,'review')
    i=cmd.index('--entrypoint');cmd[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly',
        '--mount',f'type=bind,source={target},target=/evidence,readonly']
    cmd[cmd.index('/driver/full_system_core.py'):]=['/driver/system_campaign_close_review_run.py',
        '--request','/driver/system-campaign-p02-close-review-request.json']
    receipt=dict(schema='research.system-p02-close-review-receipt/1',run_id=os.environ['GITHUB_RUN_ID'],
        head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),
        protocol_sha256=request['protocol_sha256'],arm='P02',status='NOT_STARTED',
        reviewed_financial_run_id=41214327942,reviewed_artifact_id=target_spec['artifact_id'],
        reviewed_checkpoint_sha256=target_spec['outer_sha256'],financial_replay_started=False,
        financial_book_included=False,financial_resume_authorized=False,production_contacted=False)
    known=False
    try:
        reviewer=stopped_run(cmd,name,out,deadline=request['review_wait_seconds'],inspector=inspect)
        known=True;receipt['reviewer']=reviewer;receipt['status']='STOPPED_CLOSE_REVIEW_REFUSED'
        if reviewer['exit_code']==0 and not reviewer['oom_killed']:
            proof=json.loads((out/'core-review.json').read_bytes())
            need(proof['checkpoint_sha256']==target_spec['outer_sha256']
                 and proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified'],
                 'CLOSE_REVIEW_JOB_ACTUAL_CORRECTED_FULL_REVIEW')
            receipt['status']='STOPPED_CLOSE_PREFIX_REVIEWED_NO_FINANCIAL_REPLAY'
    except StopUnknown:receipt['status']='CLOSE_REVIEW_STOP_UNKNOWN'
    except Exception:
        receipt['status']='CLOSE_REVIEW_REFUSED_AFTER_STOP' if known else 'CLOSE_REVIEW_REFUSED_BEFORE_STOP'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        receipt['encrypted_output']=seal(out,args.output.parent/'p02-close-review.tar.crseal',key,
            args.request,'P02',stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='STOPPED_CLOSE_PREFIX_REVIEWED_NO_FINANCIAL_REPLAY' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
