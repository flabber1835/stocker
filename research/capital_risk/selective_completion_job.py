"""Authenticate completed controls; run missing work on the unchanged financial source."""
import argparse,base64,hashlib,json,os,shutil
from pathlib import Path
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from weighted_job import inspect_weighted
from screen_job import encrypt
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,IMAGE,SECRET
from runtime_identity import EXECUTION_IMAGE
from probe import check_context,admitted_output,memory_bytes
from selective_job import admit_prior,need

HERE=Path(__file__).resolve().parent
CONTROL_RUN='40719685611';CONTROL_HEAD='a363edfbcc93da54d85267b7d4ba660ceb5340b2'
CONTROL_RECEIPT='838f463e6e48326977f83ce92e625ed6ff535deba6e9fc55faf71570cdb4da66'
CONTROL_CIPHER=dict(name='selective-comparison.tar.crseal',bytes=692725796,sha256='ba2d9a7c0743f83e91ef03c1a8e3c0b28a7af0e495e592b60713823f00406946')
CONTROL_MANIFEST='7cc8860fed28f8c7f35203d43273bd81af62bd4bf829640f864cc418501c2e06'

def expected_request():
    basis=json.loads((HERE/'selective-completion-basis.json').read_bytes())
    return dict(schema='research.selective-completion-request/1',id='selective-h0-p2-completion-001',
        original_protocol_sha256=PROTOCOL,financial_protocol_sha256=sha256_file(HERE/'selective-protocol.json'),
        basis_sha256=sha256_file(HERE/'selective-completion-basis.json'),
        execution_sources={n:sha256_file(HERE/n) for n in ('selective_completion.py','selective_completion_job.py')},
        control_run=CONTROL_RUN,control_head=CONTROL_HEAD,control_manifest=CONTROL_MANIFEST,
        independent_control_review_sha256=basis['independent_control_review_sha256'],worker_deadline_seconds=600,
        owner_scope='FINISH_SAME_P2_AND_EXACT_SUFFIX_CHECKS_REUSE_COMPLETE_CONTROLS_NO_ROUTINE_APPROVAL_STOPS')

def validate_request(r):
    need(r==expected_request(),'REFUSED_COMPLETION_REQUEST')
    basis=json.loads((HERE/'selective-completion-basis.json').read_bytes())
    for n,h in basis['original_drivers'].items():need(sha256_file(HERE/n)==h,'REFUSED_CHANGED_FINANCIAL_OR_ORIGINAL_DRIVER_'+n)
    need(len(basis['original_drivers'])==65,'REFUSED_ORIGINAL_DRIVER_COUNT')
    return basis

def admit_controls(download,destination,key,basis):
    rp=download/'selective-comparison.json';need(sha256_file(rp)==CONTROL_RECEIPT,'REFUSED_CONTROL_RECEIPT_BYTES');r=json.loads(rp.read_bytes())
    need(r['run_id']==CONTROL_RUN and r['source_commit']==CONTROL_HEAD and r['status']=='H0_P2_COMPARISON_REFUSED'
        and r['known_stopped'] and not r['production_contacted'] and r['encrypted_output']==CONTROL_CIPHER,'REFUSED_CONTROL_SCOPE')
    asset=download/CONTROL_CIPHER['name'];need(asset.stat().st_size==CONTROL_CIPHER['bytes'],'REFUSED_CONTROL_CIPHER_LENGTH')
    plain=destination.parent/'completed-controls.tar';decrypt(asset,plain,key,CONTROL_CIPHER['sha256'])
    m=extract_verified(plain,destination,CONTROL_MANIFEST,expected_schema='research.capital-risk-output/1')
    need(m['arm']=='H0P2' and m['stage']=='holding-comparison' and m['protocol_sha256']==PROTOCOL
        and m['screen_protocol_sha256']==sha256_file(HERE/'selective-protocol.json') and len(m['members'])==1866
        and not any(n.startswith('comparison/P2') for n in m['members']),'REFUSED_CONTROL_MANIFEST_OR_P2_ORIGIN')
    name='capital-risk-h0p2-'+CONTROL_RUN+'-1';stop=inspect_weighted(destination/(name+'-inspect.json'),name)
    need(stop['exit_code']==1 and not stop['oom'],'REFUSED_CONTROL_STOP')
    need(json.loads((destination/'driver-identities.json').read_bytes())==basis['original_drivers'],'REFUSED_CONTROL_DRIVER_BASIS')
    for n,h in basis['control_files'].items():need(sha256_file(destination/n)==h,'REFUSED_EXACT_ADMITTED_CONTROL_FILE_'+n)
    log=(destination/(name+'.log')).read_text();need('REFUSED_BASELINE_READINESS_BUDGET' in log,'REFUSED_CONTROL_FAILURE_CLASS')
    proof=dict(status='EXACT_COMPLETED_CONTROLS_AUTHENTICATED',run_id=CONTROL_RUN,head=CONTROL_HEAD,
        receipt_sha256=CONTROL_RECEIPT,ciphertext=CONTROL_CIPHER,manifest_sha256=CONTROL_MANIFEST,inventory_members=1866,
        actual_stop=stop,original_driver_count=65,original_P2_origin_absent=True,
        independent_review_sha256=basis['independent_control_review_sha256'],original_gate_failed=True,
        owner_amendment_accepts_complete_financial_evidence=True)
    return proof

