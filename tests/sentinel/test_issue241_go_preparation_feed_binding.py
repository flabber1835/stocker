"""Regression for GO preparation crossing every certified mutation boundary."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
ENTRY = ROOT / "scripts" / "sentinel_go_validate_entry.py"

spec = importlib.util.spec_from_file_location("sentinel_go_validate_entry_issue241", ENTRY)
entry = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = entry
spec.loader.exec_module(entry)

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64


class Runner:
    def __init__(self, *, bind_returncode=0):
        self.bind_returncode = bind_returncode
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        command = [str(item) for item in argv]
        snapshot = dict(env or {})
        self.calls.append((command, snapshot))
        if command == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
            return subprocess.CompletedProcess(
                command, 0,
                stdout="-f docker-compose.sentinel.yml -f docker-compose.sentinel-backup.yml\n",
                stderr="")
        if len(command) > 1 and command[1] == "scripts/sentinel_feed_gate.py":
            return subprocess.CompletedProcess(
                command, self.bind_returncode,
                stdout=(COMMIT + "\n" + DIGEST + "\n")
                if self.bind_returncode == 0 else "",
                stderr="")
        if command[:2] == ["docker", "compose"]:
            payload = {
                "schema_migrated": True,
                "source_not_before_satisfied": True,
                "following_open_future": True,
                "bounded_sharadar_daily": True,
                "publication_current": True,
            }
            return subprocess.CompletedProcess(
                command, 0,
                stdout="SENTINEL_GO_PREPARATION=" + json.dumps(payload) + "\n",
                stderr="")
        raise AssertionError("unexpected command: %r" % command)


def _env():
    return {
        "SHARADAR_API_KEY": "sharadar-private",
        "SENTINEL_POSTGRES_PASSWORD": "db-private",
        "ALPACA_API_KEY": "broker-key-must-not-cross",
        "ALPACA_SECRET_KEY": "broker-secret-must-not-cross",
        "SENTINEL_PAPER_ACCOUNT_ID": "broker-account-must-not-cross",
    }


@pytest.fixture()
def verified_lifecycle(monkeypatch):
    monkeypatch.setattr(
        entry.go_lock, "lifecycle_lock_is_held", lambda _env=None: True)
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)


def test_go_preparation_without_verified_orchestration_is_non_mutating(monkeypatch):
    # Even possession of the real lifecycle lock is insufficient. This
    # falsifies the direct lower-level path: only sentinel_go_verified_entry may
    # arm the process-local preparation capability after proving the lock.
    monkeypatch.setattr(
        entry.go_lock, "lifecycle_lock_is_held", lambda _env=None: True)
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", False)
    runner = Runner()
    summary = entry.probe_prevalidation_preparation(
        runner, env=_env(), runtime_ref=DIGEST, commit=COMMIT)

    assert summary.status == entry.go.NOT_PROVEN
    assert summary.schema_migration_attempted is False
    assert summary.bounded_sharadar_daily_attempted is False
    assert summary.complete is False
    assert runner.calls == []


def test_verified_orchestration_cannot_be_armed_without_kernel_lock(monkeypatch):
    monkeypatch.setattr(
        entry.go_lock, "lifecycle_lock_is_held", lambda _env=None: False)
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", False)
    with pytest.raises(RuntimeError, match="held lifecycle lock"):
        entry.authorize_verified_orchestration()
    assert entry._VERIFIED_ORCHESTRATION is False


def test_verified_orchestration_arms_only_after_kernel_lock(monkeypatch):
    monkeypatch.setattr(
        entry.go_lock, "lifecycle_lock_is_held", lambda _env=None: True)
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", False)
    entry.authorize_verified_orchestration()
    assert entry._VERIFIED_ORCHESTRATION is True


def test_go_preparation_reuses_host_feed_gate_and_forwards_exact_binding(
        verified_lifecycle):
    runner = Runner()
    summary = entry.probe_prevalidation_preparation(
        runner, env=_env(), runtime_ref=DIGEST, commit=COMMIT)

    assert summary.complete is True
    bind_calls = [call for call in runner.calls
                  if len(call[0]) > 1
                  and call[0][1] == "scripts/sentinel_feed_gate.py"]
    assert len(bind_calls) == 1
    bind_argv, bind_env = bind_calls[0]
    assert bind_argv[-4:] == ["--repo", str(ROOT), "--image", DIGEST]
    assert bind_env["SENTINEL_GIT_COMMIT"] == COMMIT
    assert bind_env["SENTINEL_RUNTIME_IMAGE_DIGEST"] == DIGEST

    compose_calls = [call for call in runner.calls
                     if call[0][:2] == ["docker", "compose"]]
    assert len(compose_calls) == 1
    compose_argv, compose_env = compose_calls[0]
    for key in entry._FEED_ENV_KEYS:
        position = compose_argv.index(key)
        assert compose_argv[position - 1] == "--env"
    assert compose_env["SENTINEL_GIT_COMMIT"] == COMMIT
    assert compose_env["SENTINEL_RUNTIME_IMAGE_DIGEST"] == DIGEST
    assert compose_env["SENTINEL_FEED_AUTHORIZED"] == "CLEAN_HEAD_IMAGE_V1"
    assert compose_env["SENTINEL_FEED_GIT_COMMIT"] == COMMIT
    assert compose_env["SENTINEL_FEED_RUNTIME_IMAGE_DIGEST"] == DIGEST
    assert "SENTINEL_FEED_SERVICE_MODE" not in compose_env
    assert not entry.go._BROKER_AUTH_ENV.intersection(compose_env)
    assert not entry.go._BROKER_AUTH_ENV.intersection(bind_env)


def test_go_preparation_fails_closed_before_mutation_when_binding_unavailable(
        verified_lifecycle):
    runner = Runner(bind_returncode=2)
    summary = entry.probe_prevalidation_preparation(
        runner, env=_env(), runtime_ref=DIGEST, commit=COMMIT)

    assert summary.status == entry.go.FAIL
    assert summary.complete is False
    assert not any(call[0][:2] == ["docker", "compose"]
                   for call in runner.calls)


def test_legacy_direct_entry_is_not_an_operator_path(capsys):
    assert entry.main([]) == 2
    assert "internal; use scripts/sentinel-go-validate.sh" in capsys.readouterr().err


def test_nas_launcher_reaches_feed_bound_entry_only_through_guarded_phase_chain():
    launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    phase = (ROOT / "scripts" / "sentinel_go_phase_controller.py").read_text(
        encoding="utf-8")
    verified = (ROOT / "scripts" / "sentinel_go_verified_entry.py").read_text(
        encoding="utf-8")
    assert "scripts/sentinel_go_verified_entry.py" in launcher
    assert "scripts/sentinel_go_validate_entry.py" not in launcher
    assert "import sentinel_go_validate_entry as entry" in phase
    assert "entry.probe_prevalidation_preparation" in phase
    assert "authorize_verified_orchestration()" in verified
    assert "exec \"$PYTHON\" scripts/sentinel_go_validate.py" not in launcher
