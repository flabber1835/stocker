"""Restore one admitted encrypted B predecessor and run its exact next suffix."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

from baseline_prefix import launch_arguments,run_worker,encrypt_output,UnprovenStopped,worker_stage
from probe import check_context,admitted_output,memory_bytes
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL,SECRET,IMAGE
from runtime_identity import EXECUTION_IMAGE
from suffix_contract import validate_request


def retain_immutable(path,payload):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=payload: raise ValueError('REFUSED_ANCESTRY_COLLISION')
    else: path.write_bytes(payload)


def restore_predecessor(request,download,private,key):
    validate_request(request);p=request['predecessor']
    receipt_path=download/p.get('receipt_name','baseline-prefix.json')
    receipt=json.loads(receipt_path.read_bytes())
    output=receipt['encrypted_output']
    if (receipt['status']!=p.get('receipt_status','PREFIX_PASSED') or receipt['run_id']!=str(p['run_id'])
            or receipt['source_commit']!=p['source_commit'] or receipt['protocol_sha256']!=PROTOCOL
            or receipt['arm']!='B' or receipt['full_baseline_gate_satisfied']
            or output!=dict(name=p['cipher_name'],bytes=p['cipher_bytes'],sha256=p['cipher_sha256'])):
        raise ValueError('REFUSED_PREDECESSOR_RECEIPT')
    asset=download/p['cipher_name']
    if asset.stat().st_size!=p['cipher_bytes']: raise ValueError('REFUSED_PREDECESSOR_CIPHER_LENGTH')
    plain=private.parent/'predecessor-authenticated.tar'
    decrypt(asset,plain,key,p['cipher_sha256'])
    with tarfile.open(plain) as tar:
        first=tar.next()
        if first is None or first.name!='manifest.json' or not first.isfile() or first.size>2*1024**2:
            raise ValueError('REFUSED_PREDECESSOR_MANIFEST')
        raw=tar.extractfile(first).read();manifest=json.loads(raw)
    if (manifest['schema']!='research.capital-risk-output/1' or manifest['arm']!='B'
            or manifest['stage']!=p.get('stage','baseline-prefix') or manifest['protocol_sha256']!=PROTOCOL):
        raise ValueError('REFUSED_PREDECESSOR_MANIFEST_IDENTITY')
    extract_verified(plain,private,hashlib.sha256(raw).hexdigest(),expected_schema='research.capital-risk-output/1')
    lineage=private/'lineage';lineage.mkdir(mode=0o700,exist_ok=True)
    retain_immutable(lineage/'checkpoints'/(p['outer_sha256']+'.json.gz'),(private/'run-001/checkpoint.json.gz').read_bytes())
    retain_immutable(lineage/'receipts'/(str(p['run_id'])+'-'+p['source_commit']+'.json'),receipt_path.read_bytes())
    retain_immutable(lineage/'links'/(p['outer_sha256']+'.json'),(json.dumps(dict(predecessor=p,
        manifest_sha256=hashlib.sha256(raw).hexdigest()),indent=2)+'\n').encode())


def suffix_arguments(name,frozen,private,driver,request,*,phase=None):
    validate_request(request)
    if worker_stage(name)!='baseline-suffix': raise ValueError('REFUSED_SUFFIX_WORKER_STAGE')
    args=launch_arguments(name,frozen,private,driver,review=phase is not None)
    if phase is not None:
        if phase not in {'preflight','postflight'}: raise ValueError('REFUSED_SUFFIX_REVIEW_PHASE')
        start=args.index('-u')+1
        args=args[:start]+['/driver/verify_suffix.py','--phase',phase,'--actual','/out/run-001',
            '--expected','/frozen/baseline-comparison','--request','/driver/baseline-suffix-request.json',
            '--output',f'/out/suffix-{phase}.json']
    else:
        args[args.index('--max-transitions')+1]=str(request['transitions'])
        args+=['--resume','--checkpoint','/out/run-001/checkpoint.json.gz']
        if 'repair' in request:
            args+=['--repair-overlay','/out/research-repairs/dade/overlay.json']
    return args


def main():
    parser=argparse.ArgumentParser()
    for name in ('request','staging-receipt','predecessor-download','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();check_context(os.environ)
    request=json.loads(args.request.read_bytes());validate_request(request)
    proof=json.loads(args.staging_receipt.read_bytes())
    if (proof['status']!='STAGING_PASSED' or proof['source_commit']!=os.environ['GITHUB_SHA']
            or proof['run_id']!=os.environ['GITHUB_RUN_ID'] or proof['runtime_image']!=IMAGE
            or proof['execution_image']!=EXECUTION_IMAGE or proof['protocol_sha256']!=PROTOCOL
            or not proof['runtime_index_config_layer_chain_verified'] or not proof['offline_image_source_verified']
            or proof['source_files_verified']!=514 or proof['members_verified']!=591):
        raise ValueError('REFUSED_SUFFIX_STAGING_ADMISSION')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    if len(key)!=32: raise ValueError('REFUSED_RESEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP'])
    if memory_bytes()['MemAvailable']<4*1024**3 or shutil.disk_usage(temp).free<12*1024**3:
        raise ValueError('REFUSED_SUFFIX_CAPACITY')
    frozen=temp/'capital-risk-stage-001/inputs'
    for path in frozen.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(frozen,0o555)
    private=temp/'capital-risk-suffix-output'
    target=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    name='capital-risk-b-suffix-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    driver=Path(__file__).resolve().parent
    status,error='SUFFIX_PASSED',None
    try:
        restore_predecessor(request,args.predecessor_download,private,key)
        run_worker(suffix_arguments(name+'-preflight',frozen,private,driver,request,phase='preflight'),
                   name+'-preflight',private)
        if 'repair' in request:
            qualification=launch_arguments(name+'-qualification',frozen,private,driver,review=True)
            qualification=qualification[:qualification.index('-u')+1]+['/driver/qualify_dade.py',
                '--actual','/out/run-001','--frozen','/frozen','--request','/driver/baseline-suffix-request.json',
                '--overlay','/out/research-repairs/dade/overlay.json','--output','/out/dade-qualification.json']
            run_worker(qualification,name+'-qualification',private)
        run_worker(suffix_arguments(name,frozen,private,driver,request),name,private)
        run_worker(suffix_arguments(name+'-postflight',frozen,private,driver,request,phase='postflight'),
                   name+'-postflight',private)
        review=json.loads((private/'suffix-postflight.json').read_bytes())
        if (review['status']!='SUFFIX_POSTFLIGHT_PASSED' or review['session']!=request['target_session']
                or review['formation_records']!=request['target_formation_records']
                or review['measured_closes']!=request.get('target_measured_closes',0)
                or not review['predecessor_preserved']):
            raise ValueError('REFUSED_SUFFIX_POSTFLIGHT')
    except UnprovenStopped:
        receipt=dict(schema='research.capital-risk-suffix-receipt/1',status='WRITER_STOP_UNKNOWN',
            source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],encrypted_output=None,
            full_baseline_gate_satisfied=False,production_contacted=False)
        target.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(2)
    except Exception as exc:
        status,error='SUFFIX_REFUSED',type(exc).__name__
        private.mkdir(mode=0o700,parents=True,exist_ok=True)
        (private/'suffix-failure.json').write_text(json.dumps(dict(type=error,message=str(exc)))+'\n')
    asset=target.parent/'baseline-suffix.tar.crseal'
    encrypt_output(private,asset,key,stage='baseline-suffix');key=None
    receipt=dict(schema='research.capital-risk-suffix-receipt/1',status=status,error_type=error,
        utc=datetime.now(timezone.utc).isoformat(),source_commit=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],protocol_sha256=PROTOCOL,arm='B',request_id=request['request_id'],
        predecessor=request['predecessor'],session=request['target_session'] if status=='SUFFIX_PASSED' else None,
        formation_records=request['target_formation_records'] if status=='SUFFIX_PASSED' else None,
        measured_closes=request.get('target_measured_closes',0) if status=='SUFFIX_PASSED' else None,
        full_baseline_gate_satisfied=False,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    target.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='SUFFIX_PASSED' else 2)


if __name__=='__main__':main()
