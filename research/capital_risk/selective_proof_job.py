"""Single synthetic launcher/component proof; financial request stays untouched."""
import argparse,base64,json,os,shutil
from pathlib import Path
from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from weighted_job import inspect_weighted
from seal import sha256_file
from screen_job import encrypt
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from probe import check_context,admitted_output

HERE=Path(__file__).resolve().parent
SOURCES=('baseline_prefix.py','weighted_job.py','selective_model.py','selective_policy.py','selective_input.py',
         'selective_gate.py','selective_launcher_proof.py','selective_proof_job.py')
def need(v,c):
    if not v:raise ValueError(c)
def expected():return dict(schema='research.selective-launcher-proof-request/1',id='selective-launcher-proof-001',
    failed_run=40714748373,historical_financial_accounts=0,production_contacted=False,
    sources={n:sha256_file(HERE/n) for n in SOURCES})
def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();check_context(os.environ);need(os.environ['GITHUB_RUN_ATTEMPT']=='1','REFUSED_PROOF_RERUN')
    need(json.loads(a.request.read_bytes())==expected(),'REFUSED_PROOF_REQUEST')
    stage=json.loads(a.staging_receipt.read_bytes());need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL and stage['runtime_image']==IMAGE
        and stage['execution_image']==EXECUTION_IMAGE and stage['members_verified']==591 and stage['source_files_verified']==514,'REFUSED_PROOF_INPUTS')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_PROOF_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';qualified=temp/'selective-proof-readonly'
    qualified.mkdir();(qualified/'readme.txt').write_text('Synthetic mount proof only.\n')
    private=temp/'selective-launcher-proof-001';private.mkdir(mode=0o700,exist_ok=False)
    (private/'request.json').write_bytes(a.request.read_bytes());(private/'driver-identities.json').write_text(json.dumps({p.name:sha256_file(p) for p in HERE.glob('*.py')},indent=2)+'\n')
    name='capital-risk-h0p2-proof-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    args=launch_arguments(name,frozen,private,HERE);cut=args.index(EXECUTION_IMAGE)
    args=args[:cut]+['--mount',f'type=bind,source={qualified},target=/qualified,readonly','-e','HOLDING_QUAL_HOSTED=1']+args[cut:cut+1]+['-B','-u','/driver/selective_launcher_proof.py']
    known=False;status='SYNTHETIC_LAUNCHER_PROOF_REFUSED';error=None
    try:
        run_worker(args,name,private,deadline=60);stop=inspect_weighted(private/(name+'-inspect.json'),name);known=True
        need(stop['exit_code']==0 and not stop['oom'],'PROOF_ACTUAL_STOP')
        result=json.loads((private/'proof/summary.json').read_bytes());need(result['status']=='SYNTHETIC_LAUNCHER_PROOF_PASSED'
            and result['historical_financial_accounts_started']==0 and not result['production_contacted'],'PROOF_RESULT')
        status='SYNTHETIC_LAUNCHER_PROOF_PASSED'
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
        try:inspect_weighted(private/(name+'-inspect.json'),name);known=True
        except Exception:status='WRITER_STOP_UNKNOWN'
    diagnostic=private/'diagnostics';diagnostic.mkdir();(diagnostic/'outcome.json').write_text(json.dumps(dict(status=status,error=error,known_stopped=known),indent=2)+'\n')
    out=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);out.parent.mkdir(parents=True,exist_ok=True)
    asset=out.parent/'selective-launcher-proof.tar.crseal';encrypt(private if known else diagnostic,asset,key,sha256_file(a.request),arm='H0P2',stage='holding-comparison');key=None
    receipt=dict(schema='research.selective-launcher-proof-receipt/1',status=status,run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(a.request),known_stopped=known,historical_financial_accounts=0,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if status=='SYNTHETIC_LAUNCHER_PROOF_PASSED' else 2)
if __name__=='__main__':main()
