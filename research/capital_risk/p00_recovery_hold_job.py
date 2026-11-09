"""Source-bound single P00 comparison; reuse stopped evidence and isolated containers."""
import argparse
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from p00_recovery_hold_policy import need
from probe import check_context, FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import SECRET

HERE = Path(__file__).resolve().parent
REQUEST = 'p00-recovery-hold-request.json'
WORKFLOW = '.github/workflows/capital-p00-recovery-hold.yml'
DOC = 'docs/p00-recovery-hold-experiment.md'
ROOT = '65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83'
GENERATION = 1


def baseline_transfer_root(runner_temp, generation):
    return Path(runner_temp) / ('campaign-factual-transfer-p00-recovery-hold-' + str(generation))


def expected_request():
    # Bind the entire existing DATA/AST dependency closure, including dynamically
    # selected transport readers; do not grow a second import registry by hand.
    files = {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
             if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST}
    return dict(schema='research.p00-recovery-hold-request/1', arm='P00',
                original_completed_root=ROOT, generation=GENERATION, profiles=2,
                production_contacted=False, original_campaign_resumed=False,
                original_core_backtests_resumed=False, core_recomputed=False,
                policy_change='ONLY_POST_NATIVE_RECOVERY_HOLD', native_rules_changed=False,
                protocol_sha256=sha256_file(HERE.parent.parent / DOC),
                workflow_sha256=sha256_file(HERE.parent.parent / WORKFLOW), sources=files)


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_REQUEST_AND_SOURCE_CLOSURE')
    # These imports are DATA/AST launch/transport modules, never canonical code.
    import system_campaign_financial_partial as partial
    import system_campaign_dependencies as dependencies
    from system_campaign_variants import build
    from full_system_math_job import command
    from full_system_trials_job import seal
    from alpaca_fit_job import stopped_run, StopUnknown
    need(partial.completed_result('P00')['completed'] == 2156, 'COMPLETED_RESEARCH_AUTHORITY')
    return dict(status='P00_RECOVERY_HOLD_DATA_IMPORT_PROBE_PASSED', source_files=len(expected_request()['sources']),
                canonical_runtime_executed=False)


def old_inspector():
    """Reuse the exact existing archived-inspection function without its launcher."""
    tree = ast.parse((HERE / 'system_campaign_financial_resume.py').read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'inspect']
    namespace = dict(re=re, os=os, json=json, subprocess=subprocess, need=need,
                     EXECUTION_IMAGE=EXECUTION_IMAGE, ARMS=('P00', 'P03', 'P04', 'P05', 'P06', 'P07', 'P09', 'P00', 'P11'),
                     FORBIDDEN_CREDENTIALS=FORBIDDEN_CREDENTIALS, SECRET=SECRET)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<unchanged-archived-container-inspector>', 'exec'), namespace)
    return namespace['inspect']


def command(name, source, frozen, output, core, evidence=None):
    from full_system_math_job import command as original
    result = original(name, source, frozen, output, core, evidence)
    index = result.index('/driver/full_system_controller_' + ('review.py' if evidence else 'worker.py'))
    result[index] = '/driver/p00_recovery_hold_worker.py'
    result += ['--mode', 'review' if evidence else 'worker']
    return result


def inspect(name, identity=None):
    from full_system_math_job import inspect as original
    value = original(name, identity)
    mode = 'review' if '-review-' in name else 'worker'
    expected = ['-B', '-u', '/driver/p00_recovery_hold_worker.py', '--root', '/core/book',
                '--output', '/out/review' if mode == 'review' else '/out/book']
    if mode == 'review':
        expected += ['--evidence', '/evidence/book']
    expected += ['--mode', mode]
    need(value['Config']['Entrypoint'] == ['python'] and value['Config']['Cmd'] == expected,
         'ACTUAL_EXACT_RESEARCH_ENTRYPOINT')
    return value


