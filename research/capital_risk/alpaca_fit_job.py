"""Exact isolated hosted baseline, stop receipts and encrypted evidence export."""
from __future__ import annotations
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from seal import EncryptWriter,sha256_file
from alpaca_fit_stage import SECRET,need


class StopUnknown(RuntimeError):pass


def inspect(name,identity=None):return inspect_kind(name,identity,'baseline')


def inspect_review(name,identity=None):return inspect_kind(name,identity,'review')


def inspect_kind(name,identity,kind):
    need(kind in ('baseline','review') and re.fullmatch(r'capital-alpaca-fit-'+kind+r'-[0-9]+-1',name) is not None,'WORKER_NAME')
    item=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h=item['HostConfig'];c=item['Config'];labels=c['Labels']
    need(item['Name']=='/'+name and item['Image']==EXECUTION_IMAGE
        and (identity is None or item['Id']==identity),'WORKER_IDENTITY')
    stage='canonical-baseline' if kind=='baseline' else 'canonical-baseline-review'
    need(labels.get('research.study')=='alpaca-owned55-fit-001' and labels.get('research.stage')==stage
         and h['NetworkMode']=='none' and h['Memory']==8*1024**3 and h['MemorySwap']==8*1024**3
         and h['NanoCpus']==2000000000 and h['PidsLimit']==64 and h['ReadonlyRootfs'] is True
         and h['CapDrop']==['ALL'] and any(v.startswith('no-new-privileges') for v in h['SecurityOpt']),'WORKER_FENCE')
    mounts={m['Destination']:m for m in item['Mounts'] if m['Type']=='bind'}
    extra='/bil' if kind=='baseline' else '/evidence'
    need(set(mounts)=={'/src','/inputs','/prefix',extra,'/out'} and not any(mounts[p]['RW'] for p in ('/src','/inputs','/prefix',extra))
        and mounts['/out']['RW'] and c['WorkingDir']=='/src' and c['User']==f'{os.getuid()}:{os.getgid()}','WORKER_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GITHUB_TOKEN','GH_TOKEN'}
    need(not any(k in forbidden and v for k,_,v in (e.partition('=') for e in c['Env'])),'WORKER_CREDENTIAL')
    return item


def command(name,source,inputs,prefix,bil,output):
    return ['docker','run','-d','--name',name,'--pull','never','--network','none','--memory','8g','--memory-swap','8g',
        '--cpus','2','--pids-limit','64','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--user',f'{os.getuid()}:{os.getgid()}',
        '--label','research.study=alpaca-owned55-fit-001','--label','research.stage=canonical-baseline','-w','/src',
        '-e','PYTHONPATH=/src:/src/shared:/src/research/capital_risk','-e','ALPACA_FIT_HOSTED=1',
        '-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1',
        '--mount',f'type=bind,source={source},target=/src,readonly',
        '--mount',f'type=bind,source={inputs},target=/inputs,readonly',
        '--mount',f'type=bind,source={prefix},target=/prefix,readonly',
        '--mount',f'type=bind,source={bil},target=/bil,readonly',
        '--mount',f'type=bind,source={output},target=/out','--entrypoint','python',EXECUTION_IMAGE,'-B','-u',
        '/src/research/capital_risk/alpaca_fit_baseline.py','--request','/src/research/capital_risk/alpaca-fit-request.json',
        '--protocol','/src/research/capital_risk/alpaca-fit-protocol.json','--inputs','/inputs','--prefix-inputs','/prefix','--bil-inputs','/bil','--output','/out/book']


def review_command(name,source,inputs,prefix,evidence,output):
    argv=command(name,source,inputs,prefix,evidence,output)
    index=argv.index('research.stage=canonical-baseline');argv[index]='research.stage=canonical-baseline-review'
    index=argv.index(f'type=bind,source={evidence},target=/bil,readonly')
    argv[index]=f'type=bind,source={evidence},target=/evidence,readonly'
    index=argv.index('/src/research/capital_risk/alpaca_fit_baseline.py')
    return argv[:index]+['/src/research/capital_risk/alpaca_fit_review.py','--request','/src/research/capital_risk/alpaca-fit-request.json',
        '--inputs','/inputs','--prefix-inputs','/prefix','--evidence','/evidence','--output','/out/review']


