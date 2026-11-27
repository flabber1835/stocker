from __future__ import annotations

from sentinel import archive_identifiers as archive_ids

from contextlib import contextmanager
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
DRIVER = SCRIPTS / "sentinel_autonomous_deploy_driver.py"
sys.path.insert(0, str(SCRIPTS))
core = importlib.import_module("sentinel_autonomous_deploy")
driver = importlib.import_module("sentinel_autonomous_deploy_driver")


@pytest.fixture(autouse=True)
def offline_activation_read_owner(monkeypatch):
    import sentinel_activation_read as read_probe
    @contextmanager
    def owned(command):
        yield {'command': list(command)}
    monkeypatch.setattr(read_probe, 'owned_command', owned)


def _config_env(tmp_path, exposure="1", revoke="0"):
    key = tmp_path / "signing-key"
    key.write_text("fixture", encoding="utf-8")
    authority = tmp_path / "authority"
    return {
        "SENTINEL_DEPLOYMENT_ID": "sentinel-a",
        "SENTINEL_PAPER_ACCOUNT_ID": "PAPER-1",
        "SENTINEL_RUNTIME_IMAGE_REPOSITORY": "registry.example/sentinel",
        "SENTINEL_TEST_IMAGE_REPOSITORY": "registry.example/sentinel-test",
        "SENTINEL_DEPLOY_SIGNING_KEY_ID": "ed25519-sha256:" + "1" * 64,
        "SENTINEL_DEPLOY_SIGNING_KEY_FILE": str(key),
        "SENTINEL_AUTHORITY_ARTIFACTS_DIR": str(authority),
        "SENTINEL_POSTGRES_PASSWORD": "db#password",
        "SENTINEL_BACKUP_DIR": str(tmp_path / "backup"),
        "ALPACA_API_KEY": "paper-key",
        "ALPACA_SECRET_KEY": "paper-secret",
        archive_ids.RETIRED_CREDENTIAL: 'archive_tables',
        "ALPACA_BASE_URL": core.PAPER_URL,
        "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE": exposure,
        "SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY": revoke,
    }


@pytest.mark.parametrize("value", ["1.0", "0.0", "00", ".5", "0.500"])
def test_config_refuses_noncanonical_exposure_before_deployment(tmp_path, value):
    with pytest.raises(core.DeployRefused, match="canonical"):
        driver.Config(_config_env(tmp_path, exposure=value))


@pytest.mark.parametrize("value", ["0", "1", "0.5", "0.0001", "0.999999999999999999"])
def test_config_accepts_canonical_exposure(tmp_path, value):
    cfg = driver.Config(_config_env(tmp_path, exposure=value, revoke="1"))
    assert cfg.max_exposure == value
    assert cfg.revoke_previous_signing_key is True


def test_data_wait_defaults_are_bounded_and_operator_overridable(tmp_path):
    cfg = driver.Config(_config_env(tmp_path))
    assert cfg.data_retry_seconds == 300
    assert cfg.data_wait_timeout_seconds == 43200

    env = _config_env(tmp_path)
    env["SENTINEL_DEPLOY_DATA_RETRY_SECONDS"] = "45"
    env["SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS"] = "600"
    cfg = driver.Config(env)
    assert cfg.data_retry_seconds == 45
    assert cfg.data_wait_timeout_seconds == 600


def test_deployment_requires_only_the_current_provider(tmp_path):
    env = _config_env(tmp_path)
    env.pop(archive_ids.RETIRED_CREDENTIAL)
    assert driver.Config(env).account_id == 'PAPER-1'
    for name in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY'):
        missing = dict(env)
        missing.pop(name)
        with pytest.raises(core.DeployRefused, match=name):
            driver.Config(missing)


