"""Native V FAST qualification against completed immutable REFERENCE evidence."""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from probe import memory_bytes
from seal import sha256_file
from system_campaign_parallel_discovery import body, literals, compile_body
import system_campaign_parallel_discovery_job as parallel
import system_campaign_risk_discovery_job as risk
import system_campaign_volatility_native_parent as retained
import system_campaign_p02_continue_job as inspector_source

HERE = Path(__file__).parent
ARMS = ('P10', 'P11')
PRIOR = 'system-campaign-volatility-admission-recovery-request-001.json'
PRIOR_SHA = 'b8a5349cdcd8f9017af4d1338f5b8a5fbf88ef049ddc28cba32f9083ba4d12bf'
REQUEST = 'system-campaign-volatility-native-request-001.json'
ANCHOR_SHA = '24f4c29ac2e4d5fe0392e86fb22cc24d00a8ec3493165fb98cbdbc21e3745193'
SOURCES = tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'], PRIOR,
    retained.SPEC, 'system_campaign_volatility_native_parent.py',
    'system_campaign_volatility_native_transport.py', 'system_campaign_volatility_native_gate.py',
    'system_campaign_volatility_native_run.py', 'system_campaign_anchor_proofs.py',
    'system_campaign_volatility_native_job.py', 'system_campaign_volatility_native_probe.py')))
STAGES = {'BEFORE_EXPORT_MARKER', 'EXPORT_MARKER_PASSED', 'BEFORE_INITIAL_DISK_GATE',
    'BEFORE_STRICT_PARENT_FETCH', 'STRICT_PARENT_ADMITTED', 'BEFORE_RETAINED_REFERENCE_FETCH',
    'RETAINED_REFERENCE_ADMITTED', 'BEFORE_WORKER_RESOURCE_GATE', 'QUALIFIER_LAUNCH_ATTEMPTED',
    'QUALIFIER_STOPPED', 'DISCOVERY_LAUNCH_ATTEMPTED', 'DISCOVERY_STOPPED', 'UNKNOWN_NO_SNAPSHOT', 'FAILURE'}
PUBLIC_CODES = {
    'REFUSED_FULL_SYSTEM_PARALLEL_INITIAL_DISK_RESERVE',
    'REFUSED_FULL_SYSTEM_HOSTED_FACTUAL_DESTINATION_CAPACITY',
    'REFUSED_FULL_SYSTEM_PARALLEL_ONE_WORKER_PER_VM_RESOURCE_GATE',
    'REFUSED_FULL_SYSTEM_PARALLEL_EXACT_ORIGINAL_CANDIDATE_FINANCIAL_SOURCE_NO_CONVERSION'}


def expected_request():
    need(sha256_file(HERE/PRIOR) == PRIOR_SHA, 'V_NATIVE_EXACT418_PRIOR_REQUEST')
    old = json.loads((HERE/PRIOR).read_bytes())
    need(len(old['sources']) == 418
         and all(sha256_file(HERE/name) == value for name, value in old['sources'].items()),
         'V_NATIVE_ALL418_PRIOR_DRIVER_BYTES_UNCHANGED')
    need(sha256_file(HERE/'system_campaign_anchor_proofs.py') == ANCHOR_SHA,
         'V_NATIVE_EXACT_SHARED_VERSIONED_ANCHOR_WRITER')
    value = parallel.expected_request()
    need(value == json.loads((HERE/parallel.REQUEST).read_bytes()), 'V_NATIVE_ORIGINAL383_COMMON_CONTRACT')
    specs = {arm:retained.specification(arm) for arm in ARMS}
    value.update(schema='research.volatility-native-fast-qualification-discovery-request/1',
        arms=list(ARMS), concurrent_candidate_limit=2, prior418_request_sha256=PRIOR_SHA,
        reused_reference_spec=retained.SPEC, reused_reference_spec_sha256=sha256_file(HERE/retained.SPEC),
        retained_reference_predecessors={arm:dict(run_id=spec['run_id'], head=spec['head'],
            artifact_id=spec['artifact_id'], reference_path_sha256=spec['reference_path']['sha256'],
            reference_proof_sha256=spec['reference_proof']['sha256']) for arm,spec in specs.items()},
        native_signal_closes={arm:spec['native_signal_closes'] for arm,spec in specs.items()},
        native_signal_factory_sha256={arm:spec['native_signal_factory_sha256'] for arm,spec in specs.items()},
        signal_material_selected_from_exact_immutable_private_factory=True,
        only_changed_native_fast_qualification_executed=True, completed_reference_recomputed=False,
        actual_fast_reference_full_publication_runtime_and_proof_equality_required=True,
        actual_expected_missing_input_refusal_and_zero_commits_required=True,
        diagnostic_origin_before_actual_equality=False, native_horizon_equal_for_qualification_and_traversal=True,
        shared_versioned_anchor_proofs_sha256=ANCHOR_SHA,
        immutable_anchor_qualification_and_checkpoint_commitment_required=True,
        atomic_allowlisted_nonfinancial_admission_phases=True,
        risk_guards_bypassed=False, financial_source_or_risk_rule_changed=False,
        other_candidates_unchanged=True, qualify_wait_seconds=1800, discovery_wait_seconds=14400,
        changed_fast_transition_progress_durable=True,
        sources={name:sha256_file(HERE/name) for name in SOURCES})
    return value


