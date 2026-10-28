"""One owner-authorized matched H0/P2 job. No production contact."""
import argparse,base64,hashlib,json,os,shutil,tarfile,time
from pathlib import Path
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from weighted_job import inspect_weighted
from screen_job import encrypt
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,IMAGE,SECRET
from runtime_identity import EXECUTION_IMAGE
from probe import check_context,admitted_output,memory_bytes

HERE=Path(__file__).resolve().parent
SOURCES=('selective_policy.py','selective_journal.py','selective_input.py','selective_model.py','selective_gate.py',
    'selective_screen.py','selective_job.py','holding_account.py','holding_actions.py','holding_identity.py',
    'baseline_prefix.py','screen_job.py','weighted_job.py')
def need(v,c):
    if not v:raise ValueError(c)
def expected_request():
    return dict(schema='research.selective-comparison-request/1',id='selective-h0-p2-001',
        original_protocol_sha256=PROTOCOL,contract_sha256=sha256_file(HERE/'selective-protocol.json'),
        sources={n:sha256_file(HERE/n) for n in SOURCES},owner_scope='MATCHED_H0_THEN_ONE_UNCHANGED_P2_WITH_RETAINED_DEFENSIVE_FACTOR_PROXY')
def validate_request(r):
    need(r==expected_request(),'REFUSED_SELECTIVE_REQUEST')
    p=json.loads((HERE/'selective-protocol.json').read_bytes())
    need(p['id']=='selective-h0-p2-001' and p['worker_deadline_seconds']==420 and p['baseline_readiness_seconds']==120
        and p['measured_closes']==4639 and p['formation_records']==126 and p['capital']=='50000'
        and p['defensive_model']=='BIL_TOTAL_RETURN_FACTOR_CASH_PROXY' and not p['parameter_search'] and not p['production_contacted'],'REFUSED_SELECTIVE_PROTOCOL')
def admit_prior(download,destination,key):
    rpath=download/'holding-action-price.json';need(sha256_file(rpath)=='12f252589e6ddff4f1d3b7bca7e63df5d304e5d4be527ab4165a91657eb2a3f1','REFUSED_QUAL_RECEIPT_BYTES')
    r=json.loads(rpath.read_bytes())
    need(r['run_id']=='40706014951' and r['source_commit']=='64f241d49c8d3fc5128a54deda0d435498d50089'
        and r['status']=='ACTION_PRICE_QUALIFICATION_COMPLETE' and r['known_stopped'] and not r['production_contacted'],'REFUSED_QUAL_SCOPE')
    spec=r['encrypted_output'];need(spec==dict(name='holding-action-price.tar.crseal',bytes=115875876,sha256='50d61f88de94b551c406e66c7e996365e13f5a28cf821a83930138a0755781e8'),'REFUSED_QUAL_CIPHER')
    asset=download/spec['name'];need(asset.stat().st_size==spec['bytes'],'REFUSED_QUAL_CIPHER_SIZE')
    plain=destination.parent/'selective-qualified.tar';decrypt(asset,plain,key,spec['sha256'])
    manifest_sha='b22a2e50dfde8737827cc05e35eba4a9200e229b82651e2c16d13ba2aa171793'
    m=extract_verified(plain,destination,manifest_sha,expected_schema='research.capital-risk-output/1')
    need(m['arm']=='HOLDING_QUAL' and m['stage']=='holding-qualification' and m['protocol_sha256']==PROTOCOL
        and m['screen_protocol_sha256']=='5546a0e6d113876ce67af28078d9205aa2cd773b9f17684dd3e028be9507d7f2' and len(m['members'])==11,'REFUSED_QUAL_MANIFEST')
    name='capital-risk-holding-qual-40706014951-1';stop=inspect_weighted(destination/(name+'-inspect.json'),name)
    need(stop['exit_code']==0 and not stop['oom'],'REFUSED_QUAL_STOP')
    identities=json.loads((destination/'driver-identities.json').read_bytes())
    for n in ('holding_account.py','holding_actions.py','holding_identity.py'):need(identities[n]==sha256_file(HERE/n),'REFUSED_CHANGED_QUALIFIED_ACCOUNT')
    for path in destination.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(destination,0o555)
    return dict(run_id=40706014951,receipt_sha256=sha256_file(rpath),ciphertext=spec,manifest_sha256=manifest_sha,
        inventory_members=11,actual_stop=stop,authenticated_before_parsing=True,qualified_account_source_unchanged=True)

