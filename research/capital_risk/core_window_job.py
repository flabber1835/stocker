"""One dedicated hosted VM per short window; four disjoint canonical books."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil

from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from build_core_variants import build
from core_gate_job import gate_command
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,SECRET,IMAGE

WINDOWS={'stress2021':('stress-2021','2021-01-04','2022-12-30',503),
         'recent2025':('recent-2025','2025-01-02','2026-07-31',395)}
POLICIES={'B':'wealth-core-v5-zero-share-fixed-2008-v1','B0':'wealth-core-v5-zero-share-fixed-2008-v1',
          'C':'wealth-core-capital-risk-c-v1','V':'wealth-core-capital-risk-v-v1'}
HERE=Path(__file__).resolve().parent


def validate_request(value):
    expected=dict(schema='research.capital-risk-window-request/1',request_id='short-core-windows-001',
        stage='short-core-window',core_protocol_sha256=sha256_file(HERE/'core-screen-protocol.json'),
        execution_sha256=sha256_file(HERE/'core-window-execution.json'),
        gate_admission_sha256=sha256_file(HERE/'core-gate-admission.json'))
    if value!=expected:raise ValueError('REFUSED_CORE_WINDOW_REQUEST')
    execution=json.loads((HERE/'core-window-execution.json').read_bytes())
    if (execution['arms']!=list(POLICIES) or execution['worker_deadline_seconds']!=6300
            or execution['private_workers_per_job']!=4 or execution['job_timeout_minutes']!=150
            or execution['hosted_window_jobs_parallel']!=2
            or execution['windows']!={k:list(v[1:]) for k,v in WINDOWS.items()}):
        raise ValueError('REFUSED_WINDOW_EXECUTION_CONTRACT')
    admission=json.loads((HERE/'core-gate-admission.json').read_bytes())
    if (admission['run_id']!=40557354045 or admission['source_commit']!='6a9588e32920a98e418331bc4a1b0fa784ed8b7f'
            or admission['cases']!=12 or not admission['actual_encrypted_evidence_verified']
            or admission['core_protocol_sha256']!=expected['core_protocol_sha256']):
        raise ValueError('REFUSED_CORE_GATE_ADMISSION')
    return expected,admission


def window_command(name,frozen,output,driver,variant,window,tail):
    args=launch_arguments(name,frozen,output,driver)
    args[args.index('/fixed')]='/variant'
    args[args.index('PYTHONPATH=/fixed:/fixed/shared')]='PYTHONPATH=/variant:/variant/shared:/driver'
    cut=args.index(EXECUTION_IMAGE)
    return args[:cut]+['-e','CAPITAL_RISK_WINDOW='+WINDOWS[window][0],
        '--mount',f'type=bind,source={variant},target=/variant,readonly']+args[cut:cut+1]+['-B','-u']+tail


def main():
    parser=argparse.ArgumentParser()
    for n in ('request','staging-receipt','output'):parser.add_argument('--'+n,required=True,type=Path)
    parser.add_argument('--window',choices=WINDOWS,required=True);args=parser.parse_args()
    check_context(os.environ)
    if os.environ.get('GITHUB_RUN_ATTEMPT')!='1':raise ValueError('REFUSED_FRESH_WINDOW_RERUN')
    request,admission=validate_request(json.loads(args.request.read_bytes()))
    proof=json.loads(args.staging_receipt.read_bytes())
    if (proof['status']!='STAGING_PASSED' or proof['source_commit']!=os.environ['GITHUB_SHA']
            or proof['run_id']!=os.environ['GITHUB_RUN_ID'] or proof['protocol_sha256']!=PROTOCOL
            or proof['runtime_image']!=IMAGE or proof['execution_image']!=EXECUTION_IMAGE
            or proof['manifest_sha256']!='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
            or proof['source_files_verified']!=514 or proof['members_verified']!=591
            or not all(proof[k] for k in ('runtime_index_config_layer_chain_verified',
                'authenticated_before_parsing','offline_image_source_verified')) or proof['replay_started']):
        raise ValueError('REFUSED_WINDOW_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    if len(key)!=32:raise ValueError('REFUSED_RESEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-risk-window-output';private.mkdir(mode=0o700,exist_ok=False)
    qual=private/'qualification';qual.mkdir()
    sources=temp/'capital-risk-window-sources'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),args.output);output.parent.mkdir(parents=True,exist_ok=True)
    prefix='capital-risk-core-window-'+args.window+'-'
    identity=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    env,start,end,closes=WINDOWS[args.window]
    status,error='SHORT_WINDOW_PASSED',None
    bindings={};arm_outputs={};unknown=False
    try:
        for phase,risk in (('basis',False),('risk',True)):
            variant=sources/phase;bindings[phase]=build(frozen/'source-fixed',variant,risk=risk)
            for p in variant.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
            os.chmod(variant,0o555)
            if risk:
                for name,digest in admission['qualified_component_sha256'].items():
                    if sha256_file(variant/name)!=digest:raise ValueError('REFUSED_QUALIFIED_COMPONENT_CHANGE')
            name='capital-risk-core-gate-'+identity+'-'+phase
            run_worker(gate_command(name,frozen,qual,HERE,variant,phase),name,qual,deadline=300)
        actual=json.loads((qual/'canonical-gate.json').read_bytes())
        if actual['status']!='CANONICAL_CORE_GATE_PASSED' or actual['cases']!=15:
            raise ValueError('REFUSED_OBSERVED_CANONICAL_GATE')
        name=prefix+'b-'+identity+'-input'
        command=window_command(name,frozen,qual,HERE,sources/'basis',args.window,
            ['/driver/core_window_inputs.py','--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
             '--start',start,'--end',end,'--output','/out/input-equivalence.json'])
        run_worker(command,name,qual,deadline=600)
        if (os.cpu_count() or 0)<4 or memory_bytes()['MemAvailable']<10*1024**3 or shutil.disk_usage(temp).free<20*1024**3:
            raise ValueError('REFUSED_FOUR_BOOK_RESOURCE_GATE')
        (qual/'source-bindings.json').write_text(json.dumps(bindings,indent=2)+'\n')
        def financial(arm):
            armout=private/arm;armout.mkdir();arm_outputs[arm]=armout
            name=prefix+arm.lower()+'-'+identity
            variant=sources/('basis' if arm=='B' else 'risk')
            tail=['-m','research.pooled_vacancy_funding.backtest','--policy',POLICIES[arm],
                '--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
                '--previous','/frozen/references/owned55','--compact','/frozen/references/compact/champion-daily.csv',
                '--output','/out/run-001','--max-transitions',str(126+closes)]
            run_worker(window_command(name,frozen,armout,HERE,variant,args.window,tail),name,armout,deadline=6300)
            result=json.loads((armout/'run-001/result.json').read_bytes())
            if result['status']!='COMPLETE_PENDING_REVIEW':raise ValueError('REFUSED_INCOMPLETE_WINDOW_'+arm)
        failures=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(financial,a):a for a in POLICIES}
            for future in as_completed(futures):
                try:future.result()
                except UnprovenStopped:unknown=True
                except Exception as exc:failures.append(dict(arm=futures[future],type=type(exc).__name__,message=str(exc)))
        if unknown:raise UnprovenStopped('PRIVATE_WINDOW_WRITER_UNKNOWN')
        if failures:
            (qual/'financial-failures.json').write_text(json.dumps(failures,indent=2)+'\n')
            raise ValueError('REFUSED_ONE_OR_MORE_WINDOW_BOOKS')
        for arm,armout in arm_outputs.items():
            name=prefix+arm.lower()+'-'+identity+'-review'
            variant=sources/('basis' if arm=='B' else 'risk')
            command=window_command(name,frozen,armout,HERE,variant,args.window,
                ['/driver/core_window_review.py','--root','/out/run-001','--output','/out/independent-review.json'])
            run_worker(command,name,armout,deadline=600)
        from core_window_review import compare_disabled
        equality=compare_disabled(private/'B/run-001',private/'B0/run-001')
        (qual/'disabled-equivalence.json').write_text(json.dumps(equality,indent=2)+'\n')
    except UnprovenStopped:
        output.write_text(json.dumps(dict(status='WRITER_STOP_UNKNOWN',encrypted_outputs=[],
            run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],window=args.window,
            production_contacted=False))+'\n');raise SystemExit(2)
    except Exception as exc:
        status,error='SHORT_WINDOW_REFUSED',type(exc).__name__
        (qual/'failure.json').write_text(json.dumps(dict(type=error,message=str(exc)))+'\n')
    assets=[]
    for arm,root in [('QUAL',qual),*sorted(arm_outputs.items())]:
        asset=output.parent/('window-'+args.window+'-'+arm+'.tar.crseal')
        encrypt(root,asset,key,request['core_protocol_sha256'],arm=arm,stage='short-core-window')
        assets.append(dict(arm=arm,name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    key=None
    receipt=dict(schema='research.capital-risk-window-receipt/1',status=status,error_type=error,
        utc=datetime.now(timezone.utc).isoformat(),source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
        request_id='short-core-windows-001',window=args.window,core_protocol_sha256=request['core_protocol_sha256'],
        execution_sha256=request['execution_sha256'],production_contacted=False,encrypted_outputs=assets)
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='SHORT_WINDOW_PASSED' else 2)


if __name__=='__main__':main()