def entrypoint(arm, mode):
    need(arm in ARMS and mode in ('qualify','discovery'), 'V_NATIVE_EXACT_SELECTED_ENTRYPOINTS')
    return ['-B','-u','/driver/system_campaign_volatility_native_run.py','--mode',mode,
            '--arm',arm,'--spec','/out/spec.json']


def reference_directory(arm):
    need(arm in ARMS, 'V_NATIVE_ONLY_SELECTED_REFERENCE_DESTINATION')
    return Path(os.environ['RUNNER_TEMP'])/('campaign-factual-transfer-v-native-reference-'+arm.lower())/'admitted'


def worker_command(name, arm, mode, source, frozen, out, old):
    value = parallel.worker_command(name, arm, mode, source, frozen, out, old)
    value[value.index('-B'):] = entrypoint(arm, mode)
    if mode == 'qualify':
        at = value.index('--entrypoint')
        value[at:at] = ['--mount',f'type=bind,source={reference_directory(arm)},target=/previous,readonly']
    return value


def inspect(name, identity=None):
    arm = name.split('-')[4].upper()
    mode = 'qualify' if '-qualify-' in name else 'discovery'
    need(arm in ARMS, 'V_NATIVE_ONLY_SELECTED_WORKER_INSPECTIONS')
    fn = literals(body('system_campaign_p02_continue_job.py','inspect'), {
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-parallel-discovery-p(?:10|11)-(?:qualify|worker)-[0-9]+-1'})
    sets = [node for node in ast.walk(fn) if isinstance(node, ast.Set)
        and all(isinstance(v, ast.Constant) for v in node.elts)
        and {ast.literal_eval(v) for v in node.elts} == {'/variant','/frozen','/driver','/out','/old'}]
    need(len(sets) == 1, 'V_NATIVE_ONE_QUALIFIER_READONLY_REFERENCE_MOUNT_SET')
    if mode == 'qualify':
        sets[0].elts.append(ast.Constant('/previous'))
    value = compile_body(fn, vars(inspector_source))(name, identity)
    need(value['Config']['Cmd'] == entrypoint(arm, mode), 'V_NATIVE_EXACT_CANONICAL_ENTRYPOINT')
    return value


def admit_previous(arm, temp, key):
    destination = retained.admit(arm, Path(temp)/('campaign-factual-transfer-v-native-reference-'+arm.lower()), key)
    need(destination == reference_directory(arm), 'V_NATIVE_FIXED_DISJOINT_REFERENCE_DESTINATION')
    for path in destination.rglob('*'):
        os.chmod(path, 0o555 if path.is_dir() else 0o444)
    os.chmod(destination, 0o555)
    return destination


def check_qualification(proof, arm):
    risk.check_qualification(proof, arm)
    spec = retained.specification(arm)
    need(proof['signal_material_closes'] == spec['native_signal_closes']
         and proof['native_signal_factory_sha256'] == spec['native_signal_factory_sha256']
         and proof['reference_recomputed'] is False
         and proof['actual_fast_reference_full_runtime_paths_equal'] is True
         and proof['actual_fast_reference_published_sessions_equal'] is True
         and proof['financial_source_or_risk_rule_changed'] is False,
         'V_NATIVE_ACTUAL_FULL_PUBLISHED_RUNTIME_PROOF_EQUALITY_AND_ORIGINAL_FACTORY_REQUIRED')


def note(path, arm, stage, error=None):
    need(arm in ARMS and stage in STAGES, 'V_NATIVE_PUBLIC_PHASE_AND_ARM_ALLOWLIST')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(path.read_bytes()) if path.exists() else None
    message = str(error) if error is not None else ''
    value = dict(schema='research.volatility-native-nonfinancial-admission-phase/1',
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], arm=arm, stage=stage,
        previous_stage=old['stage'] if old else None,
        free_disk_bytes=shutil.disk_usage(Path(os.environ['RUNNER_TEMP'])).free,
        available_memory_bytes=memory_bytes()['MemAvailable'],
        exception_class=type(error).__name__ if error is not None else None,
        invariant_code=message if message in PUBLIC_CODES else None,
        code_locations=[dict(file=Path(frame.filename).name,function=frame.name,line=frame.lineno)
            for frame in traceback.extract_tb(error.__traceback__)] if error is not None else [],
        exception_value_printed=False, financial_or_market_payload_included=False,
        telemetry_only=True, production_contacted=False)
    pending = path.with_suffix('.pending')
    with pending.open('wb') as stream:
        stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
        stream.flush(); os.fsync(stream.fileno())
    os.replace(pending, path)


def orchestration_tree():
    fn = risk.adopted('main')
    block, = [node for node in fn.body if isinstance(node, ast.Try)]
    token, = [i for i,node in enumerate(block.body) if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'os.environ.pop'
        and node.value.args and isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == 'GH_TOKEN']
    block.body[token:token] = ast.parse('admit_previous(arm,temp,key)').body
    at, = [i for i,node in enumerate(block.body) if isinstance(node, ast.Assign)
           and len(node.targets) == 1 and ast.unparse(node.targets[0]) == 'proof']
    block.body[at+1:at+1] = ast.parse('check_qualification(proof,args.arm)').body
    stages = {'old':'BEFORE_STRICT_PARENT_FETCH', 'binding':'STRICT_PARENT_ADMITTED',
        "receipt['qualification_worker']":'QUALIFIER_LAUNCH_ATTEMPTED', 'proof':'QUALIFIER_STOPPED',
        "receipt['worker']":'DISCOVERY_LAUNCH_ATTEMPTED', 'result':'DISCOVERY_STOPPED'}
    observed = []
    for i,node in enumerate(block.body):
        stage = 'BEFORE_INITIAL_DISK_GATE' if i == 0 else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            stage = stages.get(ast.unparse(node.targets[0]), stage)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = ast.unparse(node.value.func)
            if call == 'admit_previous':
                stage = 'BEFORE_RETAINED_REFERENCE_FETCH'
            elif call == 'os.environ.pop':
                stage = 'RETAINED_REFERENCE_ADMITTED'
            elif call == 'need' and 'MemAvailable' in ast.unparse(node):
                stage = 'BEFORE_WORKER_RESOURCE_GATE'
        if stage:
            observed.extend(ast.parse(f"note(args.output.parent/'admission-phase.json',arm,{stage!r})").body)
        observed.append(node)
    need(sum(isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
        and ast.unparse(node.value.func) == 'note' for node in observed) == 10,
        'V_NATIVE_EXACT_TEN_RESOURCE_ADMISSION_AND_WORKER_PHASE_SITES')
    block.body = observed
    probe, = [i for i,node in enumerate(fn.body) if isinstance(node, ast.Assign)
              and ast.unparse(node.targets[0]) == 'probe']
    fn.body[probe:probe] = ast.parse("note(args.output.parent/'admission-phase.json',arm,'BEFORE_EXPORT_MARKER')").body
    receipt, = [i for i,node in enumerate(fn.body) if isinstance(node, ast.Assign)
                and ast.unparse(node.targets[0]) == 'receipt']
    fn.body[receipt:receipt] = ast.parse("note(args.output.parent/'admission-phase.json',arm,'EXPORT_MARKER_PASSED')").body
    failure, = [handler for handler in block.handlers if isinstance(handler.type, ast.Name) and handler.type.id == 'Exception']
    failure.name = 'native_error'
    failure.body[:0] = ast.parse("note(args.output.parent/'admission-phase.json',arm,'FAILURE',native_error)").body
    unknown, = [handler for handler in block.handlers if isinstance(handler.type, ast.Name) and handler.type.id == 'StopUnknown']
    unknown.body[:0] = ast.parse("note(args.output.parent/'admission-phase.json',arm,'UNKNOWN_NO_SNAPSHOT')").body
    return ast.fix_missing_locations(fn)


def main(args):
    need(args.arm in ARMS, 'V_NATIVE_ONLY_TWO_UNSTARTED_DIAGNOSTIC_ARMS')
    return compile_body(orchestration_tree(), dict(vars(parallel), expected_request=expected_request,
        worker_command=worker_command, inspect=inspect, admit_previous=admit_previous,
        check_qualification=check_qualification, note=note))(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=ARMS, required=True)
    for name in ('request','staging','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    main(parser.parse_args())
