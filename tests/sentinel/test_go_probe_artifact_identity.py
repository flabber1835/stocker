"""Real artifact validation after the public GO-to-Compose environment boundary.

Feed binding, image metadata and process transport are explicit fixtures. Public
command construction, the base Compose environment and child validators are real.
No database, provider or broker is contacted.
"""
from copy import deepcopy
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml
import sentinel

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_go_validate as go
import sentinel_go_validate_entry as entry
import sentinel_go_24x7_entry as source_final

COMMIT = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
TEST_KEY = 'SENTINEL_TEST_IMAGE_DIGEST'
ROUTES = ('preparation', 'parity', 'readiness', 'database')
FUNCTIONS = {'parity': 'probe_active_wealth_parity',
             'readiness': 'probe_sharadar_readiness',
             'database': 'probe_database_financial_health'}
CHILD = '''
import json
from sentinel.identity import deployment_artifacts
from sentinel.authority import runtime_artifact_identity
from sentinel.local_paper import validate_runtime_identity
value = {'deployment_artifacts': deployment_artifacts()}
runtime_artifact_identity(value)
validate_runtime_identity(value)
print(json.dumps(value['deployment_artifacts'], sort_keys=True))
'''


class Runner:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        command = list(argv)
        self.calls.append((command, dict(env or {})))
        if command == ['bash', 'scripts/sentinel-compose.sh', '--explain']:
            return subprocess.CompletedProcess(command, 0, '-f docker-compose.sentinel.yml', '')
        if len(command) > 1 and command[1] == 'scripts/sentinel_feed_gate.py':
            return subprocess.CompletedProcess(command, 0, COMMIT + '\n' + DIGEST + '\n', '')
        if source_final._RETAINED_REVISION_CODE in command:
            return subprocess.CompletedProcess(command, 0, '{"retained_revision": null}', '')
        assert command[:2] == ['docker', 'compose']
        # We assert only the generated invocation, not financial readiness.
        return subprocess.CompletedProcess(command, 1, '', 'synthetic transport boundary')


def configured():
    return {
        'SENTINEL_POSTGRES_PASSWORD': 'synthetic-private-db',
        'SENTINEL_PUBLICATION_RECEIPT_KEY': 'synthetic-publication-key-' * 3,
        'SENTINEL_LOCAL_PAPER_MODE': 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1',
        'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': 'PAPROBESCOPE',
        'SENTINEL_LOCAL_PAPER_BACKUP_POLICY': 'REQUIRED_V1',
        'SENTINEL_GIT_COMMIT': COMMIT,
        'SENTINEL_RUNTIME_IMAGE_DIGEST': DIGEST,
        TEST_KEY: DIGEST,
        'ALPACA_API_KEY': 'synthetic-market-data-key',
        'ALPACA_SECRET_KEY': 'synthetic-market-data-secret',
        'SENTINEL_PAPER_ACCOUNT_ID': 'must-not-enter',
    }


def command_for(route, values, monkeypatch):
    runner = Runner()
    kwargs = dict(env=deepcopy(values), commit=COMMIT)
    if route == 'preparation':
        # The real verified entry selects this same source-final overlay.
        monkeypatch.setattr(entry, '_VERIFIED_ORCHESTRATION', True)
        monkeypatch.setattr(entry.go_lock, 'lifecycle_lock_is_held', lambda *_: True)
        monkeypatch.setattr(entry, '_CORE_PREPARATION_PROBE', source_final._deployment_preparation_probe)
        monkeypatch.setattr(go, '_PREPARATION_CODE', source_final._PREPARATION_CODE)
        entry.probe_prevalidation_preparation(runner, runtime_ref=DIGEST, **kwargs)
        matches = [call for call in runner.calls if call[0][-1] == source_final._PREPARATION_CODE]
    else:
        kwargs['now_text'] = '2026-10-25T03:00:00Z'
        if route == 'parity':
            go.probe_active_wealth_parity(runner, candidate_image_digest=DIGEST,
                runtime_image_digest=DIGEST, source_identity_sha256='c' * 64, **kwargs)
        elif route == 'readiness':
            go.probe_sharadar_readiness(runner, runtime_ref=DIGEST, **kwargs)
        else:
            go.probe_database_financial_health(runner, runtime_ref=DIGEST,
                bounded_ingest_milliseconds=1, full_forward_decision_replay_milliseconds=1, **kwargs)
        matches = [call for call in runner.calls if call[0][:2] == ['docker', 'compose']]
    assert len(matches) == 1
    return matches[0]