def test_shipped_wait_settings_agree_with_actual_driver(tmp_path):
    import sentinel_env
    env = _config_env(tmp_path)
    example = sentinel_env.load(ROOT / '.env.example')
    for key in ('SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS', 'SENTINEL_DEPLOY_FORMATION_TIMEOUT_SECONDS'):
        if key in example:
            env[key] = example[key]
    env.update(SENTINEL_POSTGRES_PASSWORD='synthetic-database-password',
               SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL='https://alerts.example.test/sentinel')
    sentinel_env.validate(env, profile='install', target='DUAL_RUN_OBSERVATION')
    cfg = driver.Config(env)
    assert cfg.data_wait_timeout_seconds == 43200
    assert cfg.formation_timeout_seconds == 7200
    env['SENTINEL_DEPLOY_FORMATION_TIMEOUT_SECONDS'] = '30'
    sentinel_env.validate(env, profile='install', target='DUAL_RUN_OBSERVATION')
    cfg = driver.Config(env)
    assert cfg.data_wait_timeout_seconds == 43200 and cfg.formation_timeout_seconds == 30


@pytest.mark.parametrize('elapsed,expired', [(31.0, False), (43201.0, True)])
def test_driver_attestation_wait_retains_bounded_next_decision_budget(
        tmp_path, monkeypatch, elapsed, expired):
    env = _config_env(tmp_path)
    env.update(SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS='43200',
               SENTINEL_DEPLOY_FORMATION_TIMEOUT_SECONDS='30')
    obj = object.__new__(driver.AutonomousDeploy)
    obj.cfg = driver.Config(env)
    obj.phase = lambda message: None
    obj._authorized_compose = lambda: ['docker', 'compose']
    clock = [0.0]

    def status(*args, **kwargs):
        assert 0 < kwargs['timeout'] <= 300
        clock[0] = elapsed
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'mode': 'BROKER_FREE_SHADOW', 'broker_mutations_authorized': False,
            'session': '2026-08-28', 'verification': 'VERIFIED', 'shadow_verdict': 'SHADOW_GO'}))

    obj.runner = SimpleNamespace(run=status)
    monkeypatch.setattr(core.time, 'monotonic', lambda: clock[0])
    if expired:
        with pytest.raises(core.ActivationPending, match='deadline'):
            obj._wait_for_dual_shadow_session('2026-08-28')
    else:
        assert obj._wait_for_dual_shadow_session('2026-08-28')['session'] == '2026-08-28'


def _deploy_for_wait(tmp_path):
    cfg = SimpleNamespace(
        data_retry_seconds=30,
        data_wait_timeout_seconds=300,
    )
    obj = driver.AutonomousDeploy(cfg, SimpleNamespace(env={}), tmp_path)
    obj.commit = "a" * 40
    obj.base_compose = ["docker", "compose", "-f", "base.yml"]
    obj.phase = lambda _text: None
    return obj


def test_readiness_probe_requires_complete_retained_runtime_identity(tmp_path, monkeypatch):
    """The real readiness entry must pass the identity its signed child checks."""
    from sentinel import local_paper
    from sentinel.authority.model import AuthorityRefused

    obj = _deploy_for_wait(tmp_path)
    image = 'sha256:' + 'b' * 64
    obj.runtime_digest = image
    obj.test_digest = image
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', obj.commit)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', image)
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', obj.commit)
    calls = []

    def signed_reader(command, **_kwargs):
        calls.append(list(command))
        forwarded = [command[index + 1] for index, item in enumerate(command[:-1])
                     if item == '--env']
        values = dict(item.split('=', 1) for item in forwarded)
        local_paper.validate_runtime_identity({'deployment_artifacts': {
            'schema': 'sentinel.runtime-artifacts/1',
            'git_commit': values.get('SENTINEL_GIT_COMMIT'),
            'runtime_image_digest': values.get('SENTINEL_RUNTIME_IMAGE_DIGEST'),
            'test_image_digest': values.get('SENTINEL_TEST_IMAGE_DIGEST'),
        }})
        assert forwarded.count('SENTINEL_TEST_IMAGE_DIGEST=' + image) == 1
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            'ready': True, 'rolling': True,
            'checks': [{'name': 'rolling source', 'status': 'PASS'}],
            'failures': [],
        }))

    obj.runner.run = signed_reader
    assert obj._readiness_verdict()['ready'] is True
    assert len(calls) == 1

    # Falsify the specific missing-field failure seen in the installed release.
    complete_args = obj._retained_reader_args

    def without_test_image():
        args = complete_args()
        index = args.index('SENTINEL_TEST_IMAGE_DIGEST=' + image)
        return args[:index - 1] + args[index + 1:]
    monkeypatch.setattr(obj, '_retained_reader_args', without_test_image)
    with pytest.raises(AuthorityRefused, match='test image digest'):
        obj._readiness_verdict()
    assert len(calls) == 2


