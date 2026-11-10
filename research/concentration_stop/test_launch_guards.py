"""DATA/AST-only launch-fence tests; no diagnostic financial calculations."""
import ast
import importlib.util
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).with_name('job.py')
spec = importlib.util.spec_from_file_location('concentration_launch_data', SOURCE)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def environment():
    return dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='flabber1835/stocker',
        GITHUB_REPOSITORY_OWNER='flabber1835', GITHUB_ACTOR='flabber1835',
        GITHUB_REF=job.REF, GITHUB_REF_TYPE='branch', GITHUB_EVENT_NAME='push',
        GITHUB_RUN_ATTEMPT='1', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
        RUNNER_ARCH='X64', ImageOS='ubuntu24', RUNNER_TEMP='/home/runner/work/_temp',
        GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123')


def isolated_context():
    """Use inert Linux facts so Windows cannot make negative tests vacuous."""
    class PosixPath(PurePosixPath):
        def resolve(self):
            return self
    tree = ast.parse(SOURCE.read_bytes())
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'context']
    namespace = {**vars(job), 'os': SimpleNamespace(name='posix'), 'Path': PosixPath}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<inert-host-context>', 'exec'), namespace)
    return namespace['context']


def test_valid_hosted_context_is_accepted():
    isolated_context()(environment())


@pytest.mark.parametrize('field,value,reason', [
    ('GITHUB_REF', 'refs/heads/main', 'EXACT_HOSTED_CONTEXT'),
    ('RUNNER_ENVIRONMENT', 'self-hosted', 'EXACT_HOSTED_CONTEXT'),
    ('GITHUB_RUN_ATTEMPT', '2', 'EXACT_HOSTED_CONTEXT'),
    ('GITHUB_ACTOR', 'other', 'EXACT_HOSTED_CONTEXT'),
    ('GITHUB_REPOSITORY', 'other/stocker', 'EXACT_HOSTED_CONTEXT'),
    ('GITHUB_EVENT_NAME', 'pull_request', 'EXACT_HOSTED_CONTEXT'),
    ('ALPACA_API_KEY', 'inert-not-a-real-key', 'NO_PRODUCTION_CREDENTIALS'),
    ('DATABASE_URL', 'inert-not-a-real-url', 'NO_PRODUCTION_CREDENTIALS'),
    ('GITHUB_SHA', 'bad', 'HOSTED_IDENTITY'),
    ('GITHUB_RUN_ID', '0', 'HOSTED_IDENTITY'),
    ('RUNNER_TEMP', '/different', 'HOSTED_PATH'),
])
def test_wrong_context_is_rejected(field, value, reason):
    env = environment()
    env[field] = value
    with pytest.raises(ValueError, match='^' + reason + '$'):
        isolated_context()(env)


def inspection(role):
    targets = ['/current', '/p00', '/out'] + (['/evidence'] if role == 'review' else [])
    mounts = [dict(Type='bind', Destination=target, RW=target == '/out') for target in targets]
    command = ['-B', '-u', f'/current/research/concentration_stop/{role}.py',
               '--book', '/p00/book', '--out', '/out/' + role]
    if role == 'review':
        command += ['--evidence', '/evidence/worker']
    return dict(Name=f'/concentration-stop-{role}-123-1', Image=job.IMAGE, Id='b' * 64,
        HostConfig=dict(NetworkMode='none', ReadonlyRootfs=True, Memory=8 * 1024**3,
            MemorySwap=8 * 1024**3, NanoCpus=2_000_000_000, PidsLimit=64,
            CapDrop=['ALL'], SecurityOpt=['no-new-privileges']),
        Config=dict(WorkingDir='/current', User='1001:1001',
            Labels={'research.study': 'concentration-stop-20261109', 'research.role': role},
            Env=['CONCENTRATION_STOP_HOSTED=1'], Entrypoint=['python'], Cmd=command),
        Mounts=mounts)


def fake_inspection(monkeypatch, value):
    monkeypatch.setattr(job.os, 'getuid', lambda: 1001, raising=False)
    monkeypatch.setattr(job.os, 'getgid', lambda: 1001, raising=False)
    monkeypatch.setattr(job.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(stdout=json.dumps([value]).encode()))


