from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


go24 = _load("sentinel_go_24x7_entry_test", "scripts/sentinel_go_24x7_entry.py")
deploy24 = _load(
    "sentinel_autonomous_deploy_24x7_test",
    "scripts/sentinel_autonomous_deploy_24x7.py")


DIGEST = "sha256:" + "a" * 64
COMMIT = "b" * 40


class _Runner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        self.calls.append((list(argv), dict(env or {})))
        marker = "SENTINEL_GO_PREPARATION="
        return subprocess.CompletedProcess(
            argv, 0, stdout=marker + json.dumps(self.payload) + "\n",
            stderr="")


def test_preparation_accepts_source_final_frontier_after_its_following_open(monkeypatch):
    monkeypatch.setattr(
        go24.go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])
    runner = _Runner({
        "schema_migrated": True,
        "source_not_before_satisfied": True,
        "following_open_future": False,
        "bounded_sharadar_daily": True,
        "publication_current": True,
    })
    ticks = iter((10.0, 10.25))
    summary = go24._deployment_preparation_probe(
        runner,
        env={"SHARADAR_API_KEY": "x", "SENTINEL_POSTGRES_PASSWORD": "y"},
        runtime_ref=DIGEST, commit=COMMIT,
        monotonic=lambda: next(ticks))

    assert summary.status == go24.go.PASS
    assert summary.complete is True
    assert summary.schema_migration_attempted is True
    assert summary.bounded_sharadar_daily_attempted is True
    assert summary.elapsed_milliseconds == 250
    assert "ALPACA_API_KEY" not in runner.calls[-1][1]


def test_preparation_still_refuses_non_final_target(monkeypatch):
    monkeypatch.setattr(
        go24.go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])
    runner = _Runner({
        "schema_migrated": True,
        "source_not_before_satisfied": False,
        "following_open_future": True,
        "bounded_sharadar_daily": True,
        "publication_current": True,
    })
    summary = go24._deployment_preparation_probe(
        runner,
        env={"SHARADAR_API_KEY": "x", "SENTINEL_POSTGRES_PASSWORD": "y"},
        runtime_ref=DIGEST, commit=COMMIT,
        monotonic=lambda: 1.0)
    assert summary.status == go24.go.FAIL
    assert summary.complete is False


def test_readiness_can_defer_only_not_source_final_freshness(monkeypatch):
    monkeypatch.setattr(
        go24.go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])

    class Runner:
        def run(self, argv, *, env=None, cwd=ROOT):
            payload = {
                "ready": False,
                "deployment_ready": True,
                "deferred_not_source_final": True,
                "deferred_sessions": 1,
                "checks_total": 20,
                "checks_passed": 19,
                "failures": 1,
                "transaction_read_only": True,
            }
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="SENTINEL_GO_READINESS=" + json.dumps(payload) + "\n",
                stderr="")

    gate = go24._deployment_readiness_probe(
        Runner(),
        env={"SHARADAR_API_KEY": "x", "SENTINEL_POSTGRES_PASSWORD": "y"},
        runtime_ref=DIGEST, now_text="2026-08-28T01:30:00Z")
    assert gate.status == go24.go.PASS


def test_database_view_does_not_turn_deployment_into_a_clock_window():
    class Base:
        complete = True

        def to_dict(self):
            return {"status": "PASS"}

    view = go24.DeploymentDatabaseHealthView(
        Base(), actual_remaining_to_execution_open_ms=0,
        observed_at="2026-08-28T01:30:00Z")
    assert view.complete is True
    assert view.remaining_now_ms() is None
    assert view.to_dict() == {"status": "PASS"}


def test_go_preparation_selects_latest_source_final_session_not_latest_close():
    code = go24._PREPARATION_CODE
    assert "def latest_source_final" in code
    assert "while now < publication_not_before(target)" in code
    assert "outage_recovery.catch_up(c, target_session=target)" in code
    assert "eligible = source_final and prospective" not in code


def test_fresh_shadow_staging_has_no_arbitrary_install_deadline():
    code = deploy24._SOURCE_FINAL_CODE
    assert "publication_not_before" in code
    assert "target = following" in code
    source = (ROOT / "scripts" / "sentinel_autonomous_deploy_24x7.py").read_text(
        encoding="utf-8")
    assert "WAITING_FOR_SOURCE_FINAL" in source
    assert "data_wait_timeout_seconds" not in source


def test_structural_preflight_is_separate_from_fresh_genesis_timing():
    code = deploy24._STRUCTURAL_PREFLIGHT_CODE
    assert "classify_shadow_lineage" in code
    assert "structural_only=True" in code
    assert "publication_not_before" not in code


def test_launcher_routes_through_24x7_entries():
    go_launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    deploy_launcher = (
        ROOT / "scripts" / "sentinel-autonomous-deploy.sh").read_text(
            encoding="utf-8")
    assert "scripts/sentinel_go_24x7_entry.py" in go_launcher
    assert "scripts/sentinel_autonomous_deploy_24x7.py" in deploy_launcher
