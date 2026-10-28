"""One bounded hosted E75 worker, with encrypted evidence and no Core replay."""
import argparse,base64,json,os,shutil,time
from pathlib import Path
from datetime import datetime,timezone
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from screen_job import encrypt
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import PROTOCOL,IMAGE,SECRET
from entry_gate_screen import validate_plan
from trace_screen import require

HERE=Path(__file__).resolve().parent
SOURCES=('entry_gate_policy.py','entry_gate_screen.py','entry_gate_job.py',
    'weighted_account_adapter.py','trace_screen.py','baseline_prefix.py','screen_job.py')


def expected_request():
    return dict(schema='research.owned55-entry-request/1',request_id='owned55-entry-gate-001',
        stage='entry-gate-screen',arms=['B','E75'],original_protocol_sha256=PROTOCOL,
        contract_sha256=sha256_file(HERE/'entry-gate-protocol.json'),
        source_bindings={name:sha256_file(HERE/name) for name in SOURCES},
        owner_scope='ONE_20_MINUTE_ENTRY_GATE_COMPARISON_ONLY')


def validate_request(value):
    require(value==expected_request(),'REFUSED_ENTRY_EXACT_REQUEST')
    validate_plan(json.loads((HERE/'entry-gate-protocol.json').read_bytes()))


def command(name,frozen,private):
    args=launch_arguments(name,frozen,private,HERE);cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['-e','OWNED55_ENTRY_HOSTED=1']+args[cut:cut+1]+[
        '-B','-u','/driver/entry_gate_screen.py','--root','/frozen/baseline-comparison',
        '--output','/out/screen','--protocol','/driver/entry-gate-protocol.json']


def saved_stop(path,name):
    from weighted_job import inspect_weighted
    value=inspect_weighted(path,name)
    require(value['stopped'],'REFUSED_ENTRY_STOP')
    return value


def main():
    parser=argparse.ArgumentParser()
    for key in ('request','staging-receipt','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();check_context(os.environ)
    require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_ENTRY_RERUN')
    request=json.loads(args.request.read_bytes());validate_request(request)
    proof=json.loads(args.staging_receipt.read_bytes())
    require(proof['status']=='STAGING_PASSED' and proof['source_commit']==os.environ['GITHUB_SHA']
        and proof['run_id']==os.environ['GITHUB_RUN_ID'] and proof['protocol_sha256']==PROTOCOL
        and proof['runtime_image']==IMAGE and proof['execution_image']==EXECUTION_IMAGE
        and proof['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and proof['source_files_verified']==514 and proof['members_verified']==591
        and all(proof[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified'))
        and proof['replay_started'] is False,'REFUSED_ENTRY_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    require(len(key)==32,'REFUSED_ENTRY_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    require(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_ENTRY_RESOURCE_GATE')
    for path in frozen.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(frozen,0o555)
    private=temp/'owned55-entry-gate-001';private.mkdir(mode=0o700,exist_ok=False)
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),args.output);output.parent.mkdir(parents=True,exist_ok=True)
    (private/'driver-identities.json').write_text(json.dumps({q.name:sha256_file(q) for q in sorted(HERE.glob('*.py'))},indent=2)+'\n')
    (private/'request.json').write_bytes(args.request.read_bytes())
    name='capital-risk-entry75-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    known=False;status='ENTRY_SCREEN_REFUSED';error=None;started=time.monotonic()
    try:
        run_worker(command(name,frozen,private),name,private,deadline=420)
        stop=saved_stop(private/(name+'-inspect.json'),name);known=True
        require(stop['exit_code']==0 and not stop['oom'],'REFUSED_ENTRY_WORKER_EXIT')
        result=json.loads((private/'screen/summary.json').read_bytes())
        require(result['status'] in ('ENTRY_SCREEN_PASSED','ENTRY_NO_TREATMENT')
            and result['contract_sha256']==request['contract_sha256']
            and result['formation_records']==126 and result['measured_closes']==4639,'REFUSED_ENTRY_OUTPUT')
        status=result['status']
    except UnprovenStopped as exc:
        status='WRITER_STOP_UNKNOWN';error=dict(type=type(exc).__name__,message=str(exc))
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        try:saved_stop(private/(name+'-inspect.json'),name);known=True
        except Exception:status='WRITER_STOP_UNKNOWN'
    diagnostics=private/'diagnostics';diagnostics.mkdir()
    (diagnostics/'outcome.json').write_text(json.dumps(dict(status=status,error=error,
        proven_stopped=known,worker_wall_seconds=time.monotonic()-started),indent=2)+'\n')
    asset=output.parent/'entry-gate.tar.crseal'
    encrypt(private if known else diagnostics,asset,key,request['contract_sha256'],arm='BE75',stage='entry-gate-screen')
    key=None
    receipt=dict(schema='research.owned55-entry-receipt/1',status=status,request_id=request['request_id'],
        source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        request_sha256=sha256_file(args.request),contract_sha256=request['contract_sha256'],original_protocol_sha256=PROTOCOL,
        arms=['B','E75'],book_exported=known,core_financial_changes=False,production_contacted=False,
        utc=datetime.now(timezone.utc).isoformat(),encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status in ('ENTRY_SCREEN_PASSED','ENTRY_NO_TREATMENT') else 2)


if __name__=='__main__':main()
