"""P06/P07-only successor to the frozen exact diagnostic suffix job."""
import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import system_campaign_discovery_suffix_job as original

HERE = Path(__file__).parent
PRIOR = 'system-campaign-discovery-suffix-request-001.json'
PRIOR_SHA = 'b5721050ff042d9be4dd343607625317f13c228a0e978afd321213f66318beb6'
JOB_SHA = '3fc5480ca4f7d50f539f0b24a6cd428a060ad408f7d6aa40cef982c03576179d'
REQUEST = 'system-campaign-discovery-spinoff-request-001.json'
SELECTED_ARMS = ('P06', 'P07')
SOURCES = tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'], PRIOR,
    'system-campaign-discovery-suffix-spinoff-predecessors.json',
    'system_campaign_discovery_spinoff_deferral.py', 'system_campaign_discovery_spinoff_job.py',
    'system_campaign_discovery_spinoff_probe.py')))


def method(name, namespace):
    raw = Path(original.__file__).read_bytes()
    need(sha256_file(Path(original.__file__)) == JOB_SHA, 'SPINOFF_JOB_EXACT_FROZEN_GENERIC_SUFFIX_JOB')
    fn, = [deepcopy(n) for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == name]
    if name == 'main':
        sites = [n for n in ast.walk(fn) if isinstance(n, ast.Constant)
                 and n.value == 'SUFFIX_ONLY_SELECTED_P03_P05_RECOVERY']
        need(len(sites) == 1, 'SPINOFF_JOB_ONE_SELECTED_ARM_ERROR_LABEL')
        sites[0].value = 'SPINOFF_SUFFIX_ONLY_SELECTED_P06_P07_DIAGNOSTIC_RECOVERY'
    scope = dict(vars(original), **namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
        '<frozen-exact-suffix-job-spinoff-namespace>', 'exec'), scope)
    return scope[name]


def expected_request():
    need(sha256_file(HERE/PRIOR) == PRIOR_SHA, 'SPINOFF_JOB_EXACT426_GENERIC_SUFFIX_REQUEST')
    old = json.loads((HERE/PRIOR).read_bytes())
    need(old == original.expected_request() and len(old['sources']) == 426,
         'SPINOFF_JOB_ALL426_PRIOR_DRIVER_BYTES_RETAINED')
    specs = {arm: original.specification(arm) for arm in SELECTED_ARMS}
    value = deepcopy(old)
    value.update(schema='research.exact-diagnostic-spinoff-suffix-request/1', arms=list(SELECTED_ARMS),
        prior426_request_sha256=PRIOR_SHA,
        predecessor_files={original.SPINOFF_SPEC:sha256_file(HERE/original.SPINOFF_SPEC)},
        diagnostic_predecessors={arm:dict(artifact_id=spec['artifact_id'],
            checkpoint_sha256=spec['diagnostic_checkpoint_sha256'], transitions=spec['transitions'],
            source_cursor=spec['selected_session']) for arm,spec in specs.items()},
        source_bound_spinoff_deferral_selected=True, source_unknown_raw_legs_preserved=True,
        unknown_child_identity_relationship_unresolved=True, source_cash_proxy_accrual_deferred=True,
        published_bars_and_quotes_unchanged=True, native_gzip_member_and_original_number_parser_bound=True,
        no_spinoff_receipt_liquidation_cash_or_receivable=True,
        actual_first_affected_original_refusal_and_next_transition_postconditions_required=True,
        sources={name:sha256_file(HERE/name) for name in SOURCES})
    return value


def entrypoint(arm):
    need(arm in SELECTED_ARMS, 'SPINOFF_JOB_ONLY_P06_P07_ENTRYPOINT')
    return ['-B','-u','/driver/system_campaign_discovery_suffix_run.py','--arm',arm,
            '--spec','/out/spec.json','--request','/driver/'+REQUEST]


def inspect(name, identity=None):
    return method('inspect', dict(entrypoint=entrypoint))(name, identity)


def worker_command(name, arm, source, frozen, out, old, previous):
    return method('worker_command', dict(entrypoint=entrypoint))(name, arm, source, frozen, out, old, previous)


def main(args):
    return method('main', dict(SELECTED_ARMS=SELECTED_ARMS, expected_request=expected_request,
        worker_command=worker_command, inspect=inspect))(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=SELECTED_ARMS, required=True)
    for name in ('request','staging','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    main(parser.parse_args())
