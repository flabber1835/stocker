"""Versioned metadata APIs for exact retained-Q POST_PLAN recovery."""
import ast
from copy import deepcopy
import json
import re
from pathlib import Path

from system_campaign_p10_ahl2_context import HERE
from system_campaign_p10_ahl2_contract import need, sha
from system_campaign_p10_ahl2_wire import object_bytes

PRIOR = 'system-campaign-p10-ahl2-context-request-001.json'
PRIOR_SHA = '43af76d00427751f3f945bdcf54fc1d1b56c407db8f15e01ef61079f7f061a49'
RETAINED = 'system-campaign-p10-ahl2-retained-qualification-001.json'
RETAINED_SHA = '006ad9813c20b2dba14ee4acf2ad8219b59d1a63a2d0a4f220f43a1c68e3d180'
REQUEST = 'system-campaign-p10-ahl2-post-plan-request-001.json'
WORKFLOW = 'capital-system-p10-ahl2-post-plan.yml'
WORKFLOW_SHA = '534d2c5866bef64047aec09a2be66b64564d785d7dde7f25400fa4968da2e03b'
ENTRY = '/driver/system_campaign_p10_ahl2_post_plan_run.py'
MODULES = tuple('system_campaign_p10_ahl2_post_plan'+suffix+'.py' for suffix in
    ('','_observe','_parent','_replay','_gate','_review','_run','_job','_probe'))
BUDGET = dict(admission=1800, qualification=5400, discovery=6300, review=1200,
              exports=1200, stop_metadata_reserve=1200)
STEP_MINUTES = (3,5,4,3,12,300,10)
JOB_MINUTES = 355


def prior_request():
    raw = (HERE/PRIOR).read_bytes()
    need(sha(raw) == PRIOR_SHA, 'P10_POST_PLAN_EXACT_PUBLISHED450_REQUEST')
    value = object_bytes(raw)
    need(len(value['sources']) == 450, 'P10_POST_PLAN_ORIGINAL450_COUNT')
    return value


def retained_specification():
    raw = (HERE/RETAINED).read_bytes()
    need(sha(raw) == RETAINED_SHA, 'P10_POST_PLAN_EXACT_ROOT_ADMITTED_Q_DESCRIPTOR')
    return object_bytes(raw)


def budget_contract():
    need(sum(BUDGET.values()) == 285*60 and STEP_MINUTES[5]*60 == sum(BUDGET.values())+15*60
         and JOB_MINUTES == sum(STEP_MINUTES)+18, 'P10_POST_PLAN_MECHANICAL_PROCESS_STOP_EXPORT_HEADROOM')
    return dict(phase_seconds=BUDGET, internal_envelope_seconds=sum(BUDGET.values()),
        orchestration_step_minutes=300, explicit_step_caps_minutes=list(STEP_MINUTES),
        explicit_step_total_minutes=sum(STEP_MINUTES), job_minutes=JOB_MINUTES,
        orchestration_headroom_minutes=15, outer_headroom_minutes=18)


def source_closure():
    old = prior_request()['sources']
    need(all(sha((HERE/n).read_bytes()) == h for n,h in old.items()), 'P10_POST_PLAN_ALL450_OLD_BYTES_UNCHANGED')
    names = set(old)|{PRIOR, RETAINED, *MODULES}
    todo = list(MODULES)
    while todo:
        name = todo.pop()
        for node in ast.walk(ast.parse((HERE/name).read_bytes())):
            modules = ([node.module] if isinstance(node,ast.ImportFrom) and node.level == 0 else
                       [a.name for a in node.names] if isinstance(node,ast.Import) else [])
            for module in modules:
                target = module+'.py' if module else ''
                if target and '.' not in module and (HERE/target).is_file() and target not in names:
                    names.add(target); todo.append(target)
    return {n:sha((HERE/n).read_bytes()) for n in sorted(names)}


def worker_expected_request():
    need(len(WORKFLOW_SHA) == 64, 'P10_POST_PLAN_WORKFLOW_UNBOUND')
    value = deepcopy(prior_request())
    value.update(schema='research.p10-own-ahl2-post-plan-request/1', workflow=WORKFLOW,
        workflow_sha256=WORKFLOW_SHA, sources=source_closure(), budgets=budget_contract())
    value['request_context'] = dict(schema='research.p10-post-plan-host-worker-context/1',
        predecessor_request_sha256=PRIOR_SHA, all450_published_source_bytes_unchanged=True,
        host_workflow_actual_bytes_required=True, worker_repository_layout_required=False,
        worker_workflow_file_required=False, worker_raw_request_copy_required=True, worker_entrypoint=ENTRY)
    value['retained_qualification'] = dict(descriptor=RETAINED, sha256=RETAINED_SHA,
        original_run_id=41450928937, original_artifact_id=13148420006,
        root_q_only_admission_sha256=retained_specification()['root_q_only_admission_sha256'],
        control_forward_transitions=0, cached_fast_forward_transitions=0,
        new_fast_transitions=1, new_reference_transitions=10, new_full_canonical_restores=20,
        fresh_suffix_origin='ORIGINAL_OWN1_ONLY', private_input_mount='/previous',
        own1_subtree='own1', retained_q_subtree='retained-qualification', flat_fallback=False)
    return value


def host_expected_request(path):
    path = Path(path)
    need(path.name == WORKFLOW and sha(path.read_bytes()) == WORKFLOW_SHA,
         'P10_POST_PLAN_ACTUAL_HOST_WORKFLOW_BYTES')
    workflow_budget_valid(path.read_bytes())
    return worker_expected_request()


def workflow_budget_valid(raw):
    text = raw.decode('utf8')
    jobs = re.findall(r'^    timeout-minutes: ([0-9]+)$',text,re.M)
    steps = re.findall(r'^        timeout-minutes: ([0-9]+)$',text,re.M)
    need(jobs == [str(JOB_MINUTES)] and [int(x) for x in steps] == list(STEP_MINUTES),
         'P10_POST_PLAN_ACTUAL_WORKFLOW_NESTED_BUDGETS_MATCH_SOURCE_CONTRACT')
    return budget_contract()


def worker_raw_request(path):
    raw = Path(path).read_bytes()
    need(raw == (HERE/REQUEST).read_bytes(), 'P10_POST_PLAN_ENTIRE_RAW_REQUEST_COPY')
    value = object_bytes(raw)
    need(value == worker_expected_request(), 'P10_POST_PLAN_FULL_REQUEST_MODEL_SOURCE_CLOSURE')
    return value


def entrypoint(role):
    need(role in ('qualify','worker','review'), 'P10_POST_PLAN_EXACT_ROLE')
    return ['-B','-u',ENTRY,'--mode','discovery' if role == 'worker' else role,
            '--spec','/out/spec.json','--request','/out/request.json']