def compose_environment(values):
    model = yaml.safe_load((ROOT / 'docker-compose.sentinel.yml').read_text())
    def resolve(match):
        name, operator, default = match.groups()
        value = values.get(name, '')
        if operator == ':?' and not value:
            raise AssertionError('missing fixture Compose input: ' + name)
        return value or default
    return {name: re.sub(r'\$\{([A-Z0-9_]+)(:-|:\?)([^}]*)\}', resolve, str(template))
        for name, template in model['services']['sentinel']['environment'].items()}


def child_environment(command, values):
    result = compose_environment(values)
    for index, item in enumerate(command[:command.index('--entrypoint')]):
        if item == '--env':
            name, separator, literal = command[index + 1].partition('=')
            if separator:
                result[name] = literal
            elif name in values:
                result[name] = values[name]
            else:
                result.pop(name, None)
    # This is the selected image's fixture metadata, not a forwarded grant.
    result['SENTINEL_IMAGE_SOURCE_REVISION'] = COMMIT
    result['PYTHONPATH'] = str(Path(sentinel.__file__).resolve().parent.parent)
    result['PATH'] = os.environ.get('PATH', '')
    return result


def validate_child(route, values, monkeypatch):
    command, transport = command_for(route, values, monkeypatch)
    child = child_environment(command, transport)
    if route != 'preparation':
        assert not go._BROKER_AUTH_ENV.intersection(child)
    else:
        assert 'SENTINEL_PAPER_ACCOUNT_ID' not in child
    completed = subprocess.run([sys.executable, '-B', '-c', CHILD], env=child,
        capture_output=True, text=True, timeout=15)
    return completed, child


@pytest.mark.parametrize('route', ROUTES)
def test_owned_go_child_receives_complete_actual_artifact_identity(route, monkeypatch):
    completed, child = validate_child(route, configured(), monkeypatch)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {'schema': 'sentinel.runtime-artifacts/1',
        'git_commit': COMMIT, 'runtime_image_digest': DIGEST, 'test_image_digest': DIGEST}
    assert child[TEST_KEY] == DIGEST


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('defect', ('missing', 'malformed', 'foreign'))
def test_child_does_not_invent_or_repair_unproven_test_identity(route, defect, monkeypatch):
    values = configured()
    if defect == 'missing':
        values.pop(TEST_KEY)
    else:
        values[TEST_KEY] = 'not-a-digest' if defect == 'malformed' else 'sha256:' + 'd' * 64
    completed, child = validate_child(route, values, monkeypatch)
    assert completed.returncode != 0
    assert child.get(TEST_KEY) == values.get(TEST_KEY)


@pytest.mark.parametrize('route', ROUTES)
def test_removing_test_identity_forwarding_is_detected_by_real_child(route, monkeypatch):
    if route == 'preparation':
        assert TEST_KEY in entry._FEED_ENV_KEYS
        monkeypatch.setattr(entry, '_FEED_ENV_KEYS', tuple(k for k in entry._FEED_ENV_KEYS if k != TEST_KEY))
    else:
        function = getattr(go, FUNCTIONS[route])
        raw = inspect.getsource(function)
        needle = '"--env", "SENTINEL_TEST_IMAGE_DIGEST",'
        assert raw.count(needle) == 1
        namespace = {}
        exec(compile(raw.replace(needle, ''), 'removed test image handoff', 'exec'),
            function.__globals__, namespace)
        monkeypatch.setattr(go, function.__name__, namespace[function.__name__])
    with pytest.raises(AssertionError):
        test_owned_go_child_receives_complete_actual_artifact_identity(route, monkeypatch)


def test_base_service_has_no_standing_artifact_identity():
    child = compose_environment(configured())
    assert not {'SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST', TEST_KEY}.intersection(child)
