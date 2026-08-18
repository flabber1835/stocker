from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


core = "scripts/sentinel_autonomous_deploy.py"
marker = "    def persist_success(self, health: Mapping) -> None:\n"
methods = '''    def start_fenced_runtime(self) -> Mapping:
        """Start the exact promoted runtime while durable trading fences stay on."""
        self.phase("install: start exact promoted runtime in DEPLOYED/FENCED state")
        before = self._automation_status()
        if (before.get("enabled") is not False
                or before.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "fenced runtime install requires disabled+killed automation")
        self.runner.run(self._authorized_compose() + [
            "--profile", "automation", "up", "-d", "sentinel-automation"])
        after = self._automation_status()
        if (after.get("enabled") is not False
                or after.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "new runtime did not remain disabled+killed after install")
        return after

    def _persist_deploy_facts(self, updates: Mapping[str, str]) -> None:
        update_dotenv(ENV_PATH, updates)

    def _post_deploy_backup(self) -> Optional[str]:
        self.runner.run(["bash", "scripts/sentinel-base-backup.sh"])
        self.runner.run(["bash", "scripts/sentinel-backup-status.sh"])
        return None

    def persist_deployed(self, status: Mapping) -> None:
        """Persist installation success independently of operational readiness."""
        self.phase("finalize: persist immutable DEPLOYED facts while fenced")
        if (status.get("enabled") is not False
                or status.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "deployment receipt requires disabled+killed automation")
        self._persist_deploy_facts({
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_REPOSITORY": self.cfg.test_repository,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
        })
        post_backup = self._post_deploy_backup()
        receipt = {
            "schema": DEPLOY_SCHEMA,
            "completed_at": _utc_text(_utcnow()),
            "git_commit": self.commit,
            "runtime_image": self.runtime_repo_digest,
            "test_image": self.test_repo_digest,
            "deployment_id": self.cfg.deployment_id,
            "paper_account_id": self.cfg.account_id,
            "deployment_state": "DEPLOYED",
            "operational_state": "FENCED",
            "automation_enabled": False,
            "kill_switch_engaged": True,
            "operational_ready": bool(status.get("operational_ready") is True),
            "policy_state": status.get("policy_state"),
            "active_certificate_sha256_at_install": status.get("certificate_sha256"),
            "post_deploy_backup": post_backup,
        }
        path = self.attempt_dir / "deployment-receipt.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        print("\nDEPLOYMENT PASS: exact Sentinel runtime is installed and durably fenced")
        print("operational state: FENCED (runtime readiness owns later progression)")
        print("receipt: %s" % path)

'''
replace_once(core, marker, methods + marker)

old_run = '''    def run(self) -> None:
        self.git_preflight()
        self.read_paper_account()
        self.build_promote()
        with self.transition():
            self.quiesce_backup_and_migrate()
            self.refresh_data()
            self.ensure_ownership()
            certificate, session = self.rotate_observation_authority()
            self.prepare_activate_start(certificate, session)
            health = self.verify_operational(certificate)
            self.persist_success(health)
'''
new_run = '''    def run(self) -> None:
        # Deployment establishes software/schema identity and a safe writer fence.
        # Operational readiness (data, broker, ownership, authority, plan, leader)
        # is deliberately not part of this success boundary.
        self.git_preflight()
        self.build_promote()
        with self.transition():
            self.quiesce_backup_and_migrate()
            status = self.start_fenced_runtime()
            self.persist_deployed(status)
'''
replace_once(core, old_run, new_run)
replace_once(
    core,
    '        print("git ff-only -> account read -> build/test/push -> kill/stop -> "\n              "backup/restore -> schema -> daily/readiness -> ownership -> "\n              "signed certificate rotate -> prepare -> activate killed -> start -> "\n              "release -> heartbeat proof -> post-deploy backup")\n',
    '        print("git ff-only -> build/test/push -> kill/stop -> backup/restore -> "\n              "schema -> start exact runtime disabled+killed -> persist DEPLOYED/FENCED; "\n              "runtime later owns data/readiness and activation prerequisites")\n')

bootstrap = "scripts/sentinel_autonomous_deploy_bootstrap.py"
persist_marker = "    def persist_success(self, health: Mapping) -> None:\n"
bootstrap_hooks = '''    def _persist_deploy_facts(self, updates: Mapping[str, str]) -> None:
        _safe_update_dotenv(core.ENV_PATH, updates)

    def _post_deploy_backup(self) -> str:
        return self._create_backup(restore_drill=False)

'''
replace_once(bootstrap, persist_marker, bootstrap_hooks + persist_marker)
replace_once(
    bootstrap,
    '            "discover existing durable identity -> git/build/test/push -> "\n            "kill/backup/schema/data -> certificate/key rotation -> plan -> "\n            "activate killed -> start -> release -> heartbeat proof")\n',
    '            "discover existing durable identity -> git/build/test/push -> "\n            "kill/backup/schema -> start exact runtime disabled+killed -> "\n            "persist DEPLOYED/FENCED; runtime owns later readiness progression")\n')

