"""One owner-approved bounded hosted B/B0/C trial; never PAPER."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil

from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from concentration_build import build_quarter,ENV,START,END,CLOSES
from core_gate_job import gate_command
from core_recovery_job import inspect_stopped,readonly
from core_window_review import compare_disabled
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,SECRET,IMAGE

HERE=Path(__file__).resolve().parent
POLICIES={'B':'wealth-core-v5-zero-share-fixed-2008-v1','B0':'wealth-core-v5-zero-share-fixed-2008-v1','C':'wealth-core-capital-risk-c-v1'}
BIND=('concentration_build.py','concentration_review.py','concentration_job.py','build_core_variants.py','core_policy.py','baseline_prefix.py','core_window_review.py','canonical_core_gate.py','core_window_inputs.py','core_manifest.py','core_accounting_snapshot.py')

def require(v,code):
    if not v:raise ValueError(code)

def expected_request():
    return dict(schema='research.concentration-quarter-request/1',request_id='concentration-quarter-001',
        stage='short-core-window',owner_scope='APPROVE_C_WORKFLOW_AND_ENCRYPTED_GITHUB_ARTIFACTS',
        protocol_sha256=sha256_file(HERE/'concentration-quarter-protocol.json'),
        original_core_protocol_sha256=sha256_file(HERE/'core-screen-protocol.json'),
        source_bindings={name:sha256_file(HERE/name) for name in BIND})

def validate_request(value):
    require(value==expected_request(),'REFUSED_C_QUARTER_REQUEST')
    p=json.loads((HERE/'concentration-quarter-protocol.json').read_bytes())
    require(p['arms']==list(POLICIES) and p['window']==[START,END,CLOSES]
        and p['worker_wait_seconds']==1200 and p['review_wait_seconds']==300 and p['workflow_timeout_minutes']==45
        and p['feature_sessions']==299 and p['formation_sessions']==126 and p['capital']=='50000'
        and p['own_fresh_origin_each_arm'] and not p['production_contacted'] and not p['automatic_extension']
        and not p['parameter_sweep'],'REFUSED_C_QUARTER_PROTOCOL')
    return p

def command(name,frozen,out,variant,tail):
    args=launch_arguments(name,frozen,out,HERE);args[args.index('/fixed')]='/variant'
    args[args.index('PYTHONPATH=/fixed:/fixed/shared')]='PYTHONPATH=/variant:/variant/shared:/driver'
    cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['-e','CAPITAL_RISK_WINDOW='+ENV,'--mount',f'type=bind,source={variant},target=/variant,readonly']+args[cut:cut+1]+['-B','-u']+tail

def snapshot_outputs(qual,outputs,known,unknown,*,qualification_unknown=False):
    return ([] if qualification_unknown else [('QUAL',qual)])+[(arm,outputs[arm]) for arm in sorted(known) if arm not in unknown]

def main():
    p=argparse.ArgumentParser()
    for name in ('request','staging-receipt','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();check_context(os.environ)
    require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_C_QUARTER_FRESH_RERUN')
    request=json.loads(a.request.read_bytes());validate_request(request)
    proof=json.loads(a.staging_receipt.read_bytes())
    require(proof['status']=='STAGING_PASSED' and proof['run_id']==os.environ['GITHUB_RUN_ID']
        and proof['source_commit']==os.environ['GITHUB_SHA'] and proof['protocol_sha256']==PROTOCOL
        and proof['runtime_image']==IMAGE and proof['execution_image']==EXECUTION_IMAGE
        and proof['source_files_verified']==514 and proof['members_verified']==591
        and proof['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and all(proof[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified'))
        and proof['replay_started'] is False,'REFUSED_C_QUARTER_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);require(len(key)==32,'REFUSED_C_QUARTER_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-concentration-quarter-001';private.mkdir(mode=0o700,exist_ok=False)
    qual=private/'qualification';qual.mkdir();sources=temp/'capital-concentration-quarter-sources'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    identity=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'];prefix='capital-risk-core-window-cq12025-'
    bindings={};outputs={};known={};unknown=[];reviewed=[];failures=[];qual_unknown=False
    status='C_QUARTER_REFUSED';financial_started=False
    (qual/'request.json').write_bytes(a.request.read_bytes())
    (qual/'protocol.json').write_bytes((HERE/'concentration-quarter-protocol.json').read_bytes())
    (qual/'driver-identities.json').write_text(json.dumps({x.name:sha256_file(x) for x in sorted(HERE.glob('*.py'))},indent=2)+'\n')
    try:
        readonly(frozen)
        for phase,risk in (('basis',False),('risk',True)):
            variant=sources/phase;bindings[phase]=build_quarter(frozen/'source-fixed',variant,risk=risk);readonly(variant)
            name='capital-risk-core-gate-'+identity+'-'+phase
            try:run_worker(gate_command(name,frozen,qual,HERE,variant,phase),name,qual,deadline=90)
            except UnprovenStopped:qual_unknown=True;raise
        gate=json.loads((qual/'canonical-gate.json').read_bytes())
        require(gate['status']=='CANONICAL_CORE_GATE_PASSED' and gate['cases']==15,'REFUSED_C_QUARTER_CANONICAL_GATE')
        (qual/'source-bindings.json').write_text(json.dumps(bindings,indent=2)+'\n')
        name=prefix+'b-'+identity+'-input'
        tail=['/driver/core_window_inputs.py','--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
            '--start',START,'--end',END,'--output','/out/input-equivalence.json']
        try:run_worker(command(name,frozen,qual,sources/'basis',tail),name,qual,deadline=180)
        except UnprovenStopped:qual_unknown=True;raise
        require(json.loads((qual/'input-equivalence.json').read_bytes())['status']=='BOUNDED_INPUT_BOUNDARIES_MATCHED','REFUSED_C_QUARTER_INPUTS')
        require((os.cpu_count() or 0)>=4 and memory_bytes()['MemAvailable']>=8*1024**3
            and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_C_QUARTER_CAPACITY')
        def financial(arm):
            root=outputs[arm];name=prefix+arm.lower()+'-'+identity
            tail=['-m','research.pooled_vacancy_funding.backtest','--policy',POLICIES[arm],
                '--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
                '--previous','/frozen/references/owned55','--compact','/frozen/references/compact/champion-daily.csv',
                '--output','/out/run-001','--max-transitions',str(126+CLOSES)]
            run_worker(command(name,frozen,root,sources/('basis' if arm=='B' else 'risk'),tail),name,root,deadline=1200)
        for arm in POLICIES:outputs[arm]=private/arm;outputs[arm].mkdir()
        financial_started=True
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(financial,arm):arm for arm in POLICIES}
            for future in as_completed(futures):
                arm=futures[future]
                try:future.result()
                except UnprovenStopped:unknown.append(arm)
                except Exception as exc:failures.append(dict(arm=arm,phase='worker',type=type(exc).__name__,message=str(exc)))
        candidates=[]
        for arm,root in outputs.items():
            if arm in unknown:continue
            inspection=root/(prefix+arm.lower()+'-'+identity+'-inspect.json')
            try:known[arm]=inspect_stopped(inspection,sha256_file(inspection),allow_oom=True)
            except Exception as exc:
                unknown.append(arm);failures.append(dict(arm=arm,phase='stop_receipt',type=type(exc).__name__));continue
            if not known[arm]['oom'] and known[arm]['exit_code']==0 and (root/'run-001/checkpoint.json.gz').is_file():candidates.append(arm)
        def review_arm(arm):
            root=outputs[arm];name=prefix+arm.lower()+'-'+identity+'-review'
            tail=['/driver/concentration_review.py','--root','/out/run-001','--output','/out/independent-review.json']
            run_worker(command(name,frozen,root,sources/('basis' if arm=='B' else 'risk'),tail),name,root,deadline=300)
            result=json.loads((root/'independent-review.json').read_bytes())
            require(result['status'] in ('C_QUARTER_COMPLETE_REVIEW_PASSED','C_QUARTER_PARTIAL_PREFIX_REVIEW_PASSED'),'REFUSED_C_QUARTER_REVIEW')
            return result
        reviews={}
        require(not candidates or memory_bytes()['MemAvailable']>=8*1024**3,'REFUSED_C_QUARTER_REVIEW_CAPACITY')
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(review_arm,arm):arm for arm in candidates}
            for future in as_completed(futures):
                arm=futures[future]
                try:reviews[arm]=future.result();reviewed.append(arm)
                except UnprovenStopped:unknown.append(arm);known.pop(arm,None)
                except Exception as exc:failures.append(dict(arm=arm,phase='review',type=type(exc).__name__,message=str(exc)))
        if set(reviews)==set(POLICIES) and all(x['complete'] for x in reviews.values()):
            equality=compare_disabled(outputs['B']/'run-001',outputs['B0']/'run-001')
            (qual/'disabled-equivalence.json').write_text(json.dumps(equality,indent=2)+'\n')
            status='C_QUARTER_COMPLETE_PENDING_LOCAL_REVIEW'
        elif reviews:status='C_QUARTER_INCOMPLETE_PRESERVED'
        if unknown:status='WRITER_STOP_UNKNOWN'
        (qual/'arm-outcomes.json').write_text(json.dumps(dict(stopped=known,reviewed=reviewed,unknown=unknown,failures=failures),indent=2)+'\n')
    except Exception as exc:
        status='WRITER_STOP_UNKNOWN' if qual_unknown or unknown else 'C_QUARTER_REFUSED'
        if not qual_unknown:(qual/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    assets=[]
    for arm,root in snapshot_outputs(qual,outputs,known,unknown,qualification_unknown=qual_unknown):
        asset=output.parent/('concentration-quarter-'+arm+'.tar.crseal')
        encrypt(root,asset,key,request['protocol_sha256'],arm=arm,stage='short-core-window')
        assets.append(dict(arm=arm,name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    key=None
    receipt=dict(schema='research.concentration-quarter-receipt/1',status=status,run_id=os.environ['GITHUB_RUN_ID'],
        source_commit=os.environ['GITHUB_SHA'],request_sha256=sha256_file(a.request),protocol_sha256=request['protocol_sha256'],
        original_core_protocol_sha256=request['original_core_protocol_sha256'],window=[START,END,CLOSES],
        financial_replay_started=financial_started,unknown_arms=unknown,qualification_unknown=qual_unknown,
        production_contacted=False,encrypted_outputs=assets,utc=datetime.now(timezone.utc).isoformat())
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='C_QUARTER_COMPLETE_PENDING_LOCAL_REVIEW' else 2)

if __name__=='__main__':main()
