from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


core = _load("sentinel_autonomous_deploy", SCRIPTS / "sentinel_autonomous_deploy.py")
driver = _load(
    "sentinel_autonomous_deploy_driver",
    SCRIPTS / "sentinel_autonomous_deploy_driver.py")
bootstrap = _load(
    "sentinel_autonomous_deploy_bootstrap",
    SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py")


def test_repository_parser_accepts_registry_refs_and_rejects_local_tags():
    assert bootstrap._repository_from_image(
        "ghcr.io/example/sentinel@sha256:" + "1" * 64
    ) == "ghcr.io/example/sentinel"
    assert bootstrap._repository_from_image(
        "registry.example:5000/team/sentinel:abc123"
    ) == "registry.example:5000/team/sentinel"
    assert bootstrap._repository_from_image("sentinel-authorized:latest") is None
    assert bootstrap._repository_from_image("") is None


def test_existing_owned_status_fills_missing_identity_without_overriding_conflict(
        monkeypatch, tmp_path):
    monkeypatch.setattr(
        bootstrap, "_existing_status",
        lambda _env: {
            "ownership": "OWNED", "broker": "alpaca",
            "deployment_id": "sentinel-nas-paper-01",
            "broker_account_id": "PA3UVTMJYYGM",
            "takeover_epoch": 1,
        })
    monkeypatch.setattr(
        bootstrap, "_existing_runtime_repository",
        lambda _env: "ghcr.io/example/sentinel")
    key = tmp_path / "key"
    key.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_signing_key_path", lambda _env: key)

    resolved = bootstrap.discover({})

    assert resolved["SENTINEL_DEPLOYMENT_ID"] == "sentinel-nas-paper-01"
    assert resolved["SENTINEL_PAPER_ACCOUNT_ID"] == "PA3UVTMJYYGM"
    assert resolved["SENTINEL_RUNTIME_IMAGE_REPOSITORY"] == "ghcr.io/example/sentinel"
    assert resolved["SENTINEL_TEST_IMAGE_REPOSITORY"] == "ghcr.io/example/sentinel-test"
    assert resolved["SENTINEL_DEPLOY_SIGNING_KEY_FILE"] == str(key)
    assert resolved["SENTINEL_DEPLOY_SIGNING_KEY_ID"] == "AUTO"

    with pytest.raises(core.DeployRefused, match="conflicts"):
        bootstrap.discover({"SENTINEL_DEPLOYMENT_ID": "wrong"})


def test_unknown_or_not_owned_status_never_invents_binding(monkeypatch):
    monkeypatch.setattr(
        bootstrap, "_existing_status",
        lambda _env: {"ownership": "NOT_OWNED"})
    monkeypatch.setattr(
        bootstrap, "_existing_runtime_repository", lambda _env: None)
    monkeypatch.setattr(bootstrap, "_signing_key_path", lambda _env: None)

    resolved = bootstrap.discover({})

    assert "SENTINEL_DEPLOYMENT_ID" not in resolved
    assert "SENTINEL_PAPER_ACCOUNT_ID" not in resolved
    assert resolved["SENTINEL_DEPLOY_SIGNING_KEY_ID"] == "AUTO"


def test_signing_key_auto_discovery_is_bounded_to_documented_locations(
        monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    arbitrary = tmp_path / "random-private-key"
    arbitrary.write_text("do not guess me", encoding="utf-8")
    assert bootstrap._signing_key_path({}) is None

    conventional = tmp_path / ".config" / "sentinel" / "signing-key.ed25519"
    conventional.parent.mkdir(parents=True)
    conventional.write_text("fixture", encoding="utf-8")
    assert bootstrap._signing_key_path({}) == conventional


def test_multiple_conventional_signing_keys_refuse_ambiguity(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    first = tmp_path / ".config" / "sentinel" / "signing-key.ed25519"
    second = tmp_path / ".sentinel" / "signing-key.pem"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    with pytest.raises(core.DeployRefused, match="multiple"):
        bootstrap._signing_key_path({})


def test_safe_dotenv_preserves_mode_and_collapses_managed_duplicates(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "ALPACA_SECRET_KEY=keep-me\n"
        "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:old-a\n"
        "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:old-b\n",
        encoding="utf-8")
    path.chmod(0o600)

    bootstrap._safe_update_dotenv(path, {
        "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "1" * 64,
        "SENTINEL_GIT_COMMIT": "a" * 40,
    })

    text = path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "ALPACA_SECRET_KEY=keep-me" in text
    assert text.count("SENTINEL_RUNTIME_IMAGE_DIGEST=") == 1
    assert "sha256:old-a" not in text and "sha256:old-b" not in text


@pytest.mark.parametrize("restore_drill", [False, True], ids=["pre-deploy", "post-deploy"])
def test_backup_checks_and_restore_use_the_exact_created_backup(tmp_path, restore_drill):
    calls = []
    exact = "/backups/base/base-20260817T120000Z"

    class Runner:
        env = {}
        def run(self, args, **kwargs):
            calls.append(list(args))
            if args[:2] == ["bash", "scripts/sentinel-install-backup.sh"]:
                return SimpleNamespace(
                    stdout="verified_installation_backup:" + exact + "\n",
                    stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    obj = bootstrap.BootstrapDeploy(SimpleNamespace(), Runner(), tmp_path)
    assert obj._create_backup(restore_drill=restore_drill) == exact
    assert calls == [["bash", "scripts/sentinel-install-backup.sh", '--restore',
                      'full' if restore_drill else 'physical']]


def test_promoted_runtime_becomes_the_ordinary_cli_image(monkeypatch, tmp_path):
    runner = SimpleNamespace(env={})
    obj = bootstrap.BootstrapDeploy(SimpleNamespace(), runner, tmp_path)

    def promoted(self):
        self.runtime_repo_digest = "ghcr.io/example/sentinel@sha256:" + "1" * 64

    monkeypatch.setattr(driver.AutonomousDeploy, "build_promote", promoted)
    obj.build_promote()

    assert obj.env["SENTINEL_RUNTIME_IMAGE_REF"] == obj.runtime_repo_digest
    assert runner.env["SENTINEL_RUNTIME_IMAGE_REF"] == obj.runtime_repo_digest


def test_bootstrap_key_verifier_accepts_auto_only_after_active_root_proof(tmp_path):
    cfg = SimpleNamespace(signing_key=tmp_path / "key", signing_key_id="AUTO")
    cfg.signing_key.write_text("fixture", encoding="utf-8")
    completed = SimpleNamespace(
        stdout="ed25519-sha256:" + "a" * 64 + "\n", stderr="", returncode=0)
    calls = []

    class Runner:
        env = {}
        def run(self, args, **kwargs):
            calls.append(list(args))
            return completed

    obj = bootstrap.BootstrapDeploy(cfg, Runner(), tmp_path)
    obj._verify_signing_key_is_trusted()

    assert cfg.signing_key_id == "ed25519-sha256:" + "a" * 64
    command = " ".join(calls[0])
    assert "--network none" in command
    assert "dst=/signing-key,readonly" in command
    source = (SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py").read_text(
        encoding="utf-8")
    assert "root.status == 'ACTIVE'" in source
    assert "requested in {'AUTO', actual}" in source


def test_bootstrap_does_not_persist_discovered_facts_before_final_pass(tmp_path):
    calls = []
    cfg = SimpleNamespace(
        deployment_id="sentinel-nas-paper-01",
        account_id="PA3UVTMJYYGM",
        runtime_repository="ghcr.io/example/sentinel",
        test_repository="ghcr.io/example/sentinel-test",
    )
    def storage_status(argv, **kwargs):
        assert argv == ['bash', 'scripts/sentinel-backup-status.sh']
        calls.append('backup-status')
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    obj = bootstrap.BootstrapDeploy(cfg, SimpleNamespace(env={}, run=storage_status), tmp_path)
    obj.commit = "a" * 40
    obj.runtime_digest = "sha256:" + "1" * 64
    obj.test_digest = "sha256:" + "2" * 64
    obj.runtime_repo_digest = cfg.runtime_repository + "@" + obj.runtime_digest
    obj.test_repo_digest = cfg.test_repository + "@" + obj.test_digest
    obj._post_deploy_backup = lambda: pytest.fail('financial restore inside installation')
    obj._persist_deploy_facts = lambda _updates: calls.append("persist")
    obj.verify_operator_services = lambda: calls.append("operator-verified")

    obj.persist_deployed({
        "enabled": False,
        "kill_switch_engaged": True,
        "operational_ready": False,
        "policy_state": "INERT",
    })

    assert calls == ["backup-status", "operator-verified", "persist"]


@pytest.mark.parametrize('mode', ['shadow', 'dual', 'paper', None])
@pytest.mark.parametrize('transport', ['push', 'webhook', 'unconfigured'])
def test_operator_services_start_and_verify_in_every_install_mode(tmp_path, mode, transport):
    calls = []
    env = ({'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY': 'configured'} if transport == 'push'
           else {'SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL': 'https://fixture.test'}
           if transport == 'webhook' else {})
    obj = bootstrap.BootstrapDeploy(SimpleNamespace(health_timeout=45),
        SimpleNamespace(env=env, run=lambda argv, **kw: calls.append((argv, kw))), tmp_path,
        reviewed_validation=SimpleNamespace(mode=mode) if mode else None)
    obj.base_compose = ['docker', 'compose', '-f', 'canonical.yml', '-f', 'backup.yml']
    obj.start_operator_services()
    started = [argv[-1] for argv, _ in calls if 'up' in argv]
    assert started == (['sentinel-panel'] if transport == 'unconfigured'
                       else ['sentinel-panel', 'sentinel-alert-dispatcher'])
    assert all('--wait' in argv and '--wait-timeout' in argv for argv, _ in calls if 'up' in argv)
    assert all('sentinel-automation' not in argv and 'sentinel-shadow' not in argv for argv, _ in calls)
    probes = [(argv, kwargs) for argv, kwargs in calls if 'exec' in argv]
    assert len(probes) == len(started)
    assert all(kwargs['timeout'] == 10 for _, kwargs in probes)
    assert obj.base_compose == ['docker', 'compose', '-f', 'canonical.yml', '-f', 'backup.yml']


@pytest.mark.parametrize('service', ['sentinel-panel', 'sentinel-alert-dispatcher'])
@pytest.mark.parametrize('condition', ['absent', 'stopped', 'stale', 'crashed-after-backup'])
def test_public_installation_cannot_succeed_when_operator_service_is_lost(
        tmp_path, service, condition):
    """Use real start/probe and final receipt owners, with Docker fault responses."""
    calls = []
    lost = False
    def invoke(argv, **kwargs):
        nonlocal lost
        calls.append(argv)
        if argv == ['bash', 'scripts/sentinel-backup-status.sh']:
            lost = True
        if lost and 'exec' in argv and service in argv:
            raise core.DeployRefused(condition + ': ' + service)
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    cfg = SimpleNamespace(health_timeout=45, deployment_id='fixture', account_id='paper',
                          runtime_repository='registry/sentinel', test_repository='registry/sentinel')
    obj = bootstrap.BootstrapDeploy(cfg, SimpleNamespace(
        env={'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY': 'configured'}, run=invoke), tmp_path)
    obj.base_compose = ['docker', 'compose', '-f', 'canonical.yml']
    obj.start_operator_services()
    obj._persist_deploy_facts = lambda *_: pytest.fail('wrote successful deployment facts')
    obj._post_deploy_backup = lambda: pytest.fail('financial restore inside installation')
    with pytest.raises(core.DeployRefused, match=condition):
        obj.persist_deployed({'enabled': False, 'kill_switch_engaged': True})
    assert not (tmp_path / 'deployment-receipt.json').exists()
    assert not any('release-paper-automation-kill-switch' in argv for argv in calls)


@pytest.mark.parametrize('verified', [None, '/backups/base/base-20261007T060000Z'])
def test_activation_recovery_keeps_full_restore_or_reuses_exact_milestone(tmp_path, verified):
    calls = []
    exact = '/backups/base/base-20261007T060000Z'
    def run(argv, **kwargs):
        calls.append(argv)
        assert argv == ['bash', 'scripts/sentinel-install-backup.sh', '--restore', 'full']
        assert kwargs['capture'] is True and kwargs['stream'] is True
        return SimpleNamespace(stdout='verified_installation_backup:' + exact + '\n')
    obj = bootstrap.BootstrapDeploy(SimpleNamespace(), SimpleNamespace(env={}, run=run), tmp_path)
    obj._activation_backup = verified
    assert obj._post_deploy_backup() == exact
    assert calls == ([] if verified else [
        ['bash', 'scripts/sentinel-install-backup.sh', '--restore', 'full']])


@pytest.mark.parametrize('mode', ['dual', 'paper'])
@pytest.mark.parametrize('service', ['sentinel-panel', 'sentinel-alert-dispatcher'])
def test_public_activation_rechecks_operator_services_before_kill_release(tmp_path, mode, service):
    calls = []
    def run(argv, **kwargs):
        if 'exec' in argv and service in argv:
            raise core.DeployRefused('operator service stopped')
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    obj = bootstrap.BootstrapDeploy(SimpleNamespace(account_id='PAPER', deployment_id='fixture', actor='test'),
        SimpleNamespace(env={'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY': 'fixture'}, run=run), tmp_path,
        reviewed_validation=SimpleNamespace(mode=mode))
    obj.base_compose = ['docker', 'compose', '-f', 'fixture.yml']
    plan = {'plan': {'plan_id': 'same-plan', 'decision_session': '2026-10-02'},
            'database_authorities_match': True}
    def cli(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(plan), stderr='', returncode=0)
    obj._authorized_cli = cli
    obj._base_cli = cli
    obj._verify_dual_plan_shadow_reconciliation = lambda: None
    obj._automation_status = lambda: {'enabled': True, 'kill_switch_engaged': True,
                                     'certificate_sha256': 'certificate'}
    with pytest.raises(core.DeployRefused, match='operator service stopped'):
        obj.prepare_activate_start('certificate', '2026-10-02')
    assert any(args[0] == 'activate-paper-automation' for args in calls)
    assert not any(args[0] == 'release-paper-automation-kill-switch' for args in calls)


@pytest.mark.parametrize('service', ['sentinel-panel', 'sentinel-alert-dispatcher'])
def test_active_installation_final_backup_cannot_hide_a_service_crash(tmp_path, service):
    lost = False
    def run(argv, **kwargs):
        if lost and 'exec' in argv and service in argv:
            raise core.DeployRefused('service crashed during final backup')
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    obj = bootstrap.BootstrapDeploy(SimpleNamespace(health_timeout=45),
        SimpleNamespace(env={'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY': 'fixture'}, run=run), tmp_path)
    obj.base_compose = ['docker', 'compose', '-f', 'fixture.yml']
    obj.start_operator_services()
    def backup(**kwargs):
        nonlocal lost
        lost = True
        return '/fixture/backup'
    obj._create_backup = backup
    with pytest.raises(core.DeployRefused, match='service crashed'):
        obj.persist_success({})
    assert not (tmp_path / 'deployment-receipt.json').exists()
