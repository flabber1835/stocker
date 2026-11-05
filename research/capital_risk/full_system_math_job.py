"""One bounded hosted numerical controller pass over an authenticated Core book."""
import argparse,base64,hashlib,json,os,re,shutil,subprocess,tarfile,zipfile
from datetime import datetime,timezone
from pathlib import Path
from full_system_source import build
from full_system_benchmark import need
from full_system_trials_job import command as core_command,seal
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from stage import SECRET
from seal import decrypt,safe_name,sha256_file
from alpaca_fit_job import stopped_run,StopUnknown
from runtime_identity import EXECUTION_IMAGE

HERE=Path(__file__).resolve().parent
SOURCES=('full_system_math_job.py','full_system_controller_worker.py','full_system_controller_policy.py',
    'full_system_controller_vector.py','full_system_controller_review.py','full_system_source.py','full_system_benchmark.py',
    'full_system_trials_job.py','full_system_core.py','owned_grid.py','owned_value.py','selective_journal.py',
    'build_core_variants.py','core_manifest.py','core_accounting_snapshot.py','core-source-basis.json','core_window_review.py',
    'alpaca_fit_job.py','alpaca_fit_stage.py','probe.py','runtime_identity.py','seal.py','stage.py')

def request(specs):
    from full_system_controller_policy import profiles
    return {'schema':'research.full-system-controller-request/1','core_artifacts':specs,
        'protocol_sha256':sha256_file(HERE/'full-system-search-protocol.json'),'profiles_sha256':hashlib.sha256(json.dumps(profiles(),sort_keys=True).encode()).hexdigest(),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'production_contacted':False,'hard_deadline_utc':'2026-10-29T17:57:00Z'}

def admit(spec,root,key,arm):
    archive=root/'core.zip'
    with archive.open('xb') as f:subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=f,check=True,timeout=120)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'CORE_ZIP_BYTES')
    with zipfile.ZipFile(archive) as z:
        raw=z.read('full-recovery-'+arm+'.json');need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'CORE_RECEIPT_BYTES')
        r=json.loads(raw);need(r['schema']=='research.full-system-recovery-receipt/1' and r['status']=='COMPLETE_CORE_INDEPENDENTLY_REVIEWED'
            and r['arm']==arm and int(r['run_id'])==spec['run_id'] and r['head']==spec['head']
            and r['request_sha256']==spec['request_sha256'] and not r['production_contacted'],'COMPLETE_CORE_RECEIPT')
        asset=r['encrypted_output'];need(z.getinfo(asset['name']).file_size==asset['bytes'],'CORE_CIPHER_LENGTH')
        cipher=root/'core.crseal'
        with z.open(asset['name']) as src,cipher.open('xb') as out:shutil.copyfileobj(src,out)
    plain=root/'authenticated.tar.gz';decrypt(cipher,plain,key,asset['sha256']);dest=root/'core';dest.mkdir()
    with tarfile.open(plain,'r:gz') as tar:
        first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'CORE_MANIFEST')
        raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'CORE_MANIFEST_SHA')
        m=json.loads(raw);need(m['schema']=='research.full-system-output/1' and m['stage']=='multiyear-core-path' and m['arm']==arm
            and int(m['run_id'])==spec['run_id'] and m['head']==spec['head'] and m['request_sha256']==spec['request_sha256'],'CORE_MANIFEST_SCOPE')
        inventory=m['members'];need(len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<=1024**3,'CORE_INVENTORY_BOUND');seen=set()
        for item in tar:
            if item.name=='manifest.json':continue
            safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'CORE_MEMBER');seen.add(item.name)
            v=inventory[item.name];need(item.size==v['bytes'],'CORE_MEMBER_LENGTH');p=dest/item.name;p.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(item) as src,p.open('xb') as out:shutil.copyfileobj(src,out)
            need(sha256_file(p)==v['sha256'],'CORE_MEMBER_HASH')
        need(seen==set(inventory),'ALL_CORE_MEMBERS')
    for name in ('economic-worker-inspect.json','independent-review-stop/worker-inspect.json'):
        v=json.loads((dest/name).read_bytes());h=v['HostConfig'];mounts={p['Destination']:p for p in v['Mounts'] if p['Type']=='bind'}
        need(sha256_file(dest/name)==spec['inspections'][name] and not v['State']['Running'] and not v['State']['OOMKilled'] and v['State']['ExitCode']==0
            and v['Image']==EXECUTION_IMAGE and h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['Memory']==h['MemorySwap']==8*1024**3
            and h['NanoCpus']==2000000000 and set(mounts)=={'/variant','/frozen','/driver','/out'} and mounts['/out']['RW']
            and all(not v['RW'] for k,v in mounts.items() if k!='/out'),'ACTUAL_CORE_STOP_FENCES')
    need(sha256_file(dest/'core-review.json')==spec['review_sha256'] and json.loads((dest/'core-review.json').read_bytes())['complete'],'ACTUAL_COMPLETE_CORE_REVIEW')
    return dest

