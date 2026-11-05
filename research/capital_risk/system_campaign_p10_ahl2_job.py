"""One exact P10 changed qualifier, separate fresh suffix and stopped review."""
import argparse
import ast
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import time
import traceback

from alpaca_fit_job import stopped_run, StopUnknown
from full_system_trials_job import command
from probe import check_context, memory_bytes
from seal import sha256_file
from stage import SECRET
from ephemeral_runner_capacity import validate_prepared_receipt
from system_campaign_p10_ahl2_contract import (HERE, PRIOR, PRIOR_SHA, SPEC, TAINT, sha, digest, need, specification, function)
from system_campaign_p10_ahl2_input import document_bytes, expected_document
from system_campaign_p10_ahl2_parent import admit as admit_own, retained_source
from system_campaign_parallel_discovery_parent import admit as admit_strict
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_variants import build
from system_campaign_p10_ahl2_export import (STAGE, QUALIFICATION_STAGE, RECEIPT_SCHEMA,
    qualify_export, preserve, write_receipt)
from system_campaign_p10_ahl2_gate import qualification_valid

REQUEST = 'system-campaign-p10-ahl2-request-001.json'
WORKFLOW = 'capital-system-p10-ahl2.yml'
CAPACITY_SHA = 'c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379'
MODULES = tuple('system_campaign_p10_ahl2_' + n + '.py' for n in (
    'contract','parent','input','epoch','observe','replay','gate','review','run','export','job','probe','wire'))
BUDGET = dict(admission=900, qualification=5400, discovery=7200, review=1200, exports=1200, stop_metadata_reserve=1200)
STEP_MINUTES = (3,5,4,3,12,300,10)
JOB_MINUTES = 355
PHASES = {'MARKER_PASSED','BEFORE_PARENT','PARENTS_ADMITTED','SOURCE_VERIFIED','QUALIFIER_LAUNCH',
    'QUALIFIER_STOPPED','QUALIFICATION_CIPHER_EXPORTED','DISCOVERY_LAUNCH','DISCOVERY_STOPPED',
    'REVIEW_LAUNCH','REVIEW_STOPPED','FAILURE','UNKNOWN_NO_MUTABLE_SNAPSHOT',
    'REVIEW_UNKNOWN_STOPPED_WORKER_PRESERVED','FINISHED'}


def budget_contract():
    need(sum(BUDGET.values()) == 285*60 and STEP_MINUTES[5]*60 >= sum(BUDGET.values()) + 15*60
         and JOB_MINUTES >= sum(STEP_MINUTES) + 18, 'P10_MECHANICAL_NESTED_WAITS_STOP_EXPORT_AND_OUTER_HEADROOM')
    return dict(phase_seconds=BUDGET, internal_envelope_seconds=sum(BUDGET.values()),
        orchestration_step_minutes=STEP_MINUTES[5], explicit_step_caps_minutes=list(STEP_MINUTES),
        explicit_step_total_minutes=sum(STEP_MINUTES), job_minutes=JOB_MINUTES,
        orchestration_headroom_minutes=15, outer_headroom_minutes=18)


def source_closure():
    raw = (HERE / PRIOR).read_bytes()
    need(sha(raw) == PRIOR_SHA, 'P10_EXACT_PRIOR427_SOURCE_CLOSURE')
    old = json.loads(raw)['sources']
    need(len(old) == 427 and all(sha256_file(HERE / n) == h for n,h in old.items()),
         'P10_ALL427_PUBLISHED_BYTES_RETAINED_UNCHANGED')
    names = set(old) | {PRIOR, SPEC, 'ephemeral_runner_capacity.py',
        'system_campaign_discovery_suffix_replay.py', 'system_campaign_discovery_suffix_parent.py', *MODULES}
    todo = list(names)
    while todo:
        name = todo.pop()
        if not name.endswith('.py'):
            continue
        for node in ast.walk(ast.parse((HERE / name).read_bytes())):
            imports = ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else
                       [x.name for x in node.names] if isinstance(node, ast.Import) else [])
            for module in imports:
                target = module + '.py' if module else ''
                if target and '.' not in module and (HERE / target).is_file() and target not in names:
                    names.add(target)
                    todo.append(target)
    return {n:sha256_file(HERE / n) for n in sorted(names)}