def command(name,frozen,qualified,private):
    args=launch_arguments(name,frozen,private,HERE);cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['--mount',f'type=bind,source={qualified},target=/qualified,readonly','-e','HOLDING_QUAL_HOSTED=1']+args[cut:cut+1]+[
        '-B','-u','/driver/selective_screen.py','--root','/frozen/baseline-comparison','--bundle','/frozen/bundle',
        '--qualified','/qualified','--output','/out/comparison','--protocol','/driver/selective-protocol.json']

def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','qualification-download','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();check_context(os.environ);need(os.environ['GITHUB_RUN_ATTEMPT']=='1','REFUSED_SELECTIVE_RERUN')
    request=json.loads(a.request.read_bytes());validate_request(request);s=json.loads(a.staging_receipt.read_bytes())
    need(s['status']=='STAGING_PASSED' and s['source_commit']==os.environ['GITHUB_SHA'] and s['run_id']==os.environ['GITHUB_RUN_ID']
        and s['protocol_sha256']==PROTOCOL and s['runtime_image']==IMAGE and s['execution_image']==EXECUTION_IMAGE
        and s['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and s['source_files_verified']==514 and s['members_verified']==591 and not s['replay_started']
        and all(s[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified')),'REFUSED_SELECTIVE_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_SELECTIVE_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_SELECTIVE_CAPACITY')
    qualified=temp/'selective-qualified-001';proof=admit_prior(a.qualification_download,qualified,key)
    for path in frozen.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(frozen,0o555);private=temp/'selective-h0-p2-001';private.mkdir(mode=0o700,exist_ok=False)
    (private/'driver-identities.json').write_text(json.dumps({q.name:sha256_file(q) for q in HERE.glob('*.py')},indent=2)+'\n')
    (private/'qualification-admission.json').write_text(json.dumps(proof,indent=2)+'\n');(private/'request.json').write_bytes(a.request.read_bytes())
    name='capital-risk-h0p2-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'];known=False;status='H0_P2_COMPARISON_REFUSED';error=None
    try:
        run_worker(command(name,frozen,qualified,private),name,private,deadline=420)
        stop=inspect_weighted(private/(name+'-inspect.json'),name);known=True
        need(stop['exit_code']==0 and not stop['oom'],'REFUSED_SELECTIVE_OUTCOME')
        result=json.loads((private/'comparison/summary.json').read_bytes())
        need(result['status']=='H0_P2_COMPARISON_COMPLETE' and result['measured_records']==4639 and result['months']==222
            and result['defensive_model']=='BIL_TOTAL_RETURN_FACTOR_CASH_PROXY' and not result['production_contacted'],'REFUSED_SELECTIVE_OUTPUT')
        status='H0_P2_COMPARISON_COMPLETE'
    except UnprovenStopped as exc:status='WRITER_STOP_UNKNOWN';error=dict(type=type(exc).__name__,message=str(exc))
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        try:inspect_weighted(private/(name+'-inspect.json'),name);known=True
        except Exception:status='WRITER_STOP_UNKNOWN'
    diagnostic=private/'diagnostics';diagnostic.mkdir();(diagnostic/'outcome.json').write_text(json.dumps(dict(status=status,error=error,proven_stopped=known),indent=2)+'\n')
    out=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);out.parent.mkdir(parents=True,exist_ok=True);asset=out.parent/'selective-comparison.tar.crseal'
    encrypt(private if known else diagnostic,asset,key,request['contract_sha256'],arm='H0P2',stage='holding-comparison');key=None
    receipt=dict(schema='research.selective-comparison-receipt/1',status=status,run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(a.request),contract_sha256=request['contract_sha256'],original_protocol_sha256=PROTOCOL,
        known_stopped=known,qualification_run=40706014951,production_contacted=False,parameter_search=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if status=='H0_P2_COMPARISON_COMPLETE' else 2)

if __name__=='__main__':main()
