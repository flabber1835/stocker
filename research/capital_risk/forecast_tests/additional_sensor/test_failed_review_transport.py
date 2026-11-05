"""One exact readonly quarantine target; failed stops are never admission."""
import ast
import builtins
from copy import deepcopy
import json
from pathlib import Path
import sys
import zipfile

import pytest


class Fence:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('FAILED_REVIEW_DATA_ONLY:' + fullname)


sys.meta_path.insert(0, Fence())
import system_campaign_financial_review_repair as repair
import system_campaign_financial_partial as partial
import system_campaign_financial_resume as resume


def target():
    from system_campaign_financial_requalified_parent import validated
    # The failed target remains authenticated through its historical admitted root.
    return validated(partial.root_spec('P07','75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719'))[0]


def test_actual_quarantine_target_has_no_financial_or_root_authority():
    spec = target()
    assert repair.validate_target(spec)
    request = dict(execution_mode='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION', arms=['P07'],
        financial_resume_authorized=False, readonly_partial_review=True, readonly_source_witnesses=False,
        maximum_parallel_financial_workers=0, maximum_parallel_readonly_workers=1)
    repair.request_only_readonly(request, spec)
    assert spec['prior_stops']['worker']['exit_code'] == spec['prior_stops']['reviewer']['exit_code'] == 1
    assert spec['receipt_status'] == repair.STATUS
    assert spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
    assert partial.root_spec('P07', repair.ORIGIN)['measured_closes'] == 1047


@pytest.mark.parametrize('change', ['run', 'head', 'artifact', 'outer', 'cursor', 'closes', 'descriptors', 'authority',
    'admitted', 'relabelled', 'unknown', 'oom', 'root', 'reuse', 'full', 'flag'])
def test_foreign_or_relabelled_target_refuses(change):
    s = target()
    if change == 'run': s['run_id'] += 1
    elif change == 'head': s['head'] = '0' * 40
    elif change == 'artifact': s['artifact_id'] += 1
    elif change == 'outer': s['outer_sha256'] = '0' * 64
    elif change == 'cursor': s['selected_session'] = '2022-10-03'
    elif change == 'closes': s['measured_closes'] = 1197
    elif change == 'descriptors': s['repairs'].pop()
    elif change == 'authority': s['financial_authority'] = True
    elif change == 'admitted': s['financial_predecessor_admitted'] = True
    elif change == 'relabelled': s['prior_stops']['reviewer']['exit_code'] = 0
    elif change == 'unknown': s['prior_stops']['reviewer']['stopped'] = False
    elif change == 'oom': s['prior_stops']['reviewer']['oom_killed'] = True
    elif change == 'root': s['root_admission'] = {}
    elif change == 'reuse': s['reuse_closed_hosted_prefix_review'] = True
    elif change == 'full': s['readonly_full_financial_target'] = True
    else: s[repair.FLAG] = False
    with pytest.raises(ValueError): repair.validate_target(s)


@pytest.mark.parametrize('field,value', [('financial_resume_authorized', True), ('maximum_parallel_financial_workers', 1),
    ('readonly_partial_review', False), ('readonly_source_witnesses', True), ('arms', ['P05'])])
def test_financial_or_other_request_cannot_transport_target(field, value):
    request = resume.expected_request(); request[field] = value
    with pytest.raises(ValueError): repair.request_only_readonly(request, target())


def review_files(tmp_path):
    core = dict(schema='research.full-system-core-review/1', status='PARTIAL_CORE_PREFIX_REVIEWED',
        checkpoint_sha256=repair.OUTER, counts=dict(formation=126, daily=1196), all_prefixes_verified=True,
        all_daily_factors_and_chains_verified=True, complete=False)
    branch = dict(schema='research.retained-additional-sensor-branch-review/1', checkpoint_sha256=repair.OUTER,
        passed=True, rows=149, retained_rows=593, all_financial_watch_and_proof_identities_verified=True,
        all_original_and_added_uncertainty_retained=True)
    return core, branch


def write_reviews(tmp_path, core, branch):
    (tmp_path / 'core-review.json').write_text(json.dumps(core))
    (tmp_path / 'uncertainty-certificate-review.json').write_text(json.dumps(branch))


def test_both_original_full_review_results_required(tmp_path):
    core, branch = review_files(tmp_path); write_reviews(tmp_path, core, branch)
    result = repair.require_requalified_review(tmp_path, target())
    assert result['passed'] is True and result['financial_sessions_advanced'] == 0
    assert result['financial_authority'] is False


@pytest.mark.parametrize('change', ['old_prefix_only', 'wrong_branch', 'lost_history', 'lost_input', 'unverified_core', 'tail', 'float_rows'])
def test_partial_wrong_or_unverified_recovery_result_refuses(tmp_path, change):
    core, branch = review_files(tmp_path)
    if change == 'old_prefix_only': core['counts']['daily'] = 1047
    elif change == 'wrong_branch': branch['checkpoint_sha256'] = '0' * 64
    elif change == 'lost_history': branch['retained_rows'] = 0
    elif change == 'lost_input': branch['all_original_and_added_uncertainty_retained'] = False
    elif change == 'unverified_core': core['all_prefixes_verified'] = False
    elif change == 'float_rows': branch['rows'] = 149.0
    else: core['checkpoint_sha256'] = '0' * 64
    write_reviews(tmp_path, core, branch)
    with pytest.raises(ValueError): repair.require_requalified_review(tmp_path, target())


def test_removing_request_guard_really_accepts_financial_request():
    request = resume.expected_request(); request['financial_resume_authorized'] = True
    with pytest.raises(ValueError): repair.request_only_readonly(request, target())
    fn, = [n for n in ast.parse(Path(repair.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'request_only_readonly']
    fn.body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
               and any(isinstance(v, ast.Constant) and v.value == 'REVIEW_REPAIR_ZERO_FINANCIAL_REQUEST_ONLY' for v in n.value.args))]
    scope = dict(vars(repair))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-readonly-request-guard>', 'exec'), scope)
    scope['request_only_readonly'](request, target())


