"""P11-only host-capacity successor; native financial and worker code is unchanged."""
import argparse
import ast
import json
import os
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
import ephemeral_runner_capacity as capacity
import system_campaign_volatility_native_job as native

HERE = Path(__file__).parent
ARMS = ('P11',)
PRIOR = 'system-campaign-volatility-native-request-001.json'
PRIOR_SHA = 'bcaa266acd6ba06e193f71748dff7c6b9a85ccf3c25c7502ecdc60c11ba9d5c8'
REQUEST = 'system-campaign-volatility-capacity-request-001.json'
NATIVE_JOB_SHA = '451d4b31ae6f0636b6531af7d7a9fe7cbbc2248e292f240a6cd983f1ef46a0b5'
CAPACITY_FILE = 'ephemeral_runner_capacity.py'
CAPACITY_SHA = 'c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379'
RECEIPT = 'artifacts/capital-risk/ephemeral-runner-capacity.json'
SOURCES = tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'], PRIOR,
    CAPACITY_FILE, 'system_campaign_volatility_capacity_job.py',
    'system_campaign_volatility_capacity_probe.py')))


def expected_request():
    need(sha256_file(HERE/PRIOR) == PRIOR_SHA, 'V_CAPACITY_EXACT427_NATIVE_REQUEST')
    old = json.loads((HERE/PRIOR).read_bytes())
    need(len(old['sources']) == 427
         and all(sha256_file(HERE/name) == value for name,value in old['sources'].items()),
         'V_CAPACITY_ALL427_NATIVE_DRIVER_BYTES_UNCHANGED')
    value = native.expected_request()
    need(value == old, 'V_CAPACITY_ENTIRE_NATIVE_REQUEST_UNCHANGED')
    need(sha256_file(HERE/CAPACITY_FILE) == CAPACITY_SHA,
         'V_CAPACITY_EXACT_QUALIFIED_HOST_PREPARATION_SOURCE')
    for name in ('retained_reference_predecessors','native_signal_closes','native_signal_factory_sha256'):
        value[name] = {'P11':value[name]['P11']}
    value.update(schema='research.volatility-native-capacity-discovery-request/1',
        arms=list(ARMS), concurrent_candidate_limit=1, prior427_request_sha256=PRIOR_SHA,
        capacity_helper=CAPACITY_FILE, capacity_helper_sha256=CAPACITY_SHA,
        capacity_receipt=RECEIPT, capacity_receipt_schema=capacity.SCHEMA,
        capacity_receipt_authority=capacity.AUTHORITY,
        fixed_preparation_target=capacity.TARGET,
        actual_prepared_receipt_required_before_staging_parent_or_worker=True,
        original_initial_and_preworker_disk_guards_unchanged=True,
        native_main_source_sha256=NATIVE_JOB_SHA,
        native_main_namespace_changes=['expected_request'],
        p10_qualification_or_discovery_reexecuted=False,
        prior_p11_refusal=dict(run_id=41373598360,
            head='4694642dd2e6e5f9362e964f746997d159ec057f', artifact_id=13110082519,
            zip_sha256='a88c78a57ca7629c785e5217ab8bbeafcd5a44fdb25ea2ebd5b03901b21c2abe',
            receipt_sha256='a0d07130998e7a7371f688b41496598c9032f0a37cf82dfd59122d84c1efca2b',
            admission_phase_sha256='345ef9fc1357ae12438883ec1eebc62ca0d73414f334b8b5ce1f95495a989ead',
            invariant_code='REFUSED_FULL_SYSTEM_PARALLEL_INITIAL_DISK_RESERVE',
            free_disk_bytes=8112300032, required_disk_bytes=12*1024**3,
            parent_or_worker_started=False, private_stopped_snapshot_available=False),
        sources={name:sha256_file(HERE/name) for name in SOURCES})
    return value


def native_main_tree():
    path = HERE/'system_campaign_volatility_native_job.py'
    need(sha256_file(path) == NATIVE_JOB_SHA, 'V_CAPACITY_EXACT_NATIVE_MAIN_SOURCE')
    fn, = [node for node in ast.parse(path.read_bytes()).body
           if isinstance(node, ast.FunctionDef) and node.name == 'main']
    return fn


def validate_capacity_receipt(path, *, env=None):
    env = os.environ if env is None else env
    path = Path(path)
    expected = Path(env['GITHUB_WORKSPACE'])/RECEIPT
    need(path.resolve(strict=True) == expected.resolve(strict=True)
         and not path.is_symlink() and path.is_file() and path.stat().st_size <= 16384,
         'V_CAPACITY_FIXED_PUBLIC_RECEIPT_PATH')
    need(sha256_file(HERE/CAPACITY_FILE) == CAPACITY_SHA,
         'V_CAPACITY_EXACT_QUALIFIED_HOST_PREPARATION_SOURCE')
    value = json.loads(path.read_bytes())
    capacity.validate_prepared_receipt(value, head=env['GITHUB_SHA'],
        run_id=env['GITHUB_RUN_ID'], source_sha256=CAPACITY_SHA)
    return value


def main(args):
    need(args.arm == 'P11', 'V_CAPACITY_ONLY_UNSTARTED_P11_SELECTED')
    validate_capacity_receipt(Path(os.environ['GITHUB_WORKSPACE'])/RECEIPT)
    return compile_body(native_main_tree(), dict(vars(native), expected_request=expected_request))(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=ARMS, required=True)
    for name in ('request','staging','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    main(parser.parse_args())
