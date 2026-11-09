"""DATA/AST and inert DTO qualification; financial decisions remain hosted only."""
import ast
import hashlib
import importlib.abc
import inspect
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
from types import SimpleNamespace

import pytest


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("sentinel", "stock_strategy_shared", "research.pooled_vacancy", "research.pooled_input")):
            raise AssertionError("LOCAL_CANONICAL_IMPORT_FORBIDDEN:" + fullname)


_import_fence = NoCanonical()
sys.meta_path.insert(0, _import_fence)
try:
    import p00_recovery_hold_policy as hold
    import p00_recovery_watch_policy as policy
    import p00_recovery_watch_job as job
    import p00_recovery_watch_worker as worker
finally:
    sys.meta_path.remove(_import_fence)

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent.parent
# Inert syntax DTO: parsed and transformed only, never compiled or executed.
DTO = """
class Native:
    _schema = 'ramp-free-native/1'
    def descriptive_syntax(self):
        healthy = r20 > 0 and dam <= .63 and green >= .2
        fast = self.fast_age + 1 >= 10 and self.fast_h >= 3
        slow = self.slow_age + 1 >= 20 and self.slow_h >= 6
class SyntheticCandidateDTO:
    _schema = 'ramp-free-ex3-rebound-false/1'
    def descriptive_syntax(self):
        if self.full_streak >= LDRC_REC or concordant:
            reason = 'FULL_RISK_CERTIFIED_PERSISTENCE'
        if self.latched:
            desired = min(desired, .55)
"""


@pytest.fixture(autouse=True)
def canonical_import_fence():
    finder = NoCanonical()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)


def test_three_profiles_reuse_original_parent_and_owned_constants():
    registered = policy.profiles()
    assert [p['id'] for p in registered] == [policy.BASELINE, policy.NO_EXTRA, policy.CANDIDATE]
    assert len({p['id'] for p in registered}) == 3
    assert [p['parent'] for p in registered] == [registered[0]['parent']] * 3
    assert [p['owned'] for p in registered] == [registered[0]['owned']] * 3
    assert policy.PARENT_SHA == hold.PARENT_SHA
    assert policy.CANDIDATE == 'P00_RECOVERY_WATCH_RW1'
    assert policy.NO_EXTRA == hold.CANDIDATE


def test_actual_frozen_sources_and_native_ast_are_unchanged():
    raw = (REPO/'sentinel/controller/champion_frozen.py').read_bytes()
    assert policy.source(raw, False).encode() == raw
    changed = policy.source(raw, True)
    assert changed == hold.source(raw, True)
    assert hold.native_ast(changed) == hold.native_ast(raw)
    assert 'desired = min(desired, LDRC_CEIL)' in changed
    ceiling, = [n.value.value for n in ast.parse(changed).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'LDRC_CEIL' for t in n.targets)]
    assert ceiling == .55
    assert 'research-p00-no-extra-recovery-hold/1' in changed


def test_unknown_parent_bytes_refuse_before_any_compilation():
    with pytest.raises(ValueError, match='FROZEN_PARENT_BYTES'):
        policy.source(DTO.encode(), True)


def test_reused_native_guard_refuses_changed_native(monkeypatch):
    monkeypatch.setattr(hold, 'PARENT_SHA', hashlib.sha256(DTO.encode()).hexdigest())
    monkeypatch.setattr(hold, 'transform', lambda raw, changes: DTO.replace('>= 10', '>= 1'))
    with pytest.raises(ValueError, match='NATIVE_AST_UNCHANGED'):
        policy.source(DTO.encode(), True)


def test_native_falsifier_fails_when_guard_is_bypassed(monkeypatch):
    original = hold.need
    monkeypatch.setattr(hold, 'need', lambda value, code: original(True if code == 'NATIVE_AST_UNCHANGED' else value, code))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_reused_native_guard_refuses_changed_native(monkeypatch)


@pytest.mark.parametrize('index', range(len(hold.CHANGES)))
def test_missing_no_extra_source_site_refuses(index):
    before, _ = hold.CHANGES[index]
    malformed = DTO.replace(before, 'False', 1)
    assert malformed != DTO
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        hold.transform(malformed, hold.CHANGES)


def test_duplicate_no_extra_source_site_refuses():
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        hold.transform(DTO + '\nx = self.full_streak >= LDRC_REC or concordant\n', hold.CHANGES)


