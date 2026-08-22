from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_autonomous_deploy.py"
spec = importlib.util.spec_from_file_location("issue160_deploy", SCRIPT)
deploy = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = deploy
spec.loader.exec_module(deploy)


def test_deploy_success_boundary_stops_before_operational_gates(tmp_path):
    obj = deploy.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.check_paper_account_deployment_integrity = lambda: events.append("broker-integrity")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("migrate")
    obj.check_durable_deployment_integrity = lambda: events.append("durable-integrity")
    obj.verify_reviewed_shadow_bindings_quiesced = lambda: events.append(
        "reviewed-bindings")
    obj.configure_reviewed_mode_while_fenced = lambda: events.append("mode")
    obj.start_fenced_runtime = lambda: (
        events.append("install") or {
            "enabled": False, "kill_switch_engaged": True,
            "operational_ready": False})
    obj.persist_deployed = lambda status: events.append(
        ("receipt", status["kill_switch_engaged"]))
    obj.read_paper_account = lambda: pytest.fail("operational broker-readiness gate reached")
    obj.refresh_data = lambda: pytest.fail("data gate reached")
    obj.ensure_ownership = lambda: pytest.fail("ownership gate reached")
    obj.rotate_observation_authority = lambda: pytest.fail("authority gate reached")
    obj.prepare_activate_start = lambda *_: pytest.fail("plan/activation gate reached")
    obj.verify_operational = lambda *_: pytest.fail("health gate reached")

    obj.run()

    assert events == [
        "git", "broker-integrity", "build", "migrate", "durable-integrity",
        "reviewed-bindings", "mode", "install", ("receipt", True)]


def test_quiesced_review_failure_precedes_mode_persistence_and_start(tmp_path):
    reviewed = SimpleNamespace(mode="shadow")
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path,
        reviewed_validation=reviewed)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.verify_reviewed_preflight = lambda: events.append("initial-review")
    obj.check_paper_account_deployment_integrity = lambda: events.append(
        "broker-integrity")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("quiesce")
    obj.check_durable_deployment_integrity = lambda: events.append(
        "durable-integrity")

    def changed_publication():
        events.append("quiesced-review")
        raise deploy.DeployRefused("publication changed after initial review")

    obj.verify_reviewed_shadow_bindings_quiesced = changed_publication
    obj.configure_reviewed_mode_while_fenced = lambda: pytest.fail(
        "changed corpus persisted reviewed mode")
    obj.start_fenced_runtime = lambda: pytest.fail(
        "changed corpus started shadow")
    obj.fail_close = lambda: events.append("fail-close")

    with pytest.raises(deploy.DeployRefused, match="publication changed"):
        obj.run()

    assert events == [
        "git", "initial-review", "broker-integrity", "build", "quiesce",
        "durable-integrity", "quiesced-review", "fail-close"]


def test_no_args_fenced_install_forces_stale_shadow_configuration_off(tmp_path):
    persisted = []
    cfg = SimpleNamespace()
    runner = SimpleNamespace(env={
        "SENTINEL_SHADOW_OBSERVATION_ENABLED": "1",
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": "a" * 64,
        "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": "b" * 64,
        "SENTINEL_REVIEWED_DEPLOYMENT_MODE": "shadow",
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": "c" * 64,
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": "d" * 64,
    })
    obj = deploy.AutonomousDeploy(cfg, runner, tmp_path)
    obj._automation_status = lambda: {
        "enabled": False, "kill_switch_engaged": True}
    obj._persist_deploy_facts = lambda updates: persisted.append(dict(updates))

    obj.configure_reviewed_mode_while_fenced()

    assert persisted == [{
        "SENTINEL_SHADOW_OBSERVATION_ENABLED": "0",
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": "",
        "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": "",
        "SENTINEL_REVIEWED_DEPLOYMENT_MODE": "",
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": "",
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": "",
    }]
    assert runner.env == persisted[0]


def test_persisted_deployment_receipt_is_explicitly_fenced(tmp_path):
    cfg = SimpleNamespace(
        deployment_id="sentinel-a", account_id="PAPER-1",
        runtime_repository="registry/sentinel",
        test_repository="registry/sentinel-test")
    obj = deploy.AutonomousDeploy(cfg, SimpleNamespace(env={}), tmp_path)
    obj.commit = "a" * 40
    obj.runtime_digest = "sha256:" + "1" * 64
    obj.test_digest = "sha256:" + "2" * 64
    obj.runtime_repo_digest = "registry/sentinel@" + obj.runtime_digest
    obj.test_repo_digest = "registry/sentinel-test@" + obj.test_digest
    obj.phase = lambda _text: None
    obj._persist_deploy_facts = lambda _updates: None
    obj._post_deploy_backup = lambda: "/backup/exact"

    obj.persist_deployed({
        "enabled": False, "kill_switch_engaged": True,
        "operational_ready": False, "policy_state": "KILLED",
        "certificate_sha256": "c" * 64})

    receipt = json.loads((tmp_path / "deployment-receipt.json").read_text())
    assert receipt["deployment_state"] == "DEPLOYED"
    assert receipt["operational_state"] == "FENCED"
    assert receipt["automation_enabled"] is False
    assert receipt["kill_switch_engaged"] is True
    assert receipt["operational_ready"] is False
    assert receipt["post_deploy_backup"] == "/backup/exact"


