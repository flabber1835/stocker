"""Exercise the installer adapters, not just their underlying reader helpers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_autonomous_deploy as deploy
import sentinel_autonomous_deploy_install_entry as install


def _causal_adapter(obj, monkeypatch, tmp_path, verifier):
    """Keep the real bounded/owned binding adapter; isolate financial probes."""
    timing = {'target': '2026-10-06', 'frontier': '2026-10-06',
              'execution_open_at': '2999-10-07T13:30:00+00:00',
              'remaining_ms': 60_000}
    obj._operational_source_only = True
    obj._causal_wait_deadline = time.monotonic() + 60
    obj._causal_timing = lambda: dict(timing)
    obj._data_timing_eligible = lambda _: True
    obj.attempt_dir = tmp_path
    obj.reviewed_validation.test_image_digest = obj.reviewed_validation.runtime_image_digest
    monkeypatch.setattr(install.go, 'probe_active_wealth_parity',
        lambda *_a, **kw: (kw['subject_values'].update(data_publication='publication-v1')
            or SimpleNamespace(status=install.go.PASS, evidence_sha256='1' * 64)))
    def readiness(*_a, **kw):
        assert kw.get('commit') == obj.reviewed_validation.git_commit
        assert kw['runtime_ref'] == obj.reviewed_validation.runtime_image_digest
        return SimpleNamespace(status=install.go.PASS, evidence_sha256='2' * 64)
    monkeypatch.setattr(install.go, 'probe_sharadar_readiness', readiness)
    monkeypatch.setattr(install, '_ORIGINAL_VERIFY', verifier)
    monkeypatch.setattr(install.bootstrap, '_safe_update_dotenv', lambda *_: None)
    monkeypatch.setenv('SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256', 'prior-process-value')
    return timing


@pytest.mark.parametrize('stage', ['preflight', 'quiesced', 'causal'])
@pytest.mark.parametrize('instant', [
    datetime(2026, 10, 6, 17, 30, tzinfo=timezone.utc),
    datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc),
    datetime(2026, 10, 4, 17, 30, tzinfo=timezone.utc),
])
def test_installer_runs_real_operational_shadow_preflight_during_market_hours(
        monkeypatch, tmp_path, stage, instant, capsys):
    from sentinel import shadow_service as shadow
    from sentinel.feed import operational_snapshot, readers
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant
    monkeypatch.setattr(shadow, 'datetime', Clock)
    calls = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql): calls.append(sql)
    class Conn:
        def cursor(self): return Cursor()
        def rollback(self): calls.append('rollback')
        def close(self): calls.append('close')
    conn = Conn()
    monkeypatch.setattr(shadow.feed_store, 'connect', lambda _: conn)
    monkeypatch.setattr(shadow.schema, 'require_runtime_schema', lambda _: None)
    monkeypatch.setattr(readers, 'current', lambda _: 'rolling-publication')
    monkeypatch.setattr(readers, 'is_rolling', lambda _: True)
    monkeypatch.setattr(operational_snapshot, 'require_alpaca_openfigi',
                        lambda *_: calls.append('provider-verified'))
    monkeypatch.setattr(shadow.shadow_runtime, 'classify_shadow_lineage',
                        lambda *_a, **_kw: {'status': 'NOT_STARTED'})
    monkeypatch.setattr(shadow, 'advance_once', lambda *_: pytest.fail('financial advance'))
    monkeypatch.setattr(shadow, 'run', lambda *_: pytest.fail('worker started'))
    bundle = tmp_path / 'review.zip'
    bundle.write_bytes(b'reviewed-fixture')
    review = SimpleNamespace(path=bundle,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(), git_commit='b' * 40,
        mode='dual', runtime_image_digest='sha256:' + 'c' * 64,
        source_identity_sha256='d' * 64, shadow_configuration_sha256='e' * 64,
        data_publication_sha256='f' * 64)
    env = {'ALPACA_API_KEY': 'must-not-forward', 'ALPACA_SECRET_KEY': 'must-not-forward',
           'SENTINEL_PAPER_ACCOUNT_ID': 'must-not-forward',
           'SENTINEL_DATABASE_URL': 'postgresql://local/test'}
    obj = object.__new__(install.InstallAnytimeDeploy if stage == 'causal' else deploy.AutonomousDeploy)
    obj.env = dict(env)
    obj.runner = deploy.Runner(env, tmp_path / 'log')
    obj.cfg = SimpleNamespace(account_id='must-not-forward')
    obj.commit = review.git_commit
    obj.reviewed_validation = review
    obj.phase = lambda _: None
    cleaned = []
    def invoke(argv, **kwargs):
        if argv[:2] == ['docker', 'rm']:
            cleaned.append(argv[-1])
            return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
        if argv[0] == 'bash':
            return subprocess.CompletedProcess(argv, 0, stdout='-f compose.yml', stderr='')
        child_env = kwargs['env']
        assert not set(child_env) & {'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_PAPER_ACCOUNT_ID'}
        # Run the real CLI, provider check, read-only transaction and clock gate,
        # rather than fabricate a successful subprocess response.
        with monkeypatch.context() as patch:
            patch.setattr(shadow.os, 'environ', dict(child_env))
            code = shadow.main(argv[argv.index('sentinel.shadow_service') + 1:])
        output = capsys.readouterr()
        assert code == 0, output.err
        return subprocess.CompletedProcess(argv, code, stdout=output.out, stderr=output.err)
    monkeypatch.setattr(deploy.subprocess, 'run', invoke)
    def preflight(reviewed, *, env, invoke):
        deploy._reviewed_shadow_lineage_preflight(reviewed, env=env, invoke=invoke)
    monkeypatch.setattr(deploy, 'verify_reviewed_validation_environment', preflight)
    monkeypatch.setattr(deploy, 'verify_reviewed_shadow_bindings', preflight)
    monkeypatch.setattr(deploy, 'verify_reviewed_account_binding', lambda *_: None)
    if stage == 'preflight':
        obj.verify_reviewed_preflight()
    elif stage == 'quiesced':
        obj.verify_reviewed_shadow_bindings_quiesced()
    else:
        timing = _causal_adapter(obj, monkeypatch, tmp_path, preflight)
        obj._bind_current_publication(timing)
        assert len(cleaned) == 1 and cleaned[0].startswith('sentinel-go-owned-')
        env['SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256'] = review.data_publication_sha256
    assert calls == ['BEGIN TRANSACTION READ ONLY', 'provider-verified', 'rollback', 'close']
    assert obj.env == obj.runner.env == env


@pytest.mark.parametrize('stage', ['preflight', 'quiesced', 'causal'])
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
    obj = object.__new__(install.InstallAnytimeDeploy if stage == 'causal' else deploy.AutonomousDeploy)
    obj.env = dict(original)
    obj.runner = deploy.Runner(original, tmp_path / 'commands.log')
    obj.cfg = SimpleNamespace(account_id='fixture-account')
    obj.commit, obj.reviewed_validation = review.git_commit, review
    obj.phase = lambda _: None
    reads = []
    def command(argv, **kwargs):
        if argv[:2] == ['docker', 'rm']:
            return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
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
    elif stage == 'quiesced':
        obj.verify_reviewed_shadow_bindings_quiesced()
    else:
        timing = _causal_adapter(obj, monkeypatch, tmp_path, readers)
        obj._bind_current_publication(timing)
        original['SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256'] = review.data_publication_sha256
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


@pytest.mark.parametrize('outcome', ['refused', 'timeout', 'malformed'])
def test_causal_reader_failure_cleans_owned_container_and_restores_binding(
        monkeypatch, tmp_path, outcome):
    obj = object.__new__(install.InstallAnytimeDeploy)
    review = SimpleNamespace(mode='dual', git_commit='a' * 40,
        runtime_image_digest='sha256:' + 'b' * 64, source_identity_sha256='c' * 64,
        shadow_configuration_sha256='d' * 64, data_publication_sha256='e' * 64,
        bundle_sha256='f' * 64)
    original = {'ALPACA_API_KEY': 'fixture-key', 'ALPACA_SECRET_KEY': 'fixture-secret',
                'SENTINEL_PAPER_ACCOUNT_ID': 'fixture-account',
                'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256': 'prior-binding'}
    obj.env = dict(original)
    obj.runner = SimpleNamespace(env=dict(original))
    obj.reviewed_validation = review
    obj.cfg = SimpleNamespace(account_id='fixture-account')
    timing = _causal_adapter(obj, monkeypatch, tmp_path,
        lambda reviewed, *, env, invoke: deploy._reviewed_shadow_lineage_preflight(
            reviewed, env=env, invoke=invoke))
    monkeypatch.setattr(install.core, 'verify_reviewed_account_binding',
                        lambda *_: pytest.fail('binding after refused reader'))
    monkeypatch.setattr(install.bootstrap, '_safe_update_dotenv',
                        lambda *_: pytest.fail('persisted refused publication'))
    started, cleaned = [], []
    def command(argv, **kwargs):
        if argv[:2] == ['docker', 'rm']:
            cleaned.append(argv[-1])
            return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
        if argv[0] == 'bash':
            return subprocess.CompletedProcess(argv, 0, stdout='-f compose.yml', stderr='')
        assert 0 < kwargs['timeout'] <= 60
        assert not set(kwargs['env']) & {'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_PAPER_ACCOUNT_ID'}
        started.append(argv[argv.index('--name') + 1])
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        return subprocess.CompletedProcess(argv, 2 if outcome == 'refused' else 0,
            stdout='not JSON' if outcome == 'malformed' else '', stderr='reader refused')
    monkeypatch.setattr(install.subprocess, 'run', command)
    expected = install.CausalSessionExpired if outcome == 'timeout' else deploy.DeployRefused
    with pytest.raises(expected):
        obj._bind_current_publication(timing)
    assert started == cleaned and len(started) == 1
    assert obj.env == obj.runner.env == original
    assert review.data_publication_sha256 == 'e' * 64
    assert os.environ['SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256'] == 'prior-process-value'
    assert not (tmp_path / 'causal-publication-binding.json').exists()


@pytest.mark.parametrize('reader_env', [{}, None])
def test_causal_adapter_preserves_empty_environment_and_defaults_only_when_omitted(
        monkeypatch, tmp_path, reader_env):
    obj = object.__new__(install.InstallAnytimeDeploy)
    obj.env = {'SHOULD_NOT_REACH_EMPTY_CHILD': 'fixture'}
    obj.runner = SimpleNamespace(env=dict(obj.env))
    obj.reviewed_validation = SimpleNamespace(mode='dual', git_commit='a' * 40,
        runtime_image_digest='sha256:' + 'b' * 64, source_identity_sha256='c' * 64,
        data_publication_sha256=None, bundle_sha256='d' * 64)
    obj.cfg = SimpleNamespace(account_id='fixture-account')
    observed = []
    def verify(reviewed, *, env, invoke):
        invoke(['reader-probe'], env=reader_env)
    timing = _causal_adapter(obj, monkeypatch, tmp_path, verify)
    def command(argv, **kwargs):
        assert argv == ['reader-probe']
        observed.append(dict(kwargs['env']))
        return subprocess.CompletedProcess(argv, 0, stdout='{}', stderr='')
    monkeypatch.setattr(install.subprocess, 'run', command)
    monkeypatch.setattr(install.core, 'verify_reviewed_account_binding', lambda *_: None)
    obj._bind_current_publication(timing)
    assert observed == [obj.env if reader_env is None else {}]
