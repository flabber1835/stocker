"""One isolated hosted grid and stopped-evidence review; ciphertext export."""
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

from owned_grid import need,profiles
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from stage import SECRET,PROTOCOL,IMAGE
from seal import EncryptWriter,sha256_file
from alpaca_fit_job import stopped_run,StopUnknown

HERE=Path(__file__).resolve().parent
SOURCES=('owned_grid.py','owned_grid_worker.py','owned_grid_review.py','owned_grid_job.py',
    'owned_value.py','owned_value_worker.py','owned_value_review.py',
    'trace_screen.py','selective_journal.py','probe.py','runtime_identity.py','stage.py','seal.py',
    'alpaca_fit_job.py','alpaca_fit_stage.py','policy.py')


def request_value(specs,protocol_sha):
    return {'schema':'research.sharadar-owned55-grid-request/1','request_id':'sharadar-owned55-grid-001',
        'original_protocol_sha256':PROTOCOL,'protocol_sha256':protocol_sha,'source_files':specs,
        'execution_image':EXECUTION_IMAGE,'production_contacted':False,'no_local_financial_execution':True,
        'valuation_engine':'COMPACT_EXACT_VALUE_FUNCTION','encrypted_part_plaintext_bound':128*1024**2,
        'preserved_export_failure':{'run_id':40826068033,'head':'5c72610322dc4eea0964451a970b150acfe564b7','artifact_id':12880905869,
            'artifact_zip_sha256':'5681dcd19910f2f78ed6cc54e86ba22dfd6b3df174a68d9335807c754d5a8727',
            'gcm_valid':False,'authenticated_financial_snapshot':False,'exact_suffix_available':False,
            'new_calculation_is_recovery':False},
        'preserved_pre_search_refusals':[{'run_id':40825055253,'head':'a2afd1635c5b09b9b023e25748b1a2034746ceb0',
            'artifact_id':12876247293,'artifact_zip_sha256':'2f62d80e1391d914dbd5d8211963aa05e33f9f83c22ca25c0d7cff80ad8da589',
            'actual_objective_account_origins':0,'actual_controller_path_origins':0},
            {'run_id':40825630207,'head':'d17eac3b57b211fc51aa4642d9c515b6dab0ad85','artifact_id':12876218456,
            'artifact_zip_sha256':'64365a3ba11b051b39345051788a2f539503f362238674aeca314f0578d99a82',
            'actual_objective_account_origins':0,'actual_controller_path_origins':0}]}


def inspect(name,identity=None):
    need(re.fullmatch(r'capital-owned-grid-(?:worker|review)-[0-9]+-1',name) is not None,'WORKER_NAME')
    value=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h=value['HostConfig'];c=value['Config'];mounts={m['Destination']:m for m in value['Mounts'] if m['Type']=='bind'}
    need(value['Name']=='/'+name and value['Image']==EXECUTION_IMAGE and (identity is None or value['Id']==identity),'WORKER_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==8*1024**3 and h['MemorySwap']==8*1024**3
        and h['NanoCpus']==4000000000 and h['PidsLimit']==64 and h['ReadonlyRootfs']
        and h['CapDrop']==['ALL'] and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']),'WORKER_FENCES')
    reviewer='-review-' in name;expected={'/frozen','/driver','/out'}|({'/evidence'} if reviewer else set())
    need(set(mounts)==expected and mounts['/out']['RW'] and all(not m['RW'] for d,m in mounts.items() if d!='/out')
        and c['WorkingDir']=='/fixed' and c['User']==f'{os.getuid()}:{os.getgid()}'
        and c['Labels'].get('research.study')=='sharadar-owned55-grid-001'
        and c['Labels'].get('research.stage')==('review' if reviewer else 'financial-grid'),'WORKER_MOUNTS_LABELS_USER')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'}
    need(not any(k in forbidden and v for k,_,v in (e.partition('=') for e in c['Env'])),'WORKER_CREDENTIALS')
    return value


def command(name,frozen,output,*,evidence=None):
    argv=['docker','run','-d','--name',name,'--pull','never','--network','none','--read-only',
        '--memory','8g','--memory-swap','8g','--cpus','4','--pids-limit','64','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=128m','--user',f'{os.getuid()}:{os.getgid()}',
        '--label','research.study=sharadar-owned55-grid-001','--label','research.stage='+('review' if evidence else 'financial-grid'),
        '-w','/fixed','-e','PYTHONPATH=/fixed:/fixed/shared:/driver','-e','OWNED_GRID_HOSTED=1',
        '-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1',
        '--mount',f'type=bind,source={frozen},target=/frozen,readonly',
        '--mount',f'type=bind,source={HERE},target=/driver,readonly',
        '--mount',f'type=bind,source={output},target=/out']
    if evidence:argv+=['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    argv+=['--entrypoint','python',EXECUTION_IMAGE,'-B','-u','/driver/'+('owned_value_review.py' if evidence else 'owned_value_worker.py'),
        '--root','/frozen/baseline-comparison','--protocol','/driver/sharadar-owned55-fit-protocol.json',
        '--output','/out/review' if evidence else '/out/book']
    if evidence:argv+=['--evidence','/evidence/book']
    return argv


def encrypt(root,path,key,request_sha,protocol_sha):
    members={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha256_file(p)} for p in sorted(root.rglob('*')) if p.is_file()}
    need(len(members)<=100000 and sum(s['bytes'] for s in members.values())<=4*1024**3
        and not any(p.is_symlink() for p in root.rglob('*')),'OUTPUT_INVENTORY_BOUND')
    manifest=json.dumps({'schema':'research.capital-risk-output/1','arm':'OWNED_GRID','stage':'owned55-finite-fit',
        'protocol_sha256':PROTOCOL,'screen_protocol_sha256':protocol_sha,'request_sha256':request_sha,
        'compression':'TAR_GZIP_V1','members':members},sort_keys=True).encode()+b'\n'
    import hashlib
    with path.open('xb') as destination:
        writer=EncryptWriter(destination,key)
        with tarfile.open(fileobj=writer,mode='w|gz',compresslevel=1) as archive:
            first=tarfile.TarInfo('manifest.json');first.size=len(manifest);archive.addfile(first,io.BytesIO(manifest))
            for name,spec in members.items():
                item=tarfile.TarInfo(name);item.size=spec['bytes'];item.mode=0o600
                with (root/name).open('rb') as source:archive.addfile(item,source)
        writer.finish()
    return {'name':path.name,'bytes':path.stat().st_size,'sha256':sha256_file(path),
        'manifest_sha256':hashlib.sha256(manifest).hexdigest(),'compression':'TAR_GZIP_V1'}