def test_start_fenced_runtime_never_releases_kill(tmp_path):
    cfg = SimpleNamespace()
    calls = []
    runner = SimpleNamespace(env={}, run=lambda argv, **_kwargs: calls.append(list(argv)))
    obj = deploy.AutonomousDeploy(cfg, runner, tmp_path)
    obj.phase = lambda _text: None
    obj._authorized_compose = lambda: ["docker", "compose", "-f", "authorized.yml"]
    obj._direct_stop_shadow = lambda: None
    statuses = iter([
        {"enabled": False, "kill_switch_engaged": True},
        {"enabled": False, "kill_switch_engaged": True},
    ])
    obj._automation_status = lambda: next(statuses)

    result = obj.start_fenced_runtime()

    assert result["kill_switch_engaged"] is True
    assert calls == [["docker", "compose", "-f", "authorized.yml",
                      "--profile", "automation", "up", "-d",
                      "sentinel-automation"]]


def test_reviewed_shadow_starts_only_dedicated_broker_free_service(tmp_path):
    cfg = SimpleNamespace(health_timeout=45)
    calls = []
    runner = SimpleNamespace(env={}, run=lambda argv, **_kwargs: calls.append(list(argv)))
    reviewed = SimpleNamespace(mode="shadow")
    obj = deploy.AutonomousDeploy(
        cfg, runner, tmp_path, reviewed_validation=reviewed)
    obj.phase = lambda _text: None
    obj._authorized_compose = lambda: ["docker", "compose", "-f", "authorized.yml"]
    obj._direct_stop_automation = lambda: calls.append(["STOP_AUTOMATION"])
    obj._running_automation_containers = lambda: []
    statuses = iter([
        {"enabled": False, "kill_switch_engaged": True},
        {"enabled": False, "kill_switch_engaged": True},
    ])
    obj._automation_status = lambda: next(statuses)

    result = obj.start_fenced_runtime()

    assert result["kill_switch_engaged"] is True
    assert calls == [
        ["STOP_AUTOMATION"],
        ["docker", "compose", "-f", "authorized.yml",
         "--profile", "shadow", "up", "-d", "--wait",
         "--wait-timeout", "45", "sentinel-shadow"],
    ]
    assert all("sentinel-automation" not in call for call in calls)


def test_fenced_runtime_uses_canonical_ingest_without_broker(monkeypatch):
    obj = object.__new__(automation_runtime.ProductionAutomation)
    obj.automation_config = SimpleNamespace(alert_max_attempts=8)
    obj._fenced_data_next_wake = None
    obj._fenced_data_poll_seconds = 300
    conn = SimpleNamespace(rollback=lambda: None)
    visible = iter(["2026-08-17", "2026-08-18"])
    ingested = []
    alerts = []

    monkeypatch.setattr(
        automation_runtime.schedule, "for_clock",
        lambda *_args, **_kwargs: SimpleNamespace(decision_session=date(2026, 8, 18)))
    monkeypatch.setattr(automation_runtime.feed_store, "require_feed_schema", lambda _c: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _c: None)
    monkeypatch.setattr(
        automation_runtime.feed_store, "latest_visible_session", lambda _c: next(visible))
    monkeypatch.setattr(
        automation_runtime.ingest, "daily", lambda _c, *, today: ingested.append(today))
    monkeypatch.setattr(
        automation_runtime.readiness, "check_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True))
    monkeypatch.setattr(
        automation_runtime.readiness, "save_snapshot",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        automation_runtime.outbox, "enqueue", lambda _c, **kwargs: alerts.append(kwargs))
    obj._broker = lambda *_args, **_kwargs: pytest.fail(
        "fenced data progression constructed a broker")

    asyncio.run(obj._fenced_data_wake(conn))

    assert ingested == ["2026-08-18"]
    assert alerts[-1]["event_type"] == "AUTOMATION_FENCED_DATA_READY"


def test_fenced_vendor_lag_is_retained_not_raised(monkeypatch):
    obj = object.__new__(automation_runtime.ProductionAutomation)
    obj.automation_config = SimpleNamespace(alert_max_attempts=8)
    obj._fenced_data_next_wake = None
    obj._fenced_data_poll_seconds = 300
    rolled_back = []
    conn = SimpleNamespace(rollback=lambda: rolled_back.append(True))
    alerts = []

    monkeypatch.setattr(
        automation_runtime.schedule, "for_clock",
        lambda *_args, **_kwargs: SimpleNamespace(decision_session=date(2026, 8, 18)))
    monkeypatch.setattr(automation_runtime.feed_store, "require_feed_schema", lambda _c: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _c: None)
    monkeypatch.setattr(
        automation_runtime.feed_store, "latest_visible_session", lambda _c: "2026-08-17")
    monkeypatch.setattr(
        automation_runtime.ingest, "daily",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("vendor publication incomplete")))
    monkeypatch.setattr(
        automation_runtime.outbox, "enqueue", lambda _c, **kwargs: alerts.append(kwargs))

    wake = asyncio.run(obj._fenced_data_wake(conn))

    assert wake is not None
    assert rolled_back == [True]
    assert alerts[-1]["event_type"] == "AUTOMATION_FENCED_DATA_NOT_READY"
    assert alerts[-1]["payload"]["state"] == "DEPLOYED_FENCED"


