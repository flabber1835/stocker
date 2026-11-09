"""DATA/AST and inert argument falsifiers; no local canonical execution."""
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

import p00_recovery_hold_policy as policy
import p00_recovery_hold_job as job
import p00_recovery_hold_worker as worker

HERE = Path(__file__).resolve().parents[1]
# Inert syntax DTO. This is parsed only, never compiled or executed.
DTO = '''
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
'''


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_vacancy', 'research.pooled_input')):
            raise AssertionError('LOCAL_CANONICAL_IMPORT_FORBIDDEN:' + fullname)


def test_only_extra_gate_changes_and_native_ast_is_identical():
    changed = policy.transform(DTO, policy.CHANGES)
    assert policy.native_ast(changed) == policy.native_ast(DTO)
    assert 'if True:' in changed and 'desired = min(desired, 0.55)' in changed
    assert "'research-p00-no-extra-recovery-hold/1'" in changed


@pytest.mark.parametrize('index', range(len(policy.CHANGES)))
def test_each_missing_source_site_refuses(index):
    before, _ = policy.CHANGES[index]
    modified = DTO.replace(before, 'False', 1)
    assert modified != DTO
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        policy.transform(modified, policy.CHANGES)


def test_duplicate_gate_refuses():
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        policy.transform(DTO+'\nx = self.full_streak >= LDRC_REC or concordant\n', policy.CHANGES)


def test_unknown_frozen_hash_refuses():
    with pytest.raises(ValueError, match='FROZEN_PARENT_BYTES'):
        policy.source(DTO.encode(), True)


def test_native_guard_refuses_a_changed_native(monkeypatch):
    monkeypatch.setattr(policy, 'PARENT_SHA', hashlib.sha256(DTO.encode()).hexdigest())
    monkeypatch.setattr(policy, 'transform', lambda raw, changes: DTO.replace('>= 10', '>= 1'))
    with pytest.raises(ValueError, match='NATIVE_AST_UNCHANGED'):
        policy.source(DTO.encode(), True)


def test_native_falsifier_fails_when_native_guard_is_removed(monkeypatch):
    original = policy.need
    monkeypatch.setattr(policy, 'need', lambda value, code: original(True if code == 'NATIVE_AST_UNCHANGED' else value, code))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_native_guard_refuses_a_changed_native(monkeypatch)


def test_actual_frozen_native_stays_identical_under_ast_transform():
    raw = (HERE.parent.parent/'sentinel/controller/champion_frozen.py').read_bytes()
    assert policy.source(raw, False).encode() == raw
    assert policy.native_ast(policy.source(raw, True)) == policy.native_ast(raw)


def test_independent_vector_changes_only_extra_clear_condition():
    raw = (HERE/'full_system_controller_vector.py').read_bytes()
    changed = policy.transform(raw, policy.VECTOR_CHANGES)
    assert 'clear = episode & (native >= 1)' in changed
    assert 'release = old & ~new & (age + 1 >= 10) & (fh >= 3)' in changed
    assert 'release = old & (sa + 1 >= 20) & (sh >= 6)' in changed
    before, _ = policy.VECTOR_CHANGES[0]
    pretty = ast.unparse(ast.parse(before, mode='eval').body)
    text = ast.unparse(ast.parse(raw))
    assert text.count(pretty) == 1
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        policy.transform(text.replace(pretty, 'False', 1), policy.VECTOR_CHANGES)


