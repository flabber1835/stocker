"""One isolated canonical component gate; no financial driver is invoked."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from full_system_trials_job import command
from system_campaign_evidence_export import seal
from system_campaign_large_factual_admit import admit
from system_campaign_p02_chinook_job import SOURCES as PRIOR
from system_campaign_p02_continue_job import inspect as prior_inspect
from system_campaign_variants import build
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes
from stage import SECRET, PROTOCOL, IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE = Path(__file__).resolve().parent
SOURCES = tuple(dict.fromkeys((*PRIOR, 'system_campaign_outcome_proof.py',
    'system_campaign_outcome_gate.py', 'system_campaign_outcome_gate_job.py')))


def expected_request():
    name = 'system-campaign-outcome-gate-predecessor.json'
    spec = json.loads((HERE / name).read_bytes())
    need(spec['arm'] == 'P02' and spec['run_id'] == 41187704006
         and spec['outer_sha256'] == '41226e5c113ef808d4ea7e6801d0cfad4f1c82d1966a09800b2b1b5b0c7bcb6a'
         and len(spec['repairs']) == 32 and spec['selected_session'] == '2023-07-31',
         'OUTCOME_GATE_EXACT_OWN_ADMITTED_32_INPUT_PARENT')
    proof = json.loads((HERE / 'system-campaign-uncertainty-qualification.json').read_bytes())
    return dict(schema='research.system-controller-outcome-gate-request/1',
        campaign='system-optimization-002', only_candidate='P02',
        protocol_sha256=sha256_file(HERE / 'system-campaign-search-protocol.json'),
        predecessor_file=name, predecessor_sha256=sha256_file(HERE / name),
        actual_refusal_sha256='3cf001919a6ed587ef62068c0cbd3ff08ad26775aad5f124f2464ce1f1fb5c54',
        canonical_controller_sources=proof['canonical_controller_sources'],
        sources={n: sha256_file(HERE / n) for n in SOURCES},
        source_archive_limit_bytes=2 * 1024**3,
        initial_min_disk_bytes=12 * 1024**3, worker_wait_seconds=120,
        artifact_retention_days=7, financial_replay_started=False,
        new_input_adopted=False, new_origin=False, production_contacted=False)


def inspect(name, identity=None):
    result = prior_inspect(name, identity)
    need(result['Config']['Cmd'] == ['-B', '-u', '/driver/system_campaign_outcome_gate.py',
        '--spec', '/out/spec.json', '--request', '/driver/system-campaign-outcome-gate-request.json'],
        'OUTCOME_GATE_EXACT_ZERO_FINANCIAL_ENTRYPOINT')
    return result


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'OUTCOME_GATE_SINGLE_ATTEMPT')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(), 'OUTCOME_GATE_EXACT_REQUEST')
    spec = json.loads((HERE / request['predecessor_file']).read_bytes())
    stage = json.loads(args.staging.read_bytes())
    need(stage['status'] == 'STAGING_PASSED' and stage['run_id'] == os.environ['GITHUB_RUN_ID']
         and stage['source_commit'] == os.environ['GITHUB_SHA']
         and stage['protocol_sha256'] == PROTOCOL
         and stage['runtime_image'] == IMAGE and stage['execution_image'] == EXECUTION_IMAGE
         and stage['source_files_verified'] == 514 and stage['members_verified'] == 591
         and stage['manifest_sha256'] == '80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'OUTCOME_GATE_EXACT_FROZEN_STAGING')
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'OUTCOME_GATE_KEY')
    temp = Path(os.environ['RUNNER_TEMP'])
    need(shutil.disk_usage(temp).free >= request['initial_min_disk_bytes'], 'OUTCOME_GATE_DISK')
    old = admit(spec, temp / 'outcome-gate-admitted-predecessor', key,
                max_zip_bytes=request['source_archive_limit_bytes'])
    need(sha256_file(old / 'uncertainty-refusal.json') == request['actual_refusal_sha256'],
         'OUTCOME_GATE_ACTUAL_REFUSAL_BYTES')
    source = temp / 'outcome-gate-financial-source'
    frozen = temp / 'capital-risk-stage-001/inputs'
    prior_binding = json.loads((old / 'source-bindings.json').read_bytes())
    binding = build(frozen / 'source-fixed', source, prior_binding['parameters'])
    need(binding == prior_binding, 'OUTCOME_GATE_SAME_515_SOURCE_TREE')
    out = temp / 'outcome-gate-output'
    out.mkdir(mode=0o700)
    for name, raw in (('request.json', args.request.read_bytes()),
        ('spec.json', (HERE / request['predecessor_file']).read_bytes()),
        ('source-bindings.json', (old / 'source-bindings.json').read_bytes())):
        (out / name).write_bytes(raw)
    os.environ.pop('GH_TOKEN', None)
    for root in (source, old):
        for path in root.rglob('*'):
            os.chmod(path, 0o555 if path.is_dir() else 0o444)
        os.chmod(root, 0o555)
    need(memory_bytes()['MemAvailable'] >= 10 * 1024**3, 'OUTCOME_GATE_AVAILABLE_MEMORY')
    name = 'capital-system-factual-p02-worker-' + os.environ['GITHUB_RUN_ID'] + '-1'
    argv = command(name, source, frozen, out, 'economic')
    i = argv.index('--entrypoint')
    argv[i:i] = ['--mount', f'type=bind,source={old},target=/old,readonly']
    argv[argv.index('/driver/full_system_core.py'):] = ['/driver/system_campaign_outcome_gate.py',
        '--spec', '/out/spec.json', '--request', '/driver/system-campaign-outcome-gate-request.json']
    receipt = dict(schema='research.system-controller-outcome-gate-receipt/1',
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], arm='P02',
        request_sha256=sha256_file(args.request), protocol_sha256=request['protocol_sha256'],
        predecessor_run_id=spec['run_id'], selected_predecessor_outer_sha256=spec['outer_sha256'],
        financial_replay_started=False, financial_sessions_advanced=0, new_input_adopted=False,
        production_contacted=False, status='NOT_STARTED')
    known = False
    try:
        worker = stopped_run(argv, name, out, deadline=request['worker_wait_seconds'], inspector=inspect)
        known = True
        receipt.update(worker=worker, status='STOPPED_COMPONENT_REFUSAL')
        if worker['exit_code'] == 0 and not worker['oom_killed']:
            evidence = json.loads((out / 'canonical-outcome-qualification.json').read_bytes())
            need(evidence['status'] == 'ACTUAL_CANONICAL_COMPLETE_OUTCOME_GATE_PASSED'
                 and evidence['financial_sessions_advanced'] == 0, 'OUTCOME_GATE_ACTUAL_CASE_RESULT')
            receipt['status'] = 'COMPLETE_COMPONENT_QUALIFICATION'
    except StopUnknown:
        receipt['status'] = 'COMPONENT_STOP_UNKNOWN_NO_EXPORT'
    except Exception:
        receipt['status'] = 'COMPONENT_REFUSED_KNOWN_STOP' if known else 'COMPONENT_NO_STOP_PROOF'
        if known:
            (out / 'driver-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if known:
        receipt['encrypted_output'] = seal(out, args.output.parent / 'outcome-gate.tar.crseal',
            key, args.request, 'P02', stage='campaign-factual-suffix',
            protocol_sha256=request['protocol_sha256'])
    key = None
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status'] == 'COMPLETE_COMPONENT_QUALIFICATION' else 2)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('request', 'staging', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    main(p.parse_args())