def inspect(name,identity=None):
    need(re.fullmatch(r'capital-full-core-(b|c1|c2|c3)-(worker|review)-[0-9]+-1',name) is not None,'MATH_NAME')
    v=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c=v['HostConfig'],v['Config'];mounts={m['Destination']:m for m in v['Mounts'] if m['Type']=='bind'};reviewer='-review-' in name
    need(v['Name']=='/'+name and v['Image']==EXECUTION_IMAGE and (identity is None or v['Id']==identity),'MATH_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
        and h['PidsLimit']==64 and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']),'MATH_FENCES')
    need(set(mounts)==({'/variant','/frozen','/driver','/out','/core','/evidence'} if reviewer else {'/variant','/frozen','/driver','/out','/core'})
        and mounts['/out']['RW'] and all(not m['RW'] for k,m in mounts.items() if k!='/out') and c['WorkingDir']=='/variant'
        and c['User']==f'{os.getuid()}:{os.getgid()}' and c['Labels'].get('research.study')=='full-system-search-20261029'
        and c['Labels'].get('research.role')==('review' if reviewer else 'worker'),'MATH_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'}
    need(not any(k in forbidden and val for k,_,val in (s.partition('=') for s in c['Env'])),'MATH_CREDENTIALS');return v

def command(name,source,frozen,out,core,evidence=None):
    result=core_command(name,source,frozen,out,'review' if evidence else 'economic');start=result.index('--entrypoint')
    extra=['-e','OWNED_GRID_HOSTED=1','--mount',f'type=bind,source={core},target=/core,readonly']
    if evidence:extra+=['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    tail=['--entrypoint','python',EXECUTION_IMAGE,'-B','-u','/driver/full_system_controller_'+('review.py' if evidence else 'worker.py'),
        '--root','/core/book','--output','/out/review' if evidence else '/out/book']
    if evidence:tail+=['--evidence','/evidence/book']
    return result[:start]+extra+tail

def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_MATH_RERUN');req=json.loads(a.request.read_bytes())
    need(req==request(req['core_artifacts']) and a.arm in req['core_artifacts'],'EXACT_MATH_REQUEST')
    stage=json.loads(a.staging.read_bytes());need(stage['status']=='STAGING_PASSED' and stage['authenticated_before_parsing'] and not stage['replay_started']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['run_id']==os.environ['GITHUB_RUN_ID'],'MATH_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);private=temp/('full-controller-'+a.arm);private.mkdir(mode=0o700)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'MATH_RESOURCES')
    core=admit(req['core_artifacts'][a.arm],private,key,a.arm);os.environ.pop('GH_TOKEN',None)
    frozen=temp/'capital-risk-stage-001/inputs';source=private/'source';binding=json.loads((core/'private-source-bindings.json').read_bytes())
    need(build(frozen/'source-fixed',source,binding['parameters'])==binding,'EXACT_515_CORE_SOURCE')
    output=private/'output';output.mkdir();(output/'request.json').write_bytes(a.request.read_bytes());(output/'private-source-bindings.json').write_text(json.dumps(binding)+'\n')
    for p in source.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(source,0o555)
    receipt={'schema':'research.full-system-controller-receipt/1','arm':a.arm,'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],
        'request_sha256':sha256_file(a.request),'protocol_sha256':req['protocol_sha256'],'production_contacted':False,'performance_admitted':False,'status':'NOT_STARTED'}
    known=False
    try:
        remaining=(datetime(2026,10,29,17,57,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds();need(remaining>900,'MATH_REMAINING_BUDGET')
        name='capital-full-core-'+a.arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(command(name,source,frozen,output,core),name,output,deadline=min(900,int(remaining)-600),inspector=inspect);known=True;receipt['worker']=w
        shutil.copyfile(output/'worker-inspect.json',output/'economic-worker-inspect.json');receipt['status']='STOPPED_CONTROLLER_PRESERVED'
        if w['exit_code']==0 and not w['oom_killed']:
            audit=private/'review';audit.mkdir();name='capital-full-core-'+a.arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            r=stopped_run(command(name,source,frozen,audit,core,output),name,audit,deadline=600,inspector=inspect);receipt['reviewer']=r
            shutil.copytree(audit,output/'independent-review-stop')
            if r['exit_code']==0 and not r['oom_killed'] and json.loads((audit/'review/independent-review.json').read_bytes())['status']=='FULL_SYSTEM_CONTROLLER_REVIEW_PASSED':receipt['status']='COMPLETE_CONTROLLER_INDEPENDENTLY_REVIEWED'
    except StopUnknown:receipt['status']='REVIEW_STOP_UNKNOWN_CONTROLLER_PRESERVED' if known else 'CONTROLLER_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='CONTROLLER_REFUSED'
        if known:(output/'driver-failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(output,a.output.parent/('full-controller-'+a.arm+'.tar.crseal'),key,a.request,a.arm,stage='multiyear-controller')
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='COMPLETE_CONTROLLER_INDEPENDENTLY_REVIEWED' else 2)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--arm',choices=('B','C1','C2','C3'),required=True);main(p.parse_args())
