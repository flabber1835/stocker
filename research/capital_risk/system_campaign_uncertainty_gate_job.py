"""One bounded hosted synthetic qualification, no financial replay entrypoint."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from alpaca_fit_job import stopped_run, StopUnknown
from full_system_benchmark import need
from full_system_trials_job import SOURCES as BASE, command, inspect as original_inspect, seal
from probe import check_context, memory_bytes
from seal import sha256_file
from stage import SECRET, PROTOCOL, IMAGE
from runtime_identity import EXECUTION_IMAGE
from system_campaign_space import initial
from system_campaign_variants import build

HERE = Path(__file__).resolve().parent
SOURCES = tuple(dict.fromkeys((*BASE, 'system_campaign_variants.py', 'system_campaign_space.py',
    'system_campaign_uncertainty_math.py', 'system_campaign_uncertainty_gate.py',
    'system_campaign_uncertainty_gate_job.py')))
CONTROLLER = ('sentinel/controller/median5.py', 'sentinel/controller/champion.py',
    'sentinel/controller/champion_config.py', 'sentinel/controller/champion_frozen.py',
    'sentinel/controller/terminal_returns.py', 'sentinel/core/kernel.py')


def expected_request(canonical_sources):
    need(set(canonical_sources) == set(CONTROLLER), 'UNCERTAINTY_QUALIFIED_SOURCE_CLOSURE')
    return dict(schema='research.system-uncertainty-gate-request/1',
        campaign='system-optimization-002', request_id='uncertainty-canonical-gate-001',
        objective='COMPLETE_EXISTING_CORE_CANDIDATES_P02_FIRST_SEQUENTIALLY',
        protocol_sha256=sha256_file(HERE / 'system-campaign-search-protocol.json'),
        sources={n: sha256_file(HERE / n) for n in SOURCES},
        canonical_controller_sources=canonical_sources, parameters=initial()[2]['parameters'],
        worker_deadline_seconds=240, artifact_retention_days=7,
        financial_replay_started=False, production_contacted=False)


def inspect(name, identity=None):
    result = original_inspect(name, identity)
    need(result['Config']['Cmd'] == ['-B', '-u', '/driver/system_campaign_uncertainty_gate.py',
        '--request', '/driver/system-campaign-uncertainty-gate-request.json',
        '--output', '/out/canonical-gate.json'], 'UNCERTAINTY_EXACT_SYNTHETIC_ENTRYPOINT')
    return result


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'UNCERTAINTY_NO_WORKFLOW_RERUN')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(request['canonical_controller_sources']), 'UNCERTAINTY_EXACT_GATE_REQUEST')
    stage = json.loads(args.staging.read_bytes())
    need(stage['status'] == 'STAGING_PASSED' and stage['run_id'] == os.environ['GITHUB_RUN_ID']
         and stage['source_commit'] == os.environ['GITHUB_SHA'] and stage['protocol_sha256'] == PROTOCOL
         and stage['runtime_image'] == IMAGE and stage['execution_image'] == EXECUTION_IMAGE
         and stage['source_files_verified'] == 514 and stage['members_verified'] == 591
         and stage['manifest_sha256'] == '80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'UNCERTAINTY_EXACT_FROZEN_STAGING')
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'UNCERTAINTY_KEY')
    temp = Path(os.environ['RUNNER_TEMP'])
    frozen = temp / 'capital-risk-stage-001/inputs'
    source = temp / 'uncertainty-gate-source'
    binding = build(frozen / 'source-fixed', source, request['parameters'])
    for name, digest in request['canonical_controller_sources'].items():
        need(binding['all_sources'][name] == digest, 'UNCERTAINTY_CONTROLLER_UNCHANGED_BY_CANDIDATE')
    for path in source.rglob('*'):
        os.chmod(path, 0o555 if path.is_dir() else 0o444)
    os.chmod(source, 0o555)
    out = temp / 'uncertainty-gate-output'
    out.mkdir(mode=0o700)
    (out / 'request.json').write_bytes(args.request.read_bytes())
    (out / 'source-bindings.json').write_text(json.dumps(binding, indent=2) + '\n')
    need(memory_bytes()['MemAvailable'] >= 10 * 1024 ** 3
         and shutil.disk_usage(temp).free >= 5 * 1024 ** 3, 'UNCERTAINTY_RESOURCES')
    receipt = dict(schema='research.system-uncertainty-gate-receipt/1',
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request), protocol_sha256=request['protocol_sha256'],
        financial_replay_started=False, production_contacted=False, encrypted_output=None,
        status='NOT_STARTED')
    known = False
    try:
        name = 'capital-full-core-b-worker-' + os.environ['GITHUB_RUN_ID'] + '-1'
        cmd = command(name, source, frozen, out, 'economic')
        start = cmd.index('/driver/full_system_core.py')
        cmd[start:] = ['/driver/system_campaign_uncertainty_gate.py',
            '--request', '/driver/system-campaign-uncertainty-gate-request.json',
            '--output', '/out/canonical-gate.json']
        result = stopped_run(cmd, name, out, deadline=request['worker_deadline_seconds'], inspector=inspect)
        known = True
        receipt['worker'] = result
        need(result['exit_code'] == 0 and not result['oom_killed'], 'UNCERTAINTY_ACTUAL_GATE_STOP')
        actual = json.loads((out / 'canonical-gate.json').read_bytes())
        need(actual['status'] == 'SYNTHETIC_CANONICAL_COMPARISONS_QUALIFIED'
             and actual['historical_financial_sessions_advanced'] == 0, 'UNCERTAINTY_ACTUAL_GATE_RESULT')
        receipt['status'] = actual['status']
    except StopUnknown:
        receipt['status'] = 'UNCERTAINTY_SYNTHETIC_STOP_UNKNOWN'
    except Exception:
        receipt['status'] = 'UNCERTAINTY_GATE_REFUSED_KNOWN_STOP' if known else 'UNCERTAINTY_GATE_REFUSED_NO_STOP_PROOF'
        if known:
            (out / 'failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if known:
        receipt['encrypted_output'] = seal(out, args.output.parent / 'uncertainty-gate.tar.crseal',
            key, args.request, 'P02', stage='campaign-factual-suffix', protocol_sha256=request['protocol_sha256'])
    key = None
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status'] == 'SYNTHETIC_CANONICAL_COMPARISONS_QUALIFIED' else 2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('request', 'staging', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
