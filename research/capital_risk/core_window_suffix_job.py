"""Bounded first economic suffix from independently admitted own warmup candidates."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

from baseline_prefix import run_worker,UnprovenStopped
from build_core_variants import build
from core_recovery_job import inspect_stopped,readonly
from core_window_job import window_command,WINDOWS,POLICIES
from core_window_review import compare_disabled
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,SECRET,IMAGE

HERE=Path(__file__).resolve().parent
QUAL_RUN='40568817130'
QUAL_HEAD='a5a2fe4c38cf0e95e79974e7b5ea78b171ea48b3'


def require(value,code):
    if not value:raise ValueError(code)


def validate_request(r):
    require(set(r)=={'schema','request_id','stage','core_protocol_sha256','execution_sha256',
        'qualification_request_sha256','qualification_run_id','qualification_source_commit','windows'},
        'REFUSED_WINDOW_SUFFIX_REQUEST_SHAPE')
    require(r['schema']=='research.capital-risk-window-suffix-request/1' and r['request_id']=='short-core-window-suffix-001'
        and r['stage']=='short-core-window-suffix' and r['qualification_run_id']==QUAL_RUN
        and r['qualification_source_commit']==QUAL_HEAD,'REFUSED_WINDOW_SUFFIX_IDENTITY')
    for key,name in [('core_protocol_sha256','core-screen-protocol.json'),('execution_sha256','core-window-execution.json'),
        ('qualification_request_sha256','core-recovery-request.json')]:
        require(r[key]==sha256_file(HERE/name),'REFUSED_WINDOW_SUFFIX_CONTRACT_'+key)
    require(set(r['windows'])==set(WINDOWS),'REFUSED_WINDOW_SUFFIX_WINDOWS')
    for window,v in r['windows'].items():
        require(set(v)=={'artifact_id','artifact_name','receipt_sha256','ciphertext','manifest_sha256',
            'candidate_file_sha256','candidate_outer_sha256','bridge_sha256','source_bindings_sha256','canonical_cases',
            'independent_review_sha256'},
            'REFUSED_SUFFIX_QUALIFICATION_SPEC')
        require(v['artifact_name']=='capital-risk-core-recovery-qualification-'+window+'-'+QUAL_HEAD
            and v['canonical_cases']==15 and v['ciphertext']['name']=='recovery-qualification-'+window+'.tar.crseal',
            'REFUSED_SUFFIX_QUALIFICATION_SCOPE')


def restore_qualified(request,window,download,destination,key):
    spec=request['windows'][window];receipt_path=download/'recovery-qualification.json'
    require(sha256_file(receipt_path)==spec['receipt_sha256'],'REFUSED_QUALIFICATION_RECEIPT_BYTES')
    receipt=json.loads(receipt_path.read_bytes())
    require(receipt['schema']=='research.capital-risk-recovery-qualification-receipt/1'
        and receipt['status']=='RECOVERY_QUALIFICATION_PASSED' and receipt['run_id']==QUAL_RUN
        and receipt['source_commit']==QUAL_HEAD and receipt['window']==window
        and receipt['request_sha256']==request['qualification_request_sha256']
        and receipt['core_protocol_sha256']==request['core_protocol_sha256']
        and receipt['financial_replay_started'] is False and receipt['production_contacted'] is False
        and receipt['encrypted_output']==spec['ciphertext'],'REFUSED_QUALIFICATION_RECEIPT_BINDINGS')
    asset=download/spec['ciphertext']['name']
    require(asset.stat().st_size==spec['ciphertext']['bytes'],'REFUSED_QUALIFICATION_CIPHER_SIZE')
    plain=destination.parent/'qualification.authenticated.tar'
    decrypt(asset,plain,key,spec['ciphertext']['sha256'])
    with tarfile.open(plain,'r|') as tar:
        first=tar.next();require(first is not None and first.name=='manifest.json' and first.isfile()
            and first.size<=2*1024**2,'REFUSED_QUALIFICATION_MANIFEST')
        raw=tar.extractfile(first).read()
    require(hashlib.sha256(raw).hexdigest()==spec['manifest_sha256'],'REFUSED_QUALIFICATION_MANIFEST_BYTES')
    manifest=json.loads(raw)
    require(manifest['schema']=='research.capital-risk-output/1' and manifest['arm']=='QUAL'
        and manifest['stage']=='short-core-window' and manifest['protocol_sha256']==PROTOCOL
        and manifest['screen_protocol_sha256']==request['core_protocol_sha256'],'REFUSED_QUALIFICATION_INVENTORY')
    extract_verified(plain,destination,spec['manifest_sha256'],expected_schema='research.capital-risk-output/1')
    require(sha256_file(destination/'bridge.json')==spec['bridge_sha256']
        and sha256_file(destination/'source-bindings.json')==spec['source_bindings_sha256']
        and sha256_file(destination/'candidate-B/run-001/checkpoint.json.gz')==spec['candidate_file_sha256'],
        'REFUSED_ADMITTED_QUALIFICATION_BYTES')
    gate=json.loads((destination/'canonical-gate.json').read_bytes())
    bridge=json.loads((destination/'bridge.json').read_bytes())
    require(gate['status']=='CANONICAL_CORE_GATE_PASSED' and gate['cases']==15 and gate['B0_synthetic_path_matched']
        and bridge['status']=='WARMUP_BRIDGE_QUALIFIED' and bridge['sessions_advanced']==0
        and bridge['financial_state_unchanged'] and bridge['reporting_state_unchanged']
        and bridge['successor_outer']==spec['candidate_outer_sha256']
        and bridge['successor_file_sha256']==spec['candidate_file_sha256'],'REFUSED_ADMITTED_BRIDGE')
    originals=json.loads((destination/'original-admission.json').read_bytes())
    require(originals['authenticated'] and originals['no_variant_origins']==dict(B0=True,C=True,V=True),
        'REFUSED_VARIANT_FIRST_ORIGIN_ADMISSION')
    inspected=[]
    for path in destination.glob('*-inspect.json'):
        entry=inspect_stopped(path,sha256_file(path));require(entry['exit_code']==0,'REFUSED_QUALIFICATION_WORKER_OUTCOME')
        inspected.append(entry)
    require(len(inspected)==4,'REFUSED_QUALIFICATION_WORKER_SET')
    return receipt


def financial_tail(arm,closes):
    tail=['-m','research.pooled_vacancy_funding.backtest','--policy',POLICIES[arm],
        '--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
        '--previous','/frozen/references/owned55','--compact','/frozen/references/compact/champion-daily.csv',
        '--output','/out/run-001','--max-transitions',str(126+closes)]
    if arm=='B':tail+=['--resume','--checkpoint','/out/run-001/checkpoint.json.gz']
    return tail


def snapshot_outputs(qualification,outputs,known,unknown):
    return [('QUAL',qualification),*[(arm,outputs[arm]) for arm in sorted(known) if arm not in unknown]]


def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','qualification-download','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--window',choices=WINDOWS,required=True);a=p.parse_args()
    check_context(os.environ);require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_FRESH_SUFFIX_RERUN')
    request=json.loads(a.request.read_bytes());validate_request(request)
    proof=json.loads(a.staging_receipt.read_bytes())
    require(proof['status']=='STAGING_PASSED' and proof['run_id']==os.environ['GITHUB_RUN_ID']
        and proof['source_commit']==os.environ['GITHUB_SHA'] and proof['protocol_sha256']==PROTOCOL
        and proof['runtime_image']==IMAGE and proof['execution_image']==EXECUTION_IMAGE
        and proof['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and proof['source_files_verified']==514 and proof['members_verified']==591
        and all(proof[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified'))
        and proof['replay_started'] is False,'REFUSED_SUFFIX_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);require(len(key)==32,'REFUSED_RESEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-risk-window-suffix-output';private.mkdir(mode=0o700,exist_ok=False)
    qual=private/'qualification';qual.mkdir();admitted=temp/'capital-risk-admitted-qualification'
    sources=temp/'capital-risk-window-suffix-sources'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    prefix='capital-risk-core-window-'+a.window+'-';identity=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    closes=WINDOWS[a.window][3];status='SHORT_WINDOW_SUFFIX_PASSED';arm_outputs={};known={};failures=[];unknown=[]
    try:
        receipt=restore_qualified(request,a.window,a.qualification_download,admitted,key)
        bindings=json.loads((admitted/'source-bindings.json').read_bytes())
        for phase,risk in [('basis',False),('risk',True)]:
            variant=sources/phase;actual=build(frozen/'source-fixed',variant,risk=risk)
            require(actual==bindings[phase],'REFUSED_QUALIFIED_SOURCE_CHANGE');readonly(variant)
        for name in ('canonical-gate.json','original-admission.json','preflight.json','bridge.json','source-bindings.json'):
            shutil.copyfile(admitted/name,qual/name)
        (qual/'admitted-qualification-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        (qual/'suffix-request.json').write_bytes(a.request.read_bytes())
        b=private/'B';shutil.copytree(admitted/'candidate-B',b);arm_outputs['B']=b
        shutil.copyfile(b/'run-001/checkpoint.json.gz',b/'lineage/successor-start.json.gz')
        shutil.copyfile(admitted/'source-bindings.json',b/'lineage/qualification-source-bindings.json')
        admission=dict(schema='research.capital-risk-qualified-lineage/1',qualification_run_id=QUAL_RUN,
            qualification_source_commit=QUAL_HEAD,qualification=request['windows'][a.window],
            original_request_sha256=request['qualification_request_sha256'],source_boundary_reused=True)
        (b/'lineage/qualification-admission.json').write_text(json.dumps(admission,indent=2)+'\n')
        if (os.cpu_count() or 0)<4 or memory_bytes()['MemAvailable']<10*1024**3 or shutil.disk_usage(temp).free<20*1024**3:
            raise ValueError('REFUSED_FOUR_BOOK_RESOURCE_GATE')
        def financial(arm):
            armout=arm_outputs.get(arm)
            if armout is None:armout=private/arm;armout.mkdir();arm_outputs[arm]=armout
            name=prefix+arm.lower()+'-'+identity
            run_worker(window_command(name,frozen,armout,HERE,sources/('basis' if arm=='B' else 'risk'),
                a.window,financial_tail(arm,closes)),name,armout,deadline=6300)
            result=json.loads((armout/'run-001/result.json').read_bytes())
            require(result['status']=='COMPLETE_PENDING_REVIEW','REFUSED_INCOMPLETE_WINDOW_'+arm)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(financial,arm):arm for arm in POLICIES}
            for future in as_completed(futures):
                arm=futures[future]
                try:future.result()
                except UnprovenStopped:unknown.append(arm)
                except Exception as exc:failures.append(dict(arm=arm,type=type(exc).__name__,message=str(exc)))
        reviewed=[];review_candidates=[]
        for arm,armout in arm_outputs.items():
            if arm in unknown:continue
            name=prefix+arm.lower()+'-'+identity;inspection=armout/(name+'-inspect.json')
            if not inspection.exists():unknown.append(arm);continue
            # OOM/nonzero stopped outputs are preserved, never economically admitted.
            try:known[arm]=inspect_stopped(inspection,sha256_file(inspection),allow_oom=True)
            except Exception as exc:
                unknown.append(arm);failures.append(dict(arm=arm,phase='snapshot_fences',
                    type=type(exc).__name__,message=str(exc)));continue
            if known[arm]['oom'] or known[arm]['exit_code']!=0:continue
            try:result=json.loads((armout/'run-001/result.json').read_bytes())
            except Exception as exc:
                failures.append(dict(arm=arm,phase='result',type=type(exc).__name__,message=str(exc)));continue
            if result['status']!='COMPLETE_PENDING_REVIEW':continue
            review_candidates.append(arm)
        def review_arm(arm):
            armout=arm_outputs[arm];name=prefix+arm.lower()+'-'+identity
            tail=['/driver/core_window_review.py','--root','/out/run-001','--output','/out/independent-review.json']
            if arm=='B':tail+=['--lineage','/out/lineage']
            reviewer=name+'-review'
            run_worker(window_command(reviewer,frozen,armout,HERE,sources/('basis' if arm=='B' else 'risk'),
                a.window,tail),reviewer,armout,deadline=600)
            require(json.loads((armout/'independent-review.json').read_bytes())['status']=='INDEPENDENT_SHORT_WINDOW_REVIEW_PASSED',
                'REFUSED_REVIEW_RESULT')
        if review_candidates and ((os.cpu_count() or 0)<4 or memory_bytes()['MemAvailable']<10*1024**3):
            failures.append(dict(phase='review',message='REFUSED_REVIEW_CAPACITY'))
        else:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures={pool.submit(review_arm,arm):arm for arm in review_candidates}
                for future in as_completed(futures):
                    arm=futures[future]
                    try:future.result();reviewed.append(arm)
                    except UnprovenStopped:unknown.append(arm);known.pop(arm,None)
                    except Exception as exc:failures.append(dict(arm=arm,phase='review',type=type(exc).__name__,message=str(exc)))
        if 'B' in reviewed and 'B0' in reviewed:
            try:
                equality=compare_disabled(private/'B/run-001',private/'B0/run-001')
                (qual/'disabled-equivalence.json').write_text(json.dumps(equality,indent=2)+'\n')
            except Exception as exc:failures.append(dict(phase='B0_comparison',type=type(exc).__name__,message=str(exc)))
        if len(reviewed)!=4 or failures or unknown:status='WRITER_STOP_UNKNOWN' if unknown else 'SHORT_WINDOW_SUFFIX_REFUSED'
        (qual/'arm-outcomes.json').write_text(json.dumps(dict(stopped=known,reviewed=reviewed,failures=failures,unknown=unknown),indent=2)+'\n')
    except Exception as exc:
        status='WRITER_STOP_UNKNOWN' if unknown else 'SHORT_WINDOW_SUFFIX_REFUSED'
        (qual/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    assets=[]
    # Never recurse into any unknown writer's output, including an unknown reviewer.
    for arm,root in snapshot_outputs(qual,arm_outputs,known,unknown):
        asset=output.parent/('window-suffix-'+a.window+'-'+arm+'.tar.crseal')
        encrypt(root,asset,key,request['core_protocol_sha256'],arm=arm,stage='short-core-window')
        assets.append(dict(arm=arm,name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    key=None
    receipt=dict(schema='research.capital-risk-window-suffix-receipt/1',status=status,
        run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],window=a.window,
        utc=datetime.now(timezone.utc).isoformat(),request_sha256=sha256_file(a.request),
        core_protocol_sha256=request['core_protocol_sha256'],execution_sha256=request['execution_sha256'],
        qualification_run_id=QUAL_RUN,production_contacted=False,unknown_arms=unknown,encrypted_outputs=assets)
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='SHORT_WINDOW_SUFFIX_PASSED' else 2)


if __name__=='__main__':main()
