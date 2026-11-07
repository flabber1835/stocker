"""Nonfinancial admission for a fresh canonical campaign origin; no replay here."""
import argparse
import base64
import json
import os
from pathlib import Path

from full_system_benchmark import need, save
from probe import check_context
from seal import sha256_file
from stage import SECRET
import system_campaign_candidate_job as candidate
import system_campaign_financial_resume as shared
from system_campaign_space import DEFAULT, initial

HERE = Path(__file__).parent
REQUEST = 'system-campaign-fresh-origin-request.json'
CANDIDATE = 'system-campaign-candidate-request.json'
WORKFLOW = '.github/workflows/capital-system-campaign-candidates.yml'


def candidate_basis():
    raw = (HERE / CANDIDATE).read_bytes()
    value = json.loads(raw)
    need(value == candidate.expected_request(), 'FRESH_EXACT_ORIGINAL_GENERIC_CANDIDATE_REQUEST')
    proposal = initial()[0]
    need(proposal == value['initial_candidates'][0] and proposal['parameters'] == DEFAULT
         and proposal['parameters']['family'] == 'CORE', 'FRESH_EXACT_P00_DEFAULT_PARAMETERS')
    return value, proposal


def expected_request():
    original, proposal = candidate_basis()
    # The shared closure also proves all383 frozen driver bytes unchanged.
    closure = shared.expected_request()['sources']
    names = sorted(set(closure) | {Path(__file__).name, CANDIDATE})
    return dict(schema='research.system-campaign-fresh-origin-request/1', campaign='system-optimization-002',
        arm='P00', index=0, candidate_id=proposal['id'], parameters=proposal['parameters'],
        fresh_origin=True, inherited_financial_rows=0, prior_checkpoint_imported=False,
        historical_result_reused=False, measurement_start='2018-01-02', measurement_end='2026-07-31',
        measured_closes=2156, feature_warmup_sessions=425, formation_sessions=126,
        original_candidate_request_sha256=sha256_file(HERE / CANDIDATE),
        protocol_sha256=original['search_protocol_sha256'],
        frozen_input_manifest_sha256='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a',
        sources={n: sha256_file(HERE / n) for n in names},
        workflow_sha256=sha256_file(HERE.parent.parent / WORKFLOW),
        financial_wait_seconds=original['financial_wait_seconds'], review_wait_seconds=original['review_wait_seconds'],
        maximum_parallel_financial_workers=1, production_contacted=False, current_paper_equivalence_claimed=False,
        full_financial_and_independent_data_admission_required=True)


def probe(path):
    actual = json.loads(path.read_bytes())
    need(actual == expected_request(), 'FRESH_EXACT_OWNER_REQUEST_SOURCE_WORKFLOW_AND_ORIGIN')
    return dict(schema='research.fresh-origin-scope-probe/1', status='EXACT_FRESH_P00_ORIGIN_SCOPE_PASSED',
        arm='P00', index=0, candidate_id=actual['candidate_id'], request_sha256=sha256_file(path),
        original_candidate_request_sha256=actual['original_candidate_request_sha256'],
        inherited_financial_rows=0, previous_book_selected=False, financial_runtime_executed=False,
        performance_admitted=False, production_contacted=False)


def prepare(request, capacity, output):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'FRESH_NEW_RUN_NOT_ACTION_RERUN')
    proof = probe(request)
    value = json.loads(request.read_bytes())
    from ephemeral_runner_capacity import validate_prepared_receipt
    validate_prepared_receipt(json.loads(capacity.read_bytes()), head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'], source_sha256=value['sources']['ephemeral_runner_capacity.py'])
    key = base64.b64decode(os.environ.get(SECRET, ''), validate=True)
    need(len(key) == 32, 'FRESH_SEPARATE_EXPORT_KEY')
    try:
        marker = shared.export_probe(Path(os.environ['RUNNER_TEMP']) / 'fresh-origin-export-probe-P00',
                                     request, 'P00', key)
    finally:
        key = None
    need(marker == dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED', arm='P00',
         financial_sessions_advanced=0, credentials_saved=False), 'FRESH_ACTUAL_EXPORT_PROBE_PASSED')
    output.parent.mkdir(parents=True, exist_ok=True)
    save(output.parent / 'fresh-origin-export-qualification-P00.json', marker)
    result = dict(proof, status='FRESH_EMPTY_ORIGIN_ADMITTED_BEFORE_FINANCIAL_START',
        head=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'],
        workflow_sha256=value['workflow_sha256'], parameters=value['parameters'],
        measurement_start=value['measurement_start'], measurement_end=value['measurement_end'],
        feature_warmup_sessions=425, formation_sessions=126, measured_closes=2156,
        old_p00_performance_is_not_completion_authority=True, current_paper_equivalence_claimed=False,
        capacity_prepared=True, actual_synthetic_export_passed=True)
    save(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--capacity', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.request)))
    else:
        need(args.capacity is not None and args.output is not None, 'FRESH_CAPACITY_AND_PUBLIC_PROOF_REQUIRED')
        print(json.dumps(prepare(args.request, args.capacity, args.output)))
