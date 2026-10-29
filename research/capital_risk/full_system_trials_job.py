"""Matched independent hosted Core origins; no broker/production authority."""
import argparse,base64,hashlib,io,json,os,re,shutil,subprocess,tarfile
from datetime import datetime,timezone
from pathlib import Path
from alpaca_fit_job import stopped_run,StopUnknown
from full_system_source import proposals,build
from full_system_benchmark import need
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from stage import SECRET,PROTOCOL,IMAGE
from seal import EncryptWriter,sha256_file

HERE=Path(__file__).resolve().parent
SOURCES=('full_system_trials_job.py','full_system_core.py','full_system_source.py','full_system_benchmark.py',
    'build_core_variants.py','core_manifest.py','core_accounting_snapshot.py','core-source-basis.json',
    'core_window_review.py','alpaca_fit_job.py','alpaca_fit_stage.py','probe.py','runtime_identity.py','seal.py','stage.py')
ARMS={'B':0,'B0':0,'C1':1,'C2':2,'C3':3}


def expected_request():
    return {'schema':'research.full-system-core-trials-request/1','study_id':'full-system-search-20261029',
        'stage':'MULTIYEAR_JOINT_SCREEN_CORE_PATHS','protocol_sha256':sha256_file(HERE/'full-system-search-protocol.json'),
        'measurement':{'run_id':40889340839,'head':'706a2bb5f6bb222dfe96bcc267a4b6dda8579010','artifact_id':12904023194,
            'artifact_zip_sha256':'5f66065daf87e00f10686d8722775182817997945cb179766c51796df2836f8f','independently_reviewed':True},
        'source_files':{n:{'bytes':(HERE/n).stat().st_size,'sha256':sha256_file(HERE/n)} for n in SOURCES},
        'proposals':proposals(),'arms':ARMS,'production_contacted':False,'same_approved_encrypted_artifact_flow':True,
        'four_hour_initial_budget':True,'hard_deadline_utc':'2026-10-29T17:57:00Z'}


def inspect(name,identity=None):
    need(re.fullmatch(r'capital-full-core-(?:b0|b|c1|c2|c3)-(?:worker|review)-[0-9]+-1',name) is not None,'TRIAL_WORKER_NAME')
    v=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c=v['HostConfig'],v['Config'];mounts={m['Destination']:m for m in v['Mounts'] if m['Type']=='bind'}
    need(v['Name']=='/'+name and v['Image']==EXECUTION_IMAGE and (identity is None or v['Id']==identity),'TRIAL_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
        and h['PidsLimit']==64 and h['ReadonlyRootfs'] and h['CapDrop']==['ALL']
        and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']),'TRIAL_FENCES')
    need(set(mounts)=={'/variant','/frozen','/driver','/out'} and mounts['/out']['RW']
        and all(not m['RW'] for k,m in mounts.items() if k!='/out') and c['WorkingDir']=='/variant'
        and c['User']==f'{os.getuid()}:{os.getgid()}' and c['Labels'].get('research.study')=='full-system-search-20261029'
        and c['Labels'].get('research.role')==('review' if '-review-' in name else 'worker'),'TRIAL_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'}
    need(not any(k in forbidden and val for k,_,val in (s.partition('=') for s in c['Env'])),'TRIAL_CREDENTIALS')
    return v


def command(name,source,frozen,out,mode):
    return ['docker','run','-d','--name',name,'--pull','never','--network','none','--read-only',
        '--memory','8g','--memory-swap','8g','--cpus','2','--pids-limit','64','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=128m',
        '--user',f'{os.getuid()}:{os.getgid()}','--label','research.study=full-system-search-20261029',
        '--label','research.role='+('review' if mode=='review' else 'worker'),'-w','/variant',
        '-e','PYTHONPATH=/variant:/variant/shared:/driver','-e','FULL_SYSTEM_HOSTED=1',
        '-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1',
        '--mount',f'type=bind,source={source},target=/variant,readonly',
        '--mount',f'type=bind,source={frozen},target=/frozen,readonly',
        '--mount',f'type=bind,source={HERE},target=/driver,readonly',
        '--mount',f'type=bind,source={out},target=/out','--entrypoint','python',EXECUTION_IMAGE,
        '-B','-u','/driver/full_system_core.py','--mode',mode]


def seal(root,target,key,request,arm,*,stage='multiyear-core-path',protocol_sha256=None):
    need(stage in ('multiyear-core-path','multiyear-controller','campaign-baseline','campaign-continuation'),'DECLARED_EXPORT_STAGE')
    protocol_sha256=protocol_sha256 or expected_request()['protocol_sha256']
    need(re.fullmatch('[a-f0-9]{64}',protocol_sha256) is not None,'EXPORT_PROTOCOL_SHA')
    members={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha256_file(p)}
        for p in sorted(root.rglob('*')) if p.is_file()}
    need(len(members)<5000 and sum(v['bytes'] for v in members.values())<=1024**3
        and not any(p.is_symlink() for p in root.rglob('*')),'TRIAL_EXPORT_BOUND')
    manifest=json.dumps({'schema':'research.full-system-output/1','stage':stage,'arm':arm,
        'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],
        'request_sha256':sha256_file(request),'protocol_sha256':protocol_sha256,
        'compression':'TAR_GZIP_V1','members':members},sort_keys=True).encode()+b'\n'
    temporary=target.with_suffix('.partial')
    with temporary.open('xb') as output:
        writer=EncryptWriter(output,key)
        with tarfile.open(fileobj=writer,mode='w|gz',compresslevel=1) as archive:
            first=tarfile.TarInfo('manifest.json');first.size=len(manifest);archive.addfile(first,io.BytesIO(manifest))
            for name,spec in members.items():
                info=tarfile.TarInfo(name);info.size=spec['bytes'];info.mode=0o600
                with (root/name).open('rb') as stream:archive.addfile(info,stream)
        writer.finish();output.flush();os.fsync(output.fileno())
    os.replace(temporary,target)
    return {'name':target.name,'bytes':target.stat().st_size,'sha256':sha256_file(target),
        'manifest_sha256':hashlib.sha256(manifest).hexdigest(),'compression':'TAR_GZIP_V1'}


