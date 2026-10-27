"""One owner-approved separate baseline timing trial; no performance screen."""
import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import time

from baseline_prefix import run_worker,UnprovenStopped
from build_core_variants import build
from core_recovery_job import inspect_stopped,readonly
from core_window_job import window_command
from core_window_suffix_job import restore_qualified,validate_request as validate_admission
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,SECRET,IMAGE

HERE=Path(__file__).resolve().parent


def require(value,code):
    if not value:raise ValueError(code)


def validate_request(r):
    expected=dict(schema='research.capital-risk-timing-request/1',trial_id='baseline-timing-pilot-001',stage='timing-pilot',
        pilot_protocol_sha256=sha256_file(HERE/'timing-pilot-protocol.json'),
        qualification_admission_sha256=sha256_file(HERE/'core-window-suffix-request.json'),
        worker_source_sha256=sha256_file(HERE/'timing_pilot_worker.py'),
        observer_source_sha256=sha256_file(HERE/'timing_observer.py'))
    require(r==expected,'REFUSED_TIMING_PILOT_REQUEST')
    p=json.loads((HERE/'timing-pilot-protocol.json').read_bytes())
    require(p['trial_id']=='baseline-timing-pilot-001' and p['arm']=='B' and p['window_basis']=='stress2021'
        and p['maximum_formation_transitions']==5 and p['maximum_measured_closes']==0
        and p['worker_deadline_seconds']==300 and p['review_deadline_seconds']==120
        and p['job_timeout_minutes']==15 and p['workers']==1 and p['performance_claims'] is False
        and p['automatic_followup_financial_trial'] is False,'REFUSED_TIMING_PILOT_BUDGET')
    return p


def worker_tail():return ['/driver/timing_pilot_worker.py']


