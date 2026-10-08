"""Exercise production orchestration through the actual read-only launchers."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_go_phase_controller as controller

go = controller.go
COMMIT = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
IDENTITY = 'c' * 64
NOW = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize('phased', [False, True], ids=['core', 'supported-phase'])
@pytest.mark.parametrize('installed_contract', [False, True], ids=['direct', 'installed-adapter'])
@pytest.mark.parametrize('nondefault_book', [False, True], ids=['default-book', 'configured-book'])
def test_production_readers_receive_selected_certified_identity(monkeypatch, phased, installed_contract, nondefault_book):
    """Ambient identity must not replace the Git/certification observations."""
    gate = lambda name: go.make_gate(name, go.PASS, go._utc_text(NOW), {'fixture': True})
    tests = go.TestSummary(IMAGE, IMAGE, IDENTITY, passed=1, exit_code=0,
        suites_completed=3, non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS)
    preparation = go.PreparationSummary(go.PASS, IMAGE, True, True, 0, 'd' * 64,
                                       elapsed_milliseconds=1000)
    monkeypatch.setattr(go, 'probe_git', lambda *_a, **_k:
                        (go.GitIdentity(COMMIT, True, True, COMMIT), gate('git_identity')))
    monkeypatch.setattr(go, 'probe_certified_suite', lambda *_a, **_k:
                        (tests, gate('certified_suite_no_skips')))
    monkeypatch.setattr(controller, '_certify_exact_artifacts', lambda *_a, **_k:
                        (tests, gate('certified_suite_no_skips')))
    monkeypatch.setattr(go, 'probe_prevalidation_preparation', lambda *_a, **_k: preparation)
    monkeypatch.setattr(controller.entry, 'probe_prevalidation_preparation',
                        lambda *_a, **_k: preparation)
    def parity(*_a, **kw):
        kw['timing_values']['full_forward_decision_replay'] = 1000
        return gate('wealth_core_nas_parity')
    monkeypatch.setattr(go, 'probe_active_wealth_parity', parity)
    monkeypatch.setattr(go, 'probe_alpaca_account', lambda **_k:
                        (gate('alpaca_paper_account'), {}))
    monkeypatch.setattr(go, 'shadow_configuration_sha256', lambda *_a, **_k: 'e' * 64)
    monkeypatch.setattr(controller, '_actual_remaining_ms', lambda *_a, **_k: 60_000)
    startup_checks = []
    if installed_contract:
        import sentinel_go_probe_contract as contract
        # Track every install mutation so the real wrappers cannot leak into
        # later tests. Keep the production reader implementations underneath.
        for name in ('probe_sharadar_readiness', 'probe_database_financial_health'):
            monkeypatch.setattr(go, name, getattr(go, name))
        monkeypatch.setattr(controller, '_classify_preparation_failure',
                            controller._classify_preparation_failure)
        monkeypatch.setattr(controller, contract._INSTALLED_MARKER, False, raising=False)
        monkeypatch.setattr(contract, 'ensure_postgres_ready', lambda *_a, **_k:
                            (startup_checks.append('healthy') or None))
        contract.install(controller=controller,
                         phase=SimpleNamespace(_PHASE={'certified': True, 'prepared': True}))
    children = []
    class Runner:
        last_preparation_output = ''
        def run(self, argv, *, env=None, **_kwargs):
            if argv[0] == 'bash':
                return subprocess.CompletedProcess(argv, 0, stdout='-f compose.yml', stderr='')
            assert env['SENTINEL_GIT_COMMIT'] == COMMIT
            assert env['SENTINEL_RUNTIME_IMAGE_DIGEST'] == IMAGE
            assert env['SENTINEL_RUNTIME_IMAGE_REF'] == IMAGE
            assert not set(env) & go._BROKER_AUTH_ENV
            forwarded = [argv[index + 1] for index, part in enumerate(argv) if part == '--env']
            expected = ['SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST']
            if nondefault_book:
                expected += ['SENTINEL_SHADOW_OBSERVATION_ID', 'SENTINEL_SHADOW_STARTING_CASH']
                assert env['SENTINEL_SHADOW_OBSERVATION_ID'] == 'configured-book'
                assert env['SENTINEL_SHADOW_STARTING_CASH'] == '123456.78'
            assert forwarded == expected
            code = argv[-1]
            children.append(code)
            if code == go._READINESS_CODE:
                marker = 'SENTINEL_GO_READINESS='
                payload = dict(transaction_read_only=True, ready=True,
                               checks_total=14, checks_passed=14, failures=0)
            else:
                assert code == go._DATABASE_HEALTH_CODE
                marker = 'SENTINEL_GO_DATABASE_HEALTH='
                payload = dict(checks={key: True for key in go.DATABASE_CHECK_IDS},
                    publication_versions=1, publication_chain_gaps=0,
                    duplicate_publication_run_ids=0, recent_xnys_sessions=252,
                    frontier_security_rows=1, frontier_duplicate_security_keys=0,
                    warmup_revision_sessions=252, warmup_revision_scan_ms=1,
                    source_final_to_following_open_ms=35_100_000, transaction_db_writes=0)
            return subprocess.CompletedProcess(argv, 0, stdout=marker + json.dumps(payload), stderr='')
    env = dict(ALPACA_API_KEY='must-not-forward', ALPACA_SECRET_KEY='must-not-forward',
        SENTINEL_PAPER_ACCOUNT_ID='must-not-forward', SENTINEL_POSTGRES_PASSWORD='fixture',
        SENTINEL_GIT_COMMIT='f' * 40, SENTINEL_RUNTIME_IMAGE_DIGEST='sha256:' + 'f' * 64)
    if nondefault_book:
        env.update(SENTINEL_SHADOW_OBSERVATION_ID='configured-book',
                   SENTINEL_SHADOW_STARTING_CASH='123456.78')
    run = controller.run_phased_probes if phased else go.run_production_probes
    result = run(runner=Runner(), env=env, now=NOW)
    assert result.gates['sharadar_readiness'].status == go.PASS
    assert result.gates['database_financial_health'].status == go.PASS
    assert children == [go._READINESS_CODE, go._DATABASE_HEALTH_CODE]
    assert result.production_db_writes == result.broker_mutation_attempts == 0
    if installed_contract:
        assert len(startup_checks) >= 3


@pytest.mark.parametrize('route', ['structured', 'check-data'])
def test_installer_readiness_binds_selected_runtime_and_book(monkeypatch, capsys, route):
    import sentinel_autonomous_deploy as core
    import sentinel_autonomous_deploy_driver as driver
    from sentinel.feed import store, readers, readiness
    from sentinel.cli import feed
    obj = object.__new__(driver.AutonomousDeploy)
    obj.commit, obj.runtime_digest = COMMIT, IMAGE
    obj.base_compose = ['docker', 'compose', '-f', 'compose.yml']
    obj.env = {'SENTINEL_GIT_COMMIT': 'f' * 40,
               'SENTINEL_RUNTIME_IMAGE_DIGEST': 'sha256:' + 'f' * 64,
               'ALPACA_API_KEY': 'must-not-forward', 'ALPACA_SECRET_KEY': 'must-not-forward',
               'SENTINEL_SHADOW_OBSERVATION_ID': 'configured-book',
               'SENTINEL_SHADOW_STARTING_CASH': '123456.78'}
    events = []
    class Conn:
        def rollback(self): events.append('rollback')
        def close(self): events.append('close')
    conn = Conn()
    monkeypatch.setattr(store, 'connect', lambda _: conn)
    monkeypatch.setattr(store, 'require_feed_schema', lambda _: None)
    monkeypatch.setattr(readers, 'current', lambda _: None)
    monkeypatch.setattr(readers, 'is_rolling', lambda _: False)
    def report(*_a, **_kw):
        assert os.environ['SENTINEL_GIT_COMMIT'] == COMMIT
        assert os.environ['SENTINEL_RUNTIME_IMAGE_DIGEST'] == IMAGE
        assert os.environ['SENTINEL_SHADOW_OBSERVATION_ID'] == 'configured-book'
        assert os.environ['SENTINEL_SHADOW_STARTING_CASH'] == '123456.78'
        return SimpleNamespace(ready=True, checks=[], failures=[])
    monkeypatch.setattr(readers, 'readiness', report)
    monkeypatch.setattr(readiness, 'save_snapshot', lambda *_a: events.append('snapshot'))
    calls = []
    def run(argv, **_kw):
        calls.append(argv)
        forwarded = dict(argv[i + 1].split('=', 1) for i, part in enumerate(argv) if part == '--env')
        assert set(forwarded) == {'SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST',
                                 'SENTINEL_SHADOW_OBSERVATION_ID', 'SENTINEL_SHADOW_STARTING_CASH'}
        with monkeypatch.context() as child:
            child.setattr(os, 'environ', dict(forwarded, SENTINEL_DATABASE_URL='fixture'))
            if route == 'structured':
                exec(argv[-1], {})
            else:
                assert argv[-1] == 'check-data'
                assert feed.cmd_check_data(SimpleNamespace(database_url='fixture'),
                                           SimpleNamespace(today=None)) == 0
        output = capsys.readouterr()
        return subprocess.CompletedProcess(argv, 0, stdout=output.out, stderr=output.err)
    obj.runner = SimpleNamespace(run=run)
    if route == 'structured':
        assert obj._readiness_verdict()['ready'] is True
    else:
        assert obj._base_cli(['check-data'], capture=True).returncode == 0
    assert len(calls) == 1 and events.count('snapshot') == 1
    assert obj.env['SENTINEL_GIT_COMMIT'] == 'f' * 40


@pytest.mark.parametrize('route', ['structured', 'check-data'])
@pytest.mark.parametrize('commit,digest', [(None, IMAGE), ('bad', IMAGE), (COMMIT, None), (COMMIT, 'latest')])
def test_installer_readiness_refuses_unselected_identity_before_launch(route, commit, digest):
    import sentinel_autonomous_deploy as core
    import sentinel_autonomous_deploy_driver as driver
    obj = object.__new__(driver.AutonomousDeploy)
    obj.commit, obj.runtime_digest, obj.env = commit, digest, {}
    obj.base_compose = ['docker', 'compose']
    obj.runner = SimpleNamespace(run=lambda *_a, **_k: pytest.fail('unbound child launched'))
    with pytest.raises(core.DeployRefused, match='selected commit'):
        obj._readiness_verdict() if route == 'structured' else obj._base_cli(['check-data'])
