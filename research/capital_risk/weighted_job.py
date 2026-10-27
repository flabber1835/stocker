"""Single approved hosted B/R screen; existing encrypted inputs, no Core replay."""
import argparse,base64,json,os,time,shutil
from datetime import datetime,timezone
from pathlib import Path
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,IMAGE,SECRET
from weighted_screen import validate_plan
from weighted_policy import need

HERE=Path(__file__).resolve().parent

def validate_request(request):
    expected=dict(schema='research.capital-weighted-request/1',request_id='weighted-exposure-001',
        stage='weighted-screen',original_protocol_sha256=PROTOCOL,
        contract_sha256=sha256_file(HERE/'weighted-screen-protocol.json'),
        policy_sha256=sha256_file(HERE/'weighted_policy.py'),features_sha256=sha256_file(HERE/'weighted_features.py'),
        screen_sha256=sha256_file(HERE/'weighted_screen.py'))
    need(request==expected,'REFUSED_R_REQUEST')
    validate_plan(json.loads((HERE/'weighted-screen-protocol.json').read_bytes()))

def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_R_RERUN')
    request=json.loads(a.request.read_bytes());validate_request(request);proof=json.loads(a.staging_receipt.read_bytes())
    need(proof['status']=='STAGING_PASSED' and proof['source_commit']==os.environ['GITHUB_SHA']
        and proof['run_id']==os.environ['GITHUB_RUN_ID'] and proof['protocol_sha256']==PROTOCOL
        and proof['runtime_image']==IMAGE and proof['execution_image']==EXECUTION_IMAGE
        and proof['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and proof['source_files_verified']==514 and proof['members_verified']==591
        and all(proof[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified'))
        and proof['replay_started'] is False,'REFUSED_R_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_R_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_R_CAPACITY')
    private=temp/'capital-risk-weighted-screen-001';private.mkdir(mode=0o700,exist_ok=False)
    for path in frozen.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(frozen,0o555)
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    (private/'driver-identities.json').write_text(json.dumps({p.name:sha256_file(p) for p in sorted(HERE.glob('*.py'))},indent=2)+'\n')
    name='capital-risk-br-screen-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    args=launch_arguments(name,frozen,private,HERE);cut=args.index(EXECUTION_IMAGE)
    args=args[:cut+1]+['-B','-u','/driver/weighted_screen.py','--root','/frozen/baseline-comparison',
        '--archive','/frozen/archive/corpus.zip','--output','/out/screen','--protocol','/driver/weighted-screen-protocol.json']
    status='WEIGHTED_SCREEN_REFUSED';error=None;known=False;started=time.monotonic()
    try:
        run_worker(args,name,private,deadline=600)
        path=private/(name+'-inspect.json');stopped=inspect_weighted(path,name);known=True
        result=json.loads((private/'screen/summary.json').read_bytes())
        need(result['status']=='WEIGHTED_SCREEN_PASSED' and result['contract_sha256']==request['contract_sha256']
            and result['measured_closes']==4639 and result['formation_records']==126,'REFUSED_R_OUTPUT')
        status='WEIGHTED_SCREEN_PASSED'
    except UnprovenStopped as exc:error=dict(type=type(exc).__name__,message=str(exc));status='WRITER_STOP_UNKNOWN'
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        try:inspect_weighted(private/(name+'-inspect.json'),name);known=True
        except Exception:status='WRITER_STOP_UNKNOWN'
    diagnostics=private/'diagnostics';diagnostics.mkdir()
    (diagnostics/'outcome.json').write_text(json.dumps(dict(status=status,error=error,worker_wall_seconds=time.monotonic()-started,proven_stopped=known),indent=2)+'\n')
    # Never archive a financial output when its actual writer outcome is unknown.
    asset=output.parent/'weighted-screen.tar.crseal'
    encrypt(private if known else diagnostics,asset,key,request['contract_sha256'],arm='BR',stage='weighted-screen');key=None
    receipt=dict(schema='research.capital-weighted-receipt/1',status=status,request_id=request['request_id'],
        run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],request_sha256=sha256_file(a.request),
        original_protocol_sha256=PROTOCOL,contract_sha256=request['contract_sha256'],arms=['B','R'],
        core_financial_changes=False,production_contacted=False,book_exported=known,
        utc=datetime.now(timezone.utc).isoformat(),encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='WEIGHTED_SCREEN_PASSED' else 2)

def inspect_weighted(path,name):
    need(path.is_file(),'REFUSED_R_MISSING_STOP')
    value=json.loads(path.read_bytes());need(value['Name']=='/'+name,'REFUSED_R_STOP_NAME')
    # Reuse recorded fence validation without imposing the Core-variant fourth mount.
    from baseline_prefix import worker_stage,worker_arm
    from probe import FORBIDDEN_CREDENTIALS
    h,c,s=value['HostConfig'],value['Config'],value['State']
    need(value['Image']==EXECUTION_IMAGE and not s['Running'] and s['Status']=='exited','REFUSED_R_STOP_IDENTITY')
    need(c['Labels']['research.experiment']=='capital-risk-20261027' and c['Labels']['research.stage']==worker_stage(name)
        and c['Labels']['research.arm']==worker_arm(name),'REFUSED_R_LABELS')
    need(h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['Memory']==h['MemorySwap']==2*1024**3
        and h['NanoCpus']==1000000000 and h['PidsLimit']==64 and h['CapDrop']==['ALL']
        and any(v.startswith('no-new-privileges') for v in h['SecurityOpt']),'REFUSED_R_FENCES')
    mounts={v['Destination']:v for v in value['Mounts'] if v['Type']=='bind'}
    need(set(mounts)=={'/frozen','/out','/driver'} and mounts['/out']['RW']
        and not mounts['/frozen']['RW'] and not mounts['/driver']['RW']
        and c['WorkingDir']=='/fixed' and c['User']=='1001:1001','REFUSED_R_MOUNTS')
    need(not any(v.partition('=')[0] in set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'} and v.partition('=')[2]
        for v in c['Env']),'REFUSED_R_CREDENTIALS')
    return dict(name=name,id=value['Id'],stopped=True,exit_code=s['ExitCode'],oom=s['OOMKilled'])

if __name__=='__main__':main()
