from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_backup_refresh.py"
spec = importlib.util.spec_from_file_location("sentinel_go_backup_refresh_test", SCRIPT)
backup = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)

COMMIT = "a" * 40
BACKUP_PATH = "/backup/base/base-20260829T010203Z"


class FakeRunner:
    def __init__(self, status, refresh=None, verified=None):
        self.status = status
        self.refresh = refresh
        self.verified = verified
        self.calls = []
        self.status_calls = 0

    def run(self, argv, *, env=None, cwd=None):
        command = tuple(str(item) for item in argv)
        self.calls.append((command, dict(env or {})))
        if command == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(command, 0, stdout=COMMIT + "\n", stderr="")
        if command == ("git", "status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command == ("bash", "scripts/sentinel-backup-status.sh"):
            self.status_calls += 1
            return self.status
        if command == ("bash", "scripts/sentinel-base-backup.sh"):
            if self.refresh is None:
                raise AssertionError("unexpected base-backup refresh")
            return self.refresh
        if command == (
                "bash", "scripts/sentinel-backup-status.sh", "--backup", BACKUP_PATH):
            if self.verified is None:
                raise AssertionError("unexpected exact backup verification")
            return self.verified
        raise AssertionError("unexpected command %r" % (command,))


def _cp(rc, *, out="", err=""):
    return subprocess.CompletedProcess(["x"], rc, stdout=out, stderr=err)


def _env():
    return {
        "SENTINEL_POSTGRES_PASSWORD": "db-secret",
        "SENTINEL_BACKUP_DIR": "/backup",
        "ALPACA_API_KEY": "broker-key",
        "ALPACA_SECRET_KEY": "broker-secret",
        "SENTINEL_PAPER_ACCOUNT_ID": "paper-account",
    }


@pytest.fixture(autouse=True)
def _verified_go_authority(monkeypatch):
    monkeypatch.setitem(backup.phase._PHASE, "certified", True)
    monkeypatch.setattr(
        backup.go_lock, "lifecycle_lock_is_held", lambda env=None: True)
    monkeypatch.setattr(
        backup.go_lock, "current_run_token", lambda: "one-run-capability")


def test_direct_refresh_refuses_without_exact_artifact_certification(monkeypatch):
    monkeypatch.setitem(backup.phase._PHASE, "certified", False)
    runner = FakeRunner(_cp(0, out="backup_ready:true\n"))

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BACKUP_REFRESH_CERTIFICATION_NOT_PROVEN"
    assert runner.calls == []


def test_direct_refresh_refuses_without_lifecycle_lock(monkeypatch):
    monkeypatch.setattr(
        backup.go_lock, "lifecycle_lock_is_held", lambda env=None: False)
    runner = FakeRunner(_cp(0, out="backup_ready:true\n"))

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BACKUP_REFRESH_LIFECYCLE_LOCK_NOT_PROVEN"
    assert runner.calls == []


def test_healthy_backup_checkpoint_does_not_create_another_backup():
    runner = FakeRunner(_cp(0, out="backup_ready:true\n"))

    refreshed = backup.ensure_recent_verified_base_backup(
        runner, env=_env(), commit=COMMIT)

    assert refreshed is False
    assert not any(call[0] == ("bash", "scripts/sentinel-base-backup.sh")
                   for call in runner.calls)


@pytest.mark.parametrize("message", [
    "REFUSED: latest base backup is 246h old (max 30h)\n",
    "REFUSED: last WAL archive is 31h old\n",
    "REFUSED: no base backup exists\n",
    "REFUSED: no successful WAL archive is recorded\n",
])
def test_repairable_freshness_states_create_and_verify_exact_new_backup(message):
    runner = FakeRunner(
        _cp(4, err=message),
        refresh=_cp(0, out="verified_base_backup:" + BACKUP_PATH + "\n"),
        verified=_cp(0, out="backup_ready:true\n"),
    )

    refreshed = backup.ensure_recent_verified_base_backup(
        runner, env=_env(), commit=COMMIT)

    assert refreshed is True
    assert any(call[0] == ("bash", "scripts/sentinel-base-backup.sh")
               for call in runner.calls)
    assert any(call[0] == (
        "bash", "scripts/sentinel-backup-status.sh", "--backup", BACKUP_PATH)
        for call in runner.calls)


def test_structural_backup_failure_remains_operator_refusal():
    runner = FakeRunner(_cp(4, err="REFUSED: archive_mode=off\n"))

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BACKUP_HEALTH_STRUCTURAL_REFUSAL"
    assert not any(call[0] == ("bash", "scripts/sentinel-base-backup.sh")
                   for call in runner.calls)


def test_refresh_must_emit_one_exact_verified_backup_path():
    runner = FakeRunner(
        _cp(4, err="REFUSED: latest base backup is 246h old (max 30h)\n"),
        refresh=_cp(0, out="base backup completed\n"),
    )

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BASE_BACKUP_REFRESH_EVIDENCE_UNAVAILABLE"


def test_refresh_failure_is_fail_closed():
    runner = FakeRunner(
        _cp(4, err="REFUSED: no base backup exists\n"),
        refresh=_cp(4, err="REFUSED: archive_mode=off\n"),
    )

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BASE_BACKUP_REFRESH_FAILED"


def test_backup_subprocesses_never_receive_broker_authority():
    runner = FakeRunner(
        _cp(4, err="REFUSED: latest base backup is 246h old (max 30h)\n"),
        refresh=_cp(0, out="verified_base_backup:" + BACKUP_PATH + "\n"),
        verified=_cp(0, out="backup_ready:true\n"),
    )

    backup.ensure_recent_verified_base_backup(runner, env=_env(), commit=COMMIT)

    for _command, env in runner.calls:
        assert "ALPACA_API_KEY" not in env
        assert "ALPACA_SECRET_KEY" not in env
        assert "SENTINEL_PAPER_ACCOUNT_ID" not in env


def test_checkout_identity_is_rechecked_after_refresh():
    runner = FakeRunner(
        _cp(4, err="REFUSED: latest base backup is 246h old (max 30h)\n"),
        refresh=_cp(0, out="verified_base_backup:" + BACKUP_PATH + "\n"),
        verified=_cp(0, out="backup_ready:true\n"),
    )

    backup.ensure_recent_verified_base_backup(runner, env=_env(), commit=COMMIT)

    head_checks = [call for call in runner.calls
                   if call[0] == ("git", "rev-parse", "HEAD")]
    dirty_checks = [call for call in runner.calls
                    if call[0] == (
                        "git", "status", "--porcelain=v1", "--untracked-files=all")]
    assert len(head_checks) == 2
    assert len(dirty_checks) == 2


def test_verified_entry_installs_backup_refresh_after_phase_guard():
    source = (ROOT / "scripts" / "sentinel_go_verified_entry.py").read_text(
        encoding="utf-8")
    phase_install = source.index("phase.install()")
    backup_install = source.index("backup_refresh.install()")
    observability = source.index("observability.install", backup_install)
    assert phase_install < backup_install < observability
    assert "if not development:" in source[phase_install:backup_install]


def test_overlay_requires_certification_and_lifecycle_capability_before_backup():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'phase._PHASE.get("certified")' in source
    assert "go_lock.lifecycle_lock_is_held(env)" in source
    assert "go_lock.current_run_token() is None" in source
    assert "scripts/sentinel-backup-status.sh" in source
    assert "scripts/sentinel-base-backup.sh" in source
