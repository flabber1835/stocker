"""Single source-bound paired pilot on isolated hosted machines."""
import argparse
import base64
from functools import partial
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback

from core_volatility_source import ARMS, build, need
from probe import check_context, memory_bytes, FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import SECRET, PROTOCOL, IMAGE

HERE = Path(__file__).resolve().parent
REQUEST = 'core-volatility-request.json'
DOC = 'docs/core-volatility-penalty-experiment.md'
WORKFLOW = '.github/workflows/capital-core-volatility.yml'
GENERATION = 1


def expected_request():
    sources = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
               if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return {'schema': 'research.core-volatility-request/1', 'generation': GENERATION,
            'stage': 'PAIRED_134_TRANSITION_PILOT', 'arms': ARMS, 'maximum': 134,
            'financial_wait_seconds': 3000, 'review_wait_seconds': 900,
            'protocol_sha256': sha256_file(HERE.parent.parent/DOC),
            'workflow_sha256': sha256_file(HERE.parent.parent/WORKFLOW), 'sources': sources,
            'production_contacted': False, 'original_campaign_resumed': False}


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_REQUEST_CLOSURE')
    from full_system_trials_job import command, seal
    from alpaca_fit_job import stopped_run
    from ephemeral_runner_capacity import validate_prepared_receipt
    return {'status': 'CORE_VOLATILITY_DATA_PROBE_PASSED',
            'source_files': len(expected_request()['sources']), 'canonical_runtime_executed': False}


def command(name, source, frozen, output, arm, evidence=None, *, maximum=134, previous=None, aaap_model=False):
    from full_system_trials_job import command as original
    mode = 'review' if evidence else 'economic'
    result = original(name, source, frozen, output, mode)
    result[result.index('research.study=full-system-search-20261029')] = 'research.study=core-volatility-20261108'
    result[result.index('/driver/full_system_core.py')] = '/driver/core_volatility_worker.py'
    result += ['--arm', arm, '--maximum', str(maximum)]
    if evidence:
        index = result.index('--entrypoint')
        result[index:index] = ['--mount', f'type=bind,source={evidence},target=/evidence,readonly']
    if previous:
        index = result.index('--entrypoint')
        result[index:index] = ['--mount', f'type=bind,source={previous},target=/previous,readonly']
        result += ['--resume-root', '/previous']
    if aaap_model:
        result += ['--aaap-model']
    return result