def test_canonical_compilation_is_closed_locally(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_ONLY'):
        policy.parent_module(DTO.encode(), {'id': policy.CANDIDATE}, 'unused')


def test_owned_canary_private_name_matches_actual_shared_loader_contract():
    calls = [n for n in ast.walk(ast.parse((HERE/'p00_recovery_hold_policy.py').read_bytes()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'canonical_leaf']
    assert len(calls) == 1
    name, = [kw.value.value for kw in calls[0].keywords if kw.arg == 'name']
    assert name.startswith('_private_sharadar_owned_grid')


@pytest.mark.parametrize('review', (False, True))
def test_actual_container_constructor_with_inert_linux_identity(review, monkeypatch):
    import full_system_trials_job
    monkeypatch.setattr(full_system_trials_job, 'os', SimpleNamespace(getuid=lambda: 1001, getgid=lambda: 1001))
    argv = job.command('capital-full-core-b-'+('review' if review else 'worker')+'-123-1',
                       Path('/source'), Path('/frozen'), Path('/output'), Path('/original'),
                       Path('/evidence') if review else None)
    assert argv[argv.index('--network')+1] == 'none'
    assert argv[argv.index('--entrypoint')+1] == 'python'
    assert '/driver/p00_recovery_hold_worker.py' in argv
    assert argv[-2:] == ['--mode', 'review' if review else 'worker']
    assert argv[argv.index('--root')+1] == '/core/book'
    assert argv[argv.index('--output')+1] == ('/out/review' if review else '/out/book')


def test_actual_archived_inspector_signature_uses_inert_arguments():
    inspect.signature(job.old_inspector()).bind('example', 'id', value=object(), run_id='123',
                                               user='1001:1001', correlation_prefix=False)


def test_source_bound_probe_under_canonical_import_fence():
    finder = NoCanonical()
    sys.meta_path.insert(0, finder)
    try:
        request = HERE/'p00-recovery-hold-request.json'
        assert json.loads(request.read_bytes()) == job.expected_request()
        assert job.probe(request)['canonical_runtime_executed'] is False
    finally:
        sys.meta_path.remove(finder)


class LinuxPathDTO(PurePosixPath):
    def resolve(self): return self
    def is_symlink(self): return False
    def exists(self): return False


@pytest.mark.parametrize('replacement', (None, 'artifacts/capital-risk/p00-recovery-hold-capacity.json',
                                       '$GITHUB_WORKSPACE/artifacts/capital-risk/p00-recovery-hold-capacity.json'))
def test_capacity_path_against_actual_guard(replacement, monkeypatch):
    import ephemeral_runner_capacity as capacity
    monkeypatch.setattr(capacity, 'Path', LinuxPathDTO)
    text = (HERE.parent.parent/job.WORKFLOW).read_text()
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
def test_transport_destination_against_actual_guard(bad, monkeypatch):
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
    if bad == 'nested': chosen = LinuxPathDTO(env['RUNNER_TEMP'])/'p00-recovery-hold-1/original'
    if bad == 'prefix': chosen = LinuxPathDTO(env['RUNNER_TEMP'])/'p00-recovery-hold-original'
    if bad:
        with pytest.raises(ValueError, match='HOSTED_FACTUAL_DESTINATION_CAPACITY'):
            transport.hosted_destination(chosen)
    else:
        assert transport.hosted_destination(chosen) == chosen


class TargetColumnsDTO:
    def __init__(self, count=43): self.count = count
    def __getitem__(self, key): return (0., .55 if key[1] < 17 else 1.)


def scope_rows():
    return [dict(session=str(i), decision=dict(native_target_core_exposure=1., champion_target_core_exposure=0.,
                    ldrc={'reason':'FULL_RISK_HELD'}, owned_impairment={'active':i < 17})) for i in range(43)]


def test_changed_target_scope_with_inert_rows():
    result = worker.changed_scope(scope_rows(), TargetColumnsDTO())
    assert len(result) == 43 and sum(x['owned55_active'] for x in result) == 17


def test_changed_target_outside_original_hold_refuses():
    rows = scope_rows()
    rows[0]['decision']['native_target_core_exposure'] = 0.
    with pytest.raises(ValueError, match='CHANGE_ONLY_AT_ORIGINAL_POST_NATIVE_HOLD'):
        worker.changed_scope(rows, TargetColumnsDTO())


def test_scope_falsifier_fails_when_scope_guard_is_removed(monkeypatch):
    original = worker.need
    monkeypatch.setattr(worker, 'need', lambda value, code: original(True if code == 'CHANGE_ONLY_AT_ORIGINAL_POST_NATIVE_HOLD' else value, code))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_changed_target_outside_original_hold_refuses()


def test_incomplete_changed_scope_refuses():
    with pytest.raises(ValueError, match='AUDITED_P00_43_CLOSE_HOLD_SCOPE'):
        worker.changed_scope(scope_rows()[:-1], TargetColumnsDTO())
