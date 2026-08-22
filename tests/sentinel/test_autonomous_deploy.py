from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
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


def test_runner_can_stream_progress_while_retaining_captured_output(tmp_path, capsys):
    log = tmp_path / "commands.log"
    runner = deploy.Runner(os.environ, log)

    result = runner.run([
        sys.executable, "-c",
        "import sys; print('progress-1'); print('progress-2', file=sys.stderr)",
    ], stream=True)

    visible = capsys.readouterr().out
    assert "progress-1" in visible
    assert "progress-2" in visible
    assert "progress-1" in result.stdout
    assert "progress-2" in result.stdout
    retained = log.read_text(encoding="utf-8")
    assert "progress-1" in retained
    assert "progress-2" in retained


def test_runner_streamed_failure_still_refuses_with_child_output(tmp_path, capsys):
    log = tmp_path / "commands.log"
    runner = deploy.Runner(os.environ, log)

    with pytest.raises(deploy.DeployRefused, match="streamed-failure"):
        runner.run([
            sys.executable, "-c",
            "import sys; print('streamed-failure'); raise SystemExit(7)",
        ], stream=True)

    assert "streamed-failure" in capsys.readouterr().out
    assert "streamed-failure" in log.read_text(encoding="utf-8")


def test_full_deploy_suite_uses_live_streaming_without_weakening_skip_gate():
    source = SCRIPT.read_text(encoding="utf-8")
    suite_start = source.index(
        'self.phase("test: complete Sentinel suite in the exact new test image")')
    suite_end = source.index(
        'self.phase("promote: push exact image IDs and freeze immutable RepoDigests")',
        suite_start)
    block = source[suite_start:suite_end]

    assert '"tests/sentinel", "-q", "-ra"], stream=True)' in block
    assert "complete Sentinel deployment suite skipped tests" in block


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
    obj.check_paper_account_deployment_integrity = lambda: events.append("broker-integrity")

    def fail_build():
        events.append("build")
        raise deploy.DeployRefused("registry unavailable")

    obj.build_promote = fail_build
    obj.fail_close = lambda: events.append("fenced")
    with pytest.raises(deploy.DeployRefused):
        obj.run()
    assert events == ["git", "broker-integrity", "build"]


def test_run_post_transition_install_failure_always_fail_closes(tmp_path):
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.check_paper_account_deployment_integrity = lambda: events.append("broker-integrity")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("quiesce")
    obj.check_durable_deployment_integrity = lambda: events.append("durable-integrity")
    obj.configure_reviewed_mode_while_fenced = lambda: events.append("mode")

    def fail_install():
        events.append("install")
        raise deploy.DeployRefused("runtime install failed")

    obj.start_fenced_runtime = fail_install
    obj.fail_close = lambda: events.append("fenced")
    with pytest.raises(deploy.DeployRefused):
        obj.run()
    assert events == [
        "git", "broker-integrity", "build", "quiesce",
        "durable-integrity", "mode", "install", "fenced"]


def test_reviewed_dual_starts_shadow_and_attests_before_paper_release(tmp_path):
    events = []

    class Runner:
        env = {}

        def run(self, argv, **_kwargs):
            events.append("panel" if "sentinel-panel" in argv else "runner")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    reviewed = SimpleNamespace(mode="dual")
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), Runner(), tmp_path,
        reviewed_validation=reviewed)
    obj.git_preflight = lambda: events.append("git")
    obj.verify_reviewed_preflight = lambda: events.append("review")
    obj.check_paper_account_deployment_integrity = \
        lambda: events.append("broker-integrity")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("quiesce")
    obj.check_durable_deployment_integrity = \
        lambda: events.append("durable-integrity")
    obj.verify_reviewed_shadow_bindings_quiesced = \
        lambda: events.append("quiesced-review")
    obj.configure_reviewed_mode_while_fenced = lambda: events.append("mode")
    obj.start_fenced_runtime = lambda: events.append("shadow-start")
    obj.read_paper_account = lambda: events.append("paper-read")
    obj.ensure_ownership = lambda: events.append("ownership")
    obj.rotate_observation_authority = lambda: (
        events.append("authority") or ("c" * 64, "2026-08-20"))
    obj._wait_for_dual_shadow_session = \
        lambda session: events.append("shadow-attested:" + session)
    obj.prepare_activate_start = \
        lambda cert, session: events.append("paper-released:" + session)
    obj.verify_operational = \
        lambda cert: events.append("operational") or {"ok": True}
    obj.persist_success = lambda health: events.append("receipt")

    obj.run()

    assert events == [
        "git", "review", "broker-integrity", "build", "quiesce",
        "durable-integrity", "quiesced-review", "mode", "shadow-start",
        "paper-read", "ownership", "authority",
        "shadow-attested:2026-08-20", "paper-released:2026-08-20",
        "operational", "panel", "receipt",
    ]