def public_archive(tmp_path, *, relabelled=False):
    spec = target()
    receipt = dict(status=repair.STATUS, performance_admitted=False, **deepcopy(spec['prior_stops']))
    if relabelled: receipt['reviewer']['exit_code'] = 0
    stage = dict(status='STAGING_PASSED', run_id=str(repair.RUN), source_commit=repair.HEAD,
        protocol_sha256=partial.PROTOCOL, runtime_image=partial.IMAGE, execution_image=partial.EXECUTION_IMAGE,
        source_files_verified=514, members_verified=591, authenticated_before_parsing=True,
        offline_image_source_verified=True, runtime_index_config_layer_chain_verified=True, replay_started=False)
    marker = dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED', arm='P07',
        financial_sessions_advanced=0, credentials_saved=False)
    members = {spec['receipt_name']:json.dumps(receipt).encode(), 'full-core-staging.json':json.dumps(stage).encode(),
        'resume-export-qualification-P07.json':json.dumps(marker).encode(), 'ephemeral-runner-capacity.json':b'{}'}
    spec['public_members'] = {n:dict(bytes=len(raw), sha256=repair.sha(raw)) for n,raw in members.items()}
    path = tmp_path / 'synthetic-public-members.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, raw in members.items(): archive.writestr(name, raw)
        archive.writestr(spec['encrypted_output']['name'], b'synthetic opaque asset, never decrypted')
    return spec, path


def test_exact_failed_status_is_accepted_only_as_quarantine(tmp_path):
    spec, path = public_archive(tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert len(repair.public_names(spec, archive)) == 5
        with pytest.raises(ValueError, match='ACTUAL_PRIOR_STATUS'): partial.public_names(spec, archive)


def test_relabelled_failed_review_stop_still_refuses(tmp_path):
    spec, path = public_archive(tmp_path, relabelled=True)
    with zipfile.ZipFile(path) as archive:
        with pytest.raises(ValueError, match='ACTUAL_PRIOR_STATUS'): repair.public_names(spec, archive)


def test_undoing_status_binding_restores_entire_public_guard_AST(tmp_path, monkeypatch):
    captured = []
    def capture(tree, *args, **kwargs):
        captured.append(deepcopy(tree)); return builtins.compile(tree, *args, **kwargs)
    monkeypatch.setattr(repair, 'compile', capture, raising=False)
    spec, path = public_archive(tmp_path)
    with zipfile.ZipFile(path) as archive: repair.public_names(spec, archive)
    tree, = captured; fn, = tree.body
    old = next(n for n in ast.parse(Path(partial.__file__).read_bytes()).body
               if isinstance(n, ast.FunctionDef) and n.name == 'public_names')
    before, = [n for n in old.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'status']
    after, = [n for n in fn.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'status']
    after.value = deepcopy(before.value)
    assert ast.dump(fn, include_attributes=False) == ast.dump(old, include_attributes=False)


def test_readonly_worker_launch_guard_falsifier():
    outer = next(n for n in ast.parse(Path(resume.__file__).read_bytes()).body
                 if isinstance(n, ast.FunctionDef) and n.name == 'launch')
    fn, = [n for n in ast.walk(outer) if isinstance(n, ast.FunctionDef) and n.name == 'worker']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(v, ast.Constant) and v.value == 'RESUME_READONLY_REQUEST_CANNOT_LAUNCH_ECONOMIC_WORKER' for v in n.value.args)]
    # Isolate the real guard before any command construction, then a harmless return.
    def execute(nodes):
        selected = deepcopy(fn); selected.body = deepcopy(nodes) + [ast.Return(value=ast.Constant('synthetic-only'))]
        scope = dict(need=resume.need, request=dict(financial_resume_authorized=False))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[selected], type_ignores=[])), '<actual-readonly-worker-launch-guard>', 'exec'), scope)
        return scope['worker']('economic', None)
    with pytest.raises(ValueError, match='CANNOT_LAUNCH_ECONOMIC_WORKER'): execute([guard])
    assert execute([]) == 'synthetic-only'


@pytest.mark.parametrize('event,code', [('readonly-repair', 0), ('readonly-repair-refused', 2), ('readonly-repair-unknown', 2)])
def test_repair_launch_only_runs_sequential_readers_and_keeps_failed_or_unknown_explicit(tmp_path, monkeypatch, event, code):
    from research.capital_risk.forecast_tests.test_financial_resume import launch_fixture
    args, calls, exports = launch_fixture(tmp_path, monkeypatch, event)
    qualifications = []
    def qualified(root, spec):
        qualifications.append(root)
        return dict(passed=True, financial_sessions_advanced=0, financial_authority=False)
    monkeypatch.setattr(repair, 'require_requalified_review', qualified)
    assert resume.launch(args) == code
    assert calls == ['preflight', 'review'] and 'economic' not in calls
    receipt = json.loads(args.output.read_bytes())
    assert receipt['financial_resume_authorized'] is False
    assert receipt['performance_admitted'] is False and len(exports) == 1
    if code == 0:
        assert receipt['status'] == 'READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'
        assert len(qualifications) == 1
    else:
        assert not qualifications
        assert receipt['status'] != 'READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'
        if event.endswith('unknown'):
            assert 'UNKNOWN' in receipt['status']
            assert not (exports[0] / 'requalified-review').exists()


@pytest.mark.parametrize('prefix', ['research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_import_fence(prefix):
    with pytest.raises(ImportError): Fence().find_spec(prefix)