def partition(members,bound=128*1024**2):
    parts=[];part={};size=0
    def priority(item):
        name=item[0]
        if name in ('worker-inspect.json','source-bindings.json','request.json') or name.startswith('stopped-independent-review/'):return (0,name)
        if name.startswith('book/') and name.count('/')==1:return (1,name)
        if name.endswith('/checkpoint.json.gz'):return (2,name)
        if name.endswith('/result.json'):return (3,name)
        return (4,name)
    for name,spec in sorted(members.items(),key=priority):
        need(0<=spec['bytes']<=bound,'SINGLE_MEMBER_EXPORT_BOUND')
        if part and (size+spec['bytes']>bound or len(part)>=20000):parts.append(part);part={};size=0
        part[name]=spec;size+=spec['bytes']
    if part:parts.append(part)
    return parts


def receipt_save(path,receipt):
    temporary=path.with_suffix('.json.partial')
    with temporary.open('w') as f:f.write(json.dumps(receipt,indent=2)+'\n');f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)


def encrypt_parts(root,path,key,receipt):
    import hashlib
    members={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha256_file(p)} for p in sorted(root.rglob('*')) if p.is_file()}
    need(len(members)<=100000 and sum(v['bytes'] for v in members.values())<=4*1024**3
        and not any(p.is_symlink() for p in root.rglob('*')),'COMPACT_EXPORT_INVENTORY_BOUND')
    groups=partition(members);whole=hashlib.sha256(json.dumps(members,sort_keys=True).encode()).hexdigest();final_status=receipt['status']
    receipt.update(status='EXPORT_PARTS_IN_PROGRESS',encrypted_outputs=[],output_inventory_sha256=whole,output_parts_expected=len(groups))
    receipt_save(path,receipt)
    for i,part in enumerate(groups):
        manifest=json.dumps({'schema':'research.capital-risk-output/1','arm':'OWNED_GRID','stage':'owned55-finite-fit',
            'protocol_sha256':PROTOCOL,'screen_protocol_sha256':receipt['protocol_sha256'],'request_sha256':receipt['request_sha256'],
            'compression':'TAR_GZIP_V1','part_index':i,'parts':len(groups),'output_inventory_sha256':whole,'members':part},sort_keys=True).encode()+b'\n'
        target=path.parent/f'owned-grid-{i:03d}.tar.crseal';temporary=target.with_suffix('.partial')
        with temporary.open('xb') as destination:
            writer=EncryptWriter(destination,key)
            with tarfile.open(fileobj=writer,mode='w|gz',compresslevel=1) as archive:
                first=tarfile.TarInfo('manifest.json');first.size=len(manifest);archive.addfile(first,io.BytesIO(manifest))
                for name,spec in part.items():
                    item=tarfile.TarInfo(name);item.size=spec['bytes'];item.mode=0o600
                    with (root/name).open('rb') as source:archive.addfile(item,source)
            writer.finish();destination.flush();os.fsync(destination.fileno())
        os.replace(temporary,target);receipt['encrypted_outputs'].append({'name':target.name,'bytes':target.stat().st_size,'sha256':sha256_file(target),
            'manifest_sha256':hashlib.sha256(manifest).hexdigest(),'compression':'TAR_GZIP_V1','part_index':i});receipt_save(path,receipt)
    receipt['status']=final_status;receipt_save(path,receipt)


