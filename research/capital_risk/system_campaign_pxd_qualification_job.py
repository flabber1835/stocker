"""One fenced hosted PXD zero-session component qualification; no financial arm."""
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
from system_campaign_close_review_job import SOURCES as PRIOR,expected_request as inherited_request
from system_campaign_close_review_admit import admit as admit_target
from system_campaign_pxd_review_admit import admit as admit_review,scope as review_scope
from system_campaign_pxd_facts import contract
from system_campaign_p02_continue_job import inspect as prior_inspect
from system_campaign_variants import build
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE=Path(__file__).resolve().parent
REQUEST='system-campaign-pxd-qualification-request.json'
SOURCES=tuple((*PRIOR,'system-campaign-pxd-preopen-contract.json',
    'system-campaign-pxd-corrected-review.json','system_campaign_pxd_scope.py',
    'system_campaign_pxd_facts.py','system_campaign_pxd_basis.py','system_campaign_pxd_reuse.py',
    'system_campaign_pxd_gate.py','system_campaign_pxd_review.py','system_campaign_pxd_pause.py',
    'system_campaign_pxd_materialize.py','system_campaign_pxd_review_admit.py',
    'system_campaign_pxd_qualification_run.py','system_campaign_pxd_qualification_job.py',
    'system_campaign_pxd_qualification_import_probe.py'))
ALLOWED={'request.json','source-bindings.json','qualification-summary.json','zero-session-startup-proof.json',
    'prefix-and-tail-proof.json','common-factual-and-uncertainty-basis.json',
    'hydrated-pxd-preopen-fact.json','pxd-unowned-preopen-input.json','pxd-canonical-qualification.json',
    'pxd-collision-preflight.json','qualification-checkpoint.json.gz','phase-timing.json',
    'startup-attempt.json','worker-inspect.json','worker.log','driver-failure.txt'}


def expected_request():
    old=inherited_request();contract()
    review='system-campaign-pxd-corrected-review.json'
    review_scope(json.loads((HERE/review).read_bytes()))
    return dict(schema='research.p02-pxd-zero-session-qualification-request/1',
        protocol_sha256=old['protocol_sha256'],original_target_file=old['review_target_file'],
        original_target_sha256=old['review_target_sha256'],corrected_review_file=review,
        corrected_review_sha256=sha256_file(HERE/review),source_contract_file='system-campaign-pxd-preopen-contract.json',
        source_contract_sha256=sha256_file(HERE/'system-campaign-pxd-preopen-contract.json'),
        financial_replay_authorized=False,financial_resume_from_qualification_copy_authorized=False,
        full_local_financial_admission_required_before_financial_resume=True,
        qualification_wait_seconds=900,source_archive_limit_bytes=512*1024**2,
        initial_min_disk_bytes=old['initial_min_disk_bytes'],export_expanded_limit_bytes=16*1024**2,
        metadata_dependencies_sha256=old['metadata_dependencies_sha256'],
        sources={name:sha256_file(HERE/name) for name in SOURCES},production_contacted=False)


def inspect(name,identity=None):
    value=prior_inspect(name,identity)
    need(value['Config']['Cmd']==['-B','-u','/driver/system_campaign_pxd_qualification_run.py',
        '--request','/driver/'+REQUEST],'PXD_QUALIFICATION_JOB_ONLY_ZERO_SESSION_ENTRYPOINT')
    return value