def stopped_run(argv,name,output,deadline,inspector=None):
    inspector=inspector or inspect
    try:identity=subprocess.run(argv,capture_output=True,check=True,timeout=30).stdout.decode().strip()
    except Exception as exc:raise StopUnknown('PRIVATE_LAUNCH_OUTCOME_UNKNOWN') from exc
    if not re.fullmatch('[a-f0-9]{64}',identity):raise StopUnknown('PRIVATE_LAUNCH_ID_UNKNOWN')
    wait_error=None
    try:
        inspector(name,identity)
        subprocess.run(['docker','wait',identity],capture_output=True,check=True,timeout=deadline)
    except Exception as exc:wait_error=type(exc).__name__
    finally:
        try:
            item=inspector(name,identity)
            if item['State']['Running']:
                subprocess.run(['docker','stop','--time','90',identity],capture_output=True,check=True,timeout=110)
                item=inspector(name,identity)
            need(not item['State']['Running'],'WRITER_STILL_RUNNING')
            # Durable actual receipt BEFORE any timeout propagates to the caller.
            with (output/'worker-inspect.json').open('x') as f:
                f.write(json.dumps(item,indent=2)+'\n');f.flush();os.fsync(f.fileno())
        except Exception as exc:raise StopUnknown('PRIVATE_WRITER_STOP_UNKNOWN') from exc
    try:
        with (output/'worker.log').open('xb') as log:
            subprocess.run(['docker','logs',identity],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
    except Exception as exc:
        (output/'log-copy-failure.json').write_text(json.dumps({'type':type(exc).__name__})+'\n')
    return {'stopped':True,'exit_code':item['State']['ExitCode'],'oom_killed':item['State']['OOMKilled'],'wait_error':wait_error}


def seal_output(root,path,key,protocol_sha,kind):
    members={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha256_file(p)}
        for p in sorted(root.rglob('*')) if p.is_file()}
    need(not any(p.is_symlink() for p in root.rglob('*')),'OUTPUT_SYMLINK')
    manifest=json.dumps({'schema':'research.alpaca-fit-output/1','stage':'canonical-baseline','kind':kind,
        'protocol_sha256':protocol_sha,'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'members':members},sort_keys=True).encode()+b'\n'
    import hashlib
    with path.open('xb') as out:
        writer=EncryptWriter(out,key)
        with tarfile.open(fileobj=writer,mode='w|') as tar:
            item=tarfile.TarInfo('manifest.json');item.size=len(manifest);tar.addfile(item,io.BytesIO(manifest))
            for name in members:
                item=tarfile.TarInfo(name);item.size=members[name]['bytes'];item.mode=0o600
                with (root/name).open('rb') as f:tar.addfile(item,f)
        writer.finish()
    return {'name':path.name,'bytes':path.stat().st_size,'sha256':sha256_file(path),'manifest_sha256':hashlib.sha256(manifest).hexdigest()}


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--staging',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();check_context(os.environ)
    need(os.environ['GITHUB_RUN_ATTEMPT']=='1','NO_FRESH_RERUN')
    request=json.loads(a.request.read_bytes());stage=json.loads(a.staging.read_bytes())
    need(stage['status']=='AUTHENTICATED_INPUTS_AND_RUNTIME' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['head']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==request['protocol_sha256']
         and stage['execution_image']==EXECUTION_IMAGE and stage['authenticated_before_parsing'] is True
         and stage['dataset_sha256']==request['dataset_sha256'],'STAGING_ADMISSION')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    private=Path(os.environ['RUNNER_TEMP'])/'alpaca-fit-baseline-001';private.mkdir(mode=0o700,exist_ok=False)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    receipt={'schema':'research.alpaca-fit-baseline-receipt/1','status':'NOT_STARTED','run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'protocol_sha256':request['protocol_sha256'],'financial_replay_started':False,
        'production_contacted':False,'encrypted_outputs':{}}
    name='capital-alpaca-fit-baseline-'+os.environ['GITHUB_RUN_ID']+'-1';known=False
    try:
        need((os.cpu_count() or 0)>=4 and memory_bytes()['MemAvailable']>=11*1024**3
             and shutil.disk_usage(private).free>=14*1024**3,'CAPACITY')
        receipt['financial_replay_started']=True
        argv=command(name,Path(os.environ['GITHUB_WORKSPACE']).resolve(),Path(stage['inputs_root']).resolve(),
            Path(stage['prefix_inputs_root']).resolve(),Path(stage['bil_inputs_root']).resolve(),private)
        if request.get('continuation'):
            need(stage['predecessor_admission']['archive_cipher_inventory_verified'] is True,'PREDECESSOR_STAGING')
            argv+=['--resume-prefix','/inputs/_continuation/previous/book','--input-reference','/inputs/_continuation/source/alpaca_fit_inputs.py']
        outcome=stopped_run(argv,name,private,deadline=3720)
        known=True;receipt['worker']=outcome
        status_path=private/'book/baseline-status.json'
        receipt['status']='BASELINE_PRESERVED' if status_path.is_file() else 'STOPPED_WITHOUT_COMPLETE_STATUS'
        if outcome['exit_code'] or outcome['oom_killed']:receipt['status']='BASELINE_INCOMPLETE_PRESERVED'
        if all((private/'book'/p).is_file() for p in ('plan.json','retained-checkpoints.json','baseline-status.json')):
            if json.loads((private/'book/retained-checkpoints.json').read_bytes()):
                audit=Path(os.environ['RUNNER_TEMP'])/'alpaca-fit-baseline-review';audit.mkdir(mode=0o700,exist_ok=False)
                review_name='capital-alpaca-fit-review-'+os.environ['GITHUB_RUN_ID']+'-1'
                review_outcome=stopped_run(review_command(review_name,Path(os.environ['GITHUB_WORKSPACE']).resolve(),
                    Path(stage['inputs_root']).resolve(),Path(stage['prefix_inputs_root']).resolve(),private/'book',audit),
                    review_name,audit,deadline=300,inspector=inspect_review)
                receipt['review_worker']=review_outcome
                shutil.copytree(audit,private/'stopped-independent-review')
                if review_outcome['exit_code'] or review_outcome['oom_killed']:receipt['status']='BASELINE_PRESERVED_REVIEW_REFUSED'
    except StopUnknown:
        receipt['status']='REVIEWER_STOP_UNKNOWN_FINANCIAL_PRESERVED' if known else 'WRITER_STOP_UNKNOWN'
        receipt['financial_snapshot_exported']=known
    except Exception as exc:
        receipt['status']='BASELINE_REFUSED';receipt['error_type']=type(exc).__name__
        known=known or not receipt['financial_replay_started']
    if known:
        receipt['encrypted_outputs']['full']=seal_output(private,a.output.parent/'alpaca-fit-baseline-full.tar.crseal',key,request['protocol_sha256'],'FULL_STOPPED_EVIDENCE')
        summary=Path(os.environ['RUNNER_TEMP'])/'alpaca-fit-baseline-summary';summary.mkdir(mode=0o700,exist_ok=False)
        for name in ('worker-inspect.json','book/baseline-status.json','book/timing-gate.json','book/normalization.json',
                     'book/feature-qualification.json','book/retained-checkpoints.json','book/source-bindings.json','book/failure.json',
                     'book/controller-component-qualification.json','stopped-independent-review/worker-inspect.json',
                     'stopped-independent-review/review/independent-review.json','book/packed-input-equivalence.json',
                     'book/suffix-budget.json','book/lineage/admission.json'):
            source=private/name
            if source.is_file():
                destination=summary/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
        receipt['encrypted_outputs']['summary']=seal_output(summary,a.output.parent/'alpaca-fit-baseline-summary.tar.crseal',key,request['protocol_sha256'],'BOUNDED_SUMMARY')
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='BASELINE_PRESERVED' else 2)


if __name__=='__main__':main()