@pytest.mark.parametrize('no_extra', (False, True))
def test_vector_instrumentation_adds_only_current_native_stress_capture(no_extra):
    raw = (HERE/'full_system_controller_vector.py').read_bytes()
    tree = ast.parse(policy.vector_source(raw, no_extra))
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'targets']
    loop, = [n for n in function.body if isinstance(n, ast.For)]
    initial, = [n for n in function.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'native_stress_paths' for t in n.targets)]
    capture, = [n for n in loop.body if isinstance(n, ast.Expr)
                and ast.unparse(n).startswith('native_stress_paths.append(')]
    assert ast.unparse(capture) == 'native_stress_paths.append((ordinary | bf | fast | slow).copy())'
    function.body.remove(initial)
    loop.body.remove(capture)
    function.body[-1].value = ast.parse('np.asarray(paths, dtype=float).T', mode='eval').body
    original = hold.transform(raw, hold.VECTOR_CHANGES) if no_extra else raw.decode()
    assert ast.dump(tree, include_attributes=False) == ast.dump(ast.parse(original), include_attributes=False)


def test_unknown_independent_vector_bytes_refuse():
    with pytest.raises(ValueError, match='INDEPENDENT_VECTOR_BYTES'):
        policy.vector_source(DTO.encode(), False)


def snapshot_dto():
    return dict(schema=policy.SCHEMA, policy_id=policy.CANDIDATE,
                mode='WATCH', peak=100., active_cap=True, healthy_count=0,
                last_session='2000-01-03')


@pytest.mark.parametrize('mode,peak,active,count,cursor', (
    ('NORMAL', None, False, 0, None), ('NORMAL', None, False, 0, '2000-01-03'),
    ('PENDING', None, False, 0, '2000-01-03'),
    ('WATCH', 100., False, 0, '2000-01-03'), ('WATCH', 100., True, 7, '2000-01-03'),
))
def test_valid_snapshot_dto_without_state_machine_execution(mode, peak, active, count, cursor):
    payload = dict(schema=policy.SCHEMA, policy_id=policy.CANDIDATE, mode=mode, peak=peak,
                   active_cap=active, healthy_count=count, last_session=cursor)
    checked = policy._validated_snapshot(payload)
    assert checked == payload and checked is not payload


@pytest.mark.parametrize('changes', (
    {'schema': 'another-policy/1'}, {'policy_id': hold.CANDIDATE}, {'mode': 'UNKNOWN'},
    {'mode': True}, {'peak': None}, {'peak': True}, {'peak': 0.}, {'peak': float('nan')},
    {'active_cap': 1}, {'healthy_count': True}, {'healthy_count': -1}, {'healthy_count': 8},
    {'active_cap': False, 'healthy_count': 1}, {'last_session': None},
    {'last_session': '2000-02-30'}, {'last_session': '2000-1-3'},
    {'mode': 'PENDING'}, {'mode': 'NORMAL'},
))
def test_malformed_snapshot_dto_refuses_without_state_machine_execution(changes):
    payload = snapshot_dto()
    payload.update(changes)
    with pytest.raises(ValueError, match='REFUSED_P00_RECOVERY_WATCH_'):
        policy._validated_snapshot(payload)


@pytest.mark.parametrize('changes', ('missing', 'extra'))
def test_snapshot_dto_requires_exact_fields(changes):
    payload = snapshot_dto()
    if changes == 'missing':
        del payload['active_cap']
    else:
        payload['unexpected_state'] = False
    with pytest.raises(ValueError, match='SNAPSHOT_FIELDS'):
        policy._validated_snapshot(payload)


def test_pending_snapshot_requires_observed_session():
    payload = snapshot_dto()
    payload.update(mode='PENDING', peak=None, active_cap=False, last_session=None)
    with pytest.raises(ValueError, match='SNAPSHOT_INITIAL_STATE'):
        policy._validated_snapshot(payload)


