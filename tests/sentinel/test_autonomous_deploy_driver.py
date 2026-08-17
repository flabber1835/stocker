from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
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


def _freshness_failure(detail="missing latest closed session"):
    return {
        "ready": False,
        "failures": [{
            "name": "freshness",
            "detail": detail,
            "value": {"missing_sessions": ["2026-08-17"]},
        }],
    }


def test_freshness_only_waits_then_continues_same_deployment(tmp_path, monkeypatch):
    obj = _deploy_for_wait(tmp_path)
    verdicts = [_freshness_failure(), {"ready": True, "failures": []}]
    events = []

    obj._automation_status = lambda: {
        "enabled": False, "kill_switch_engaged": True}
    obj._readiness_verdict = lambda: verdicts.pop(0)

    def base(args, *, capture=False, check=True):
        events.append(("base", list(args), check))
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    obj._base_cli = base
    obj.runner = SimpleNamespace(
        env={},
        run=lambda args, **kwargs: events.append(("runner", list(args))))
    monotonic = iter([100.0, 101.0, 131.0, 132.0])
    monkeypatch.setattr(driver.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(
        driver.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    obj.refresh_data()

    feed_calls = [e for e in events if e[:2] == ("base", ["feed-daily"])]
    check_calls = [e for e in events if e[:2] == ("base", ["check-data"])]
    assert len(feed_calls) == 2
    assert len(check_calls) == 1 and check_calls[0][2] is True
    assert ("sleep", 30) in events
    assert sum(1 for e in events if e[0] == "runner") == 1
    state = json.loads((tmp_path / "deployment-state.json").read_text())
    assert state["state"] == "DATA_READY"
    assert state["attempt"] == 2


def test_nonfreshness_readiness_failure_still_refuses_immediately(tmp_path, monkeypatch):
    obj = _deploy_for_wait(tmp_path)
    events = []
    obj._automation_status = lambda: {
        "enabled": False, "kill_switch_engaged": True}
    obj._readiness_verdict = lambda: {
        "ready": False,
        "failures": [{"name": "continuity", "detail": "gap", "value": None}],
    }
    obj._base_cli = lambda args, *, capture=False, check=True: (
        events.append((list(args), check))
        or SimpleNamespace(stdout="", stderr="", returncode=2))
    obj.runner = SimpleNamespace(env={}, run=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        driver.time, "sleep",
        lambda _seconds: pytest.fail("non-freshness faults must never sleep/retry"))

    with pytest.raises(core.DeployRefused, match="continuity"):
        obj.refresh_data()

    assert events == [(["feed-daily"], True), (["check-data"], False)]
    state = json.loads((tmp_path / "deployment-state.json").read_text())
    assert state["state"] == "DATA_REFUSED"


def test_freshness_wait_timeout_refuses_and_retains_waiting_state(tmp_path, monkeypatch):
    obj = _deploy_for_wait(tmp_path)
    obj._automation_status = lambda: {
        "enabled": False, "kill_switch_engaged": True}
    obj._readiness_verdict = lambda: _freshness_failure("2026-08-17 missing")
    obj._base_cli = lambda *args, **kwargs: SimpleNamespace(
        stdout="", stderr="", returncode=0)
    obj.runner = SimpleNamespace(env={}, run=lambda *args, **kwargs: None)
    monotonic = iter([100.0, 401.0])
    monkeypatch.setattr(driver.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(
        driver.time, "sleep",
        lambda _seconds: pytest.fail("expired wait budget must not sleep"))

    with pytest.raises(core.DeployRefused, match="timed out waiting"):
        obj.refresh_data()

    state = json.loads((tmp_path / "deployment-state.json").read_text())
    assert state["state"] == "WAITING_FOR_DATA"
    assert state["failures"][0]["name"] == "freshness"


def test_waiting_for_data_refuses_if_automation_fence_is_lost(tmp_path):
    obj = _deploy_for_wait(tmp_path)
    obj._automation_status = lambda: {
        "enabled": True, "kill_switch_engaged": False}
    with pytest.raises(core.DeployRefused, match="lost the required"):
        obj._assert_wait_fence()


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


def test_bootstrap_is_the_launcher_target():
    launcher = SCRIPTS / "sentinel-autonomous-deploy.sh"
    source = launcher.read_text(encoding="utf-8")
    assert "scripts/sentinel_autonomous_deploy_bootstrap.py" in source
    assert "scripts/sentinel_autonomous_deploy_driver.py" not in source