def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','qualification-download','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();check_context(os.environ)
    require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_TIMING_PILOT_RERUN')
    request=json.loads(a.request.read_bytes());protocol=validate_request(request)
    admission=json.loads((HERE/'core-window-suffix-request.json').read_bytes());validate_admission(admission)
    stage=json.loads(a.staging_receipt.read_bytes())
    require(stage['status']=='STAGING_PASSED' and stage['source_commit']==os.environ['GITHUB_SHA']
        and stage['run_id']==os.environ['GITHUB_RUN_ID'] and stage['protocol_sha256']==PROTOCOL
        and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
        and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['source_files_verified']==514 and stage['members_verified']==591
        and stage['authenticated_before_parsing'] and stage['runtime_index_config_layer_chain_verified']
        and stage['offline_image_source_verified'] and stage['replay_started'] is False,'REFUSED_TIMING_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);require(len(key)==32,'REFUSED_RESEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-risk-baseline-timing-pilot-001';private.mkdir(mode=0o700,exist_ok=False)
    diagnostics=private/'diagnostics';diagnostics.mkdir();book=private/'book'
    qualified=temp/'capital-risk-timing-qualified-origin';variant=temp/'capital-risk-timing-source'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    name='capital-risk-timing-pilot-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    status='TIMING_PILOT_REFUSED';financial_stopped=False;review_stopped=True;book_exported=False
    timings={};worker_error=None;deadline_hit=False
    try:
        restore_qualified(admission,'stress2021',a.qualification_download,qualified,key)
        bindings=json.loads((qualified/'source-bindings.json').read_bytes())
        require(build(frozen/'source-fixed',variant,risk=False)==bindings['basis'],'REFUSED_TIMING_QUALIFIED_SOURCE_CHANGE')
        readonly(variant)
        shutil.copytree(qualified/'candidate-B',book)
        shutil.copyfile(book/'run-001/checkpoint.json.gz',book/'lineage/successor-start.json.gz')
        shutil.copyfile(qualified/'source-bindings.json',book/'lineage/qualification-source-bindings.json')
        lineage=dict(schema='research.capital-risk-qualified-lineage/1',qualification_run_id=admission['qualification_run_id'],
            qualification_source_commit=admission['qualification_source_commit'],qualification=admission['windows']['stress2021'],
            original_request_sha256=admission['qualification_request_sha256'],source_boundary_reused=True)
        (book/'lineage/qualification-admission.json').write_text(json.dumps(lineage,indent=2)+'\n')
        trial=dict(schema='research.capital-risk-separate-timing-trial/1',trial_id=protocol['trial_id'],
            owner_authorization=protocol['owner_authorization'],origin_role='PRESERVED_PREFORMATION_ORIGIN_FOR_NEW_TIMING_TRIAL',
            origin_checkpoint_sha256=admission['windows']['stress2021']['candidate_file_sha256'],
            prior_failed_run_id='40571817063',is_continuation_of_prior_failed_run=False,
            max_formation_transitions=5,measured_closes=0,performance_claim=False)
        (diagnostics/'trial-identity.json').write_text(json.dumps(trial,indent=2)+'\n')
        (diagnostics/'pilot-request.json').write_bytes(a.request.read_bytes())
        if memory_bytes()['MemAvailable']<4*1024**3 or shutil.disk_usage(temp).free<12*1024**3:
            raise ValueError('REFUSED_TIMING_PILOT_RESOURCE_GATE')
        started=time.monotonic()
        try:run_worker(window_command(name,frozen,book,HERE,variant,'stress2021',worker_tail()),name,book,deadline=300)
        except UnprovenStopped:raise
        except Exception as exc:worker_error=dict(type=type(exc).__name__,message=str(exc));deadline_hit=str(exc)=='REFUSED_PREFIX_DEADLINE'
        timings['worker_wall_seconds']=time.monotonic()-started
        path=book/(name+'-inspect.json')
        try:stop=inspect_stopped(path,sha256_file(path),allow_oom=True)
        except Exception as exc:raise UnprovenStopped('TIMING_PILOT_STOP_UNKNOWN') from exc
        financial_stopped=True
        (diagnostics/'worker-outcome.json').write_text(json.dumps(dict(inspection=stop,error=worker_error,
            deadline_hit=deadline_hit,**timings),indent=2)+'\n')
        reviewer=name+'-review';review_stopped=False;started=time.monotonic();review_error=None
        tail=['/driver/timing_pilot_review.py','--root','/out/run-001','--lineage','/out/lineage',
            '--timings','/out/pilot-timings.jsonl','--output','/out/timing-review.json']
        try:run_worker(window_command(reviewer,frozen,book,HERE,variant,'stress2021',tail),reviewer,book,deadline=120)
        except UnprovenStopped:raise
        except Exception as exc:review_error=dict(type=type(exc).__name__,message=str(exc))
        timings['review_wall_seconds']=time.monotonic()-started
        rpath=book/(reviewer+'-inspect.json')
        try:rstop=inspect_stopped(rpath,sha256_file(rpath),allow_oom=True)
        except Exception as exc:raise UnprovenStopped('TIMING_REVIEW_STOP_UNKNOWN') from exc
        review_stopped=True
        if review_error is None and rstop['exit_code']==0 and not rstop['oom']:
            reviewed=json.loads((book/'timing-review.json').read_bytes())
            require(reviewed['status']=='TIMING_PILOT_PREFIX_REVIEW_PASSED','REFUSED_TIMING_REVIEW_RESULT')
            if not stop['oom'] and stop['exit_code']==0 and (worker_error is None or deadline_hit):
                status=('TIMING_PILOT_REVIEWED_COMPLETE' if reviewed['formation_transitions']==5
                    and reviewed['committed_timings_complete'] and not deadline_hit else 'TIMING_PILOT_REVIEWED_PARTIAL')
        (diagnostics/'review-outcome.json').write_text(json.dumps(dict(inspection=rstop,error=review_error,**timings),indent=2)+'\n')
    except UnprovenStopped as exc:
        status='WRITER_STOP_UNKNOWN'
        (diagnostics/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    except Exception as exc:
        (diagnostics/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    root=private if financial_stopped and review_stopped else diagnostics
    book_exported=root==private
    asset=output.parent/'baseline-timing-pilot.tar.crseal'
    encrypt(root,asset,key,request['pilot_protocol_sha256'],arm='B',stage='timing-pilot');key=None
    receipt=dict(schema='research.capital-risk-timing-pilot-receipt/1',status=status,trial_id=protocol['trial_id'],
        run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],request_sha256=sha256_file(a.request),
        pilot_protocol_sha256=request['pilot_protocol_sha256'],utc=datetime.now(timezone.utc).isoformat(),
        separate_trial=True,deadline_hit=deadline_hit,book_exported=book_exported,performance_claim=False,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status.startswith('TIMING_PILOT_REVIEWED_') else 2)


if __name__=='__main__':main()
