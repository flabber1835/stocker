"""Quarantine one stopped failed-review artifact for readonly qualification only."""
import ast
import json
from pathlib import Path
import re
import zipfile

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import sha

FLAG = 'readonly_failed_review_requalification'
FAILURE = 'ADDITIONAL_ORDINARY_SCRATCH_INPUTS'
ARM = 'P07'
RUN = 42062617391
HEAD = '81a96ab16f3d8e1cc88791beb12c6df603d91335'
ARTIFACT = 13433939196
ZIP_SHA = 'afc984b1e14d9b8d5882e6e27bda3ede9d98804a4234c153f4b0c423b61aa2d6'
OUTER = '6e3e15d25a055f5025e51b08712b56cadf8e396eb5866918d43ec4fe08fb4917'
ORIGIN = '532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd'
STATUS = 'FINANCIAL_REVIEW_REFUSED_PRESERVED'


def applies(spec):
    return isinstance(spec, dict) and spec.get(FLAG) is True


def validate_target(spec):
    need(applies(spec) and spec['arm'] == ARM and spec['archive_format'] == 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1'
         and (spec['run_id'], spec['head'], spec['artifact_id'], spec['zip_bytes'], spec['zip_sha256'])
             == (RUN, HEAD, ARTIFACT, 341939703, ZIP_SHA)
         and (spec['measured_closes'], spec['selected_session'], spec['outer_sha256']) == (1196, '2022-09-30', OUTER)
         and spec['selected_checkpoint'] == 'book/checkpoint.json.gz' and len(spec['repairs']) == 22
         and spec['monthly_seed_root_admission_sha256'] == ORIGIN
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and spec['receipt_status'] == STATUS and spec['review_refusal'] == FAILURE
         and 'root_admission' not in spec and 'readonly_full_financial_target' not in spec
         and 'reuse_closed_hosted_prefix_review' not in spec,
         'REVIEW_REPAIR_ONLY_EXACT_UNADMITTED1196_READONLY_TARGET')
    need(all(spec['prior_stops'][role]['stopped'] is True
             and type(spec['prior_stops'][role]['exit_code']) is int
             and spec['prior_stops'][role]['exit_code'] == code
             and spec['prior_stops'][role]['oom_killed'] is False
             for role,code in (('preflight', 0), ('worker', 1), ('reviewer', 1))),
         'REVIEW_REPAIR_ORIGINAL_FAILED_STOPS_NEVER_RELABELED')
    return True


def request_only_readonly(request, spec):
    validate_target(spec)
    need(request['execution_mode'] == 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
         and request['arms'] == [ARM] and request['financial_resume_authorized'] is False
         and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
         and request['maximum_parallel_financial_workers'] == 0
         and request['maximum_parallel_readonly_workers'] == 1,
         'REVIEW_REPAIR_ZERO_FINANCIAL_REQUEST_ONLY')


def public_names(spec, archive):
    """Retain all existing public-member guards; bind the actual failed status."""
    import system_campaign_financial_partial as partial
    validate_target(spec)
    node, = [n for n in ast.parse(Path(partial.__file__).read_bytes()).body
             if isinstance(n, ast.FunctionDef) and n.name == 'public_names']
    assignment, = [n for n in node.body if isinstance(n, ast.Assign)
                   and ast.unparse(n.targets[0]) == 'status']
    need(ast.unparse(assignment.value) ==
         "'COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT' if full_target(spec) else 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'",
         'REVIEW_REPAIR_ONE_EXACT_PRIOR_STATUS_ASSIGNMENT')
    assignment.value = ast.Constant(STATUS)
    namespace = dict(vars(partial))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<unchanged-public-member-guards-actual-failed-review-status>', 'exec'), namespace)
    return namespace['public_names'](spec, archive)