def test_retained_data_and_plan_readers_share_one_test_image(tmp_path):
    obj = _deploy_for_wait(tmp_path)
    image = 'sha256:' + 'b' * 64
    obj.runtime_digest = image
    obj.test_digest = image
    obj.reviewed_validation = None
    calls = []
    obj.runner.run = lambda command, **_kwargs: (calls.append(list(command)) or
        SimpleNamespace(returncode=0, stderr='', stdout='{}'))

    obj._base_cli(['check-data'])
    obj._base_cli(['current-paper-plan'])
    assert len(calls) == 2
    for command in calls:
        assert command.count('SENTINEL_TEST_IMAGE_DIGEST=' + image) == 1


@pytest.mark.parametrize('test_image', [None, 'sha256:bad'])
def test_retained_readers_refuse_missing_test_image_before_child(tmp_path, test_image):
    obj = _deploy_for_wait(tmp_path)
    obj.runtime_digest = 'sha256:' + 'b' * 64
    obj.test_digest = test_image
    obj.runner.run = lambda *_a, **_k: pytest.fail('unbound child was launched')

    with pytest.raises(core.DeployRefused, match='selected commit'):
        obj._readiness_verdict()


def _freshness_failure(detail="missing latest closed session",
                       missing=None):
    missing = list(missing or ["2026-08-17"])
    freshness = {
        "name": "freshness",
        "status": "FAIL",
        "detail": detail,
        "value": {
            "evaluable": True,
            "ahead": False,
            "expected_session": missing[-1],
            "frontier": "2026-08-14",
            "missing_sessions": missing,
        },
    }
    return {
        "ready": False,
        "checks": [
            {
                "name": "frontier population",
                "status": "PASS",
                "detail": "healthy prior frontier",
                "value": {
                    "frontier": 6000,
                    "minimum": 5000,
                    "recent_median": 6300.0,
                },
            },
            freshness,
        ],
        "failures": [freshness],
    }


def _ready_verdict():
    return {"ready": True, "checks": [], "failures": []}


def _probe(ready, count=0, sessions=None, ticker_rows=6000):
    sessions = list(sessions or ["2026-08-17"])
    return {
        "ready": ready,
        "minimum_resolved_positive_securities": 5000,
        "vendor_ticker_rows_total": 50000,
        "vendor_sep_ticker_rows_reaching_window": ticker_rows,
        "sep_resolved_positive_securities": {
            session: count for session in sessions},
        "spy_sessions": list(sessions) if ready else [],
    }


def test_deployed_installer_refuses_legacy_before_vendor_probe(tmp_path):
    obj = _deploy_for_wait(tmp_path)
    obj._operational_source_only = True
    obj._assert_wait_fence = lambda: None
    obj._readiness_verdict = lambda: _freshness_failure()
    obj._base_cli = lambda *_: pytest.fail("legacy data reached the CLI")
    with pytest.raises(core.DeployRefused, match="requires rolling Alpaca"):
        obj.refresh_data()



def test_deployed_installer_requires_ready_rolling_go_without_ingest(tmp_path):
    obj = _deploy_for_wait(tmp_path)
    obj._operational_source_only = True
    obj._assert_wait_fence = lambda: None
    stale = {"rolling": True, "ready": False, "failures": [
        {"name": "rolling source-final frontier", "status": "FAIL"}]}
    obj._readiness_verdict = lambda: stale
    obj._refuse_data_readiness = lambda *_a, **_k: (_ for _ in ()).throw(
        core.DeployRefused("run GO again"))
    commands = []
    obj._base_cli = lambda args, **_k: commands.append(args)
    obj.runner.run = lambda args: commands.append(args)
    obj._write_deployment_state = lambda *args, **kwargs: commands.append(
        ["state", args[0]])
    with pytest.raises(core.DeployRefused, match="run GO again"):
        obj.refresh_data()
    assert commands == []
    obj._readiness_verdict = lambda: {"rolling": True, "ready": True,
                                      "failures": []}
    obj.refresh_data()
    assert commands == [["check-data"],
                        obj.base_compose + ["up", "-d", "sentinel-panel"],
                        ["state", "DATA_READY"]]


