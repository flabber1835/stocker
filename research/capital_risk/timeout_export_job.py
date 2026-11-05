"""One hosted synthetic timeout/export proof; never advances a financial session."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import time

from baseline_prefix import launch_arguments,run_worker,fenced_inspect,UnprovenStopped
from probe import check_context,admitted_output
from runtime_identity import EXECUTION_IMAGE
from screen_job import encrypt
from seal import sha256_file
from stage import PROTOCOL,SECRET,IMAGE
from timeout_marker import MARKER

HERE=Path(__file__).resolve().parent


def require(value,code):
    if not value:raise ValueError(code)


def validate_request(value):
    expected=dict(schema='research.capital-risk-timeout-export-request/1',request_id='timeout-export-001',
        stage='engineering-only',core_protocol_sha256=sha256_file(HERE/'core-screen-protocol.json'),
        execution_image=EXECUTION_IMAGE,deadline_seconds=3,financial_sessions=0,
        marker_source_sha256=sha256_file(HERE/'timeout_marker.py'),marker_payload_sha256=hashlib.sha256(MARKER).hexdigest())
    require(value==expected,'REFUSED_TIMEOUT_PROOF_REQUEST')
    return expected


def proof_command(name,frozen,private,driver):
    command=launch_arguments(name,frozen,private,driver)
    command[command.index('/fixed')]='/variant'
    command[command.index('PYTHONPATH=/fixed:/fixed/shared')]='PYTHONPATH=/variant:/variant/shared:/driver'
    cut=command.index(EXECUTION_IMAGE)
    return command[:cut]+['--mount',f'type=bind,source={frozen/"source-fixed"},target=/variant,readonly']+command[cut:cut+1]+['-B','-u','/driver/timeout_marker.py']


def main():
    p=argparse.ArgumentParser()
    for n in ('request','staging-receipt','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();check_context(os.environ)
    require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REFUSED_TIMEOUT_PROOF_RERUN')
    request=validate_request(json.loads(a.request.read_bytes()));stage=json.loads(a.staging_receipt.read_bytes())
    require(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
        and stage['execution_image']==EXECUTION_IMAGE and stage['runtime_image']==IMAGE
        and stage['authenticated_before_parsing'] and stage['runtime_index_config_layer_chain_verified']
        and stage['offline_image_source_verified'] and stage['replay_started'] is False,'REFUSED_TIMEOUT_PROOF_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);require(len(key)==32,'REFUSED_RESEARCH_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    private=temp/'capital-risk-timeout-export-proof';private.mkdir(mode=0o700,exist_ok=False)
    output=admitted_output(Path(os.environ['GITHUB_WORKSPACE']),a.output);output.parent.mkdir(parents=True,exist_ok=True)
    name='capital-risk-timeout-proof-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    status='TIMEOUT_EXPORT_PROOF_PASSED';started=time.monotonic()
    try:
        caught=None;receipt_present_at_exception=False
        try:run_worker(proof_command(name,frozen,private,HERE),name,private,deadline=3)
        except ValueError as exc:
            caught=str(exc);receipt_present_at_exception=(private/(name+'-inspect.json')).is_file()
        require(caught=='REFUSED_PREFIX_DEADLINE' and receipt_present_at_exception,'REFUSED_TIMEOUT_RECEIPT_MISSING')
        try:
            actual=fenced_inspect(name)
            saved=json.loads((private/(name+'-inspect.json')).read_bytes())
            require(actual['Id']==saved['Id'] and not actual['State']['Running']
                and not actual['State']['OOMKilled'],'REFUSED_TIMEOUT_STOP_PROOF')
        except Exception as exc:raise UnprovenStopped('TIMEOUT_PROOF_STOP_UNKNOWN') from exc
        require((private/'timeout-marker.bin').read_bytes()==MARKER,'REFUSED_SYNTHETIC_MARKER')
        require(b'SYNTHETIC_TIMEOUT_MARKER_COMMITTED' in (private/(name+'.log')).read_bytes()
            and not (private/(name+'-log-capture-error.json')).exists(),'REFUSED_TIMEOUT_LOG_CAPTURE')
        proof=dict(schema='research.capital-risk-timeout-export-proof/1',status=status,expected_deadline_error=caught,
            receipt_present_at_exception=True,actual_stopped=True,oom=False,container_id=actual['Id'],
            actual_exit_code=actual['State']['ExitCode'],marker_sha256=hashlib.sha256(MARKER).hexdigest(),
            marker_bytes=len(MARKER),elapsed_seconds=time.monotonic()-started,
            financial_sessions=0,market_data_processed=False,production_contacted=False)
        (private/'timeout-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    except UnprovenStopped:
        output.write_text(json.dumps(dict(status='WRITER_STOP_UNKNOWN',run_id=os.environ['GITHUB_RUN_ID'],
            source_commit=os.environ['GITHUB_SHA'],encrypted_output=None,financial_replay_started=False))+'\n');raise SystemExit(2)
    except Exception as exc:
        status='TIMEOUT_EXPORT_PROOF_REFUSED'
        (private/'failure.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc)))+'\n')
    asset=output.parent/'timeout-export-proof.tar.crseal'
    encrypt(private,asset,key,request['core_protocol_sha256'],arm='CORE_GATE',stage='core-integration');key=None
    receipt=dict(schema='research.capital-risk-timeout-export-receipt/1',status=status,
        run_id=os.environ['GITHUB_RUN_ID'],source_commit=os.environ['GITHUB_SHA'],request_sha256=sha256_file(a.request),
        core_protocol_sha256=request['core_protocol_sha256'],financial_replay_started=False,production_contacted=False,
        encrypted_output=dict(name=asset.name,bytes=asset.stat().st_size,sha256=sha256_file(asset)))
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if status=='TIMEOUT_EXPORT_PROOF_PASSED' else 2)


if __name__=='__main__':main()
