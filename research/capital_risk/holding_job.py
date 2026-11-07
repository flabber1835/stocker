"""One owner-authorized bounded hosted account/identity qualification."""
import argparse,base64,json,os,shutil,time
from datetime import datetime,timezone
from pathlib import Path
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from screen_job import encrypt
from stage import PROTOCOL,IMAGE,SECRET
from runtime_identity import EXECUTION_IMAGE
from probe import check_context,admitted_output,memory_bytes
from seal import sha256_file

HERE=Path(__file__).resolve().parent
SOURCES=('holding_account.py','holding_identity.py','holding_qualification.py','holding_job.py','baseline_prefix.py','screen_job.py')

def need(value,code):
    if not value:raise ValueError(code)

def expected_request():
    return dict(schema='research.holding-qualification-request/1',id='holding-account-qualification-001',
        original_protocol_sha256=PROTOCOL,qualification_protocol_sha256=sha256_file(HERE/'holding-qualification-protocol.json'),
        sources={name:sha256_file(HERE/name) for name in SOURCES},owner_scope='BOUNDED_COMPONENT_QUALIFICATION_NO_PERFORMANCE_TRIAL',
        harness_refusal_prior_run=40699456818)

def validate_request(value):
    need(value==expected_request(),'REFUSED_HOLDING_REQUEST')
    plan=json.loads((HERE/'holding-qualification-protocol.json').read_bytes())
    need(plan['id']=='holding-account-qualification-001' and plan['worker_deadline_seconds']==180
        and plan['job_timeout_minutes']==20 and plan['historical_funded_accounts_to_run']==0
        and plan['original_formation_records']==126 and plan['original_measured_records']==4639
        and not any(plan[k] for k in ('P2_policy_to_run','parameter_search','ticker_only_join','automatic_rerun_or_extension','production_contacted')),
        'REFUSED_HOLDING_PROTOCOL')

def command(name,frozen,private):
    args=launch_arguments(name,frozen,private,HERE);cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['-e','HOLDING_QUAL_HOSTED=1']+args[cut:cut+1]+['-B','-u','/driver/holding_qualification.py',
        '--root','/frozen/baseline-comparison','--output','/out/qualification']

def stopped(path,name):
    from weighted_job import inspect_weighted
    result=inspect_weighted(path,name);need(result['stopped'],'REFUSED_HOLDING_STOP');return result

def main():
    p=argparse.ArgumentParser()
    for name in ('request','staging-receipt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_HOLDING_RERUN')
    request=json.loads(a.request.read_bytes());validate_request(request);s=json.loads(a.staging_receipt.read_bytes())
    need(s['status']=='STAGING_PASSED' and s['run_id']==os.environ['GITHUB_RUN_ID'] and s['source_commit']==os.environ['GITHUB_SHA']
        and s['protocol_sha256']==PROTOCOL and s['runtime_image']==IMAGE and s['execution_image']==EXECUTION_IMAGE
        and s['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and s['source_files_verified']==514 and s['members_verified']==591
        and all(s[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified'))
        and s['replay_started'] is False,'REFUSED_HOLDING_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_HOLDING_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_HOLDING_CAPACITY')
    for path in frozen.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(frozen,0o555)
    private=temp/'holding-account-qualification-001';private.mkdir(mode=0o700,exist_ok=False)
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    (private/'driver-identities.json').write_text(json.dumps({q.name:sha256_file(q) for q in HERE.glob('*.py')},indent=2)+'\n')
    (private/'request.json').write_bytes(a.request.read_bytes())
    name='capital-risk-holding-qual-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    known=False;status='HOLDING_QUALIFICATION_REFUSED';error=None;started=time.monotonic()
    try:
        run_worker(command(name,frozen,private),name,private,deadline=180)
        actual=stopped(private/(name+'-inspect.json'),name);known=True
        need(actual['exit_code']==0 and not actual['oom'],'REFUSED_HOLDING_WORKER_OUTCOME')
        result=json.loads((private/'qualification/summary.json').read_bytes())
        need(result['status']=='HOLDING_QUALIFICATION_PASSED' and result['old_scalar_equivalence']=='MODEL_CHANGED_PROVEN'
            and result['identity']['records']==4765 and result['identity']['duplicate_security_closes']==8
            and result['full_history_funded_accounts_executed']==0 and not result['P2_policy_executed']
            and not result['optimization_executed'] and not result['production_contacted'],'REFUSED_HOLDING_OUTPUT')
        status='HOLDING_QUALIFICATION_PASSED'
    except UnprovenStopped as exc:status='WRITER_STOP_UNKNOWN';error=dict(type=type(exc).__name__,message=str(exc))
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        try:stopped(private/(name+'-inspect.json'),name);known=True
        except Exception:status='WRITER_STOP_UNKNOWN'
    diagnostic=private/'diagnostics';diagnostic.mkdir()
    (diagnostic/'outcome.json').write_text(json.dumps(dict(status=status,error=error,proven_stopped=known,worker_wall_seconds=time.monotonic()-started),indent=2)+'\n')
    asset=output.parent/'holding-qualification.tar.crseal'
    encrypt(private if known else diagnostic,asset,key,request['qualification_protocol_sha256'],arm='HOLDING_QUAL',stage='holding-qualification');key=None
    receipt=dict(schema='research.holding-qualification-receipt/1',status=status,run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(a.request),qualification_protocol_sha256=request['qualification_protocol_sha256'],original_protocol_sha256=PROTOCOL,
        known_stopped=known,synthetic_qualification_only=True,historical_funded_accounts=0,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)),utc=datetime.now(timezone.utc).isoformat())
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='HOLDING_QUALIFICATION_PASSED' else 2)

if __name__=='__main__':main()