def test_pre_authority_recheck_refuses_source_change_before_rotation(tmp_path):
    obj = _deploy_for_wait(tmp_path)
    obj._readiness_verdict = _freshness_failure
    obj._base_cli = lambda *a, **k: None
    obj._write_deployment_state = lambda *args, **kwargs: None
    with pytest.raises(core.DeployRefused, match="readiness changed"):
        obj.rotate_observation_authority()


def test_execution_generation_advances_past_abandoned_staged_certificate(tmp_path):
    obj = driver.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    payload = {
        "highest_issuer_generation": 8,
        "active_certificate_sha256": "a" * 64,
        "max_installed_issuer_generation": 11,
        "active_key_id": "old-key",
    }
    completed = SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    class Runner:
        env = {}
        def run(self, *_args, **_kwargs):
            return completed

    obj.runner = Runner()
    obj.base_compose = ["docker", "compose", "-f", "base.yml"]
    obj.automation_overlay = "automation.yml"

    state = obj._execution_authority_state()

    assert state["highest_issuer_generation"] == 8
    source = DRIVER.read_text(encoding="utf-8")
    assert "MAX(issuer_generation)" in source
    assert "max(highest,installed)" in source
    assert obj.predecessor_key_id == "old-key"


def test_admin_generation_uses_max_installed_and_confirms_active_predecessor(tmp_path):
    source = DRIVER.read_text(encoding="utf-8")
    assert "max_installed_issuer_generation" in source
    assert "--confirm-supersedes-certificate-sha256" in source
    assert "empty-binding candidate predecessor differs" in source


def test_private_key_is_proved_before_transition_using_network_none(tmp_path):
    source = DRIVER.read_text(encoding="utf-8")
    assert "configured private key does not match key id" in source
    assert "configured signing key is not an ACTIVE trust root" in source
    assert '"--network", "none"' in source
    assert "dst=/signing-key,readonly" in source


def test_plan_reread_mismatch_refuses_before_automation_activation(tmp_path):
    obj = driver.AutonomousDeploy(
        SimpleNamespace(account_id="PAPER-1", deployment_id="sentinel-a",
                        actor="deploy"),
        SimpleNamespace(env={}), tmp_path)
    calls = []

    def authorized(args, *, capture=False, check=True):
        calls.append(list(args))
        if args[0] == "prepare-paper-plan":
            return SimpleNamespace(
                stdout=json.dumps({"plan": {
                    "plan_id": "prepared", "decision_session": "2026-08-14"}}),
                stderr="", returncode=0)
        raise AssertionError("automation command must not be reached")

    def base(args, *, capture=False, check=True):
        assert args == ["current-paper-plan"]
        return SimpleNamespace(
            stdout=json.dumps({
                "database_authorities_match": True,
                "plan": {"plan_id": "different", "decision_session": "2026-08-14"},
            }), stderr="", returncode=0)

    obj._authorized_cli = authorized
    obj._base_cli = base
    obj.quiesce_activation_writers = lambda: None  # Dedicated handoff tests own process checks.

    with pytest.raises(core.DeployRefused, match="exact plan"):
        obj.prepare_activate_start("c" * 64, "2026-08-14")
    assert [call[0] for call in calls] == ["prepare-paper-plan"]