def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_TRIAL_RERUN')
    request=json.loads(a.request.read_bytes());need(request==expected_request(),'EXACT_TRIAL_REQUEST')
    proof=json.loads(a.staging.read_bytes())
    need(proof['status']=='STAGING_PASSED' and proof['run_id']==os.environ['GITHUB_RUN_ID']
        and proof['source_commit']==os.environ['GITHUB_SHA'] and proof['protocol_sha256']==PROTOCOL
        and proof['runtime_image']==IMAGE and proof['execution_image']==EXECUTION_IMAGE
        and proof['source_files_verified']==514 and proof['members_verified']==591
        and proof['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and proof['authenticated_before_parsing'] and proof['offline_image_source_verified']
        and proof['runtime_index_config_layer_chain_verified'] and not proof['replay_started'],'TRIAL_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';source=temp/('full-core-source-'+a.arm)
    root=temp/('full-core-output-'+a.arm);root.mkdir(mode=0o700,exist_ok=False)
    need((os.cpu_count() or 0)>=4 and memory_bytes()['MemAvailable']>=10*1024**3
        and shutil.disk_usage(temp).free>=12*1024**3,'TRIAL_RESOURCES')
    choice=proposals()[ARMS[a.arm]];binding=build(frozen/'source-fixed',source,choice['parameters'])
    (root/'private-source-bindings.json').write_text(json.dumps(binding,indent=2)+'\n')
    (root/'request.json').write_bytes(a.request.read_bytes())
    (root/'protocol.json').write_bytes((HERE/'full-system-search-protocol.json').read_bytes())
    for p in source.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(source,0o555)
    receipt={'schema':'research.full-system-core-trial-receipt/1','arm':a.arm,'profile_id':choice['id'],
        'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],
        'request_sha256':sha256_file(a.request),'protocol_sha256':request['protocol_sha256'],
        'production_contacted':False,'performance_admitted':False,'status':'NOT_STARTED'}
    known=False
    try:
        seconds=(datetime(2026,10,29,17,57,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds()
        deadline=min(10600,int(seconds)-900);need(deadline>600,'STUDY_TIME_BUDGET')
        name='capital-full-core-'+a.arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        worker=stopped_run(command(name,source,frozen,root,'economic'),name,root,deadline=deadline,inspector=inspect)
        known=True;receipt['worker']=worker;receipt['status']='STOPPED_CORE_PRESERVED'
        # Preserve exact economic stop independently of the reviewer receipt.
        shutil.copyfile(root/'worker-inspect.json',root/'economic-worker-inspect.json')
        shutil.copyfile(root/'worker.log',root/'economic-worker.log')
        if (root/'book/checkpoint.json.gz').is_file() and not worker['oom_killed']:
            reviewroot=temp/('full-core-review-'+a.arm);reviewroot.mkdir(mode=0o700)
            # Reviewer shares the proven stopped private output, in a new process.
            name='capital-full-core-'+a.arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            # stopped_run writes an inspection to its separate diagnostics folder.
            reviewed=stopped_run(command(name,source,frozen,root,'review'),name,reviewroot,deadline=600,inspector=inspect)
            receipt['reviewer']=reviewed;shutil.copytree(reviewroot,root/'independent-review-stop')
            if reviewed['exit_code']==0 and not reviewed['oom_killed']:
                actual=json.loads((root/'core-review.json').read_bytes())
                receipt['status']='COMPLETE_CORE_INDEPENDENTLY_REVIEWED' if actual['complete'] and worker['exit_code']==0 else 'PARTIAL_CORE_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='REVIEW_STOP_UNKNOWN_CORE_PRESERVED' if known else 'CORE_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='CORE_REFUSED';receipt['error_type']=type(exc).__name__
        if known:(root/'driver-failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(root,a.output.parent/('full-core-'+a.arm+'.tar.crseal'),key,a.request,a.arm)
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='COMPLETE_CORE_INDEPENDENTLY_REVIEWED' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--arm',choices=ARMS,required=True);main(p.parse_args())
