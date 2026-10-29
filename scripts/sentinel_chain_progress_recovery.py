#!/usr/bin/env python3
"""Apply one restored progress-migration witness under the canonical host lock."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import sentinel_autonomous_deploy as core
import sentinel_ci_certification_verify as certification
import sentinel_env
from sentinel_phase_records import publish_immutable, read_document


def execute(args):
    root=Path(__file__).resolve().parents[1]
    ambient={key:value for key,value in os.environ.items() if key in {
        'PATH','HOME','USER','LOGNAME','LANG','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'}}
    env={**ambient,**sentinel_env.operational_values(sentinel_env.load(root/'.env'))}
    sentinel_env.validate(env,profile='install')
    if (env.get('SENTINEL_LOCAL_PAPER_MODE')!='OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
            or env.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY')!='REQUIRED_V1'
            or env.get('SENTINEL_LOCAL_PAPER_ACCOUNT_ID')!=env.get('SENTINEL_PAPER_ACCOUNT_ID')
            or env.get('ALPACA_BASE_URL','').rstrip('/')!=core.PAPER_URL):
        raise core.DeployRefused('coverage recovery requires the backed owner PAPER profile')
    receipt=read_document(args.installation_receipt)
    if (receipt.get('schema')!='sentinel.installation-receipt/1'
            or receipt.get('installation_state')!='INSTALLED'
            or receipt.get('activation_state')!='FENCED'
            or receipt.get('automation_enabled') is not False
            or receipt.get('kill_switch_engaged') is not True
            or receipt.get('deployment_id')!=env.get('SENTINEL_DEPLOYMENT_ID')
            or receipt.get('paper_account_id')!=env.get('SENTINEL_PAPER_ACCOUNT_ID')
            or receipt.get('runtime_image')!=env.get('SENTINEL_RUNTIME_IMAGE_REF')):
        raise core.DeployRefused('recovery requires this exact installed/fenced release')
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],env=env,text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(root),'status','--porcelain'],env=env,text=True).strip()
    if dirty or head!=receipt.get('git_commit'):
        raise core.DeployRefused('recovery checkout differs from installation')
    proof=certification.verify_current(root=root,commit=head,client=certification.GitHubReadClient(
        token=os.environ.get('SENTINEL_GITHUB_READ_TOKEN') or os.environ.get('GH_TOKEN')))
    if proof.get('certified_image')!=receipt['runtime_image']:
        raise core.DeployRefused('recovery runtime differs from signed CI publication')
    if args.witness.is_symlink() or not args.witness.is_file():
        raise core.DeployRefused('immutable witness file is unavailable')
    raw_witness=args.witness.read_bytes()
    if hashlib.sha256(raw_witness).hexdigest()!=args.confirm_witness_sha256:
        raise core.DeployRefused('exact immutable witness confirmation differs')
    witness_content=core._json_value(raw_witness,label='migration witness')
    content_sha=hashlib.sha256(json.dumps(witness_content,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()
    # The result is one-shot; a retained log after interruption requires
    # inspection, never an automatic second mutation attempt.
    log=args.output.with_suffix('.commands.log')
    if args.output.exists() or log.exists():
        raise core.DeployRefused('inspect existing recovery result/owner before another attempt')
    with open('/tmp/sentinel-autonomous-deploy.lock','a+') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        with log.open('x'):
            pass
        runner=core.Runner(env,log)
        graph=runner.run(['bash','scripts/sentinel-compose.sh','--explain'],capture=True)
        import shlex
        graph_args=shlex.split(graph.stdout.strip())
        if not graph_args or '-f' not in graph_args:
            raise core.DeployRefused('Sentinel Compose graph is unavailable')
        compose=['docker','compose',*graph_args]
        result=core._json_output(runner.run(compose+[
            '--profile','cli','run','--rm','-T','--no-deps',
            '--volume',str(args.witness.resolve())+':/progress-witness.json:ro',
            '--entrypoint','timeout','sentinel','--kill-after=5s','600s',
            'python','-B','-m','sentinel.chain_progress_recovery',
            '--apply','/progress-witness.json','--backup',args.backup,
            '--confirm-witness-sha256',args.confirm_witness_sha256,
            '--expect-account',receipt['paper_account_id'],
            '--deployment-id',receipt['deployment_id']],capture=True,timeout=660),
            label='progress coverage transfer')
        if (set(result)!={'schema','witness_content_sha256','backup','prefixes',
                         'operational_ready','broker_contacted'}
                or result.get('schema')!='sentinel.chain-progress-coverage-transfer/1'
                or result.get('witness_content_sha256')!=content_sha
                or result.get('backup')!=args.backup
                or not isinstance(result.get('prefixes'),dict)
                or set(result['prefixes'])!={'MIRROR','OBSERVATION'}
                or any(not isinstance(value,str) or core._HEX64.fullmatch(value) is None
                       for value in result['prefixes'].values())
                or result.get('operational_ready') is not False
                or result.get('broker_contacted') is not False):
            raise core.DeployRefused('coverage transfer result is malformed')
        result.update(source_commit=head,runtime_image=receipt['runtime_image'],
            installation_sha256=hashlib.sha256(args.installation_receipt.read_bytes()).hexdigest(),
            witness_file_sha256=args.confirm_witness_sha256)
        publish_immutable(args.output,result)
        print('coverage_transfer_receipt:'+str(args.output))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--installation-receipt',type=Path,required=True)
    parser.add_argument('--witness',type=Path,required=True)
    parser.add_argument('--confirm-witness-sha256',required=True)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        execute(args);return 0
    except (OSError,ValueError,core.DeployRefused,certification.CertificationVerificationRefused) as exc:
        print('REFUSED: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':
    raise SystemExit(main())
