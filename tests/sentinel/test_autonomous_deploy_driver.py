from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if not SCRIPTS.is_dir():
    SCRIPTS = ROOT / "repo" / "scripts"
CORE = SCRIPTS / "sentinel_autonomous_deploy.py"
DRIVER = SCRIPTS / "sentinel_autonomous_deploy_driver.py"

core_spec = importlib.util.spec_from_file_location("sentinel_autonomous_deploy", CORE)
core = importlib.util.module_from_spec(core_spec)
assert core_spec.loader is not None
core_spec.loader.exec_module(core)
import sys
sys.modules["sentinel_autonomous_deploy"] = core

driver_spec = importlib.util.spec_from_file_location(
    "sentinel_autonomous_deploy_driver", DRIVER)
driver = importlib.util.module_from_spec(driver_spec)
assert driver_spec.loader is not None
driver_spec.loader.exec_module(driver)


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
        "SHARADAR_API_KEY": "sharadar",
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

    # The method intentionally exposes max(active-highest, max-installed) under
    # the key consumed by the core rotation state machine.
    assert state["highest_issuer_generation"] == 8
    # This fixture bypasses the SQL computation itself, so lock the intended
    # query shape too: MAX(installed) must be read and max(highest,installed)
    # must be emitted by the embedded code.
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

    with pytest.raises(core.DeployRefused, match="exact plan"):
        obj.prepare_activate_start("c" * 64, "2026-08-14")
    assert [call[0] for call in calls] == ["prepare-paper-plan"]


def test_optional_key_rotation_revokes_only_different_predecessor_after_rotation(tmp_path):
    obj = driver.AutonomousDeploy(
        SimpleNamespace(
            revoke_previous_signing_key=True,
            signing_key_id="new-key"),
        SimpleNamespace(env={}), tmp_path)
    obj.predecessor_key_id = "old-key"
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


def test_driver_is_the_launcher_target():
    launcher = SCRIPTS / "sentinel-autonomous-deploy.sh"
    source = launcher.read_text(encoding="utf-8")
    assert "scripts/sentinel_autonomous_deploy_driver.py" in source
