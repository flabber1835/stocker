from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap
import sentinel_autonomous_deploy_ci_runtime as ci

COMMIT = 'a' * 40
RUNTIME = 'sha256:' + 'b' * 64
LENS = 'sha256:' + 'c' * 64
SOURCE = 'd' * 64
REFERENCE = 'ghcr.io/flabber1835/stocker/sentinel@' + RUNTIME


def reviewed(*, lens=RUNTIME, auxiliary=()):
    return SimpleNamespace(git_commit=COMMIT, runtime_image_digest=RUNTIME,
        test_image_digest=lens, auxiliary_image_digests=auxiliary,
        source_identity_sha256=SOURCE, mode='paper')


def certificate():
    return dict(source_commit=COMMIT, certified_image=REFERENCE, image_digest=RUNTIME,
                software_certification='VERIFIED', required_ci_jobs='PASS')


def image(image_id=RUNTIME, *, layers=None):
    return dict(Id=image_id, RepoDigests=[REFERENCE],
                Config={'Labels': {'org.opencontainers.image.revision': COMMIT}},
                RootFS={'Layers': layers or ['runtime-layer']})


class Commands:
    def __init__(self, *, record=None, lens_layers=None):
        self.commands = []
        self.record = record or image()
        self.lens_layers = lens_layers

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[:2] == ['git', 'status']:
            output = ''
        elif argv[:2] == ['git', 'symbolic-ref']:
            output = 'main'
        elif argv[:2] == ['git', 'rev-parse']:
            output = COMMIT
        elif argv[:3] == ['docker', 'image', 'inspect']:
            records = [self.record if value in {RUNTIME, REFERENCE}
                       else image(value, layers=self.lens_layers) for value in argv[3:]]
            output = json.dumps(records)
        elif argv[:2] == ['docker', 'run']:
            output = json.dumps({'identity_hash': SOURCE})
        else:
            pytest.fail('Unexpected command: ' + str(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr='')


def test_environment_accepts_one_signed_runtime_and_inspects_each_id_once(monkeypatch):
    monkeypatch.setattr(ci.verifier, 'verify_current', lambda **kw: certificate())
    commands = Commands()
    core.verify_reviewed_validation_environment(reviewed(), env={}, invoke=commands)
    inspections = [cmd[3:] for cmd in commands.commands if cmd[:3] == ['docker', 'image', 'inspect']]
    assert inspections == [[RUNTIME], [REFERENCE]]


def test_single_runtime_cannot_replace_missing_signed_certification(monkeypatch):
    def refuse(**kwargs):
        raise ci.verifier.CertificationVerificationRefused('CERT_NOT_FOUND', 'missing certificate')
    monkeypatch.setattr(ci.verifier, 'verify_current', refuse)
    with pytest.raises(core.DeployRefused, match='CERT_NOT_FOUND'):
        core.verify_reviewed_validation_environment(reviewed(), env={}, invoke=Commands())


def test_installer_uses_the_supported_read_token(monkeypatch):
    selected = []
    monkeypatch.setattr(ci.verifier, 'GitHubReadClient',
                        lambda token: selected.append(token))
    monkeypatch.setattr(ci.verifier, 'verify_current', lambda **kw: certificate())
    ci.verify_reviewed_runtime(reviewed(), env={
        'SENTINEL_GITHUB_READ_TOKEN': 'read-only-token', 'GITHUB_TOKEN': 'other'},
        invoke=Commands(), root=ROOT)
    assert selected == ['read-only-token']


def test_shadow_preflight_carries_reviewed_authority_without_broker_credentials():
    from sentinel.shadow_service import ShadowServiceConfig
    review = reviewed()
    review.mode = 'dual'
    review.bundle_sha256 = 'e' * 64
    review.shadow_configuration_sha256 = 'f' * 64
    review.data_publication_sha256 = '1' * 64
    def invoke(argv, **kwargs):
        if argv[:2] == ['bash', 'scripts/sentinel-compose.sh']:
            return subprocess.CompletedProcess(argv, 0, stdout='-f compose.yml', stderr='')
        forwarded = [argv[i + 1] for i, value in enumerate(argv) if value == '-e']
        assert set(forwarded) >= {
            'SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256',
            'SENTINEL_REVIEWED_DEPLOYMENT_MODE'}
        env = kwargs['env']
        assert not any(name in env for name in (
            'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_PAPER_ACCOUNT_ID'))
        assert env['SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256'] == review.bundle_sha256
        assert env['SENTINEL_REVIEWED_DEPLOYMENT_MODE'] == 'dual'
        ShadowServiceConfig.from_env(env)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
            'schema': 'sentinel.shadow-service-preflight/1', 'mode': 'BROKER_FREE_SHADOW',
            'status': 'NOT_STARTED', 'broker_mutations_authorized': False}), stderr='')
    core._reviewed_shadow_lineage_preflight(review, env={
        'SENTINEL_DATABASE_URL': 'postgresql://local/test', 'ALPACA_API_KEY': 'key',
        'ALPACA_SECRET_KEY': 'secret', 'SENTINEL_PAPER_ACCOUNT_ID': 'account'}, invoke=invoke)


