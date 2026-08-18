from __future__ import annotations

import asyncio
import importlib.util
import json
import os
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
spec.loader.exec_module(deploy)


def test_deploy_success_boundary_stops_before_operational_gates(tmp_path):
    obj = deploy.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("migrate")
    obj.start_fenced_runtime = lambda: (
        events.append("install") or {
            "enabled": False, "kill_switch_engaged": True,
            "operational_ready": False})
    obj.persist_deployed = lambda status: events.append(
        ("receipt", status["kill_switch_engaged"]))
    obj.read_paper_account = lambda: pytest.fail("broker gate reached")
    obj.refresh_data = lambda: pytest.fail("data gate reached")
    obj.ensure_ownership = lambda: pytest.fail("ownership gate reached")
    obj.rotate_observation_authority = lambda: pytest.fail("authority gate reached")
    obj.prepare_activate_start = lambda *_: pytest.fail("plan/activation gate reached")
    obj.verify_operational = lambda *_: pytest.fail("health gate reached")

    obj.run()

    assert events == ["git", "build", "migrate", "install", ("receipt", True)]


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
