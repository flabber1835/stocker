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
def test_production_readers_receive_selected_certified_identity(monkeypatch, phased, installed_contract):
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
            assert forwarded == ['SENTINEL_GIT_COMMIT', 'SENTINEL_RUNTIME_IMAGE_DIGEST']
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
    run = controller.run_phased_probes if phased else go.run_production_probes
    result = run(runner=Runner(), env=env, now=NOW)
    assert result.gates['sharadar_readiness'].status == go.PASS
    assert result.gates['database_financial_health'].status == go.PASS
    assert children == [go._READINESS_CODE, go._DATABASE_HEALTH_CODE]
    assert result.production_db_writes == result.broker_mutation_attempts == 0
    if installed_contract:
        assert len(startup_checks) >= 3