def export_bound(root,limit):
    paths=[p for p in root.rglob('*') if p.is_file()]
    need(not any(p.is_symlink() for p in root.rglob('*'))
         and all(p.relative_to(root).as_posix() in ALLOWED for p in paths)
         and sum(p.stat().st_size for p in paths)<=limit,
         'PXD_QUALIFICATION_JOB_COMPACT_PROOF_ONLY_NO_DISPOSABLE_BOOK_EXPORT')


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','PXD_QUALIFICATION_JOB_NO_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'PXD_QUALIFICATION_JOB_EXACT_REQUEST')
    staging=json.loads(args.staging.read_bytes())
    need(staging['status']=='STAGING_PASSED' and staging['run_id']==os.environ['GITHUB_RUN_ID']
         and staging['source_commit']==os.environ['GITHUB_SHA'] and staging['protocol_sha256']==PROTOCOL
         and staging['runtime_image']==IMAGE and staging['execution_image']==EXECUTION_IMAGE
         and staging['source_files_verified']==514 and staging['members_verified']==591
         and staging['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and staging['authenticated_before_parsing'] and staging['offline_image_source_verified']
         and staging['runtime_index_config_layer_chain_verified'] and not staging['replay_started'],
         'PXD_QUALIFICATION_JOB_EXACT_OFFLINE_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'PXD_QUALIFICATION_JOB_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'PXD_QUALIFICATION_JOB_INITIAL_CAPACITY')
    target_spec=json.loads((HERE/request['original_target_file']).read_bytes())
    review_spec=json.loads((HERE/request['corrected_review_file']).read_bytes())
    target=admit_target(target_spec,temp/'campaign-factual-transfer-pxd-original',key)
    review=admit_review(review_spec,temp/'campaign-factual-transfer-pxd-corrected-review',key)
    source=temp/'p02-pxd-qualification-source'
    binding=build(frozen/'source-fixed',source,json.loads((target/'source-bindings.json').read_bytes())['parameters'])
    need(binding==json.loads((target/'source-bindings.json').read_bytes()),'PXD_QUALIFICATION_JOB_IDENTICAL_515_FINANCIAL_SOURCE')
    out=temp/'p02-pxd-qualification-output';out.mkdir(mode=0o700);proof=out/'proof';proof.mkdir()
    shutil.copyfile(args.request,proof/'request.json');shutil.copyfile(target/'source-bindings.json',proof/'source-bindings.json')
    os.environ.pop('GH_TOKEN',None)
    for root in (source,target,review):
        for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
        os.chmod(root,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
         'PXD_QUALIFICATION_JOB_PRIVATE_RESOURCE_GATE')
    name='capital-system-factual-p02-review-'+os.environ['GITHUB_RUN_ID']+'-1'
    cmd=command(name,source,frozen,out,'review');index=cmd.index('--entrypoint')
    cmd[index:index]=['--mount',f'type=bind,source={target},target=/old,readonly',
        '--mount',f'type=bind,source={review},target=/evidence,readonly']
    cmd[cmd.index('/driver/full_system_core.py'):]=['/driver/system_campaign_pxd_qualification_run.py',
        '--request','/driver/'+REQUEST]
    receipt=dict(schema='research.system-p02-pxd-qualification-receipt/1',run_id=os.environ['GITHUB_RUN_ID'],
        head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        arm='P02',status='NOT_STARTED',source_financial_run_id=41214327942,source_financial_artifact_id=13048057396,
        corrected_review_run_id=41218813778,corrected_review_artifact_id=13049271803,
        canonical_backtest_startup_invoked=None,financial_sessions_advanced=None,financial_replay_authorized=False,
        financial_resume_from_qualification_copy_authorized=False,financial_book_included=False,
        qualification_checkpoint_included=False,production_contacted=False)
    known=False
    try:
        worker=stopped_run(cmd,name,out,deadline=request['qualification_wait_seconds'],inspector=inspect)
        known=True;receipt['worker']=worker;receipt['status']='STOPPED_PXD_QUALIFICATION_REFUSED'
        if worker['exit_code']==0 and not worker['oom_killed']:
            summary=json.loads((proof/'qualification-summary.json').read_bytes())
            need(summary['status']=='PXD_ZERO_SESSION_STARTUP_CANONICALLY_QUALIFIED'
                 and summary['source_checkpoint_sha256']==target_spec['outer_sha256']
                 and summary['typed_inputs']==8 and summary['completed']==1592
                 and summary['financial_sessions_advanced']==0 and summary['financial_admission'] is False
                 and summary['actual_canonical_roundtrip'] is True
                 and summary['actual_all_prefixes_and_tails_verified'] is True,
                 'PXD_QUALIFICATION_JOB_ACTUAL_ZERO_SESSION_INTEGRATION_PROOF')
            receipt.update(status='STOPPED_PXD_ZERO_SESSION_STARTUP_QUALIFIED',
                canonical_backtest_startup_invoked=True,financial_sessions_advanced=0)
    except StopUnknown:receipt['status']='PXD_QUALIFICATION_STOP_UNKNOWN'
    except Exception:
        receipt['status']='PXD_QUALIFICATION_REFUSED_AFTER_STOP' if known else 'PXD_QUALIFICATION_REFUSED_BEFORE_STOP'
        if known:(proof/'driver-failure.txt').write_text(traceback.format_exc())
    try:
        if known:
            for filename in ('worker-inspect.json','worker.log'):shutil.copyfile(out/filename,proof/filename)
            receipt['qualification_checkpoint_included']=(proof/'qualification-checkpoint.json.gz').is_file()
            export_bound(proof,request['export_expanded_limit_bytes'])
            args.output.parent.mkdir(parents=True,exist_ok=True)
            receipt['encrypted_output']=seal(proof,args.output.parent/'p02-pxd-qualification.tar.crseal',key,
                args.request,'P02',stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    except Exception as error:
        receipt['status']='PXD_QUALIFICATION_STOP_PROVEN_EXPORT_REFUSED'
        receipt['export_error_type']=type(error).__name__
    finally:
        key=None;args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='STOPPED_PXD_ZERO_SESSION_STARTUP_QUALIFIED' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