@pytest.mark.parametrize('role', ['worker', 'review'])
def test_valid_actual_container_is_accepted(monkeypatch, role):
    value = inspection(role)
    fake_inspection(monkeypatch, value)
    assert job.inspect(f'concentration-stop-{role}-123-1', 'b' * 64) == value


@pytest.mark.parametrize('role', ['worker', 'review'])
@pytest.mark.parametrize('mutation,reason', [
    ('image', 'ACTUAL_IDENTITY'), ('identity', 'ACTUAL_IDENTITY'),
    ('network', 'ACTUAL_FENCES'), ('rootfs', 'ACTUAL_FENCES'),
    ('writable_input', 'ACTUAL_MOUNTS'), ('entrypoint', 'ACTUAL_ENTRYPOINT'),
    ('arguments', 'ACTUAL_ENTRYPOINT'), ('credential', 'ACTUAL_NO_CREDENTIALS'),
    ('user', 'ACTUAL_MOUNTS'), ('swap', 'ACTUAL_FENCES'),
])
def test_actual_container_mutations_are_rejected(monkeypatch, role, mutation, reason):
    value = inspection(role)
    if mutation == 'image':
        value['Image'] = 'sha256:' + '0' * 64
    elif mutation == 'identity':
        value['Id'] = 'c' * 64
    elif mutation == 'network':
        value['HostConfig']['NetworkMode'] = 'bridge'
    elif mutation == 'rootfs':
        value['HostConfig']['ReadonlyRootfs'] = False
    elif mutation == 'writable_input':
        value['Mounts'][0]['RW'] = True
    elif mutation == 'entrypoint':
        value['Config']['Entrypoint'] = ['different']
    elif mutation == 'arguments':
        value['Config']['Cmd'][-1] = '/different'
    elif mutation == 'credential':
        value['Config']['Env'].append('GH_TOKEN=inert-not-a-real-token')
    elif mutation == 'user':
        value['Config']['User'] = '0:0'
    else:
        value['HostConfig']['MemorySwap'] = -1
    fake_inspection(monkeypatch, value)
    with pytest.raises(ValueError, match='^' + reason + '$'):
        job.inspect(f'concentration-stop-{role}-123-1', 'b' * 64)


@pytest.mark.parametrize('role', ['worker', 'review'])
def test_launch_command_uses_offline_readonly_inputs(monkeypatch, role):
    monkeypatch.setattr(job.os, 'getuid', lambda: 1001, raising=False)
    monkeypatch.setattr(job.os, 'getgid', lambda: 1001, raising=False)
    argv = job.command(f'concentration-stop-{role}-123-1', role, Path('/inert-input'),
                       Path('/inert-output'), Path('/inert-evidence') if role == 'review' else None)
    assert argv[argv.index('--network') + 1] == 'none'
    assert '--read-only' in argv
    assert argv[argv.index('--memory') + 1] == argv[argv.index('--memory-swap') + 1] == '8g'
    assert argv[argv.index('--user') + 1] == '1001:1001'
    assert sum(arg.endswith(',readonly') for arg in argv) == (3 if role == 'review' else 2)
    assert not any('TOKEN=' in arg or 'KEY=' in arg or 'DATABASE_URL=' in arg for arg in argv)


def test_removing_exact_argument_guard_is_detectable(monkeypatch):
    tree = ast.parse(SOURCE.read_bytes())
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'inspect']
    checks = [n for n in ast.walk(function) if isinstance(n, ast.Compare)
              and ast.unparse(n) == "c['Cmd'] == expected"]
    assert len(checks) == 1
    checks[0].left = ast.Name(id='expected', ctx=ast.Load())
    namespace = dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<removed-command-guard-falsifier>', 'exec'), namespace)
    value = inspection('worker')
    value['Config']['Cmd'][-1] = '/different'
    fake_inspection(monkeypatch, value)
    with pytest.raises(ValueError, match='^ACTUAL_ENTRYPOINT$'):
        job.inspect('concentration-stop-worker-123-1', 'b' * 64)
    assert namespace['inspect']('concentration-stop-worker-123-1', 'b' * 64) == value