def test_fenced_shadow_mode_advances_without_constructing_broker(monkeypatch):
    from sentinel import shadow_runtime

    obj = object.__new__(automation_runtime.ProductionAutomation)
    obj.automation_config = SimpleNamespace(alert_max_attempts=8)
    obj._fenced_data_next_wake = None
    obj._fenced_data_poll_seconds = 300
    obj._shadow_observation_enabled = True
    obj._shadow_observation_id = "primary"
    obj._shadow_starting_cash = 100_000
    conn = SimpleNamespace(rollback=lambda: None)
    alerts = []
    result = SimpleNamespace(
        record_sha256="a" * 64,
        to_dict=lambda: {
            "session": "2026-08-18", "shadow_verdict": "SHADOW_GO",
            "verification": "VERIFIED", "strategy_nav": "100100",
            "strategy_cumulative_return": "0.001"})

    monkeypatch.setattr(
        automation_runtime.schedule, "for_clock",
        lambda *_args, **_kwargs: SimpleNamespace(
            decision_session=date(2026, 8, 18)))
    monkeypatch.setattr(
        automation_runtime.feed_store, "require_feed_schema", lambda _c: None)
    monkeypatch.setattr(
        automation_runtime.schema, "require_runtime_schema", lambda _c: None)
    monkeypatch.setattr(
        automation_runtime.feed_store, "latest_visible_session",
        lambda _c: "2026-08-18")
    monkeypatch.setattr(
        automation_runtime.readiness, "check_readiness",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True))
    monkeypatch.setattr(
        automation_runtime.readiness, "save_snapshot",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        shadow_runtime, "advance_ready_shadow",
        lambda _conn, **kwargs: (
            result if kwargs == {
                "through": "2026-08-18", "observation_id": "primary",
                "starting_cash": 100_000} else pytest.fail(kwargs)))
    monkeypatch.setattr(
        automation_runtime.outbox, "enqueue",
        lambda _c, **kwargs: alerts.append(kwargs))
    obj._broker = lambda *_args, **_kwargs: pytest.fail(
        "broker-free shadow mode constructed a broker")

    asyncio.run(obj._fenced_data_wake(conn))

    assert [item["event_type"] for item in alerts] == [
        "SHADOW_OBSERVATION_VERIFIED", "AUTOMATION_FENCED_DATA_READY"]
    assert alerts[0]["payload"]["verification"] == "VERIFIED"
    assert alerts[1]["payload"]["shadow_observation"]["strategy_nav"] == \
        "100100"


def test_shadow_mode_configuration_is_explicit_and_finite():
    assert automation_runtime.shadow_config_from_env({}) == (
        False, "primary", automation_runtime.Decimal("100000"))
    assert automation_runtime.shadow_config_from_env({
        "SENTINEL_SHADOW_OBSERVATION_ENABLED": "true",
        "SENTINEL_SHADOW_OBSERVATION_ID": "year-end-2026",
        "SENTINEL_SHADOW_STARTING_CASH": "125000",
    }) == (True, "year-end-2026", automation_runtime.Decimal("125000"))
    with pytest.raises(ValueError):
        automation_runtime.shadow_config_from_env({
            "SENTINEL_SHADOW_OBSERVATION_ENABLED": "maybe"})
    with pytest.raises(ValueError):
        automation_runtime.shadow_config_from_env({
            "SENTINEL_SHADOW_STARTING_CASH": "NaN"})


def test_shadow_enabled_runtime_cannot_construct_an_execution_broker(monkeypatch):
    obj = object.__new__(automation_runtime.ProductionAutomation)
    obj._shadow_observation_enabled = True
    monkeypatch.setattr(
        automation_runtime.paper, "build_security_resolver",
        lambda *_args: pytest.fail("shadow mode reached broker resolver"))
    monkeypatch.setattr(
        automation_runtime, "build_execution_broker",
        lambda *_args, **_kwargs: pytest.fail("shadow mode built a broker"))

    with pytest.raises(
            automation_runtime.NonRetryableCallbackRefused,
            match="broker construction is forbidden"):
        obj._broker(object(), "2026-08-20")  # noqa: SLF001


def test_disabled_or_killed_control_wake_owns_fenced_data_progress(monkeypatch):
    obj = object.__new__(automation_runtime.ProductionAutomation)
    called = []

    async def fenced(_conn):
        called.append(True)
        return "wake"

    obj._fenced_data_wake = fenced
    monkeypatch.setattr(
        automation_runtime.store, "load_control",
        lambda _conn: SimpleNamespace(enabled=False, kill_switch_engaged=True))

    assert asyncio.run(obj.control_wake(object())) == "wake"
    assert called == [True]
