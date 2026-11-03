"""Bounded hosted throughput stage for joint research; encrypted stopped output."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from alpaca_fit_job import stopped_run, StopUnknown, seal_output
from full_system_benchmark import need
from probe import check_context, memory_bytes, FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import SECRET, PROTOCOL, IMAGE

HERE = Path(__file__).resolve().parent
SOURCES = ('full_system_job.py', 'full_system_benchmark.py', 'full_system_protocol.json',
           'alpaca_fit_job.py', 'alpaca_fit_stage.py', 'probe.py', 'runtime_identity.py', 'seal.py', 'stage.py')


def expected_request():
    return {'schema': 'research.full-system-measurement-request/1',
        'study_id': 'full-system-search-20261029', 'stage': 'THROUGHPUT_ONLY',
        'protocol_sha256': sha256_file(HERE/'full_system_protocol.json'),
        'source_files': {n: {'bytes': (HERE/n).stat().st_size, 'sha256': sha256_file(HERE/n)} for n in SOURCES},
        'execution_image': EXECUTION_IMAGE, 'production_contacted': False,
        'same_approved_encrypted_artifact_flow': True, 'financial_performance_selection': False}


def inspect(name, identity=None):
    need(re.fullmatch(r'capital-full-system-(?:measure|review)-[0-9]+-1', name) is not None, 'WORKER_NAME')
    value = json.loads(subprocess.run(['docker', 'inspect', name], capture_output=True, check=True, timeout=20).stdout)[0]
    h, c = value['HostConfig'], value['Config']
    mounts = {m['Destination']: m for m in value['Mounts'] if m['Type'] == 'bind'}
    reviewer = '-review-' in name
    need(value['Name'] == '/'+name and value['Image'] == EXECUTION_IMAGE
         and (identity is None or value['Id'] == identity), 'WORKER_IDENTITY')
    need(h['NetworkMode'] == 'none' and h['Memory'] == h['MemorySwap'] == 8*1024**3
         and h['NanoCpus'] == 2000000000 and h['PidsLimit'] == 64 and h['ReadonlyRootfs']
         and h['CapDrop'] == ['ALL'] and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']), 'WORKER_FENCES')
    need(set(mounts) == {'/frozen', '/driver', '/out'} | ({'/evidence'} if reviewer else set())
         and mounts['/out']['RW'] and all(not m['RW'] for k, m in mounts.items() if k != '/out')
         and c['WorkingDir'] == '/fixed' and c['User'] == f'{os.getuid()}:{os.getgid()}'
         and c['Labels'].get('research.study') == 'full-system-search-20261029'
         and c['Labels'].get('research.stage') == ('review' if reviewer else 'throughput'), 'WORKER_BOUNDARY')
    forbidden = set(FORBIDDEN_CREDENTIALS) | {SECRET, 'GH_TOKEN', 'GITHUB_TOKEN'}
    need(not any(k in forbidden and v for k, _, v in (e.partition('=') for e in c['Env'])), 'WORKER_CREDENTIALS')
    return value


def command(name, frozen, output, evidence=None):
    argv = ['docker', 'run', '-d', '--name', name, '--pull', 'never', '--network', 'none',
        '--read-only', '--memory', '8g', '--memory-swap', '8g', '--cpus', '2', '--pids-limit', '64',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m',
        '--user', f'{os.getuid()}:{os.getgid()}', '--label', 'research.study=full-system-search-20261029',
        '--label', 'research.stage='+('review' if evidence else 'throughput'), '-w', '/fixed',
        '-e', 'PYTHONPATH=/fixed:/fixed/shared:/driver', '-e', 'FULL_SYSTEM_HOSTED=1',
        '-e', 'OPENBLAS_NUM_THREADS=1', '-e', 'OMP_NUM_THREADS=1',
        '--mount', f'type=bind,source={frozen},target=/frozen,readonly',
        '--mount', f'type=bind,source={HERE},target=/driver,readonly',
        '--mount', f'type=bind,source={output},target=/out']
    if evidence:
        argv += ['--mount', f'type=bind,source={evidence},target=/evidence,readonly']
    argv += ['--entrypoint', 'python', EXECUTION_IMAGE, '-B', '-u', '/driver/full_system_benchmark.py']
    if evidence:
        argv += ['--review']
    return argv


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'NO_DUPLICATE_RUN')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(), 'EXACT_REQUEST')
    stage = json.loads(args.staging.read_bytes())
    need(stage['status'] == 'STAGING_PASSED' and stage['source_commit'] == os.environ['GITHUB_SHA']
         and stage['run_id'] == os.environ['GITHUB_RUN_ID'] and stage['protocol_sha256'] == PROTOCOL
         and stage['execution_image'] == EXECUTION_IMAGE and stage['runtime_image'] == IMAGE
         and stage['source_files_verified'] == 514 and stage['members_verified'] == 591
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'], 'STAGING')
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'KEY')
    temp = Path(os.environ['RUNNER_TEMP'])
    need((os.cpu_count() or 0) >= 4 and memory_bytes()['MemAvailable'] >= 10*1024**3
         and shutil.disk_usage(temp).free >= 12*1024**3, 'RESOURCES')
    root = temp/'full-system-measurement'; root.mkdir(mode=0o700, exist_ok=False)
    frozen = temp/'capital-risk-stage-001/inputs'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = {'schema': 'research.full-system-measurement-receipt/1',
        'run_id': os.environ['GITHUB_RUN_ID'], 'head': os.environ['GITHUB_SHA'],
        'request_sha256': sha256_file(args.request), 'protocol_sha256': request['protocol_sha256'],
        'performance_scored': False, 'production_contacted': False, 'status': 'NOT_STARTED'}
    known = False
    try:
        (root/'request.json').write_bytes(args.request.read_bytes())
        outcome = stopped_run(command('capital-full-system-measure-'+os.environ['GITHUB_RUN_ID']+'-1', frozen, root),
            'capital-full-system-measure-'+os.environ['GITHUB_RUN_ID']+'-1', root, deadline=900, inspector=inspect)
        known = True; receipt['worker'] = outcome
        need(outcome['exit_code'] == 0 and not outcome['oom_killed'], 'MEASUREMENT_STOP')
        audit = temp/'full-system-measurement-review'; audit.mkdir(mode=0o700, exist_ok=False)
        outcome = stopped_run(command('capital-full-system-review-'+os.environ['GITHUB_RUN_ID']+'-1', frozen, audit, root),
            'capital-full-system-review-'+os.environ['GITHUB_RUN_ID']+'-1', audit, deadline=300, inspector=inspect)
        receipt['reviewer'] = outcome
        shutil.copytree(audit, root/'independent-review')
        need(outcome['exit_code'] == 0 and not outcome['oom_killed'], 'REVIEW_STOP')
        need(json.loads((audit/'review.json').read_bytes())['status'] == 'CANONICAL_MEASUREMENT_REVIEW_PASSED', 'ACTUAL_REVIEW')
        receipt['status'] = 'COMPLETE_REVIEWED_THROUGHPUT'
    except StopUnknown:
        receipt['status'] = 'REVIEW_STOP_UNKNOWN' if known else 'WORKER_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status'] = 'REFUSED_MEASUREMENT'; receipt['error_type'] = type(exc).__name__
        if known:
            (root/'failure.json').write_text(json.dumps({'type': type(exc).__name__, 'message': str(exc)})+'\n')
    if known:
        need(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) <= 128*1024**2, 'BOUNDED_EXPORT')
        receipt['encrypted_output'] = seal_output(root, args.output.parent/'full-system-measurement.tar.crseal',
            key, request['protocol_sha256'], 'FULL_STOPPED_EVIDENCE', stage='full-system-throughput')
    key = None
    args.output.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status'] == 'COMPLETE_REVIEWED_THROUGHPUT' else 2)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('request', 'staging', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    main(p.parse_args())
