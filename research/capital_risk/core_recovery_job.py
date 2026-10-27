"""Hosted qualification of exact diagnostic source succession; no session replay."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import tarfile

from baseline_prefix import run_worker,UnprovenStopped,worker_stage,worker_arm
from build_core_variants import build
from core_gate_job import gate_command
from core_window_job import window_command
from probe import check_context,admitted_output,FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,SECRET,IMAGE

HERE=Path(__file__).resolve().parent
OLD_HEAD='14332ba4b490086a3294205f4fef9a0ba8ae9ce4'
OLD_RUN='40564376348'


def require(value,code):
    if not value:raise ValueError(code)


def validate_request(r):
    require(set(r)=={'schema','request_id','stage','core_protocol_sha256','execution_sha256',
        'compiler_fixture_sha256','old_run_id','old_source_commit','windows'},'REFUSED_RECOVERY_REQUEST_SHAPE')
    require(r['schema']=='research.capital-risk-recovery-qualification-request/1'
        and r['request_id']=='core-window-recovery-qualification-001' and r['stage']=='recovery-qualification'
        and r['old_run_id']==OLD_RUN and r['old_source_commit']==OLD_HEAD,'REFUSED_RECOVERY_IDENTITY')
    for field,name in [('core_protocol_sha256','core-screen-protocol.json'),
        ('execution_sha256','core-window-execution.json'),('compiler_fixture_sha256','fixtures/window001_build_core_variants.py.txt')]:
        require(r[field]==sha256_file(HERE/name),'REFUSED_RECOVERY_CONTRACT_'+field)
    require(set(r['windows'])=={'stress2021','recent2025'},'REFUSED_RECOVERY_WINDOWS')
    for window,v in r['windows'].items():
        require(set(v)=={'artifact_id','artifact_name','receipt_sha256','encrypted_outputs',
            'baseline_predecessor','source_bindings_sha256','recorded_inspections'},'REFUSED_RECOVERY_WINDOW_SPEC')
        require(v['artifact_name']=='capital-risk-short-window-'+window+'-'+OLD_HEAD,'REFUSED_RECOVERY_ARTIFACT_NAME')
        require({a['arm'] for a in v['encrypted_outputs']}=={'QUAL','B','B0','C','V'}
            and len(v['encrypted_outputs'])==5,'REFUSED_RECOVERY_ARM_SET')


def inspect_stopped(path,expected_sha,*,allow_oom=False):
    require(sha256_file(path)==expected_sha,'REFUSED_RECORDED_INSPECTION_DIGEST')
    v=json.loads(path.read_bytes());name=v['Name'][1:];h=v['HostConfig'];c=v['Config']
    require(v['State']['Status']=='exited' and not v['State']['Running'] and (allow_oom or not v['State']['OOMKilled']),
        'REFUSED_OLD_WORKER_NOT_STOPPED')
    require(v['Image']==EXECUTION_IMAGE and c['Labels']['research.experiment']=='capital-risk-20261027'
        and c['Labels']['research.stage']==worker_stage(name) and c['Labels']['research.arm']==worker_arm(name),
        'REFUSED_OLD_WORKER_IDENTITY')
    require(h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['Memory']==h['MemorySwap']==2*1024**3
        and h['NanoCpus']==1000000000 and h['PidsLimit']==64 and h['CapDrop']==['ALL']
        and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),'REFUSED_OLD_WORKER_FENCES')
    mounts={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
    require(set(mounts)=={'/frozen','/out','/driver','/variant'} and mounts['/out']['RW']
        and all(not mounts[k]['RW'] for k in ('/frozen','/driver','/variant'))
        and c['WorkingDir']=='/variant' and c['User']=='1001:1001','REFUSED_OLD_WORKER_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GITHUB_TOKEN','GH_TOKEN'}
    require(not any(x.partition('=')[0] in forbidden and x.partition('=')[2] for x in c['Env']),
        'REFUSED_OLD_WORKER_CREDENTIALS')
    return dict(name=name,id=v['Id'],exit_code=v['State']['ExitCode'],stopped=True,oom=v['State']['OOMKilled'])


def restore_original(r,window,download,private,key):
    spec=r['windows'][window];path=download/'window.json'
    require(sha256_file(path)==spec['receipt_sha256'],'REFUSED_OLD_RECEIPT_DIGEST')
    receipt=json.loads(path.read_bytes())
    require(receipt['schema']=='research.capital-risk-window-receipt/1' and receipt['status']=='SHORT_WINDOW_REFUSED'
        and receipt['run_id']==OLD_RUN and receipt['source_commit']==OLD_HEAD and receipt['window']==window
        and receipt['core_protocol_sha256']==r['core_protocol_sha256']
        and receipt['execution_sha256']==r['execution_sha256'] and receipt['production_contacted'] is False
        and receipt['encrypted_outputs']==spec['encrypted_outputs'],'REFUSED_OLD_RECEIPT_BINDINGS')
    prior=private/'prior';prior.mkdir()
    for asset in receipt['encrypted_outputs']:
        arm=asset['arm'];require(asset['name']=='window-'+window+'-'+arm+'.tar.crseal','REFUSED_OLD_CIPHER_NAME')
        cipher=download/asset['name'];require(cipher.stat().st_size==asset['bytes'],'REFUSED_OLD_CIPHER_LENGTH')
        plain=private/(arm+'-original.authenticated.tar')
        decrypt(cipher,plain,key,asset['sha256'])
        with tarfile.open(plain,'r|') as tar:
            first=tar.next();require(first is not None and first.name=='manifest.json' and first.isfile()
                and first.size<=2*1024**2,'REFUSED_OLD_MANIFEST')
            raw=tar.extractfile(first).read();manifest=json.loads(raw)
        require(manifest['schema']=='research.capital-risk-output/1' and manifest['arm']==arm
            and manifest['stage']=='short-core-window' and manifest['protocol_sha256']==PROTOCOL
            and manifest['screen_protocol_sha256']==r['core_protocol_sha256'],'REFUSED_OLD_INVENTORY_IDENTITY')
        extract_verified(plain,prior/arm,hashlib.sha256(raw).hexdigest(),expected_schema='research.capital-risk-output/1')
    require(sha256_file(prior/'QUAL/source-bindings.json')==spec['source_bindings_sha256'],'REFUSED_OLD_SOURCE_BINDINGS')
    inspections=[]
    actual={p.relative_to(prior).as_posix() for p in prior.rglob('*-inspect.json')}
    require(actual==set(spec['recorded_inspections']) and len(actual)==7,'REFUSED_OLD_INSPECTION_SET')
    for name,expected in spec['recorded_inspections'].items():inspections.append(inspect_stopped(prior/name,expected))
    no_origins={}
    for arm in ('B0','C','V'):
        root=prior/arm/'run-001';result=json.loads((root/'result.json').read_bytes())
        require(result['status']=='REFUSED' and result['last_good_session'] is None and result['completed_sessions']==0
            and not list(root.rglob('*.json.gz')) and not (root/'identity.json').exists()
            and all((root/(n+'.jsonl')).stat().st_size==0 for n in ('formation','daily','monthly','watch')),
            'REFUSED_EXISTING_VARIANT_ORIGIN_'+arm)
        no_origins[arm]=True
    qualification=json.loads((prior/'QUAL/canonical-gate.json').read_bytes())
    require(qualification['status']=='CANONICAL_CORE_GATE_PASSED' and qualification['cases']==13,'REFUSED_OLD_QUALIFICATION')
    require(json.loads((prior/'QUAL/input-equivalence.json').read_bytes())['status']=='BOUNDED_INPUT_BOUNDARIES_MATCHED',
        'REFUSED_OLD_INPUT_BOUNDARIES')
    (private/'original-admission.json').write_text(json.dumps(dict(stopped_inspections=inspections,
        no_variant_origins=no_origins,authenticated=True,source_bindings_sha256=spec['source_bindings_sha256']),indent=2)+'\n')
    return prior


def readonly(root):
    for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(root,0o555)


def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','predecessor-download','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--window',choices=['stress2021','recent2025'],required=True);a=p.parse_args()
    check_context(os.environ);require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_QUALIFICATION_RERUN')
    request=json.loads(a.request.read_bytes());validate_request(request)
    stage=json.loads(a.staging_receipt.read_bytes())
    require(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
        and stage['execution_image']==EXECUTION_IMAGE and stage['source_files_verified']==514
        and stage['runtime_image']==IMAGE
        and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['members_verified']==591 and stage['authenticated_before_parsing']
        and stage['runtime_index_config_layer_chain_verified'] and stage['offline_image_source_verified']
        and stage['replay_started'] is False,'REFUSED_RECOVERY_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);require(len(key)==32,'REFUSED_RESEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-risk-core-recovery-qualification';private.mkdir(mode=0o700,exist_ok=False)
    sources=temp/'capital-risk-core-recovery-sources'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    identity=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'];status='RECOVERY_QUALIFICATION_PASSED'
    try:
        prior=restore_original(request,a.window,a.predecessor_download,private,key)
        namespace=dict(__name__='retained_window001_compiler',__file__=str(HERE/'build_core_variants.py'))
        fixture=HERE/'fixtures/window001_build_core_variants.py.txt'
        exec(compile(fixture.read_bytes(),str(fixture),'exec'),namespace)
        old=namespace['build'](frozen/'source-fixed',sources/'old',risk=False)
        require(old==json.loads((prior/'QUAL/source-bindings.json').read_bytes())['basis'],'REFUSED_OLD_SOURCE_RECONSTRUCTION')
        readonly(sources/'old');bindings=dict(old=old)
        admission=json.loads((HERE/'core-gate-admission.json').read_bytes())
        for phase,risk in [('basis',False),('risk',True)]:
            variant=sources/phase;bindings[phase]=build(frozen/'source-fixed',variant,risk=risk);readonly(variant)
            if risk:
                for name,digest in admission['qualified_component_sha256'].items():
                    require(sha256_file(variant/name)==digest,'REFUSED_QUALIFIED_COMPONENT_CHANGE')
            name='capital-risk-core-gate-'+identity+'-'+phase
            run_worker(gate_command(name,frozen,private,HERE,variant,phase),name,private,deadline=600)
        result=json.loads((private/'canonical-gate.json').read_bytes())
        require(result['status']=='CANONICAL_CORE_GATE_PASSED' and result['cases']==15,'REFUSED_CORRECTED_CANONICAL_GATE')
        (private/'source-bindings.json').write_text(json.dumps(bindings,indent=2)+'\n')
        for phase,variant in [('preflight','old'),('bridge','basis')]:
            name='capital-risk-core-recovery-'+a.window+'-'+identity+'-'+phase
            tail=['/driver/core_recovery.py','--phase',phase,'--request','/driver/core-recovery-request.json',
                '--window',a.window,'--root','/out/prior/B/run-001','--output','/out/'+phase+'.json']
            run_worker(window_command(name,frozen,private,HERE,sources/variant,a.window,tail),name,private,deadline=600)
        result=json.loads((private/'bridge.json').read_bytes())
        require(result['status']=='WARMUP_BRIDGE_QUALIFIED' and result['sessions_advanced']==0,'REFUSED_BRIDGE_QUALIFICATION')
    except UnprovenStopped:
        output.write_text(json.dumps(dict(status='WRITER_STOP_UNKNOWN',run_id=os.environ['GITHUB_RUN_ID'],
            source_commit=os.environ['GITHUB_SHA'],window=a.window,encrypted_output=None))+'\n');raise SystemExit(2)
    except Exception as exc:
        status='RECOVERY_QUALIFICATION_REFUSED'
        (private/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    asset=output.parent/('recovery-qualification-'+a.window+'.tar.crseal')
    encrypt(private,asset,key,request['core_protocol_sha256'],arm='QUAL',stage='short-core-window');key=None
    receipt=dict(schema='research.capital-risk-recovery-qualification-receipt/1',status=status,
        run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],window=a.window,
        utc=datetime.now(timezone.utc).isoformat(),request_sha256=sha256_file(a.request),
        core_protocol_sha256=request['core_protocol_sha256'],financial_replay_started=False,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='RECOVERY_QUALIFICATION_PASSED' else 2)


if __name__=='__main__':main()