def expected_request():
    spec = specification()
    raw_input = document_bytes(spec)
    candidate_descriptor = dict(filename=sha(raw_input)+'.json', sha256=sha(raw_input),
        resume_session=spec['selected_session'], predecessor_checkpoint_sha256=spec['runtime_checkpoint_sha256'])
    need(sha256_file(HERE / 'ephemeral_runner_capacity.py') == CAPACITY_SHA, 'P10_FROZEN_CAPACITY_HELPER')
    return dict(schema='research.p10-own-ahl2-diagnostic-request/1', campaign='system-optimization-002',
        authority=TAINT, financial_authority=False, account_performance_computed=False, production_contacted=False,
        arm='P10', execution_mode='EXACT_OWN_DIAGNOSTIC_FOURTH_INPUT_SUFFIX',
        predecessor_file=SPEC, predecessor_file_sha256=sha256_file(HERE / SPEC),
        prior427_request_sha256=PRIOR_SHA, diagnostic_parent_file_sha256=spec['diagnostic_checkpoint_sha256'],
        diagnostic_parent_runtime_sha256=spec['runtime_checkpoint_sha256'], own_source_binding_sha256=spec['source_binding_sha256'],
        source_physical_files=516, source_canonical_files=224, old_inputs=3, new_inputs=4,
        candidate_document_raw_sha256=sha(raw_input), candidate_document_model_sha256=digest(expected_document(spec)),
        candidate_input_descriptor=candidate_descriptor,
        expected_successor_input_sha256=digest(dict(base=spec['base'], repairs=spec['old_descriptors']+[candidate_descriptor])),
        selected_session=spec['selected_session'], next_session=spec['next_session'], native_horizon=21,
        target_end=spec['target_end'], qualification_through='2019-02-15', qualified_candidate_sessions=10,
        qualifier_state_or_unsent_tail_adopted=False, risk_rule_or_financial_source_changed=False,
        actual_old_refusal_and_full_changed_FAST_REFERENCE_required=True,
        actual_held_role_quantity_settlement_sensor_and_V21_required=True,
        actual_export_marker_before_parent_or_worker=True, qualification_cipher_before_suffix=True,
        actual_known_stops_before_export=True, UNKNOWN_mutable_snapshot=False,
        request_serialization='COPY_EXACT_SOURCE_BYTES', artifact_retention_days=7,
        initial_min_disk_bytes=12*1024**3, downstream_min_disk_bytes=10*1024**3,
        capacity_source_sha256=CAPACITY_SHA, budgets=budget_contract(),
        protocol_sha256=sha256_file(HERE / 'system-campaign-search-protocol.json'),
        workflow=WORKFLOW, workflow_sha256=sha256_file(HERE.parents[1] / '.github/workflows' / WORKFLOW),
        sources=source_closure())


def entrypoint(role):
    need(role in ('qualify','worker','review'), 'P10_EXACT_DECLARED_WORKER_ROLE')
    return ['-B','-u','/driver/system_campaign_p10_ahl2_run.py','--mode',
        'discovery' if role == 'worker' else role, '--spec','/out/spec.json','--request','/out/request.json']


def bind_user_fences(value, role):
    binds = [x for x in value['Mounts'] if x['Type'] == 'bind']
    expected = {'/variant','/frozen','/driver','/out','/old','/previous'} | ({'/evidence'} if role == 'review' else set())
    need(len(binds) == len(expected) and len({x['Destination'] for x in binds}) == len(binds)
         and {x['Destination'] for x in binds} == expected
         and all(x['RW'] is (x['Destination'] == '/out') for x in binds),
         'P10_EXACT_UNIQUE_BIND_DESTINATIONS_AND_READONLY_INPUTS')
    user = value['Config']['User'].split(':')
    need(len(user) == 2 and all(x.isdigit() and int(x) > 0 for x in user),
         'P10_EXPLICIT_POSITIVE_NONROOT_UID_AND_GID')