def command(name,frozen,qualified,private):
    args=launch_arguments(name,frozen,private,HERE);cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['--mount',f'type=bind,source={qualified},target=/qualified,readonly','-e','HOLDING_QUAL_HOSTED=1']+args[cut:cut+1]+[
        '-B','-u','/driver/selective_completion.py','--root','/frozen/baseline-comparison','--bundle','/frozen/bundle',
        '--qualified','/qualified/price','--controls','/qualified/controls','--output','/out/comparison','--protocol','/driver/selective-protocol.json']

def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','qualification-download','control-download','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();check_context(os.environ);need(os.environ['GITHUB_RUN_ATTEMPT']=='1','REFUSED_COMPLETION_FRESH_RERUN')
    request=json.loads(a.request.read_bytes());basis=validate_request(request);s=json.loads(a.staging_receipt.read_bytes())
    need(s['status']=='STAGING_PASSED' and s['source_commit']==os.environ['GITHUB_SHA'] and s['run_id']==os.environ['GITHUB_RUN_ID']
        and s['protocol_sha256']==PROTOCOL and s['runtime_image']==IMAGE and s['execution_image']==EXECUTION_IMAGE
        and s['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and s['source_files_verified']==514 and s['members_verified']==591 and not s['replay_started']
        and all(s[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified')),'REFUSED_COMPLETION_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_COMPLETION_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(memory_bytes()['MemAvailable']>=4*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_COMPLETION_CAPACITY')
    qualified=temp/'selective-completion-qualified';qualified.mkdir(mode=0o700)
    price=admit_prior(a.qualification_download,qualified/'price',key)
    controls=admit_controls(a.control_download,qualified/'controls',key,basis)
    for root in (frozen,qualified):
        for path in root.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
        os.chmod(root,0o555)
    private=temp/'selective-completion-output';private.mkdir(mode=0o700)
    (private/'driver-identities.json').write_text(json.dumps({q.name:sha256_file(q) for q in HERE.glob('*.py')},indent=2)+'\n')
    (private/'qualification-admission.json').write_text(json.dumps(price,indent=2)+'\n')
    (private/'completed-control-admission.json').write_text(json.dumps(controls,indent=2)+'\n')
    (private/'request.json').write_bytes(a.request.read_bytes())
    name='capital-risk-h0p2-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'];known=False;status='H0_P2_COMPLETION_REFUSED';error=None
    try:
        run_worker(command(name,frozen,qualified,private),name,private,deadline=600)
        stop=inspect_weighted(private/(name+'-inspect.json'),name);known=True
        need(stop['exit_code']==0 and not stop['oom'],'REFUSED_COMPLETION_OUTCOME')
        result=json.loads((private/'comparison/summary.json').read_bytes())
        need(result['status']=='H0_P2_COMPARISON_COMPLETE' and result['measured_records']==4639 and result['months']==222
            and result['reused_control_run']==40719685611 and result['neutral_accounts_replayed']==0 and not result['production_contacted'],'REFUSED_COMPLETION_OUTPUT')
        status='H0_P2_COMPARISON_COMPLETE'
    except UnprovenStopped as exc:status='WRITER_STOP_UNKNOWN';error=dict(type=type(exc).__name__,message=str(exc))
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        try:inspect_weighted(private/(name+'-inspect.json'),name);known=True
        except Exception:status='WRITER_STOP_UNKNOWN'
    diagnostic=private/'diagnostics';diagnostic.mkdir();(diagnostic/'outcome.json').write_text(json.dumps(dict(status=status,error=error,proven_stopped=known),indent=2)+'\n')
    out=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);out.parent.mkdir(parents=True,exist_ok=True);asset=out.parent/'selective-completion.tar.crseal'
    contract=sha256_file(a.request);encrypt(private if known else diagnostic,asset,key,contract,arm='H0P2',stage='holding-comparison');key=None
    receipt=dict(schema='research.selective-completion-receipt/1',status=status,run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],
        request_sha256=contract,financial_protocol_sha256=request['financial_protocol_sha256'],original_protocol_sha256=PROTOCOL,
        known_stopped=known,reused_control_run=CONTROL_RUN,production_contacted=False,parameter_search=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if status=='H0_P2_COMPARISON_COMPLETE' else 2)

if __name__=='__main__':main()