runtime = "sentinel/automation_runtime.py"
replace_once(runtime, "import asyncio\nimport os\n", "import asyncio\nimport hashlib\nimport os\n")
replace_once(runtime, "from datetime import date, datetime, timezone\n",
             "from datetime import date, datetime, timedelta, timezone\n")
replace_once(
    runtime,
    '        self.alert_adapter = alert_adapter or outbox.LogAlertAdapter()\n        self.service = AutomationService(\n',
    '        self.alert_adapter = alert_adapter or outbox.LogAlertAdapter()\n        # Fenced installs may advance only the canonical corpus path. The timer\n        # is deliberately process-local: restart may cause one extra safe probe,\n        # never broker authority or a duplicate trading command.\n        self._fenced_data_next_wake: datetime | None = None\n        self._fenced_data_poll_seconds = 300\n        self.service = AutomationService(\n')

control_marker = "    async def control_wake(self, conn):\n"
fenced_method = '''    async def _fenced_data_wake(self, conn):
        """Advance canonical Sharadar readiness while broker mutation is fenced.

        This path intentionally has no CycleContext, leader permit, broker, plan,
        or execution grant. It can only call the same ingest.daily/publication/
        readiness path used by active automation. Vendor lag and corpus refusal
        are retained as alerts and retried; they never release the kill switch.
        """
        now = datetime.now(timezone.utc)
        if (self._fenced_data_next_wake is not None
                and now < self._fenced_data_next_wake):
            return self._fenced_data_next_wake
        next_wake = now + timedelta(seconds=self._fenced_data_poll_seconds)
        self._fenced_data_next_wake = next_wake
        target = schedule.for_clock(now, self.automation_config).decision_session.isoformat()
        try:
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            visible = feed_store.latest_visible_session(conn)
            if visible != target:
                ingest.daily(conn, today=target)
                visible = feed_store.latest_visible_session(conn)
            report = readiness.check_readiness(
                conn, today=now.astimezone(
                    ZoneInfo(calendar.EXCHANGE_TZ)).isoformat())
            if visible != target or not report.ready:
                raise RuntimeError(
                    "fenced data progression has not reached exact ready frontier "
                    f"{target}; visible={visible!r}")
        except Exception as exc:                              # noqa: BLE001
            conn.rollback()
            detail = f"{type(exc).__name__}: {exc}"[:4000]
            digest = hashlib.sha256(detail.encode("utf-8")).hexdigest()[:16]
            outbox.enqueue(
                conn,
                idempotency_key=f"fenced-data:{target}:not-ready:{digest}",
                event_type="AUTOMATION_FENCED_DATA_NOT_READY",
                severity="WARN",
                payload={
                    "decision_session": target,
                    "state": "DEPLOYED_FENCED",
                    "readiness": "DATA_NOT_READY",
                    "detail": detail,
                },
                max_attempts=self.automation_config.alert_max_attempts)
            return next_wake
        outbox.enqueue(
            conn,
            idempotency_key=f"fenced-data:{target}:ready",
            event_type="AUTOMATION_FENCED_DATA_READY",
            severity="WARN",
            payload={
                "decision_session": target,
                "state": "DEPLOYED_FENCED",
                "readiness": "DATA_READY",
                "frontier": target,
            },
            max_attempts=self.automation_config.alert_max_attempts)
        return next_wake

'''
replace_once(runtime, control_marker, fenced_method + control_marker)
replace_once(
    runtime,
    '        control = store.load_control(conn)\n        if not control.enabled or control.kill_switch_engaged:\n            return None\n',
    '        control = store.load_control(conn)\n        if not control.enabled or control.kill_switch_engaged:\n            return await self._fenced_data_wake(conn)\n')

tests = "tests/sentinel/test_autonomous_deploy.py"
replace_once(
    tests,
    '    obj.read_paper_account = lambda: events.append("account")\n\n    def fail_build():\n',
    '    obj.read_paper_account = lambda: pytest.fail(\n        "broker readiness must not be consulted for deployment success")\n\n    def fail_build():\n')
replace_once(tests,
             '    assert events == ["git", "account", "build"]\n',
             '    assert events == ["git", "build"]\n')
old_test = '''def test_run_post_transition_failure_always_fail_closes(tmp_path):
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
'''
new_test = '''def test_run_post_transition_install_failure_always_fail_closes(tmp_path):
    obj = deploy.AutonomousDeploy(
        SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj.git_preflight = lambda: events.append("git")
    obj.read_paper_account = lambda: pytest.fail(
        "broker readiness is not a deployment gate")
    obj.build_promote = lambda: events.append("build")
    obj.quiesce_backup_and_migrate = lambda: events.append("quiesce")

    def fail_install():
        events.append("install")
        raise deploy.DeployRefused("runtime install failed")

    obj.start_fenced_runtime = fail_install
    obj.fail_close = lambda: events.append("fenced")
    with pytest.raises(deploy.DeployRefused):
        obj.run()
    assert events == ["git", "build", "quiesce", "install", "fenced"]
'''
replace_once(tests, old_test, new_test)

issue_test = Path("tests/sentinel/test_issue_160_deployed_fenced.py")
issue_test.write_text(r'''from __future__ import annotations

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
''', encoding="utf-8")