@pytest.mark.parametrize('change', ['id', 'revision', 'repo_digest', 'config'])
def test_signed_registry_binding_rejects_drift(monkeypatch, change):
    monkeypatch.setattr(ci.verifier, 'verify_current', lambda **kw: certificate())
    record = image()
    if change == 'id':
        record['Id'] = LENS
    elif change == 'revision':
        record['Config']['Labels']['org.opencontainers.image.revision'] = 'e' * 40
    elif change == 'repo_digest':
        record['RepoDigests'] = []
    else:
        record['Config'] = ['malformed']
    with pytest.raises(ci.CertifiedInstallRefused, match='differs'):
        ci.verify_reviewed_runtime(reviewed(), env={}, invoke=Commands(record=record), root=ROOT)


@pytest.mark.parametrize('field,value', [('source_commit', 'e' * 40),
    ('software_certification', 'UNVERIFIED'), ('required_ci_jobs', 'FAIL'),
    ('image_digest', 'sha256:' + 'Z' * 64)])
def test_certificate_result_cannot_weaken_binding(monkeypatch, field, value):
    result = certificate()
    result[field] = value
    monkeypatch.setattr(ci.verifier, 'verify_current', lambda **kw: result)
    with pytest.raises(ci.CertifiedInstallRefused, match='malformed'):
        ci.verify_reviewed_runtime(reviewed(), env={}, invoke=Commands(), root=ROOT)


def test_local_full_lens_retains_runtime_prefix_requirement():
    core.verify_reviewed_validation_environment(
        reviewed(lens=LENS), env={}, invoke=Commands(lens_layers=['runtime-layer', 'tool-layer']))
    with pytest.raises(core.DeployRefused, match='not layered'):
        core.verify_reviewed_validation_environment(
            reviewed(lens=LENS), env={}, invoke=Commands(lens_layers=['unrelated-layer']))


def test_auxiliary_alias_is_still_rejected():
    with pytest.raises(core.DeployRefused, match='auxiliary.*not distinct'):
        core.verify_reviewed_validation_environment(
            reviewed(auxiliary=(RUNTIME,)), env={}, invoke=Commands())


def test_single_runtime_selection_never_builds_tests_or_pushes(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, 'verify_reviewed_runtime', lambda *a, **kw: certificate())
    deployment = object.__new__(bootstrap.BootstrapDeploy)
    deployment.reviewed_validation = reviewed()
    deployment.cfg = SimpleNamespace(runtime_repository=REFERENCE.split('@')[0],
                                      test_repository='unused', authority_dir=tmp_path)
    deployment.commit = COMMIT
    deployment.env = {}
    deployment.runner = SimpleNamespace(env={})
    deployment.attempt_dir = tmp_path
    deployment.phase = lambda detail: None
    deployment.resolve_compose = lambda: None
    checked = []
    deployment._verify_signing_key_is_trusted = lambda: checked.append('key')
    deployment.build_promote()
    assert checked == ['key']
    assert deployment.runtime_repo_digest == deployment.test_repo_digest == REFERENCE
    assert deployment.runtime_digest == deployment.test_digest == RUNTIME
    assert deployment.env['SENTINEL_RUNTIME_IMAGE_REF'] == REFERENCE
    assert json.loads((tmp_path / 'ci-certified-runtime.json').read_text()) == certificate()


def test_offline_issuer_uses_one_runtime_and_readonly_tools(monkeypatch):
    deployment = object.__new__(core.AutonomousDeploy)
    deployment._ci_single_runtime = True
    deployment.runtime_repo_digest = REFERENCE
    monkeypatch.setattr(os, 'getuid', lambda: 1234, raising=False)
    monkeypatch.setattr(os, 'getgid', lambda: 5678, raising=False)
    command = deployment._offline_tool_argv(
        ['type=bind,src=/private/key,dst=/signing-key,readonly'],
        ['-m', 'tools.sentinel_certificate_issuer', 'issue'])
    assert command[:5] == ['docker', 'run', '--rm', '--network', 'none']
    assert command[command.index('--user') + 1] == '1234:5678'
    assert f'type=bind,src={core.ROOT / "tools"},dst=/app/tools,readonly' in command
    assert command[command.index('--entrypoint') + 2] == REFERENCE
    assert not any(value in command for value in ['-e', '--env', '--env-file'])