def prove_refusal(spec, inventory, root):
    import system_campaign_financial_partial as partial
    validate_target(spec)
    name = 'stopped-review/worker.log'
    raw = (root / name).read_bytes()
    need(sha(raw) == spec['review_log_sha256'] == inventory[name]['sha256']
         and b'ordinary_reconstruction' in raw
         and b"FileNotFoundError: [Errno 2] No such file or directory: '/out/additional-review-ordinary/book/repairs/0e9e38b9e053c2545f45e7137187071c4058a7583077fe131717c6e46b745c8f.json'" in raw
         and 'stopped-review/core-review.json' not in inventory,
         'REVIEW_REPAIR_EXACT_DIAGNOSED_MISSING_INPUT_REFUSAL')
    origin = partial.root_spec(ARM, ORIGIN)
    need(json.loads((root / 'spec.json').read_bytes()) == origin,
         'REVIEW_REPAIR_EXACT_AUTHENTICATED_ORIGINAL_ADMITTED_PARENT')
    old = json.loads((root / 'old-prefix-canonical-review.json').read_bytes())
    need(old['checkpoint_sha256'] == origin['outer_sha256']
         and old['counts'] == dict(formation=126, daily=1047)
         and old['all_prefixes_verified'] is old['all_daily_factors_and_chains_verified'] is True,
         'REVIEW_REPAIR_ONLY_OLD1047_ACCOUNTING_REVIEW_EXISTS')


def admit(spec, root, key, inspector):
    """Authenticate bytes into quarantine; a new hosted review must follow."""
    import system_campaign_financial_partial as partial
    request = json.loads((partial.HERE / 'system-campaign-factual-request.json').read_bytes())
    request_only_readonly(request, spec)
    namespace = dict(vars(partial.crypto), public_names=public_names, prove_review_refusal=prove_refusal)
    node = partial.admission_tree()
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<readonly-failed-review-quarantine-transport>', 'exec'), namespace)
    destination = namespace['admit'](spec, root, key, max_zip_bytes=512 * 1024**2)
    for name, expected in spec['inspections'].items():
        value = json.loads((destination / name).read_bytes())
        need(re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', expected['user']) is not None,
             'REVIEW_REPAIR_POSITIVE_ORIGINAL_UID_GID')
        partial.archived_inspection(spec, expected, value, inspector)
        state = value['State']
        need(state['Running'] is state['OOMKilled'] is False
             and type(state['ExitCode']) is int and state['ExitCode'] == expected['exit_code'],
             'REVIEW_REPAIR_ACTUAL_ARCHIVED_POSITIVE_STOPS')
    raw = (destination / 'request.json').read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['original_request_member']
         and sha(raw) == spec['request_sha256'], 'REVIEW_REPAIR_ORIGINAL_FIN296_REQUEST_BYTES')
    from ephemeral_runner_capacity import validate_prepared_receipt
    with zipfile.ZipFile(destination.parent / 'predecessor.zip') as archive:
        capacity = json.loads(archive.read('ephemeral-runner-capacity.json'))
    validate_prepared_receipt(capacity, head=HEAD, run_id=str(RUN),
        source_sha256=json.loads(raw)['sources']['ephemeral_runner_capacity.py'])
    return destination


def require_requalified_review(root, spec):
    validate_target(spec)
    root = Path(root)
    core = json.loads((root / 'core-review.json').read_bytes())
    branch = json.loads((root / 'uncertainty-certificate-review.json').read_bytes())
    need(core['checkpoint_sha256'] == branch['checkpoint_sha256'] == OUTER
         and core['schema'] == 'research.full-system-core-review/1'
         and core['status'] == 'PARTIAL_CORE_PREFIX_REVIEWED'
         and branch['schema'] == 'research.retained-additional-sensor-branch-review/1'
         and core['counts'] == dict(formation=126, daily=1196)
         and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True
         and core['complete'] is False
         and branch['passed'] is True and type(branch['rows']) is type(branch['retained_rows']) is int
         and branch['rows'] == 149 and branch['retained_rows'] == 593
         and branch['all_financial_watch_and_proof_identities_verified'] is True
         and branch['all_original_and_added_uncertainty_retained'] is True,
         'REVIEW_REPAIR_FULL_ORIGINAL_CORE_AND_BRANCH_QUALIFICATION_REQUIRED')
    return dict(passed=True, financial_sessions_advanced=0, financial_authority=False,
                original_financial_artifact_id=ARTIFACT, checkpoint_sha256=OUTER,
                core_review_sha256=sha256_file(root / 'core-review.json'),
                branch_review_sha256=sha256_file(root / 'uncertainty-certificate-review.json'))
