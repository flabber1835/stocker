"""Owner-authorized exact B/B0/C suffix, with no financial source conversion."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil

from baseline_prefix import run_worker,UnprovenStopped
from concentration_build import build_quarter,CLOSES
from concentration_job import command,POLICIES,snapshot_outputs
from concentration_predecessor import admit,copy_for_resume,preserved_prefixes,need
from core_recovery_job import inspect_stopped,readonly
from core_window_review import compare_disabled
from probe import check_context,admitted_output,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,IMAGE,SECRET

HERE=Path(__file__).resolve().parent
CONTRACT='74ec187ef27d250ed5d53bba1a3c97115001a5156c0d360406f2da5a9b97dfa7'
SOURCES=('concentration_extension_job.py','concentration_predecessor.py','concentration_review.py',
    'concentration_build.py','concentration_job.py','build_core_variants.py','core_policy.py','baseline_prefix.py',
    'core_manifest.py','core_window_review.py','core_accounting_snapshot.py')

def expected_request():
    return dict(schema='research.concentration-extension-request/1',request_id='concentration-quarter-extension-001',
        owner_scope='EXPLICIT_OWNER_C_EXTENSION_TO_COMPLETION_SAME_ENCRYPTED_CHANNEL',numerical_protocol_sha256=CONTRACT,
        execution_sha256=sha256_file(HERE/'concentration-extension-execution.json'),
        predecessor_sha256=sha256_file(HERE/'concentration-extension-predecessor.json'),
        source_bindings={name:sha256_file(HERE/name) for name in SOURCES})

def validate_request(value):
    need(value==expected_request(),'REFUSED_C_EXTENSION_REQUEST')
    need(sha256_file(HERE/'concentration-quarter-protocol.json')==CONTRACT,'REFUSED_C_EXTENSION_NUMERICAL_CHANGE')
    execution=json.loads((HERE/'concentration-extension-execution.json').read_bytes())
    need(execution['arms']==list(POLICIES) and execution['window']==['2025-01-02','2025-03-31',60]
        and execution['numerical_protocol_sha256']==CONTRACT and execution['same_financial_source_required']
        and execution['resume_each_own_exact_checkpoint'] and not execution['fresh_origin']
        and not execution['new_rule_or_window'] and not execution['production_contacted']
        and execution['worker_wait_seconds']==3600 and execution['review_wait_seconds']==600
        and execution['workflow_timeout_minutes']==90,'REFUSED_C_EXTENSION_EXECUTION')
    prior=json.loads((HERE/'concentration-extension-predecessor.json').read_bytes())
    need(prior['run_id']==40613063158 and prior['head']=='594d2ed42f30171a3a4da05e5a0179aa82c9034f'
        and prior['artifact_id']==12784623212 and set(prior['arms'])==set(POLICIES),'REFUSED_C_EXTENSION_PREDECESSOR')
    return execution,prior

def suffix_tail(arm,spec):
    remaining=126+CLOSES-spec['formation_closes']-spec['measured_closes']
    need(0<remaining<=186,'REFUSED_C_EXTENSION_REMAINING')
    return ['-m','research.pooled_vacancy_funding.backtest','--policy',POLICIES[arm],
        '--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
        '--previous','/frozen/references/owned55','--compact','/frozen/references/compact/champion-daily.csv',
        '--output','/out/run-001','--resume','--checkpoint','/out/run-001/checkpoint.json.gz',
        '--max-transitions',str(remaining)]

def main():
    p=argparse.ArgumentParser()
    for name in ('request','staging-receipt','predecessor-download','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_C_EXTENSION_RERUN')
    request=json.loads(a.request.read_bytes());execution,spec=validate_request(request)
    stage=json.loads(a.staging_receipt.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
        and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
        and stage['source_files_verified']==514 and stage['members_verified']==591
        and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and all(stage[k] for k in ('authenticated_before_parsing','runtime_index_config_layer_chain_verified','offline_image_source_verified'))
        and stage['replay_started'] is False,'REFUSED_C_EXTENSION_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'REFUSED_C_EXTENSION_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-concentration-extension-001';private.mkdir(mode=0o700,exist_ok=False)
    qual=private/'qualification';qual.mkdir();sources=temp/'capital-concentration-extension-sources'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    identity=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'];prefix='capital-risk-core-window-cq12025-'
    outputs={};known={};unknown=[];failures=[];reviewed=[];financial_started=False;status='C_EXTENSION_REFUSED'
    (qual/'extension-request.json').write_bytes(a.request.read_bytes())
    for name in ('concentration-extension-execution.json','concentration-extension-predecessor.json'):
        (qual/name).write_bytes((HERE/name).read_bytes())
    (qual/'driver-identities.json').write_text(json.dumps({q.name:sha256_file(q) for q in sorted(HERE.glob('*.py'))},indent=2)+'\n')
    try:
        admitted,manifests=admit(a.predecessor_download,private,spec,key,CONTRACT)
        original_bindings=json.loads((admitted/'QUAL/source-bindings.json').read_bytes());bindings={}
        for phase,risk in (('basis',False),('risk',True)):
            variant=sources/phase;bindings[phase]=build_quarter(frozen/'source-fixed',variant,risk=risk)
            need(bindings[phase]==original_bindings[phase],'REFUSED_C_EXTENSION_FINANCIAL_SOURCE_CHANGE')
            readonly(variant)
        (qual/'source-bindings.json').write_text(json.dumps(bindings,indent=2)+'\n')
        shutil.copytree(admitted/'QUAL',qual/'predecessor-qualification')
        shutil.copyfile(a.predecessor_download/'concentration-quarter.json',qual/'predecessor-receipt.json')
        admissions={}
        for arm in POLICIES:
            root=private/arm;root.mkdir();outputs[arm]=root
            admissions[arm]=copy_for_resume(admitted/arm/'run-001',root/'run-001',spec['arms'][arm],POLICIES[arm])
            lineage=root/'lineage';lineage.mkdir()
            for name in ('independent-review.json',*spec['arms'][arm]['inspections']):shutil.copyfile(admitted/arm/name,lineage/name)
            (lineage/'predecessor-admission.json').write_text(json.dumps(admissions[arm],indent=2)+'\n')
        (qual/'predecessor-admission.json').write_text(json.dumps(dict(manifests=manifests,arms=admissions,
            entire_financial_source_unchanged=True,no_fresh_origin=True),indent=2)+'\n')
        readonly(admitted);readonly(frozen)
        need((os.cpu_count() or 0)>=4 and memory_bytes()['MemAvailable']>=8*1024**3
            and shutil.disk_usage(temp).free>=12*1024**3,'REFUSED_C_EXTENSION_CAPACITY')
        def financial(arm):
            name=prefix+arm.lower()+'-'+identity
            run_worker(command(name,frozen,outputs[arm],sources/('basis' if arm=='B' else 'risk'),
                suffix_tail(arm,spec['arms'][arm])),name,outputs[arm],deadline=3600)
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
            try:
                known[arm]=inspect_stopped(inspection,sha256_file(inspection),allow_oom=True)
                preserved=preserved_prefixes(root/'run-001',spec['arms'][arm])
                (root/'lineage/prefix-preservation.json').write_text(json.dumps(preserved,indent=2)+'\n')
            except Exception as exc:
                if arm not in known:unknown.append(arm)
                failures.append(dict(arm=arm,phase='stop_or_prefix',type=type(exc).__name__,message=str(exc)));continue
            if not known[arm]['oom'] and known[arm]['exit_code']==0:candidates.append(arm)
        def review_arm(arm):
            name=prefix+arm.lower()+'-'+identity+'-review'
            tail=['/driver/concentration_review.py','--root','/out/run-001','--output','/out/independent-review.json']
            run_worker(command(name,frozen,outputs[arm],sources/('basis' if arm=='B' else 'risk'),tail),name,outputs[arm],deadline=600)
            v=json.loads((outputs[arm]/'independent-review.json').read_bytes())
            need(v['status'] in ('C_QUARTER_COMPLETE_REVIEW_PASSED','C_QUARTER_PARTIAL_PREFIX_REVIEW_PASSED'),'REFUSED_C_EXTENSION_REVIEW')
            return v
        reviews={};need(not candidates or memory_bytes()['MemAvailable']>=8*1024**3,'REFUSED_C_EXTENSION_REVIEW_CAPACITY')
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(review_arm,arm):arm for arm in candidates}
            for future in as_completed(futures):
                arm=futures[future]
                try:reviews[arm]=future.result();reviewed.append(arm)
                except UnprovenStopped:unknown.append(arm);known.pop(arm,None)
                except Exception as exc:failures.append(dict(arm=arm,phase='review',type=type(exc).__name__,message=str(exc)))
        if set(reviews)==set(POLICIES) and all(v['complete'] for v in reviews.values()):
            equality=compare_disabled(outputs['B']/'run-001',outputs['B0']/'run-001')
            (qual/'disabled-equivalence.json').write_text(json.dumps(equality,indent=2)+'\n')
            status='C_EXTENSION_COMPLETE_PENDING_LOCAL_REVIEW'
        elif reviews:status='C_EXTENSION_PARTIAL_PRESERVED'
        if unknown:status='WRITER_STOP_UNKNOWN'
        (qual/'arm-outcomes.json').write_text(json.dumps(dict(stopped=known,unknown=unknown,reviewed=reviewed,failures=failures),indent=2)+'\n')
    except Exception as exc:
        status='WRITER_STOP_UNKNOWN' if unknown else 'C_EXTENSION_REFUSED'
        (qual/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    assets=[]
    for arm,root in snapshot_outputs(qual,outputs,known,unknown):
        target=output.parent/('concentration-extension-'+arm+'.tar.crseal')
        encrypt(root,target,key,CONTRACT,arm=arm,stage='short-core-window')
        assets.append(dict(arm=arm,name=target.name,bytes=target.stat().st_size,sha256=sha256_file(target)))
    key=None
    receipt=dict(schema='research.concentration-extension-receipt/1',status=status,run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(a.request),numerical_protocol_sha256=CONTRACT,execution_sha256=request['execution_sha256'],
        predecessor_run_id=spec['run_id'],predecessor_head=spec['head'],predecessor_sha256=request['predecessor_sha256'],
        window=['2025-01-02','2025-03-31',60],financial_replay_started=financial_started,no_fresh_origin=True,
        unknown_arms=unknown,encrypted_outputs=assets,production_contacted=False,utc=datetime.now(timezone.utc).isoformat())
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='C_EXTENSION_COMPLETE_PENDING_LOCAL_REVIEW' else 2)

if __name__=='__main__':main()