def launch(a):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'NO_BLIND_RERUN')
    probe(a.request)
    import system_campaign_financial_partial as partial
    from system_campaign_variants import build
    from full_system_trials_job import seal
    from alpaca_fit_job import stopped_run, StopUnknown
    started = time.monotonic()
    stage = json.loads(a.staging.read_bytes())
    need(stage['status'] == 'STAGING_PASSED' and stage['authenticated_before_parsing']
         and stage['source_commit'] == os.environ['GITHUB_SHA']
         and stage['run_id'] == os.environ['GITHUB_RUN_ID']
         and stage['replay_started'] is False, 'AUTHENTICATED_OFFLINE_RUNTIME')
    from ephemeral_runner_capacity import validate_prepared_receipt
    validate_prepared_receipt(json.loads(a.capacity.read_bytes()), head=os.environ['GITHUB_SHA'],
                             run_id=os.environ['GITHUB_RUN_ID'],
                             source_sha256=expected_request()['sources']['ephemeral_runner_capacity.py'])
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'SEPARATE_TRANSFER_KEY')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(schema='research.p00-recovery-hold-receipt/1', arm='P00', generation=GENERATION,
                   run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
                   request_sha256=sha256_file(a.request), original_completed_root=ROOT,
                   status='PARENT_AUTHENTICATION_PENDING', performance_admitted=False,
                   production_contacted=False, original_campaign_resumed=False)
    def publish():
        temporary = a.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
        os.replace(temporary, a.output)
    publish()
    temp = Path(os.environ['RUNNER_TEMP']) / ('p00-recovery-hold-' + str(GENERATION))
    temp.mkdir(mode=0o700, exist_ok=False)
    output = temp / 'output'
    output.mkdir()
    known = False
    try:
        need(shutil.disk_usage(temp).free >= 12 * 1024**3, 'DISK_RESERVE')
        entry = json.loads((HERE / partial.ROOTS).read_bytes())['completed_financial_roots']['P00']
        need(entry['admission_sha256'] == ROOT, 'EXACT_ORIGINAL_COMPLETED_ROOT')
        partial.authorized_completion(entry, 'P00')
        core = partial.admit(entry['transport'], baseline_transfer_root(os.environ['RUNNER_TEMP'], GENERATION),
                             key, old_inspector())
        os.environ.pop('GH_TOKEN', None)
        frozen = Path(os.environ['RUNNER_TEMP']) / 'capital-risk-stage-001/inputs'
        binding = json.loads((core / 'source-bindings.json').read_bytes())
        source = temp / 'source'
        need(build(frozen / 'source-fixed', source, binding['parameters']) == binding,
             'EXACT_ORIGINAL_CORE_AND_ACCOUNT_SOURCE')
        for directory in (source, core):
            for p in directory.rglob('*'):
                os.chmod(p, 0o555 if p.is_dir() else 0o444)
            os.chmod(directory, 0o555)
        (output / 'request.json').write_bytes(a.request.read_bytes())
        receipt['setup_authentication_seconds'] = time.monotonic() - started
        receipt['status'] = 'ISOLATED_PAIRED_CONTROLLER_RUNNING'
        publish()
        name = 'capital-full-core-b-worker-' + os.environ['GITHUB_RUN_ID'] + '-1'
        worker_started = time.monotonic()
        receipt['worker'] = stopped_run(command(name, source, frozen, output, core), name,
                                       output, deadline=900, inspector=inspect)
        known = True
        receipt['worker_seconds'] = time.monotonic() - worker_started
        receipt['status'] = 'WORKER_STOPPED_REVIEW_PENDING'
        publish()
        if receipt['worker']['exit_code'] == 0 and not receipt['worker']['oom_killed']:
            audit = temp / 'independent-review'
            audit.mkdir()
            name = 'capital-full-core-b-review-' + os.environ['GITHUB_RUN_ID'] + '-1'
            review_started = time.monotonic()
            receipt['reviewer'] = stopped_run(command(name, source, frozen, audit, core, output),
                                            name, audit, deadline=600, inspector=inspect)
            receipt['review_seconds'] = time.monotonic() - review_started
            shutil.copytree(audit, output / 'independent-review-stop')
            if receipt['reviewer']['exit_code'] == 0 and not receipt['reviewer']['oom_killed']:
                review = json.loads((audit / 'review/independent-review.json').read_bytes())
                need(review['status'] == 'P00_RECOVERY_HOLD_INDEPENDENT_REVIEW_PASSED', 'ACTUAL_REVIEW_VERDICT')
                receipt['status'] = 'P00_RECOVERY_HOLD_REVIEWED_PENDING_INDEPENDENT_ARTIFACT_ADMISSION'
    except StopUnknown:
        receipt['status'] = 'P00_RECOVERY_HOLD_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status'] = 'P00_RECOVERY_HOLD_REFUSED'
        receipt['failure'] = dict(type=type(exc).__name__, message=str(exc))
        (output / 'driver-failure.json').write_text(json.dumps(dict(type=type(exc).__name__, message=str(exc))) + '\n')
    finally:
        # An uncertain stop never receives an exported financial authority claim.
        if known:
            receipt['encrypted_output'] = seal(output, a.output.parent / 'p00-recovery-hold.tar.crseal', key,
                a.request, 'P00', stage='multiyear-controller',
                protocol_sha256=expected_request()['protocol_sha256'])
        key = None
        receipt['elapsed_seconds'] = time.monotonic() - started
        publish()
    print(json.dumps(receipt), flush=True)
    need(receipt['status'] == 'P00_RECOVERY_HOLD_REVIEWED_PENDING_INDEPENDENT_ARTIFACT_ADMISSION', 'POSITIVE_STOPPED_REVIEW_REQUIRED')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--request', type=Path, default=HERE / REQUEST)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--staging', type=Path)
    p.add_argument('--capacity', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.prepare:
        need(not a.request.exists(), 'REQUEST_ALREADY_EXISTS')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2) + '\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        launch(a)
