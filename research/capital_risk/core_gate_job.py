"""Hosted canonical C/V engineering qualification; no economic replay launcher."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path

from baseline_prefix import launch_arguments,run_worker,UnprovenStopped
from build_core_variants import build
from probe import check_context,admitted_output
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,IMAGE,SECRET


def validate_request(value,protocol):
    if value.get('request_id') not in {'canonical-core-gate-001','canonical-core-gate-002'}:
        raise ValueError('REFUSED_CORE_GATE_REQUEST_ID')
    expected=dict(schema='research.capital-risk-core-gate-request/1',request_id=value['request_id'],
        stage='core-integration',original_protocol_sha256=PROTOCOL,core_protocol_sha256=sha256_file(protocol))
    if value!=expected:
        raise ValueError('REFUSED_CORE_GATE_REQUEST')


def gate_command(name,frozen,private,driver,variant,phase):
    command=launch_arguments(name,frozen,private,driver)
    command[command.index('/fixed')]='/variant'
    command[command.index('PYTHONPATH=/fixed:/fixed/shared')]='PYTHONPATH=/variant:/variant/shared:/driver'
    cut=command.index(EXECUTION_IMAGE)
    command=command[:cut]+['--mount',f'type=bind,source={variant},target=/variant,readonly']+command[cut:cut+1]
    command+=['-B','-u','/driver/canonical_core_gate.py','--phase',phase,
        '--output','/out/basis-synthetic.json' if phase=='basis' else '/out/canonical-gate.json']
    if phase=='risk':command+=['--basis-output','/out/basis-synthetic.json']
    return command


def main():
    parser=argparse.ArgumentParser()
    for n in ('request','staging-receipt','output'):parser.add_argument('--'+n,required=True,type=Path)
    args=parser.parse_args();check_context(os.environ)
    driver=Path(__file__).resolve().parent;protocol=driver/'core-screen-protocol.json'
    request=json.loads(args.request.read_bytes());validate_request(request,protocol)
    proof=json.loads(args.staging_receipt.read_bytes())
    if (proof['status']!='STAGING_PASSED' or proof['source_commit']!=os.environ['GITHUB_SHA']
            or proof['run_id']!=os.environ['GITHUB_RUN_ID'] or proof['protocol_sha256']!=PROTOCOL
            or proof['runtime_image']!=IMAGE or proof['execution_image']!=EXECUTION_IMAGE
            or proof['manifest_sha256']!='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
            or proof['source_files_verified']!=514 or proof['members_verified']!=591
            or not all(proof[k] for k in ('runtime_index_config_layer_chain_verified',
                'authenticated_before_parsing','offline_image_source_verified')) or proof['replay_started']):
        raise ValueError('REFUSED_CORE_GATE_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True)
    if len(key)!=32:raise ValueError('REFUSED_RESEARCH_KEY')
    frozen=Path(os.environ['RUNNER_TEMP'])/'capital-risk-stage-001/inputs'
    private=Path(os.environ['RUNNER_TEMP'])/'capital-risk-core-gate-output';private.mkdir(mode=0o700,exist_ok=False)
    sources=Path(os.environ['RUNNER_TEMP'])/'capital-risk-core-gate-sources'
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),args.output);output.parent.mkdir(parents=True,exist_ok=True)
    status,error='CANONICAL_CORE_GATE_PASSED',None
    try:
        binding={}
        for phase,risk in (('basis',False),('risk',True)):
            variant=sources/phase;binding[phase]=build(frozen/'source-fixed',variant,risk=risk)
            for path in variant.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(variant,0o555)
            name='capital-risk-core-gate-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']+'-'+phase
            run_worker(gate_command(name,frozen,private,driver,variant,phase),name,private,deadline=300)
        (private/'source-bindings.json').write_text(json.dumps(binding,indent=2)+'\n')
        actual=json.loads((private/'canonical-gate.json').read_bytes())
        if actual['status']!='CANONICAL_CORE_GATE_PASSED':raise ValueError('REFUSED_CANONICAL_GATE_RESULT')
    except UnprovenStopped:
        output.write_text(json.dumps(dict(status='WRITER_STOP_UNKNOWN',encrypted_output=None,
            source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],production_contacted=False))+'\n')
        raise SystemExit(2)
    except Exception as exc:
        status,error='CANONICAL_CORE_GATE_REFUSED',type(exc).__name__
        (private/'failure.json').write_text(json.dumps(dict(type=error,message=str(exc)))+'\n')
    asset=output.parent/'core-gate.tar.crseal'
    encrypt(private,asset,key,request['core_protocol_sha256'],arm='CORE_GATE',stage='core-integration');key=None
    receipt=dict(schema='research.capital-risk-core-gate-receipt/1',status=status,error_type=error,
        utc=datetime.now(timezone.utc).isoformat(),source_commit=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],request_id=request['request_id'],
        original_protocol_sha256=PROTOCOL,core_protocol_sha256=request['core_protocol_sha256'],
        economic_replay_started=False,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='CANONICAL_CORE_GATE_PASSED' else 2)


if __name__=='__main__':main()
