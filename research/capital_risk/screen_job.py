"""Hosted, encrypted orchestration for the restricted B/G trace screen."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tarfile

from baseline_prefix import launch_arguments, run_worker, UnprovenStopped
from probe import check_context, admitted_output
from runtime_identity import EXECUTION_IMAGE
from seal import EncryptWriter, sha256_file
from stage import PROTOCOL, IMAGE, SECRET


def validate_request(value, protocol):
    expected=dict(schema='research.capital-risk-screen-request/1',request_id='fast-bg-screen-001',
        stage='quick-screen',arms=['B','G'],original_protocol_sha256=PROTOCOL,
        screen_protocol_sha256=sha256_file(protocol))
    if value!=expected or any(type(value[k]) is not type(v) for k,v in expected.items()):
        raise ValueError('REFUSED_SCREEN_REQUEST')
    plan=json.loads(protocol.read_bytes())
    if plan['id']!='fast-bg-trace-screen-001' or plan['original_protocol_sha256']!=PROTOCOL:
        raise ValueError('REFUSED_SCREEN_PROTOCOL')


def encrypt(root, asset, key, contract, *, arm='BG',stage='quick-screen'):
    if (arm,stage) not in {('BG','quick-screen'),('CORE_GATE','core-integration'),
            ('BR','weighted-screen'),
            ('B','timing-pilot'),
            *((a,'short-core-window') for a in ('B','B0','C','V','QUAL'))}:
        raise ValueError('REFUSED_ENCRYPTED_OUTPUT_SCOPE')
    members={p.relative_to(root).as_posix():dict(bytes=p.stat().st_size,sha256=sha256_file(p))
             for p in sorted(root.rglob('*')) if p.is_file()}
    manifest=json.dumps(dict(schema='research.capital-risk-output/1',arm=arm,stage=stage,
        protocol_sha256=PROTOCOL,screen_protocol_sha256=contract,members=members),sort_keys=True).encode()+b'\n'
    with asset.open('xb') as stream:
        writer=EncryptWriter(stream,key)
        with tarfile.open(fileobj=writer,mode='w|') as tar:
            info=tarfile.TarInfo('manifest.json');info.size=len(manifest)
            tar.addfile(info,io.BytesIO(manifest))
            for name,spec in members.items():
                path=root/name
                if path.is_symlink(): raise ValueError('REFUSED_OUTPUT_LINK')
                info=tarfile.TarInfo(name);info.size=spec['bytes'];info.mode=0o600
                with path.open('rb') as source: tar.addfile(info,source)
        writer.finish()


def screen_command(name, frozen, private, driver):
    command=launch_arguments(name,frozen,private,driver)
    return command[:command.index(EXECUTION_IMAGE)+1]+['-B','-u','/driver/trace_screen.py',
        '--root','/frozen/baseline-comparison','--output','/out/screen',
        '--protocol','/driver/screen-protocol.json']


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True,type=Path)
    p.add_argument('--staging-receipt',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();check_context(os.environ)
    driver=Path(__file__).resolve().parent;protocol=driver/'screen-protocol.json'
    request=json.loads(args.request.read_bytes());validate_request(request,protocol)
    proof=json.loads(args.staging_receipt.read_bytes())
    if (proof['status']!='STAGING_PASSED' or proof['source_commit']!=os.environ['GITHUB_SHA']
            or proof['run_id']!=os.environ['GITHUB_RUN_ID'] or proof['protocol_sha256']!=PROTOCOL
            or proof['runtime_image']!=IMAGE or proof['execution_image']!=EXECUTION_IMAGE
            or proof['manifest_sha256']!='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
            or proof['source_files_verified']!=514 or proof['members_verified']!=591
            or not all(proof[k] for k in ('runtime_index_config_layer_chain_verified',
                    'authenticated_before_parsing','offline_image_source_verified')) or proof['replay_started']):
        raise ValueError('REFUSED_SCREEN_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    if len(key)!=32: raise ValueError('REFUSED_RESEARCH_KEY')
    frozen=Path(os.environ['RUNNER_TEMP'])/'capital-risk-stage-001/inputs'
    for path in frozen.rglob('*'): os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(frozen,0o555)
    private=Path(os.environ['RUNNER_TEMP'])/'capital-risk-screen-output'
    private.mkdir(mode=0o700,exist_ok=False)
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    (private/'driver-identities.json').write_text(json.dumps({
        path.name:sha256_file(path) for path in sorted(driver.glob('*.py'))},indent=2)+'\n')
    name='capital-risk-bg-screen-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    command=screen_command(name,frozen,private,driver)
    status,error='SCREEN_PASSED',None
    try:
        run_worker(command,name,private,deadline=600)
        result=json.loads((private/'screen/summary.json').read_bytes())
        if result['status']!='SCREEN_PASSED': raise ValueError('REFUSED_SCREEN_RESULT')
    except UnprovenStopped:
        output.write_text(json.dumps(dict(status='WRITER_STOP_UNKNOWN',encrypted_output=None,
            source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
            production_contacted=False))+'\n')
        raise SystemExit(2)
    except Exception as exc:
        status,error='SCREEN_REFUSED',type(exc).__name__
        (private/'failure.json').write_text(json.dumps(dict(type=error,message=str(exc)))+'\n')
    asset=output.parent/'quick-screen.tar.crseal'
    encrypt(private,asset,key,request['screen_protocol_sha256']);key=None
    receipt=dict(schema='research.capital-risk-screen-receipt/1',status=status,error_type=error,
        utc=datetime.now(timezone.utc).isoformat(),source_commit=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],original_protocol_sha256=PROTOCOL,
        screen_protocol_sha256=request['screen_protocol_sha256'],request_id=request['request_id'],
        arms=['B','G'],core_financial_changes=False,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='SCREEN_PASSED' else 2)


if __name__=='__main__': main()