@pytest.mark.parametrize('entrypoint,args', (
    ('parent_module', (DTO.encode(), {'id': 'P00_RECOVERY_WATCH_RW1'}, 'unused')),
    ('targets', ([], [])),
    ('independent_targets', ([], [])),
    ('canary', (DTO.encode(),)),
    ('RecoveryWatch', ()),
))
def test_every_policy_financial_entrypoint_refuses_local_execution(entrypoint, args, monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_ONLY'):
        getattr(policy, entrypoint)(*args)


@pytest.mark.parametrize('entrypoint,args', (
    ('controller_paths', ([], Path('/unused'))),
    ('run', (Path('/unused'), Path('/unused'))),
    ('review', (Path('/unused'), Path('/unused'), Path('/unused'))),
))
def test_worker_financial_entrypoints_refuse_before_io(entrypoint, args, monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_ONLY'):
        getattr(worker, entrypoint)(*args)


class TargetColumnsDTO:
    """Already recorded targets; contains no financial calculation or policy."""
    def __init__(self, actual=(1., .55, .55, 0.)):
        self.columns = {1: (1., 1., .55, 0.), 2: actual}

    def __getitem__(self, key):
        column, index = key
        return self.columns[column][index]


def recorded_scope_dtos():
    return ([dict(session=str(i)) for i in range(4)],
            [dict(active_cap=i > 0) for i in range(4)])


def test_recorded_scope_accepts_only_binding_reductions():
    rows, states = recorded_scope_dtos()
    changed = worker.watch_scope(rows, TargetColumnsDTO(), states)
    assert changed == [dict(session='1', no_extra=1., recovery_watch=.55, state=states[1])]


@pytest.mark.parametrize('actual', ((.55, .55, .55, 0.), (1., 1., .55, 0.),
                                    (1., .55, 1., 0.), (1., .55, .55, .55)))
def test_recorded_scope_refuses_outside_declared_cap(actual):
    rows, states = recorded_scope_dtos()
    with pytest.raises(ValueError, match='WATCH_REDUCTION_ONLY_AT_DECLARED_CEILING'):
        worker.watch_scope(rows, TargetColumnsDTO(actual), states)


def test_scope_falsifier_fails_when_guard_is_bypassed(monkeypatch):
    original = worker.need
    monkeypatch.setattr(worker, 'need', lambda value, code: original(
        True if code == 'WATCH_REDUCTION_ONLY_AT_DECLARED_CEILING' else value, code))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_recorded_scope_refuses_outside_declared_cap((.55, .55, .55, 0.))


def episode_state_dto(mode):
    return dict(mode=mode, active_cap=False)


def episode_outcomes_dtos():
    # Reporting labels only: no NAVs, returns, prices or account calculations.
    return {pid: object() for pid in (policy.BASELINE, policy.NO_EXTRA, policy.CANDIDATE)}


def period_labels_dto(series, first, last):
    return dict(first_index=first, last_index=last)


def test_instantaneous_recovery_is_reported_without_an_entry():
    rows = [dict(session=day) for day in ('2000-01-03', '2000-01-04')]
    states = [episode_state_dto(mode) for mode in ('PENDING', 'NORMAL')]
    result = worker.episode_reports(rows, states, TargetColumnsDTO(actual=(1., 1.)),
                                    episode_outcomes_dtos(), period_labels_dto)
    episode, = result['watch']
    assert result['cap'] == []
    assert episode['signal'] == episode['end'] == '2000-01-04'
    assert episode['instantaneous'] is True and episode['complete'] is True
    assert episode['cap_signal_closes'] == episode['changed_target_closes'] == 0
    assert episode['first_effective_session'] is None
    assert episode['account_anchor'] == '2000-01-04'
    assert episode['profiles'][policy.CANDIDATE] == dict(first_index=1, last_index=1)


def test_formation_watch_retains_true_signal_and_measured_account_anchor():
    formation = [dict(session=day) for day in ('1999-12-29', '1999-12-30')]
    formation_states = [episode_state_dto(mode) for mode in ('PENDING', 'WATCH')]
    rows = [dict(session=day) for day in ('2000-01-03', '2000-01-04')]
    states = [episode_state_dto(mode) for mode in ('WATCH', 'NORMAL')]
    result = worker.episode_reports(rows, states, TargetColumnsDTO(actual=(1., 1.)),
                                    episode_outcomes_dtos(), period_labels_dto,
                                    formation, formation_states)
    episode, = result['watch']
    assert result['cap'] == []
    assert episode['signal'] == '1999-12-30'
    assert episode['first_effective_session'] == episode['account_anchor'] == '2000-01-03'
    assert episode['end'] == '2000-01-04'
    assert episode['started_during_formation'] is True and episode['measurement_overlap'] is True
    assert episode['instantaneous'] is False and episode['complete'] is True
    assert episode['profiles'][policy.CANDIDATE] == dict(first_index=0, last_index=1)


def test_watch_serialization_and_step_guard_precede_state_access():
    tree = ast.parse((HERE/'p00_recovery_watch_policy.py').read_bytes())
    watch, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RecoveryWatch']
    methods = {n.name: n for n in watch.body if isinstance(n, ast.FunctionDef)}
    for name in ('__init__', 'step', 'snapshot', 'from_snapshot'):
        body = methods[name].body
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        assert isinstance(body[0], ast.Expr)
        assert isinstance(body[0].value, ast.Call)
        assert isinstance(body[0].value.func, ast.Name) and body[0].value.func.id == 'hosted'
    assert policy.SCHEMA == 'research.p00-recovery-watch-rw1/1'


@pytest.mark.parametrize('review', (False, True))
def test_actual_container_constructor_with_inert_linux_identity(review, monkeypatch):
    import full_system_trials_job
    monkeypatch.setattr(full_system_trials_job, 'os', SimpleNamespace(getuid=lambda: 1001, getgid=lambda: 1001))
    argv = job.command('capital-full-core-b-' + ('review' if review else 'worker') + '-123-1',
                       Path('/source'), Path('/frozen'), Path('/output'), Path('/original'),
                       Path('/evidence') if review else None)
    assert argv[argv.index('--network')+1] == 'none'
    assert argv[argv.index('--entrypoint')+1] == 'python'
    assert '/driver/p00_recovery_watch_worker.py' in argv
    assert argv[-2:] == ['--mode', 'review' if review else 'worker']
    assert argv[argv.index('--root')+1] == '/core/book'
    assert argv[argv.index('--output')+1] == ('/out/review' if review else '/out/book')
    assert '--read-only' in argv
    mounts = [argv[i+1] for i, arg in enumerate(argv[:-1]) if arg == '--mount']
    assert any('target=/variant' in value and 'readonly' in value for value in mounts)
    assert any('target=/core' in value and 'readonly' in value for value in mounts)


def test_archived_inspector_signature_with_inert_arguments():
    inspect.signature(job.old_inspector()).bind('example', 'id', value=object(), run_id='123',
                                               user='1001:1001', correlation_prefix=False)


@pytest.mark.parametrize('review', (False, True))
@pytest.mark.parametrize('corruption', (None, 'entrypoint', 'command'))
def test_actual_inspector_wrapper_checks_inert_container_identity(review, corruption, monkeypatch):
    import full_system_math_job
    mode = 'review' if review else 'worker'
    cmd = ['-B', '-u', '/driver/p00_recovery_watch_worker.py', '--root', '/core/book',
           '--output', '/out/review' if review else '/out/book']
    if review:
        cmd += ['--evidence', '/evidence/book']
    cmd += ['--mode', mode]
    value = {'Config': {'Entrypoint': ['python'], 'Cmd': cmd}}
    if corruption == 'entrypoint':
        value['Config']['Entrypoint'] = ['sh']
    elif corruption == 'command':
        value['Config']['Cmd'] = ['-B', '/driver/p00_recovery_hold_worker.py']
    monkeypatch.setattr(full_system_math_job, 'inspect', lambda name, identity=None: value)
    name = 'capital-full-core-b-' + mode + '-123-1'
    if corruption:
        with pytest.raises(ValueError, match='ACTUAL_EXACT_RESEARCH_ENTRYPOINT'):
            job.inspect(name)
    else:
        assert job.inspect(name) is value


def test_exact_source_bound_request_and_probe():
    request = HERE/job.REQUEST
    expected = job.expected_request()
    assert json.loads(request.read_bytes()) == expected
    assert expected['profiles'] == 3 and expected['generation'] == 1
    assert expected['native_rules_changed'] is False
    assert expected['core_recomputed'] is False
    assert expected['original_core_backtests_resumed'] is False
    assert expected['production_contacted'] is False
    for name in ('p00_recovery_watch_policy.py', 'p00_recovery_watch_worker.py', 'p00_recovery_watch_job.py',
                 'p00_recovery_hold_policy.py', 'p00-sentinel-grid-references.json'):
        assert expected['sources'][name] == hashlib.sha256((HERE/name).read_bytes()).hexdigest()
    assert job.REQUEST not in expected['sources']
    result = job.probe(request)
    assert result['canonical_runtime_executed'] is False
    assert result['status'] == 'P00_RECOVERY_WATCH_DATA_IMPORT_PROBE_PASSED'


@pytest.mark.parametrize('field,value', (
    ('profiles', 2), ('generation', 2), ('policy_change', 'ANOTHER_POLICY'),
    ('native_rules_changed', True), ('production_contacted', True),
))
def test_altered_request_refuses_before_imports(tmp_path, field, value):
    request = job.expected_request()
    request[field] = value
    path = tmp_path/'wrong-request.json'
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError, match='EXACT_REQUEST_AND_SOURCE_CLOSURE'):
        job.probe(path)


class LinuxPathDTO(PurePosixPath):
    def resolve(self): return self
    def is_symlink(self): return False
    def exists(self): return False


@pytest.mark.parametrize('replacement', (None, 'artifacts/capital-risk/p00-recovery-watch-capacity.json',
                                       '$GITHUB_WORKSPACE/artifacts/capital-risk/p00-recovery-watch-capacity.json'))
def test_actual_capacity_output_guard(replacement, monkeypatch):
    import ephemeral_runner_capacity as capacity
    monkeypatch.setattr(capacity, 'Path', LinuxPathDTO)
    text = (REPO/job.WORKFLOW).read_text()
    line, = [s.strip()[6:].strip("'") for s in text.splitlines()
             if s.strip().startswith('run:') and 'ephemeral_runner_capacity.py' in s]
    argv = shlex.split(line)
    chosen = argv[argv.index('--output')+1] if replacement is None else replacement
    dto = LinuxPathDTO(chosen.replace('$GITHUB_WORKSPACE', capacity.WORKSPACE))
    if replacement is None:
        assert capacity.admitted_output(dto) == LinuxPathDTO(capacity.WORKSPACE)/capacity.OUTPUT
    else:
        with pytest.raises(capacity.Refusal, match='REFUSED_CAPACITY_OUTPUT'):
            capacity.admitted_output(dto)


@pytest.mark.parametrize('bad', (False, 'nested', 'prefix'))
def test_actual_transport_destination_guard(bad, monkeypatch):
    import system_campaign_factual_admit as transport
    env = dict(RUNNER_TEMP='/home/runner/work/_temp', GITHUB_ACTIONS='true',
               GITHUB_REPOSITORY='flabber1835/stocker', GITHUB_REF='refs/heads/codex/capital-risk-research',
               GITHUB_ACTOR='flabber1835', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
               GITHUB_EVENT_NAME='push', GITHUB_SHA='a'*40)
    monkeypatch.setattr(job, 'Path', LinuxPathDTO)
    monkeypatch.setattr(transport, 'Path', LinuxPathDTO)
    monkeypatch.setattr(transport, 'os', SimpleNamespace(name='posix', environ=env))
    monkeypatch.setattr(transport, 'shutil', SimpleNamespace(disk_usage=lambda _: SimpleNamespace(free=12*1024**3)))
    chosen = job.baseline_transfer_root(env['RUNNER_TEMP'], job.GENERATION)
    if bad == 'nested': chosen = LinuxPathDTO(env['RUNNER_TEMP'])/'p00-recovery-watch-1/original'
    if bad == 'prefix': chosen = LinuxPathDTO(env['RUNNER_TEMP'])/'p00-recovery-watch-original'
    if bad:
        with pytest.raises(ValueError, match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):
            transport.hosted_destination(chosen)
    else:
        assert transport.hosted_destination(chosen) == chosen


def test_workflow_is_single_new_non_cancelling_request():
    text = (REPO/job.WORKFLOW).read_text()
    assert "paths: ['research/capital_risk/p00-recovery-watch-request.json']" in text
    assert 'group: p00-recovery-watch-generation-1' in text
    assert 'cancel-in-progress: false' in text
    assert 'persist-credentials: false' in text
    assert 'capital-p00-recovery-hold.yml' not in text
    assert 'capital-p00-sentinel-grid.yml' not in text
