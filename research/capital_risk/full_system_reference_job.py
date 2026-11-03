"""Remaining-budget parent reference calculation; no new Core financial replay."""
import argparse,base64,hashlib,json,os,shutil
from datetime import datetime,timezone
from pathlib import Path
from full_system_math_job import SOURCES,command,inspect
from full_system_trials_job import seal
from full_system_controller_policy import profiles
from full_system_benchmark import need
from probe import check_context,memory_bytes
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from alpaca_fit_job import stopped_run,StopUnknown

HERE=Path(__file__).resolve().parent
REFERENCE_SOURCES=tuple(dict.fromkeys((*SOURCES,'full_system_reference_job.py','owned_grid_worker.py','trace_screen.py','policy.py')))

def request():
    return {'schema':'research.full-system-parent-reference-request/1','stage':'ORIGINAL_2008_CORE_REFERENCE_ONLY',
        'protocol_sha256':sha256_file(HERE/'full-system-search-protocol.json'),
        'profiles_sha256':hashlib.sha256(json.dumps(profiles(),sort_keys=True).encode()).hexdigest(),
        'sources':{n:sha256_file(HERE/n) for n in REFERENCE_SOURCES},'existing_approved_encrypted_channel':True,
        'core_financial_replays':0,'not_recovery_of_unknown_arms':True,'production_contacted':False,
        'hard_deadline_utc':'2026-10-29T17:57:00Z'}

def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_REFERENCE_RERUN')
    req=json.loads(a.request.read_bytes());need(req==request(),'EXACT_REFERENCE_REQUEST')
    s=json.loads(a.staging.read_bytes());need(s['status']=='STAGING_PASSED' and s['source_commit']==os.environ['GITHUB_SHA']
        and s['run_id']==os.environ['GITHUB_RUN_ID'] and s['protocol_sha256']==PROTOCOL and s['runtime_image']==IMAGE
        and s['execution_image']==EXECUTION_IMAGE and s['source_files_verified']==514 and s['members_verified']==591
        and s['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and s['authenticated_before_parsing'] and s['runtime_index_config_layer_chain_verified'] and s['offline_image_source_verified']
        and not s['replay_started'],'REFERENCE_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';private=temp/'full-parent-reference';private.mkdir(mode=0o700)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'REFERENCE_RESOURCES')
    core=private/'core';core.mkdir();shutil.copytree(frozen/'baseline-comparison',core/'book')
    source=frozen/'source-fixed';output=private/'output';output.mkdir();(output/'request.json').write_bytes(a.request.read_bytes())
    (output/'reference-input-bindings.json').write_text(json.dumps({'original_core_checkpoint_file_sha256':sha256_file(core/'book/checkpoint.json.gz'),
        'original_completion_review_sha256':sha256_file(core/'book/fixed-review.json'),'original_sources':514,
        'source_files':{p.relative_to(source).as_posix():sha256_file(p) for p in sorted(source.rglob('*')) if p.is_file()}},indent=2)+'\n')
    receipt={'schema':'research.full-system-parent-reference-receipt/1','arm':'B','run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':req['protocol_sha256'],
        'production_contacted':False,'core_variants_tested':False,'unknown_core_recovered':False,'status':'NOT_STARTED','performance_admitted':False}
    known=False
    def cmd(name,out,evidence=None):return command(name,source,frozen,out,core,evidence)+['--reference']
    try:
        remaining=(datetime(2026,10,29,17,57,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds();need(remaining>1200,'REFERENCE_BUDGET')
        name='capital-full-core-b-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(cmd(name,output),name,output,deadline=min(1200,int(remaining)-900),inspector=inspect);known=True;receipt['worker']=w
        shutil.copyfile(output/'worker-inspect.json',output/'economic-worker-inspect.json');receipt['status']='STOPPED_REFERENCE_PRESERVED'
        if w['exit_code']==0 and not w['oom_killed']:
            audit=private/'audit';audit.mkdir();name='capital-full-core-b-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            reviewed=stopped_run(cmd(name,audit,output),name,audit,deadline=900,inspector=inspect);receipt['reviewer']=reviewed
            shutil.copytree(audit,output/'independent-review-stop')
            if reviewed['exit_code']==0 and not reviewed['oom_killed'] and json.loads((audit/'review/independent-review.json').read_bytes())['status']=='FULL_SYSTEM_CONTROLLER_REVIEW_PASSED':receipt['status']='COMPLETE_PARENT_REFERENCE_INDEPENDENTLY_REVIEWED'
    except StopUnknown:receipt['status']='REVIEW_STOP_UNKNOWN_REFERENCE_PRESERVED' if known else 'REFERENCE_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='REFERENCE_REFUSED'
        if known:(output/'driver-failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(output,a.output.parent/'parent-reference.tar.crseal',key,a.request,'B',stage='multiyear-controller')
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='COMPLETE_PARENT_REFERENCE_INDEPENDENTLY_REVIEWED' else 2)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