def stopped_record(value, metadata, role, run_id):
    """Pure matching-client validator: actual inspection, never public booleans alone."""
    need(role in ('qualify','worker','review') and set(metadata) == {'stopped','exit_code','oom_killed','wait_error'}
         and metadata['stopped'] is True and type(metadata['exit_code']) is int
         and type(metadata['wait_error']) in (str, type(None)) and type(value['State']['ExitCode']) is int
         and metadata['oom_killed'] is False and value['State']['Running'] is False
         and value['State']['OOMKilled'] is False and value['State']['ExitCode'] == metadata['exit_code'],
         'P10_ACTUAL_INSPECTION_REQUIRED_NOT_RECEIPT_STOP_BOOLEAN')
    h, c = value['HostConfig'], value['Config']
    need(value['Name'] == f'/capital-system-p10-ahl2-{role}-{run_id}-1'
         and re.fullmatch('[a-f0-9]{64}', value['Id']) is not None
         and value['Image'] == 'sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
         and h['NetworkMode'] == 'none' and h['Memory'] == h['MemorySwap'] == 8*1024**3
         and h['NanoCpus'] == 2000000000 and h['ReadonlyRootfs'] is True and h['PidsLimit'] == 64
         and h['CapDrop'] == ['ALL'] and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),
         'P10_ACTUAL_IDENTITY_AND_ALL_OFFLINE_2CPU_8GIB_NO_SWAP_FENCES')
    bind_user_fences(value, role)
    need(c['WorkingDir'] == '/variant' and c['Cmd'] == entrypoint(role)
         and c['Labels']['research.study'] == 'full-system-search-20261029'
         and c['Labels']['research.role'] == ('review' if role == 'review' else 'worker')
         and not any(x.partition('=')[0] in {'GH_TOKEN','GITHUB_TOKEN','CAPITAL_RISK_RESEARCH_KEY_20261027'}
                     and x.partition('=')[2] for x in c['Env']),
         'P10_ACTUAL_NEW_ENTRYPOINT_LABELS_AND_NO_CREDENTIALS')
    return value


