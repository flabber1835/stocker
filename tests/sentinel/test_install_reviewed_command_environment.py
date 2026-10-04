"""Exercise the installer adapters, not just their underlying reader helpers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_autonomous_deploy as deploy


@pytest.mark.parametrize('stage', ['preflight', 'quiesced'])
def test_real_installer_adapter_preserves_narrowed_reviewed_environment(tmp_path, monkeypatch, stage):
    bundle = tmp_path / 'review.zip'
    bundle.write_bytes(b'reviewed-fixture')
    review = SimpleNamespace(path=bundle, bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        git_commit='a' * 40, mode='dual', runtime_image_digest='sha256:' + 'b' * 64,
        source_identity_sha256='c' * 64, shadow_configuration_sha256='d' * 64,
        data_publication_sha256='e' * 64)
    original = {'ALPACA_API_KEY': 'fixture-key', 'ALPACA_SECRET_KEY': 'fixture-secret',
                'SENTINEL_PAPER_ACCOUNT_ID': 'fixture-account',
                'SENTINEL_RUNTIME_IMAGE_REF': 'stale:latest',
                'SENTINEL_DATABASE_URL': 'postgresql://local/test'}
    obj = object.__new__(deploy.AutonomousDeploy)
    obj.env = dict(original)
    obj.runner = deploy.Runner(original, tmp_path / 'commands.log')
    obj.cfg = SimpleNamespace(account_id='fixture-account')
    obj.commit, obj.reviewed_validation = review.git_commit, review
    obj.phase = lambda _: None
    reads = []
    def command(argv, **kwargs):
        assert kwargs['check'] is False
        assert kwargs['cwd'] == str(deploy.ROOT)
        if argv[0] == 'bash':
            output = '-f compose.yml'
        else:
            env = kwargs['env']
            assert env['SENTINEL_RUNTIME_IMAGE_REF'] == review.runtime_image_digest
            assert not set(env) & {'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_PAPER_ACCOUNT_ID'}
            reads.append(argv)
            if '--preflight' in argv:
                assert env['SENTINEL_SHADOW_OBSERVATION_ENABLED'] == '1'
                assert env['SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256'] == review.bundle_sha256
                assert env['SENTINEL_GIT_COMMIT'] == review.git_commit
                output = json.dumps({'schema': 'sentinel.shadow-service-preflight/1',
                    'mode': 'BROKER_FREE_SHADOW', 'status': 'NOT_STARTED',
                    'broker_mutations_authorized': False})
            else:
                output = 'SENTINEL_DEPLOY_DATA_BINDING=' + json.dumps({
                    'transaction_read_only': True, 'binding': {
                        'publication_fingerprint': 'f' * 64, 'visible_frontier': '2026-10-02'}})
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr='')
    monkeypatch.setattr(deploy.subprocess, 'run', command)
    def readers(reviewed, *, env, invoke):
        deploy._current_data_publication_subject(reviewed, env=env, invoke=invoke)
        deploy._reviewed_shadow_lineage_preflight(reviewed, env=env, invoke=invoke)
    monkeypatch.setattr(deploy, 'verify_reviewed_validation_environment', readers)
    monkeypatch.setattr(deploy, 'verify_reviewed_shadow_bindings', readers)
    monkeypatch.setattr(deploy, 'verify_reviewed_account_binding', lambda *args: None)
    if stage == 'preflight':
        obj.verify_reviewed_preflight()
    else:
        obj.verify_reviewed_shadow_bindings_quiesced()
    assert len(reads) == 2
    assert obj.env == obj.runner.env == original


@pytest.mark.parametrize('stream', [False, True])
def test_runner_empty_environment_is_not_replaced_by_shared_credentials(tmp_path, stream):
    runner = deploy.Runner({'SHOULD_NOT_REACH_CHILD': 'fixture'}, tmp_path / 'log')
    result = runner.run([sys.executable, '-c',
        "import os,sys; print(os.environ.get('SHOULD_NOT_REACH_CHILD','absent')); sys.exit(7)"],
        env={}, check=False, capture=True, stream=stream, timeout=5)
    assert result.returncode == 7 and result.stdout.strip() == 'absent'
    assert runner.env == {'SHOULD_NOT_REACH_CHILD': 'fixture'}
