"""Source-bound transport and offline launch; no local oracle calculations."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BASE = '1e7f4b181fbcb998b3086833ab813c21b1c2ca8e'
LEGACY = '0bc38753ac1f85b31eb95f560720e6b037e892c5'
TRANSPORT = '553590ca197c55942aadeb690d5436abd49a35d1'
STOP_SOURCE = 'd482a44ace51114d22cc98c3a4ce251410f8d153'
REF = 'refs/heads/codex/sentinel-hindsight-oracle'
SECRET = 'CAPITAL_RISK_RESEARCH_KEY_20261027'
IMAGE = 'sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
DOC = 'docs/sentinel-hindsight-oracle-20261110.md'
WORKFLOW = '.github/workflows/sentinel-oracle-diagnostic.yml'
REQUEST = HERE / 'request.json'
FORBIDDEN = {'ALPACA_API_KEY','ALPACA_SECRET_KEY','APCA_API_KEY_ID','APCA_API_SECRET_KEY',
             'DATABASE_URL','PGPASSWORD','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY'}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    import hashlib
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    os.replace(temporary, path)


def expected_request():
    files = list(HERE.glob('*.py')) + [ROOT/DOC, ROOT/WORKFLOW, HERE/'solver-wheel.json']
    return dict(schema='research.sentinel-oracle-request/1', generation=2,
        prior_stopped_unadmitted_runs=[42772229461],
        harness_correction='ATTEST_NATIVE_MODEL_LOADING_AND_EXPLICIT_NUMERICAL_COEFFICIENT_POLICY',
        verified_main=BASE, legacy_commit=LEGACY, transport_commit=TRANSPORT,
        stop_source_commit=STOP_SOURCE,
        start='2018-01-02', end='2026-07-31', closes=2156,
        levels=['0','0.55','1'], first_funded_level='1', max_ordinary_changes=19,
        objectives=['MAX_WEALTH_NO_DD_DP','MAX_WEALTH_BASELINE_DD',
                    'MAX_WEALTH_HALF_BASELINE_DD','MIN_DD_ALWAYS_CORE_GROWTH'],
        solver_seconds_per_problem=1800, solver_relative_gap='0.0000001',
        solver_edge_log_zero_threshold='0.000000000001',
        phase='HINDSIGHT_DIAGNOSTIC_ONLY', Core_steps=0, Sentinel_steps=0,
        production_performance_claim=False, model_training=False, production_contacted=False,
        sources={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)})


def context(env):
    expected = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='flabber1835/stocker',
        GITHUB_REPOSITORY_OWNER='flabber1835', GITHUB_ACTOR='flabber1835',
        GITHUB_REF=REF, GITHUB_REF_TYPE='branch', GITHUB_EVENT_NAME='push',
        GITHUB_RUN_ATTEMPT='1', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
        RUNNER_ARCH='X64', ImageOS='ubuntu24')
    need(all(env.get(k)==v for k,v in expected.items()), 'EXACT_HOSTED_CONTEXT')
    need(not any(env.get(k) for k in FORBIDDEN), 'NO_PRODUCTION_CREDENTIALS')
    need(os.name=='posix' and Path(env['RUNNER_TEMP']).resolve()==Path('/home/runner/work/_temp'), 'HOSTED_PATH')
    need(re.fullmatch('[a-f0-9]{40}',env.get('GITHUB_SHA','')) and
         re.fullmatch('[1-9][0-9]*',env.get('GITHUB_RUN_ID','')), 'HOSTED_IDENTITY')


def dependencies(legacy, transport, stoprepo):
    for folder, expected in ((legacy,LEGACY),(transport,TRANSPORT),(stoprepo,STOP_SOURCE)):
        head = subprocess.run(['git','-C',str(folder),'rev-parse','HEAD'],capture_output=True,text=True,check=True,timeout=20).stdout.strip()
        clean = subprocess.run(['git','-C',str(folder),'status','--porcelain','--untracked-files=no'],capture_output=True,text=True,check=True,timeout=20).stdout.strip()
        need(head==expected and not clean, 'PINNED_UNCHANGED_DEPENDENCY')
    sys.path.insert(0,str(legacy/'research/capital_risk'))
    path = transport/'research/persistent_share_reconciliation/job.py'
    spec = importlib.util.spec_from_file_location('_qualified_transport_data',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe(legacy, transport, stoprepo):
    need(json.loads(REQUEST.read_bytes())==expected_request(), 'EXACT_REQUEST')
    module = dependencies(legacy,transport,stoprepo)
    from runtime_identity import EXECUTION_IMAGE
    from alpaca_fit_job import stopped_run
    from full_system_trials_job import seal
    need(EXECUTION_IMAGE==IMAGE, 'RUNTIME_IDENTITY')
    return dict(status='DATA_SOURCE_PROBE_PASSED',canonical_runtime_executed=False)


def command(name, role, p00, legacy, stoprepo, solver, out, evidence=None):
    argv = ['docker','run','-d','--name',name,'--pull','never','--network','none','--read-only',
        '--memory','8g','--memory-swap','8g','--cpus','2','--pids-limit','64','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=128m',
        '--user',f'{os.getuid()}:{os.getgid()}','--label','research.study=sentinel-oracle-20261110',
        '--label','research.role='+role,'-w','/current','-e','SENTINEL_ORACLE_HOSTED=1',
        '-e','PYTHONPATH=/current/research/sentinel_oracle:/fixed:/fixed/shared:/legacy/research/capital_risk:/solver',
        '-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1',
        '--mount',f'type=bind,source={ROOT},target=/current,readonly',
        '--mount',f'type=bind,source={stoprepo},target=/stoprepo,readonly',
        '--mount',f'type=bind,source={legacy},target=/legacy,readonly',
        '--mount',f'type=bind,source={solver},target=/solver,readonly',
        '--mount',f'type=bind,source={p00},target=/p00,readonly',
        '--mount',f'type=bind,source={out},target=/out']
    if evidence is not None:
        argv += ['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    argv += ['--entrypoint','python',IMAGE,'-B','-u',f'/current/research/sentinel_oracle/{role}.py',
             '--book','/p00/book','--out','/out/'+role]
    if evidence is not None:
        argv += ['--evidence','/evidence/worker']
    return argv


def inspect(name, identity=None):
    need(re.fullmatch('sentinel-oracle-(worker|review)-[1-9][0-9]*-1',name), 'CONTAINER_NAME')
    value = json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c = value['HostConfig'],value['Config']
    role = 'review' if '-review-' in name else 'worker'
    mounts = {m['Destination']:m for m in value['Mounts'] if m['Type']=='bind'}
    need(value['Name']=='/'+name and value['Image']==IMAGE and (identity is None or value['Id']==identity), 'ACTUAL_IDENTITY')
    need(h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['Memory']==h['MemorySwap']==8*1024**3
         and h['NanoCpus']==2000000000 and h['PidsLimit']==64 and h['CapDrop']==['ALL']
         and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']), 'ACTUAL_FENCES')
    need(set(mounts)==({'/current','/stoprepo','/legacy','/solver','/p00','/out'}|({'/evidence'} if role=='review' else set()))
         and mounts['/out']['RW'] and all(not m['RW'] for k,m in mounts.items() if k!='/out')
         and c['WorkingDir']=='/current' and c['User']==f'{os.getuid()}:{os.getgid()}'
         and c['Labels'].get('research.study')=='sentinel-oracle-20261110'
         and c['Labels'].get('research.role')==role, 'ACTUAL_MOUNTS')
    need(not any(k in FORBIDDEN|{SECRET,'GH_TOKEN','GITHUB_TOKEN'} and v
         for k,_,v in (item.partition('=') for item in c['Env'])), 'ACTUAL_NO_CREDENTIALS')
    expected = ['-B','-u',f'/current/research/sentinel_oracle/{role}.py','--book','/p00/book','--out','/out/'+role]
    if role=='review':
        expected += ['--evidence','/evidence/worker']
    need(c['Entrypoint']==['python'] and c['Cmd']==expected, 'ACTUAL_ENTRYPOINT')
    return value


def acquire_solver(temp):
    """Authenticate one published dependency wheel; no numerical calls."""
    spec=json.loads((HERE/'solver-wheel.json').read_bytes())
    need(spec['version']=='1.15.1' and spec['bytes']==5034168
         and spec['filename']=='highspy-1.15.1-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl'
         and spec['sha256']=='9730647160a6481426729f46d9989a0507d05f3cf96f9fb180f4ab9891bea67b'
         and spec['url']=='https://files.pythonhosted.org/packages/82/6b/18bec60d8585df860b8d33d310e99e7893eaabe3c8e9ebfa7e387ba9d2a4/highspy-1.15.1-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl',
         'EXACT_SOLVER_DEPENDENCY')
    target=temp/spec['filename']
    with urllib.request.urlopen(spec['url'],timeout=60) as src,target.open('xb') as dst:
        while block:=src.read(1024**2):
            dst.write(block)
            need(dst.tell()<=spec['bytes'],'SOLVER_DOWNLOAD_BOUND')
    need(target.stat().st_size==spec['bytes'] and sha(target)==spec['sha256'],'AUTHENTICATED_SOLVER_WHEEL')
    folder=temp/'solver';folder.mkdir(mode=0o700)
    members={}
    with zipfile.ZipFile(target) as zipped:
        infos=zipped.infolist()
        need(len(infos)<1000 and sum(v.file_size for v in infos)<100*1024**2,'SOLVER_EXPANDED_BOUND')
        for info in infos:
            name=info.filename
            need('\\' not in name and ':' not in name and not name.startswith('/')
                 and all(p not in ('','.','..') for p in name.rstrip('/').split('/')),'SOLVER_MEMBER_PATH')
            need((info.external_attr>>16)&0o170000 in (0,0o100000,0o040000),'SOLVER_MEMBER_TYPE')
            path=folder/name
            need(path.resolve().is_relative_to(folder.resolve()),'SOLVER_MEMBER_SCOPE')
            if info.is_dir():path.mkdir(parents=True,exist_ok=True);continue
            need(name not in members,'UNIQUE_SOLVER_MEMBER')
            path.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(info) as src,path.open('xb') as dst:shutil.copyfileobj(src,dst)
            members[name]={'bytes':path.stat().st_size,'sha256':sha(path)}
    save(folder/'wheel-proof.json',{'wheel':spec,'members':members})
    need((folder/'highspy/__init__.py').is_file(),'SOLVER_PACKAGE_PRESENT')
    return folder


def launch(legacy, transport, stoprepo, output):
    context(os.environ)
    probe(legacy,transport,stoprepo)
    helper = dependencies(legacy,transport,stoprepo)
    import stage
    from runtime_identity import verify_archive,verify_loaded
    from seal import decrypt
    from alpaca_fit_job import stopped_run,StopUnknown
    from full_system_trials_job import seal
    key = base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    need(len(key)==32, 'RESEARCH_TRANSFER_KEY')
    temp = Path(os.environ['RUNNER_TEMP'])/'sentinel-oracle-001'
    temp.mkdir(mode=0o700)
    need(shutil.disk_usage(temp).free>=6*1024**3, 'DISK_RESERVE')
    out = temp/'output';out.mkdir()
    receipt = dict(schema='research.sentinel-oracle-receipt/1',status='INPUT_AUTHENTICATION_PENDING',
        head=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],request_sha256=sha(REQUEST),
        protocol_sha256=sha(ROOT/DOC),production_contacted=False,Core_steps=0,Sentinel_steps=0,
        diagnostic_qualified=False,portfolio_performance_admitted=False,
        phase='HINDSIGHT_DIAGNOSTIC_ONLY',model_training=False)
    save(output,receipt)
    known,launched,started = False,False,time.monotonic()
    try:
        original = json.loads((legacy/'research/capital_risk/stage-request.json').read_bytes())
        stage.validate_request(original)
        asset = stage.acquire('runtime.tar.crseal',original['assets']['runtime.tar.crseal'],temp)
        runtime = temp/'runtime.tar'
        decrypt(asset,runtime,key,original['assets']['runtime.tar.crseal']['sha256'])
        verify_archive(runtime)
        with runtime.open('rb') as stream:
            subprocess.run(['docker','load','--quiet'],stdin=stream,capture_output=True,check=True,timeout=120)
        image = json.loads(subprocess.run(['docker','image','inspect',IMAGE],capture_output=True,check=True,timeout=20).stdout)[0]
        verify_loaded(image)
        solver=acquire_solver(temp)
        receipt['solver_wheel_sha256']='9730647160a6481426729f46d9989a0507d05f3cf96f9fb180f4ab9891bea67b'
        p00 = helper.admit_p00(legacy,temp,key)
        os.environ.pop('GH_TOKEN',None)
        (out/'request.json').write_bytes(REQUEST.read_bytes())
        name = 'sentinel-oracle-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['status']='OFFLINE_DIAGNOSTIC_RUNNING';save(output,receipt)
        launched = True
        receipt['worker']=stopped_run(command(name,'worker',p00,legacy,stoprepo,solver,out),name,out,deadline=6000,inspector=inspect)
        known = True
        receipt['status']='STOPPED_DIAGNOSTIC_REVIEW_PENDING';save(output,receipt)
        if receipt['worker']['exit_code']==0 and not receipt['worker']['oom_killed']:
            audit=temp/'review';audit.mkdir()
            name='sentinel-oracle-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            receipt['reviewer']=stopped_run(command(name,'review',p00,legacy,stoprepo,solver,audit,out),name,audit,deadline=1800,inspector=inspect)
            shutil.copytree(audit,out/'independent-review-stop')
            if receipt['reviewer']['exit_code']==0 and not receipt['reviewer']['oom_killed']:
                reviewed=json.loads((audit/'review/independent-review.json').read_bytes())
                need(reviewed['status']=='SENTINEL_ORACLE_DIAGNOSTIC_REVIEW_PASSED', 'INDEPENDENT_REVIEW_VERDICT')
                receipt['status']='REVIEWED_PENDING_ARTIFACT_ADMISSION'
    except StopUnknown:
        receipt['status']='STOP_UNKNOWN_NO_ADMISSION'
    except Exception as error:
        receipt['status']='REFUSED_NO_ADMISSION';receipt['error_type']=type(error).__name__
        (out/'driver-failure.json').write_bytes((json.dumps(dict(type=type(error).__name__,message=str(error)))+'\n').encode())
        known=known or not launched
    finally:
        if known:
            receipt['encrypted_output']=seal(out,output.parent/'sentinel-oracle.tar.crseal',key,REQUEST,'P00',
                stage='campaign-candidate',protocol_sha256=sha(ROOT/DOC))
        key=None
        receipt['elapsed_seconds']=time.monotonic()-started
        save(output,receipt)
    print(json.dumps(receipt))
    need(receipt['status']=='REVIEWED_PENDING_ARTIFACT_ADMISSION','POSITIVE_DIAGNOSTIC_AND_REVIEW_REQUIRED')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('prepare','probe','run'),required=True)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--transport',type=Path,required=True)
    parser.add_argument('--stoprepo',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.mode=='prepare':
        need(not REQUEST.exists(),'REQUEST_ALREADY_EXISTS');save(REQUEST,expected_request())
    elif args.mode=='probe':
        print(json.dumps(probe(args.legacy,args.transport,args.stoprepo)))
    else:
        launch(args.legacy,args.transport,args.stoprepo,args.output)