def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_FRESH_WORKFLOW_RERUN')
    p=HERE/'sharadar-owned55-fit-protocol.json';protocol=json.loads(p.read_bytes());profiles(protocol)
    request=json.loads(a.request.read_bytes());actual={n:{'bytes':(HERE/n).stat().st_size,'sha256':sha256_file(HERE/n)} for n in SOURCES}
    need(request==request_value(actual,sha256_file(p)),'EXACT_HOSTED_REQUEST')
    staging=json.loads(a.staging.read_bytes())
    need(staging['status']=='STAGING_PASSED' and staging['source_commit']==os.environ['GITHUB_SHA']
        and staging['run_id']==os.environ['GITHUB_RUN_ID'] and staging['protocol_sha256']==PROTOCOL
        and staging['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and staging['runtime_image']==IMAGE and staging['execution_image']==EXECUTION_IMAGE
        and staging['source_files_verified']==514 and staging['members_verified']==591
        and staging['authenticated_before_parsing'] and staging['runtime_index_config_layer_chain_verified']
        and staging['offline_image_source_verified'] and staging['replay_started'] is False,'FROZEN_INPUT_ADMISSION')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);private=temp/'owned-grid-private';private.mkdir(mode=0o700,exist_ok=False)
    frozen=temp/'capital-risk-stage-001/inputs';a.output.parent.mkdir(parents=True,exist_ok=True)
    need((os.cpu_count() or 0)>=4 and memory_bytes()['MemAvailable']>=11*1024**3
        and shutil.disk_usage(temp).free>=12*1024**3,'PRIVATE_RESOURCE_GATE')
    (private/'request.json').write_bytes(a.request.read_bytes());(private/'source-bindings.json').write_text(json.dumps(actual,indent=2)+'\n')
    receipt={'schema':'research.sharadar-owned55-grid-receipt/1','status':'NOT_STARTED','run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':sha256_file(p),
        'original_protocol_sha256':PROTOCOL,'production_contacted':False,'financial_replay_started':False}
    known=False
    try:
        name='capital-owned-grid-worker-'+os.environ['GITHUB_RUN_ID']+'-1';receipt['financial_replay_started']=True
        outcome=stopped_run(command(name,frozen,private),name,private,deadline=5520,inspector=inspect);known=True;receipt['worker']=outcome
        receipt['status']='STOPPED_EVIDENCE_PRESERVED'
        if outcome['exit_code']==0 and not outcome['oom_killed']:
            audit=temp/'owned-grid-private-review';audit.mkdir(mode=0o700,exist_ok=False)
            review_name='capital-owned-grid-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            reviewed=stopped_run(command(review_name,frozen,audit,evidence=private),review_name,audit,deadline=1200,inspector=inspect)
            receipt['reviewer']=reviewed;shutil.copytree(audit,private/'stopped-independent-review')
            if reviewed['exit_code']==0 and not reviewed['oom_killed']:
                proof=json.loads((audit/'review/independent-review.json').read_bytes())
                need(proof['status']=='INDEPENDENT_GRID_REVIEW_PASSED','ACTUAL_REVIEW_RESULT');receipt['status']='COMPLETE_INDEPENDENTLY_REVIEWED'
            else:receipt['status']='FINANCIAL_EVIDENCE_PRESERVED_REVIEW_REFUSED'
    except StopUnknown:
        receipt['status']='REVIEWER_STOP_UNKNOWN_FINANCIAL_PRESERVED' if known else 'WRITER_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='REFUSED_KNOWN_STOPPED_EVIDENCE' if known else 'REFUSED_NO_ADMITTED_FINANCIAL_SNAPSHOT'
        receipt['error_type']=type(exc).__name__
        if known:(private/'driver-failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    receipt_save(a.output,receipt)
    if known:
        try:encrypt_parts(private,a.output,key,receipt)
        except Exception as exc:
            receipt.update(status='EXPORT_INCOMPLETE_COMPLETED_PARTS_PRESERVED',export_error_type=type(exc).__name__)
            receipt_save(a.output,receipt)
    key=None;receipt_save(a.output,receipt);print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='COMPLETE_INDEPENDENTLY_REVIEWED' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
