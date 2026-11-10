"""Source-bound transport and offline launch; no local stop calculations."""
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BASE = '1e7f4b181fbcb998b3086833ab813c21b1c2ca8e'
LEGACY = '0bc38753ac1f85b31eb95f560720e6b037e892c5'
TRANSPORT = '553590ca197c55942aadeb690d5436abd49a35d1'
STOP_SOURCE = 'd482a44ace51114d22cc98c3a4ce251410f8d153'
REF = 'refs/heads/codex/wider-stop-diagnostic'
SECRET = 'CAPITAL_RISK_RESEARCH_KEY_20261027'
IMAGE = 'sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
DOC = 'docs/wider-stop-diagnostic-20261109.md'
WORKFLOW = '.github/workflows/wider-stop-diagnostic.yml'
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
    files = list(HERE.glob('*.py')) + [ROOT/DOC, ROOT/WORKFLOW]
    return dict(schema='research.wider-stop-request/1', generation=1,
        verified_main=BASE, legacy_commit=LEGACY, transport_commit=TRANSPORT,
        stop_source_commit=STOP_SOURCE,
        start='2018-01-02', end='2026-07-31', closes=2156, activation='0.10',
        stops=['0.30','0.35','0.40'], forward_sessions=60,
        cohort_episodes=17, completed_episodes=16, full_followup=13,
        original_stop='0.30', Core_steps=0, Sentinel_steps=0,
        portfolio_performance_claim=False, production_contacted=False,
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


def command(name, role, p00, frozen, stoprepo, out, evidence=None):
    argv = ['docker','run','-d','--name',name,'--pull','never','--network','none','--read-only',
        '--memory','8g','--memory-swap','8g','--cpus','2','--pids-limit','64','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=128m',
        '--user',f'{os.getuid()}:{os.getgid()}','--label','research.study=wider-stop-20261109',
        '--label','research.role='+role,'-w','/current','-e','WIDER_STOP_HOSTED=1',
        '-e','PYTHONPATH=/current/research/wider_stop',
        '--mount',f'type=bind,source={ROOT},target=/current,readonly',
        '--mount',f'type=bind,source={stoprepo},target=/stoprepo,readonly',
        '--mount',f'type=bind,source={frozen},target=/frozen,readonly',
        '--mount',f'type=bind,source={p00},target=/p00,readonly',
        '--mount',f'type=bind,source={out},target=/out']
    if evidence is not None:
        argv += ['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    argv += ['--entrypoint','python',IMAGE,'-B','-u',f'/current/research/wider_stop/{role}.py',
             '--book','/p00/book','--archive','/frozen/archive/corpus.zip',
             '--bundle','/frozen/bundle','--out','/out/'+role]
    if evidence is not None:
        argv += ['--evidence','/evidence/worker']
    return argv


def inspect(name, identity=None):
    need(re.fullmatch('wider-stop-(worker|review)-[1-9][0-9]*-1',name), 'CONTAINER_NAME')
    value = json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c = value['HostConfig'],value['Config']
    role = 'review' if '-review-' in name else 'worker'
    mounts = {m['Destination']:m for m in value['Mounts'] if m['Type']=='bind'}
    need(value['Name']=='/'+name and value['Image']==IMAGE and (identity is None or value['Id']==identity), 'ACTUAL_IDENTITY')
    need(h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['Memory']==h['MemorySwap']==8*1024**3
         and h['NanoCpus']==2000000000 and h['PidsLimit']==64 and h['CapDrop']==['ALL']
         and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']), 'ACTUAL_FENCES')
    need(set(mounts)==({'/current','/stoprepo','/frozen','/p00','/out'}|({'/evidence'} if role=='review' else set()))
         and mounts['/out']['RW'] and all(not m['RW'] for k,m in mounts.items() if k!='/out')
         and c['WorkingDir']=='/current' and c['User']==f'{os.getuid()}:{os.getgid()}'
         and c['Labels'].get('research.study')=='wider-stop-20261109'
         and c['Labels'].get('research.role')==role, 'ACTUAL_MOUNTS')
    need(not any(k in FORBIDDEN|{SECRET,'GH_TOKEN','GITHUB_TOKEN'} and v
         for k,_,v in (item.partition('=') for item in c['Env'])), 'ACTUAL_NO_CREDENTIALS')
    expected = ['-B','-u',f'/current/research/wider_stop/{role}.py','--book','/p00/book',
                '--archive','/frozen/archive/corpus.zip','--bundle','/frozen/bundle','--out','/out/'+role]
    if role=='review':
        expected += ['--evidence','/evidence/worker']
    need(c['Entrypoint']==['python'] and c['Cmd']==expected, 'ACTUAL_ENTRYPOINT')
    return value


def launch(legacy, transport, stoprepo, output):
    context(os.environ)
    probe(legacy,transport,stoprepo)
    helper = dependencies(legacy,transport,stoprepo)
    import stage
    from runtime_identity import verify_archive,verify_loaded
    from seal import decrypt,extract_verified
    from alpaca_fit_job import stopped_run,StopUnknown
    from full_system_trials_job import seal
    key = base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    need(len(key)==32, 'RESEARCH_TRANSFER_KEY')
    temp = Path(os.environ['RUNNER_TEMP'])/'wider-stop-001'
    temp.mkdir(mode=0o700)
    need(shutil.disk_usage(temp).free>=12*1024**3, 'DISK_RESERVE')
    out = temp/'output';out.mkdir()
    receipt = dict(schema='research.wider-stop-receipt/1',status='INPUT_AUTHENTICATION_PENDING',
        head=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],request_sha256=sha(REQUEST),
        protocol_sha256=sha(ROOT/DOC),production_contacted=False,Core_steps=0,Sentinel_steps=0,
        diagnostic_qualified=False,portfolio_performance_admitted=False)
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
        asset = stage.acquire('data.tar.crseal',original['assets']['data.tar.crseal'],temp)
        plain = temp/'data.tar'
        decrypt(asset,plain,key,original['assets']['data.tar.crseal']['sha256'])
        frozen = temp/'inputs'
        manifest = extract_verified(plain,frozen,original['manifest_sha256'])
        need(manifest['source_files']==514 and manifest['protocol_sha256']==stage.PROTOCOL
             and manifest['expected_image']==stage.IMAGE, 'FROZEN_INPUT_LINEAGE')
        need(sha(frozen/'archive/corpus.zip')==
             'c0a62a6bbb8b67f77a1fca34f5e836a36f90bdf67dd83e196ef3d3369a7925f6',
             'POST_EXIT_CORPUS_IDENTITY')
        receipt['frozen_manifest_sha256']=original['manifest_sha256']
        receipt['post_exit_corpus_sha256']=sha(frozen/'archive/corpus.zip')
        p00 = helper.admit_p00(legacy,temp,key)
        os.environ.pop('GH_TOKEN',None)
        (out/'request.json').write_bytes(REQUEST.read_bytes())
        name = 'wider-stop-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['status']='OFFLINE_DIAGNOSTIC_RUNNING';save(output,receipt)
        launched = True
        receipt['worker']=stopped_run(command(name,'worker',p00,frozen,stoprepo,out),name,out,deadline=600,inspector=inspect)
        known = True
        receipt['status']='STOPPED_DIAGNOSTIC_REVIEW_PENDING';save(output,receipt)
        if receipt['worker']['exit_code']==0 and not receipt['worker']['oom_killed']:
            audit=temp/'review';audit.mkdir()
            name='wider-stop-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            receipt['reviewer']=stopped_run(command(name,'review',p00,frozen,stoprepo,audit,out),name,audit,deadline=600,inspector=inspect)
            shutil.copytree(audit,out/'independent-review-stop')
            if receipt['reviewer']['exit_code']==0 and not receipt['reviewer']['oom_killed']:
                reviewed=json.loads((audit/'review/independent-review.json').read_bytes())
                need(reviewed['status']=='WIDER_STOP_DIAGNOSTIC_REVIEW_PASSED', 'INDEPENDENT_REVIEW_VERDICT')
                receipt['status']='REVIEWED_PENDING_ARTIFACT_ADMISSION'
    except StopUnknown:
        receipt['status']='STOP_UNKNOWN_NO_ADMISSION'
    except Exception as error:
        receipt['status']='REFUSED_NO_ADMISSION';receipt['error_type']=type(error).__name__
        (out/'driver-failure.json').write_bytes((json.dumps(dict(type=type(error).__name__,message=str(error)))+'\n').encode())
        known=known or not launched
    finally:
        if known:
            receipt['encrypted_output']=seal(out,output.parent/'wider-stop.tar.crseal',key,REQUEST,'P00',
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