def inspect(name, identity=None):
    import system_campaign_p02_continue_job as original
    fn = function(retained_source(original), 'inspect')
    regex = [n for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value ==
             r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1']
    need(len(regex) == 1, 'P10_ONE_CURRENT_WORKER_NAMESPACE_SITE')
    regex[0].value = r'capital-system-p10-ahl2-(?:qualify|worker|review)-[0-9]+-1'
    mounts, = [n for n in ast.walk(fn) if isinstance(n, ast.Set)
               and ast.unparse(n) == "{'/variant', '/frozen', '/driver', '/out', '/old'}"]
    mounts.elts.append(ast.Constant('/previous'))
    scope = dict(vars(original))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<p10-current-worker-fences>', 'exec'), scope)
    value = scope['inspect'](name, identity)
    role = re.fullmatch(r'capital-system-p10-ahl2-(qualify|worker|review)-[0-9]+-1', name)[1]
    bind_user_fences(value, role)
    need(value['Config']['Cmd'] == entrypoint(role), 'P10_CURRENT_EXACT_ENTRYPOINT_NO_OLD_NAMESPACE_FALLBACK')
    return value


def worker_command(name, role, source, frozen, out, old, previous, evidence=None):
    value = command(name, source, frozen, out, 'review' if role == 'review' else 'discovery')
    at = value.index('--entrypoint')
    extra = ['--mount',f'type=bind,source={old},target=/old,readonly',
             '--mount',f'type=bind,source={previous},target=/previous,readonly']
    if role == 'review':
        need(evidence is not None, 'P10_REVIEW_REQUIRES_DISJOINT_STOPPED_EVIDENCE')
        extra += ['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    value[at:at] = extra
    value[value.index('-B'):] = entrypoint(role)
    return value


@contextmanager
def deadline(seconds):
    need(os.name == 'posix' and type(seconds) is int and seconds > 0, 'P10_BOUNDED_HOST_PHASE')
    prior = signal.getsignal(signal.SIGALRM)
    def expired(*_): raise TimeoutError('P10_BOUNDED_HOST_PHASE_EXPIRED')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prior)


def phase(path, stage, error=None):
    need(stage in PHASES, 'P10_SAFE_PUBLIC_PHASE_ALLOWLIST')
    value = dict(schema='research.p10-ahl2-nonfinancial-phase/1', arm='P10',
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], phase=stage,
        available_memory_bytes=memory_bytes()['MemAvailable'], free_disk_bytes=shutil.disk_usage(Path(os.environ['RUNNER_TEMP'])).free,
        exception_class=type(error).__name__ if error else None,
        locations=[dict(file=Path(x.filename).name, function=x.name, line=x.lineno)
                   for x in traceback.extract_tb(error.__traceback__)] if error else [],
        exception_values_included=False, market_or_financial_payload_included=False, financial_authority=False)
    path = Path(path)
    pending = path.with_suffix('.partial')
    with pending.open('w', encoding='utf8', newline='\n') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def roots(out, request, previous):
    out.mkdir(mode=0o700)
    for source, name in ((HERE / SPEC, 'spec.json'), (request, 'request.json'),
                         (previous / 'source-bindings.json', 'source-bindings.json'),
                         (previous / 'source-bindings.json', 'source-map.json')):
        shutil.copyfile(source, out / name)


def resource_gate(temp):
    need(memory_bytes()['MemAvailable'] >= 10*1024**3 and shutil.disk_usage(temp).free >= 10*1024**3,
         'P10_ONE_WORKER_MEMORY_AND_DISK_EXPORT_RESERVE')


def qualified_for_suffix(receipt, summary, spec, request):
    stop = receipt['qualification_worker']
    need(receipt.get('qualification_exported') is True and 'qualification_encrypted_output' in receipt
         and stop['stopped'] is True and type(stop['exit_code']) is int and stop['exit_code'] == 0
         and stop['oom_killed'] is False and stop['wait_error'] is None,
         'P10_SUCCESSFUL_ACTUAL_QUALIFIER_AND_DURABLE_CIPHER_REQUIRED')
    qualification_valid(summary, spec)
    need(summary['successor_input_sha256'] == request['expected_successor_input_sha256'],
         'P10_ACTUAL_ZERO_PARSER_INPUT_EQUALS_SOURCE_BOUND_REQUEST_CANDIDATE')
    return summary


def unknown_preservation(role, worker_known):
    need(role in ('qualify','worker','review') and type(worker_known) is bool,
         'P10_UNKNOWN_ROLE_AND_ACTUAL_WORKER_STOP_STATE_REQUIRED')
    if role == 'review' and worker_known:
        return dict(known=True, status='REVIEW_UNKNOWN_STOPPED_WORKER_PRESERVED', review_stop_unknown=True)
    return dict(known=False, status='UNKNOWN_NO_MUTABLE_SNAPSHOT', review_stop_unknown=role == 'review')


def retain_qualification(source, target):
    """Retain new proofs, never a qualifier book/lineage as continuation state."""
    target.mkdir()
    omitted = {'lineage','book','diagnostic-book'}
    for p in Path(source).rglob('*'):
        relative = p.relative_to(source)
        if not p.is_file() or any(part in omitted for part in relative.parts):
            continue
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)