def inspect(name, identity=None, *, value=None, user=None, maximum=134, continuation=False, aaap_model=False):
    need(re.fullmatch(r'core-volatility-(control|vol075)-(worker|review)-[0-9]+-1', name), 'CONTAINER_NAME')
    if value is None:
        value = json.loads(subprocess.run(['docker', 'inspect', name], capture_output=True,
                                         check=True, timeout=20).stdout)[0]
    h, c = value['HostConfig'], value['Config']
    mounts = {m['Destination']: m for m in value['Mounts'] if m['Type'] == 'bind'}
    review = '-review-' in name
    arm = 'CONTROL' if '-control-' in name else 'VOL075'
    need(value['Name'] == '/'+name and value['Image'] == EXECUTION_IMAGE
         and (identity is None or value['Id'] == identity), 'CONTAINER_IDENTITY')
    need(h['NetworkMode'] == 'none' and h['Memory'] == h['MemorySwap'] == 8*1024**3
         and h['NanoCpus'] == 2000000000 and h['PidsLimit'] == 64 and h['ReadonlyRootfs']
         and h['CapDrop'] == ['ALL'] and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']), 'FENCES')
    expected_mounts = {'/variant', '/frozen', '/driver', '/out'} | ({'/evidence'} if review else set())
    if continuation:
        expected_mounts.add('/previous')
    need(set(mounts) == expected_mounts and mounts['/out']['RW']
         and all(not m['RW'] for k, m in mounts.items() if k != '/out')
         and c['WorkingDir'] == '/variant' and c['User'] == (user or f'{os.getuid()}:{os.getgid()}')
         and c['Labels']['research.study'] == 'core-volatility-20261108'
         and c['Labels']['research.role'] == ('review' if review else 'worker'), 'MOUNTS')
    forbidden = set(FORBIDDEN_CREDENTIALS) | {SECRET, 'GH_TOKEN', 'GITHUB_TOKEN'}
    need(not any(k in forbidden and v for k, _, v in (s.partition('=') for s in c['Env'])), 'NO_CREDENTIALS')
    expected = [
        '-B', '-u', '/driver/core_volatility_worker.py', '--mode', 'review' if review else 'economic',
        '--arm', arm, '--maximum', str(maximum)]
    if continuation:
        expected += ['--resume-root', '/previous']
    if aaap_model:
        expected += ['--aaap-model']
    need(c['Entrypoint'] == ['python'] and c['Cmd'] == expected, 'EXACT_ENTRYPOINT')
    return value


def require_continuation_stage(request, receipt, outcome, arm):
    need(receipt['worker']['exit_code'] == 0 and receipt['reviewer']['exit_code'] == 0,
         'SUCCESSFUL_STAGE_STOPS')
    if request['maximum'] > 0:
        need(receipt['status'] == 'PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'
             and outcome.get('completed') == request['parents'][arm]['completed']+request['maximum'],
             'EXACT_BOUNDED_SEGMENT_REVIEW_REQUIRED')
    else:
        need(receipt['status'] == 'COMPLETE_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'
             and outcome.get('completed') == 2156 and outcome.get('complete') is True
             and outcome.get('session') == '2026-07-31', 'COMPLETE_REVIEWED_AXIS_REQUIRED')


def launch(a, *, contract=None):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'NO_BLIND_RERUN')
    if contract is None:
        probe(a.request)
        request = expected_request()
    else:
        need(json.loads(a.request.read_bytes()) == contract, 'EXACT_CONTINUATION_REQUEST')
        request = contract
        paired = request['stage'] == 'OWN_PILOT_CONTINUATION' and set(request['parents']) == set(ARMS)
        followup = (request['stage'] == 'OWN_REVIEWED_FOLLOWUP' and request['generation'] >= 3
                    and set(request['parents']) == set(request['arms'])
                    and set(request['parents']) <= set(ARMS) and a.arm in request['parents'])
        need((paired or followup)
             and 0 <= request['maximum'] <= 2156 and 0 < request['financial_wait_seconds'] <= 12600
             and 0 < request['review_wait_seconds'] <= 2700, 'BOUNDED_OWN_CONTINUATION_CONTRACT')
    stage = json.loads(a.staging.read_bytes())
    need(stage['status'] == 'STAGING_PASSED' and stage['run_id'] == os.environ['GITHUB_RUN_ID']
         and stage['source_commit'] == os.environ['GITHUB_SHA'] and stage['protocol_sha256'] == PROTOCOL
         and stage['runtime_image'] == IMAGE and stage['execution_image'] == EXECUTION_IMAGE
         and stage['source_files_verified'] == 514 and stage['members_verified'] == 591
         and stage['manifest_sha256'] == '80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'], 'STAGING')
    from ephemeral_runner_capacity import validate_prepared_receipt
    validate_prepared_receipt(json.loads(a.capacity.read_bytes()), head=os.environ['GITHUB_SHA'],
                             run_id=os.environ['GITHUB_RUN_ID'],
                             source_sha256=request['sources']['ephemeral_runner_capacity.py'])
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'TRANSFER_KEY')
    from full_system_trials_job import seal
    from alpaca_fit_job import stopped_run, StopUnknown
    generation = request['generation']
    temp = Path(os.environ['RUNNER_TEMP'])/('core-volatility-'+a.arm.lower()+'-'+str(generation))
    temp.mkdir(mode=0o700, exist_ok=False)
    root = temp/'output'
    root.mkdir()
    diagnostic = temp/'diagnostic'
    diagnostic.mkdir()
    frozen = Path(os.environ['RUNNER_TEMP'])/'capital-risk-stage-001/inputs'
    source = temp/'source'
    receipt = {'schema': 'research.core-volatility-receipt/1', 'arm': a.arm,
               'generation': generation, 'stage': request['stage'], 'run_id': os.environ['GITHUB_RUN_ID'],
               'head': os.environ['GITHUB_SHA'], 'request_sha256': sha256_file(a.request),
               'protocol_sha256': request['protocol_sha256'], 'status': 'SETUP_PENDING',
               'performance_admitted': False, 'production_contacted': False, 'original_campaign_resumed': False}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    def publish():
        temporary = a.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2)+'\n')
        os.replace(temporary, a.output)
    publish()
    known = False
    started = time.monotonic()
    try:
        need(memory_bytes()['MemAvailable'] >= 10*1024**3 and shutil.disk_usage(temp).free >= 12*1024**3, 'CAPACITY')
        binding = build(frozen/'source-fixed', source, a.arm)
        previous = None
        if contract is not None:
            from core_volatility_admit import hosted as admit_parent
            previous = admit_parent(request['parents'][a.arm], Path(os.environ['RUNNER_TEMP']) /
                                    ('core-volatility-transfer-'+a.arm.lower()+'-'+str(generation)), key)
            need(json.loads((previous/'source-bindings.json').read_bytes()) == binding,
                 'EXACT_REBUILT_OWN_PARENT_SOURCE')
            shutil.copyfile(previous.parent/'admission.json', root/'parent-artifact-admission.json')
            for p in previous.rglob('*'):
                os.chmod(p, 0o555 if p.is_dir() else 0o444)
            os.chmod(previous, 0o555)
        os.environ.pop('GH_TOKEN', None)
        (root/'source-bindings.json').write_text(json.dumps(binding, sort_keys=True, indent=2)+'\n')
        (root/'request.json').write_bytes(a.request.read_bytes())
        for p in source.rglob('*'):
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        os.chmod(source, 0o555)
        receipt.update(status='BOUNDED_OWN_ORIGIN_RUNNING', setup_seconds=time.monotonic()-started)
        publish()
        name = 'core-volatility-'+a.arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        aaap_model = request.get('input_model') == 'ORIGINAL_AAAP_TENDER'
        inspector = partial(inspect, maximum=request['maximum'], continuation=previous is not None, aaap_model=aaap_model)
        then = time.monotonic()
        receipt['worker'] = stopped_run(command(name, source, frozen, root, a.arm,
                                       maximum=request['maximum'], previous=previous, aaap_model=aaap_model), name, root,
                                       deadline=request['financial_wait_seconds'], inspector=inspector)
        known = True
        receipt.update(status='WORKER_STOPPED_PREFIX_PRESERVED', worker_seconds=time.monotonic()-then)
        publish()
        if (root/'book/checkpoint.json.gz').is_file() and not receipt['worker']['oom_killed']:
            audit = temp/'review'
            audit.mkdir()
            name = 'core-volatility-'+a.arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            then = time.monotonic()
            receipt['reviewer'] = stopped_run(command(name, source, frozen, audit, a.arm, root,
                                            maximum=request['maximum'], previous=previous, aaap_model=aaap_model), name,
                                            audit, deadline=request['review_wait_seconds'], inspector=inspector)
            receipt['review_seconds'] = time.monotonic()-then
            shutil.copytree(audit, root/'independent-review-stop')
            if receipt['reviewer']['exit_code'] == 0 and not receipt['reviewer']['oom_killed']:
                proof = json.loads((audit/'core-review.json').read_bytes())
                if receipt['worker']['exit_code'] == 0 and proof['counts'] == {'formation': 126, 'daily': 8}:
                    receipt['status'] = 'PAIRED_ARM_PILOT_REVIEWED_PENDING_ARTIFACT_ADMISSION'
                if contract is not None:
                    receipt['status'] = ('COMPLETE_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'
                        if proof['complete'] and receipt['worker']['exit_code'] == 0
                        else 'PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION')
    except StopUnknown:
        receipt['status'] = 'STOP_UNKNOWN_NO_NEW_FINANCIAL_AUTHORITY'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
    except Exception as exc:
        receipt.update(status='REFUSED_PREFIX_PRESERVED', error_type=type(exc).__name__)
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
    finally:
        if known:
            if any(diagnostic.iterdir()):
                shutil.copytree(diagnostic, root/'driver-diagnostics')
            receipt['encrypted_output'] = seal(root, a.output.parent/('core-volatility-'+a.arm+'.tar.crseal'),
                key, a.request, a.arm, stage='campaign-candidate', protocol_sha256=request['protocol_sha256'])
        elif any(diagnostic.iterdir()):
            receipt['diagnostic_output'] = seal(diagnostic, a.output.parent/('core-volatility-'+a.arm+'-diagnostic.tar.crseal'),
                key, a.request, a.arm, stage='campaign-candidate', protocol_sha256=request['protocol_sha256'])
        key = None
        receipt['elapsed_seconds'] = time.monotonic()-started
        publish()
    print(json.dumps(receipt), flush=True)
    if contract is not None:
        outcome = json.loads((root/'experiment-outcome.json').read_bytes()) if (root/'experiment-outcome.json').is_file() else {}
        require_continuation_stage(request, receipt, outcome, a.arm)
    else:
        need(receipt['status'] == 'PAIRED_ARM_PILOT_REVIEWED_PENDING_ARTIFACT_ADMISSION', 'POSITIVE_REVIEWED_COMPLETION_REQUIRED')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--request', type=Path, default=HERE/REQUEST)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--arm', choices=ARMS)
    for field in ('staging', 'capacity', 'output'):
        p.add_argument('--'+field, type=Path)
    a = p.parse_args()
    if a.prepare:
        need(not a.request.exists(), 'NEW_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        launch(a)