class _AccountResponse:
    def __init__(self, payload):
        import json
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def _broker_probe(tmp_path):
    cfg = _cfg()
    runner = SimpleNamespace(env={
        "ALPACA_API_KEY": "key",
        "ALPACA_SECRET_KEY": "secret",
    })
    obj = deploy.AutonomousDeploy(cfg, runner, tmp_path)
    obj.phase = lambda _text: None
    return obj


def _account_payload(**updates):
    payload = {
        "id": "PAPER-123",
        "account_number": "account-number",
        "status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    payload.update(updates)
    return payload


def test_broker_unavailable_is_operational_not_deployment_failure(tmp_path, monkeypatch):
    obj = _broker_probe(tmp_path)
    monkeypatch.setattr(
        deploy.urllib.request, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))

    assert obj.check_paper_account_deployment_integrity() == "BROKER_NOT_READY"


def test_broker_trading_block_is_operational_not_deployment_failure(tmp_path, monkeypatch):
    obj = _broker_probe(tmp_path)
    monkeypatch.setattr(
        deploy.urllib.request, "urlopen",
        lambda *_args, **_kwargs: _AccountResponse(
            _account_payload(trading_blocked=True)))

    assert obj.check_paper_account_deployment_integrity() == "BROKER_NOT_READY"


def test_broker_identity_contradiction_still_blocks_deployment(tmp_path, monkeypatch):
    obj = _broker_probe(tmp_path)
    monkeypatch.setattr(
        deploy.urllib.request, "urlopen",
        lambda *_args, **_kwargs: _AccountResponse(
            _account_payload(id="DIFFERENT", account_number="DIFFERENT")))

    with pytest.raises(deploy.DeployRefused, match="different paper account"):
        obj.check_paper_account_deployment_integrity()


def test_durable_not_owned_and_noncurrent_authority_are_valid_fenced_install_states():
    status = {
        "ownership": "NOT_OWNED",
        "paper_execution_authority": {
            "authority_mode": None,
            "lifecycle_current": False,
        },
        "administrative_authority": {
            "active_certificate_sha256": None,
        },
    }
    assert deploy.validate_deployment_integrity_status(status, _cfg()) == "NOT_OWNED"


def test_durable_owned_identity_contradiction_still_blocks_deployment():
    status = {
        "ownership": "OWNED",
        "broker": "alpaca",
        "broker_account_id": "OTHER",
        "deployment_id": "sentinel-nas-paper-01",
        "takeover_epoch": 1,
        "paper_execution_authority": {},
        "administrative_authority": {},
    }
    with pytest.raises(deploy.DeployRefused, match="contradicts"):
        deploy.validate_deployment_integrity_status(status, _cfg())


def test_unreadable_durable_authority_still_blocks_deployment():
    status = {
        "ownership": "NOT_OWNED",
        "paper_execution_authority": {"error": "corrupt authority row"},
        "administrative_authority": {},
    }
    with pytest.raises(deploy.DeployRefused, match="durable state is unreadable"):
        deploy.validate_deployment_integrity_status(status, _cfg())


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
