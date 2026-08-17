from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_autonomous_deploy.py"
LAUNCHER = ROOT / "scripts" / "sentinel-autonomous-deploy.sh"

spec = importlib.util.spec_from_file_location("sentinel_autonomous_deploy", SCRIPT)
deploy = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(deploy)


def _cfg(*, allow_empty=False):
    return SimpleNamespace(
        deployment_id="sentinel-nas-paper-01",
        account_id="PAPER-123",
        allow_empty_bind=allow_empty,
    )


def test_dotenv_is_literal_and_does_not_truncate_hash_password(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\n"
        "SENTINEL_POSTGRES_PASSWORD=a#b#c\n"
        "QUOTED=\"hello world\"\n"
        "export EXPORTED=value\n",
        encoding="utf-8")

    values = deploy.load_dotenv(path)

    assert values["SENTINEL_POSTGRES_PASSWORD"] == "a#b#c"
    assert values["QUOTED"] == "hello world"
    assert values["EXPORTED"] == "value"


def test_update_dotenv_changes_only_named_deploy_facts(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "ALPACA_SECRET_KEY=keep-this-secret\n"
        "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:old\n",
        encoding="utf-8")

    deploy.update_dotenv(path, {
        "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "1" * 64,
        "SENTINEL_GIT_COMMIT": "a" * 40,
    })
    text = path.read_text(encoding="utf-8")

    assert "ALPACA_SECRET_KEY=keep-this-secret" in text
    assert "sha256:old" not in text
    assert "SENTINEL_GIT_COMMIT=" + "a" * 40 in text


def test_owned_binding_must_match_every_configured_identity():
    exact = {
        "ownership": "OWNED",
        "broker": "alpaca",
        "broker_account_id": "PAPER-123",
        "deployment_id": "sentinel-nas-paper-01",
        "takeover_epoch": 2,
    }
    assert deploy.validate_owned_status(exact, _cfg()) == "OWNED"

    for field, wrong in (
        ("broker", "other"),
        ("broker_account_id", "PAPER-999"),
        ("deployment_id", "other-deploy"),
        ("takeover_epoch", 0),
    ):
        broken = dict(exact)
        broken[field] = wrong
        with pytest.raises(deploy.DeployRefused):
            deploy.validate_owned_status(broken, _cfg())


def test_unknown_and_unapproved_unbound_ownership_fail_closed():
    with pytest.raises(deploy.DeployRefused, match="UNKNOWN"):
        deploy.validate_owned_status({"ownership": "UNKNOWN"}, _cfg())
    with pytest.raises(deploy.DeployRefused, match="ALLOW_EMPTY_BIND"):
        deploy.validate_owned_status({"ownership": "NOT_OWNED"}, _cfg())
    assert deploy.validate_owned_status(
        {"ownership": "NOT_OWNED"}, _cfg(allow_empty=True)) == "NOT_OWNED"


def _health(heartbeat="2026-08-17T12:00:00+00:00"):
    return {
        "operational_ready": True,
        "policy_state": "LEADER_ACTIVE",
        "deployment_id": "sentinel-nas-paper-01",
        "broker_account_id": "PAPER-123",
        "certificate_sha256": "c" * 64,
        "authority_verdict": "PASS",
        "authority_lifecycle_current": True,
        "dead_letter_alerts": 0,
        "latest_cycle_state": "WAITING_OPEN",
        "latest_failure_code": None,
        "control_generation": 7,
        "leader_holder": "worker-1",
        "fencing_token": 11,
        "leader_heartbeat_at": heartbeat,
    }


def test_final_health_requires_same_fence_and_advancing_heartbeat():
    first = _health("2026-08-17T12:00:00+00:00")
    second = _health("2026-08-17T12:00:12+00:00")
    deploy.health_heartbeat_proof(
        first, second, cfg=_cfg(), certificate_sha256="c" * 64)

    stale = dict(second)
    stale["leader_heartbeat_at"] = first["leader_heartbeat_at"]
    with pytest.raises(deploy.DeployRefused, match="did not advance"):
        deploy.health_heartbeat_proof(
            first, stale, cfg=_cfg(), certificate_sha256="c" * 64)

    changed = dict(second)
    changed["fencing_token"] = 12
    with pytest.raises(deploy.DeployRefused, match="fencing_token"):
        deploy.health_heartbeat_proof(
            first, changed, cfg=_cfg(), certificate_sha256="c" * 64)


def test_failure_boundary_fences_only_after_transition(tmp_path):
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.fail_close = lambda: events.append("fenced")

    with pytest.raises(RuntimeError):
        with obj.transition():
            raise RuntimeError("after mutation boundary")
    assert events == ["fenced"]


def test_run_build_failure_does_not_enter_fail_close(tmp_path):
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.read_paper_account = lambda: events.append("account")

    def fail_build():
        events.append("build")
        raise deploy.DeployRefused("registry unavailable")

    obj.build_promote = fail_build
    obj.fail_close = lambda: events.append("fenced")
    with pytest.raises(deploy.DeployRefused):
        obj.run()
    assert events == ["git", "account", "build"]


def test_run_post_transition_failure_always_fail_closes(tmp_path):
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.read_paper_account = lambda: events.append("account")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("quiesce")

    def fail_refresh():
        events.append("refresh")
        raise deploy.DeployRefused("feed failed")

    obj.refresh_data = fail_refresh
    obj.fail_close = lambda: events.append("fenced")
    with pytest.raises(deploy.DeployRefused):
        obj.run()
    assert events == ["git", "account", "build", "quiesce", "refresh", "fenced"]


def test_deployer_contains_no_destructive_reseed_or_account_migration_command():
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden_command_shapes = (
        '["feed-seed"',
        '["migrate-account"',
        '"docker", "volume", "rm"',
        '"docker", "compose", "down"',
        '"git", "reset"',
        "DROP TABLE",
        "TRUNCATE ",
    )
    for forbidden in forbidden_command_shapes:
        assert forbidden not in source


def test_signer_is_network_disabled_and_private_key_is_read_only():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--network", "none"' in source
    assert "dst=/signing-key,readonly" in source
    assert "configured signing key is not an ACTIVE trust root" in source


def test_launcher_serializes_before_fast_forward_and_reexecs_after_update():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "/tmp/sentinel-autonomous-deploy.lock" in source
    assert "SENTINEL_DEPLOY_LOCK_FD" in source
    assert 'git pull --ff-only origin "$TARGET_BRANCH"' in source
    assert "git reset" not in source
    assert "git clean" not in source
    assert "--after-fast-forward" not in source
    assert 'exec bash scripts/sentinel-autonomous-deploy.sh "$@"' in source


def test_empty_issuer_keeps_original_confirmation_and_autonomous_alias():
    issuer = ROOT / "tools" / "sentinel_empty_account_authority.py"
    source = issuer.read_text(encoding="utf-8")
    assert "--confirm-issue-admin-bind-empty" in source
    assert "--confirm-issue-empty-paper-binding" in source