@pytest.mark.parametrize("reconciliation_passes", [True, False])
@pytest.mark.parametrize('backup_ready', [True, False])
def test_public_dual_activation_reconciles_before_enabling_automation(
        tmp_path, reconciliation_passes, backup_ready):
    import sentinel_autonomous_deploy_bootstrap as bootstrap
    obj = bootstrap.BootstrapDeploy(
        SimpleNamespace(account_id="PAPER-1", deployment_id="fixture", actor="test"),
        SimpleNamespace(env={}), tmp_path,
        reviewed_validation=SimpleNamespace(mode="dual"))
    events = []
    from tests.sentinel.test_activation_completion_protocol import prepared_plan, activation_read
    plan = prepared_plan('2026-08-14', '2026-08-17')
    def cli(args, **kwargs):
        events.append(args[0])
        if '--for-dual-activation' in args:
            payload = activation_read(plan, verdict='MATCH' if reconciliation_passes else 'MISMATCH')
            return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=0)
        return SimpleNamespace(stdout=json.dumps(plan), stderr="", returncode=0)
    obj._authorized_cli = obj._base_cli = cli
    obj.quiesce_activation_writers = lambda: None
    obj._require_activation_writers_stopped = lambda: None
    obj.start_activated_runtime = lambda *a: events.append("resume-runtime")
    obj._authorized_compose = lambda: ["docker", "compose"]
    obj.runner.run = lambda *a, **k: events.append("start-service")
    obj._automation_status = lambda: {
        "enabled": True, "kill_switch_engaged": True,
        "certificate_sha256": "certificate"}
    obj.verify_operator_services = lambda: events.append("verify-services")
    def recovery():
        events.append('verify-recovery')
        if not backup_ready:
            raise core.DeployRefused('restore qualification refused')
        return '/backups/base/base-20261007T060000Z'
    obj._post_deploy_backup = recovery
    obj._verify_dual_plan_shadow_reconciliation = lambda: pytest.fail("duplicate pre-enable proof")
    if reconciliation_passes and backup_ready:
        obj.prepare_activate_start("certificate", "2026-08-14")
        assert events == ["prepare-paper-plan", "current-paper-plan",
            "activate-paper-automation",
            "verify-services", 'verify-recovery', "release-paper-automation-kill-switch", "resume-runtime"]
    else:
        with pytest.raises(core.DeployRefused, match="certified shadow intent|restore qualification refused"):
            obj.prepare_activate_start("certificate", "2026-08-14")
        if not reconciliation_passes:
            assert events == ["prepare-paper-plan", "current-paper-plan"]
        else:
            assert events == ['prepare-paper-plan', 'current-paper-plan',
                'activate-paper-automation', 'verify-services', 'verify-recovery']
        assert 'release-paper-automation-kill-switch' not in events


def test_optional_key_rotation_revokes_only_different_predecessor_after_rotation(tmp_path):
    obj = driver.AutonomousDeploy(
        SimpleNamespace(
            revoke_previous_signing_key=True,
            signing_key_id="new-key"),
        SimpleNamespace(env={}), tmp_path)
    obj.predecessor_key_id = "old-key"
    obj._readiness_verdict = lambda: _ready_verdict()
    events = []
    obj.phase = lambda text: events.append(("phase", text))
    obj._authorized_cli = lambda args, **kwargs: events.append(("cli", list(args)))

    original = core.AutonomousDeploy.rotate_observation_authority
    try:
        core.AutonomousDeploy.rotate_observation_authority = (
            lambda self: ("c" * 64, "2026-08-14"))
        result = obj.rotate_observation_authority()
    finally:
        core.AutonomousDeploy.rotate_observation_authority = original

    assert result == ("c" * 64, "2026-08-14")
    revoke = [e for e in events if e[0] == "cli"]
    assert len(revoke) == 1
    assert revoke[0][1][:3] == ["revoke-system-key", "--key-id", "old-key"]


@pytest.mark.parametrize("argv,mode", [
    ([], None),
    (["--mode", "shadow"], "shadow"),
    (["--mode=dual", "--ticket", "fixture-ticket"], "dual"),
    (["--mode", "paper"], "paper"),
])
def test_launcher_entry_delegates_to_software_installation_only(
        monkeypatch, argv, mode):
    launcher = SCRIPTS / "sentinel-autonomous-deploy.sh"
    source = launcher.read_text(encoding="utf-8")
    assert 'exec "$PYTHON" scripts/sentinel_autonomous_deploy_entry.py "$@"' in source

    import sentinel_autonomous_deploy_entry as entry

    calls = []
    import sentinel_activation_roles as roles
    monkeypatch.setattr(roles, 'activation_types', lambda _mode: pytest.fail('financial role during installation'))

    def bootstrap_main(forwarded):
        assert forwarded is argv
        calls.append(("installation", forwarded))
        return 77

    import sentinel_installation_phase as installation
    monkeypatch.setattr(installation, "main", bootstrap_main)
    assert entry.main(argv) == 77
    assert calls == [("installation", argv)]