def main(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1' and os.name == 'posix', 'P10_SINGLE_HOSTED_ATTEMPT')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request(), 'P10_EXACT_REQUEST_SOURCE_CLOSURE_BUDGETS')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()), head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'], source_sha256=CAPACITY_SHA)
    stage_valid(json.loads(args.staging.read_bytes()))
    spec = specification()
    temp = Path(os.environ['RUNNER_TEMP'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with deadline(60):
        marker = qualify_export(temp / 'p10-ahl2-export-marker', args.request)
    marker_path = args.output.parent / 'p10-ahl2-export-qualification.json'
    marker_path.write_text(json.dumps(marker, sort_keys=True, indent=2) + '\n')
    receipt = dict(schema=RECEIPT_SCHEMA, authority=TAINT, arm='P10', stage=STAGE,
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request), protocol_sha256=request['protocol_sha256'],
        strict_parent_outer_sha256=spec['strict_parent_outer_sha256'],
        diagnostic_parent_file_sha256=spec['diagnostic_checkpoint_sha256'],
        export_qualification_sha256=sha256_file(marker_path), status='MARKER_PASSED_PARENT_NOT_FETCHED',
        financial_authority=False, account_performance_computed=False, production_contacted=False)
    write_receipt(args.output, receipt)
    phase_path = args.output.parent / 'p10-ahl2-phase.json'
    phase(phase_path, 'MARKER_PASSED')
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'P10_SEPARATE_KEY')
    qout = dout = None
    known = False
    active_role = None
    try:
        need(shutil.disk_usage(temp).free >= 12*1024**3, 'P10_INITIAL_DISK_RESERVE')
        phase(phase_path, 'BEFORE_PARENT')
        with deadline(BUDGET['admission']):
            old = admit_strict(spec['financial_strict_predecessor'], temp / 'campaign-factual-transfer-p10-ahl2-strict', key)
            previous = admit_own(temp / 'campaign-factual-transfer-p10-ahl2-diagnostic', key, spec)
            phase(phase_path, 'PARENTS_ADMITTED')
            frozen = temp / 'capital-risk-stage-001/inputs'
            source = temp / 'p10-ahl2-own-source'
            binding = json.loads((previous / 'source-bindings.json').read_bytes())
            need((old / 'source-bindings.json').read_bytes() == (previous / 'source-bindings.json').read_bytes()
                 and build(frozen / 'source-fixed', source, binding['parameters']) == binding,
                 'P10_EXACT_OWN_V_SOURCE_NO_P01_EPOCH_OR_CONVERSION')
            for directory in (source, old, previous):
                for path in directory.rglob('*'):
                    os.chmod(path, 0o555 if path.is_dir() else 0o444)
                os.chmod(directory, 0o555)
        phase(phase_path, 'SOURCE_VERIFIED')
        os.environ.pop('GH_TOKEN', None)
        resource_gate(temp)
        qout = temp / 'p10-ahl2-changed-qualification'
        roots(qout, args.request, previous)
        name = 'capital-system-p10-ahl2-qualify-' + os.environ['GITHUB_RUN_ID'] + '-1'
        phase(phase_path, 'QUALIFIER_LAUNCH')
        active_role = 'qualify'
        receipt['qualification_worker'] = stopped_run(worker_command(name, 'qualify', source, frozen, qout, old, previous),
            name, qout, BUDGET['qualification'], inspector=inspect)
        active_role = None
        receipt['qualification_log_copy_failed'] = (qout / 'log-copy-failure.json').exists()
        receipt['status'] = 'QUALIFIER_KNOWN_STOP'
        phase(phase_path, 'QUALIFIER_STOPPED')
        with deadline(600):
            preserve(receipt, qout, args.output, key, args.request, qualification=True, known=True)
        need(receipt.get('qualification_exported') is True, 'P10_QUALIFICATION_CIPHER_DURABLE_BEFORE_SUFFIX')
        qualified_for_suffix(receipt, json.loads((qout / 'qualification-summary.json').read_bytes()), spec, request)
        stopped_record(json.loads((qout / 'worker-inspect.json').read_bytes()), receipt['qualification_worker'],
                       'qualify', os.environ['GITHUB_RUN_ID'])
        phase(phase_path, 'QUALIFICATION_CIPHER_EXPORTED')
        resource_gate(temp)
        dout = temp / 'p10-ahl2-fresh-diagnostic'
        roots(dout, args.request, previous)
        retain_qualification(qout, dout / 'retained-qualification')
        name = 'capital-system-p10-ahl2-worker-' + os.environ['GITHUB_RUN_ID'] + '-1'
        phase(phase_path, 'DISCOVERY_LAUNCH')
        active_role = 'worker'
        receipt['worker'] = stopped_run(worker_command(name, 'worker', source, frozen, dout, old, previous),
            name, dout, BUDGET['discovery'], inspector=inspect)
        active_role = None
        known = True
        receipt['worker_log_copy_failed'] = (dout / 'log-copy-failure.json').exists()
        receipt['status'] = 'DIAGNOSTIC_SUFFIX_KNOWN_STOP'
        phase(phase_path, 'DISCOVERY_STOPPED')
        need(not receipt['worker']['oom_killed'], 'P10_STOPPED_WORKER_NO_OOM_BEFORE_REVIEW')
        stopped_record(json.loads((dout / 'worker-inspect.json').read_bytes()), receipt['worker'],
                       'worker', os.environ['GITHUB_RUN_ID'])
        resource_gate(temp)
        rout = temp / 'p10-ahl2-stopped-review'
        roots(rout, args.request, previous)
        name = 'capital-system-p10-ahl2-review-' + os.environ['GITHUB_RUN_ID'] + '-1'
        phase(phase_path, 'REVIEW_LAUNCH')
        active_role = 'review'
        receipt['reviewer'] = stopped_run(worker_command(name, 'review', source, frozen, rout, old, previous, evidence=dout),
            name, rout, BUDGET['review'], inspector=inspect)
        active_role = None
        receipt['review_log_copy_failed'] = (rout / 'log-copy-failure.json').exists()
        shutil.copytree(rout, dout / 'stopped-review')
        stopped_record(json.loads((rout / 'worker-inspect.json').read_bytes()), receipt['reviewer'],
                       'review', os.environ['GITHUB_RUN_ID'])
        phase(phase_path, 'REVIEW_STOPPED')
        receipt['status'] = 'DIAGNOSTIC_SUFFIX_REVIEWED_PENDING_INDEPENDENT_CLIENT' if receipt['reviewer']['exit_code'] == 0 \
            and not receipt['reviewer']['oom_killed'] else 'DIAGNOSTIC_SUFFIX_REVIEW_REFUSED_KNOWN_STOP'
    except StopUnknown as error:
        preservation = unknown_preservation(active_role, known)
        known = preservation['known']
        receipt['status'] = preservation['status']
        receipt['review_stop_unknown'] = preservation['review_stop_unknown']
        phase(phase_path, receipt['status'], error)
        raise
    except BaseException as error:
        if receipt['status'] != 'KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK':
            receipt['status'] = 'KNOWN_STOP_FAILURE_PRESERVED' if known else 'PRE_SUFFIX_FAILURE_NO_MUTABLE_EXPORT'
        phase(phase_path, 'FAILURE', error)
        raise
    finally:
        try:
            with deadline(600):
                preserve(receipt, dout, args.output, key, args.request, known=known and dout is not None)
        finally:
            key = None
    phase(phase_path, 'FINISHED')
    need(receipt.get('encrypted_output_exported') is True and receipt.get('reviewer', {}).get('exit_code') == 0,
         'P10_SUCCESS_REQUIRES_ACTUAL_STOPPED_REVIEW_AND_ENCRYPTED_EXPORT')
    print(json.dumps(dict(status=receipt['status'], financial_authority=False)))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):
        p.add_argument('--' + name, type=Path, required=True)
    main(p.parse_args())
