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
RUNTIME_REF = "sha256:" + "b" * 64
TOKEN = "c" * 64
BACKUP_PATH = "/backup/base/base-20260829T010203Z"
STATUS_PREFIX = "SENTINEL_BACKUP_STATUS_REASON="
DB_MUTATION = "SENTINEL_BASE_BACKUP_DB_MUTATION=RECOVERY_MARKER_SCHEMA_AND_ROW"
REFRESH_OUT = DB_MUTATION + "\nverified_base_backup:" + BACKUP_PATH + "\n"


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


def _status(code: str, message: str, *, diagnostic: str = ""):
    return _cp(
        4,
        err=(diagnostic + ("\n" if diagnostic else "")
             + STATUS_PREFIX + code + "\nREFUSED: " + message + "\n"),
    )


def _env():
    return {
        "SENTINEL_POSTGRES_PASSWORD": "db-secret",
        "SENTINEL_BACKUP_DIR": "/backup",
        "ALPACA_API_KEY": "broker-key",
        "ALPACA_SECRET_KEY": "broker-secret",
        "SENTINEL_PAPER_ACCOUNT_ID": "paper-account",
        backup.go_lock.RUN_TOKEN_ENV: TOKEN,
    }


@pytest.fixture(autouse=True)
def _verified_go_authority(monkeypatch):
    monkeypatch.setitem(backup.phase._PHASE, "certified", True)
    monkeypatch.setattr(
        backup.go_lock, "lifecycle_lock_is_held", lambda env=None: True)

    def current_run_token(env=None):
        if env is None:
            return TOKEN
        return TOKEN if str(env.get(backup.go_lock.RUN_TOKEN_ENV) or "") == TOKEN else None

    monkeypatch.setattr(backup.go_lock, "current_run_token", current_run_token)


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


def test_direct_refresh_requires_exact_current_run_token_in_supplied_environment():
    env = _env()
    env[backup.go_lock.RUN_TOKEN_ENV] = "d" * 64
    runner = FakeRunner(_cp(0, out="backup_ready:true\n"))

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=env, commit=COMMIT)

    assert exc.value.reason_code == "BACKUP_REFRESH_RUN_CAPABILITY_NOT_PROVEN"
    assert runner.calls == []


def test_healthy_backup_checkpoint_does_not_create_another_backup():
    runner = FakeRunner(_cp(0, out="backup_ready:true\n"))

    result = backup.ensure_recent_verified_base_backup(
        runner, env=_env(), commit=COMMIT)

    assert result.refreshed is False
    assert result.reason_code == "BACKUP_HEALTHY"
    assert result.recovery_marker_database_mutation is False
    assert not any(call[0] == ("bash", "scripts/sentinel-base-backup.sh")
                   for call in runner.calls)


@pytest.mark.parametrize(("code", "message"), [
    ("BASE_BACKUP_STALE", "latest base backup is 246h old (max 30h)"),
    ("WAL_ARCHIVE_STALE", "last WAL archive is 31h old"),
    ("BASE_BACKUP_MISSING", "no base backup exists"),
    ("BASE_BACKUP_NOT_FOUND", "requested base backup does not exist: /backup/base/x"),
    ("WAL_ARCHIVE_UNINITIALIZED", "no successful WAL archive is recorded"),
    ("WAL_ARCHIVE_UNRESOLVED_FAILURE",
     "an unresolved archive failure is newer than the last success"),
    ("BASE_BACKUP_MANIFEST_MISSING",
     "latest backup has no manifest: /backup/base/base-20260828T010203Z"),
    ("BASE_BACKUP_RECOVERY_MARKER_MISSING",
     "latest backup lacks a post-base recovery marker"),
])
def test_repairable_states_create_and_verify_exact_new_backup(code, message):
    runner = FakeRunner(
        _status(code, message),
        refresh=_cp(0, out=REFRESH_OUT),
        verified=_cp(0, out="backup_ready:true\n"),
    )

    result = backup.ensure_recent_verified_base_backup(
        runner, env=_env(), commit=COMMIT)

    assert result.refreshed is True
    assert result.reason_code == code
    assert result.backup_path == BACKUP_PATH
    assert result.recovery_marker_database_mutation is True
    assert result.post_refresh_exact_path_verified is True
    assert any(call[0] == ("bash", "scripts/sentinel-base-backup.sh")
               for call in runner.calls)
    assert any(call[0] == (
        "bash", "scripts/sentinel-backup-status.sh", "--backup", BACKUP_PATH)
        for call in runner.calls)


def test_repairable_reason_is_not_broken_by_unrelated_diagnostics():
    runner = FakeRunner(
        _status(
            "BASE_BACKUP_STALE",
            "latest base backup is 246h old (max 30h)",
            diagnostic="WARN: Docker Compose emitted a harmless diagnostic"),
        refresh=_cp(0, out=REFRESH_OUT),
        verified=_cp(0, out="backup_ready:true\n"),
    )

    result = backup.ensure_recent_verified_base_backup(
        runner, env=_env(), commit=COMMIT)

    assert result.refreshed is True
    assert result.reason_code == "BASE_BACKUP_STALE"


def test_structural_backup_failure_remains_operator_refusal():
    runner = FakeRunner(_status("ARCHIVE_MODE_DISABLED", "archive_mode=off"))

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BACKUP_HEALTH_STRUCTURAL_REFUSAL"
    assert not any(call[0] == ("bash", "scripts/sentinel-base-backup.sh")
                   for call in runner.calls)


def test_status_reason_requires_exit_four_and_one_well_formed_reason():
    assert backup._repairable_reason(_cp(
        2, err=STATUS_PREFIX + "BASE_BACKUP_STALE\n")) is None
    assert backup._repairable_reason(_cp(
        4, err=(STATUS_PREFIX + "BASE_BACKUP_STALE\n"
                + STATUS_PREFIX + "WAL_ARCHIVE_STALE\n"))) is None
    assert backup._repairable_reason(_cp(
        4, err=STATUS_PREFIX + "bad-code\n")) is None


def test_refresh_must_emit_one_exact_verified_backup_path():
    runner = FakeRunner(
        _status("BASE_BACKUP_STALE", "latest base backup is 246h old (max 30h)"),
        refresh=_cp(0, out=DB_MUTATION + "\nbase backup completed\n"),
    )

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BASE_BACKUP_REFRESH_EVIDENCE_UNAVAILABLE"


def test_refresh_must_prove_recovery_marker_database_mutation():
    runner = FakeRunner(
        _status("BASE_BACKUP_STALE", "latest base backup is 246h old (max 30h)"),
        refresh=_cp(0, out="verified_base_backup:" + BACKUP_PATH + "\n"),
    )

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BASE_BACKUP_DB_MUTATION_EVIDENCE_UNAVAILABLE"


def test_refresh_failure_is_fail_closed():
    runner = FakeRunner(
        _status("BASE_BACKUP_MISSING", "no base backup exists"),
        refresh=_cp(4, err="REFUSED: archive_mode=off\n"),
    )

    with pytest.raises(backup.BackupRefreshRefused) as exc:
        backup.ensure_recent_verified_base_backup(
            runner, env=_env(), commit=COMMIT)

    assert exc.value.reason_code == "BASE_BACKUP_REFRESH_FAILED"


def test_backup_subprocesses_never_receive_broker_authority():
    runner = FakeRunner(
        _status("BASE_BACKUP_STALE", "latest base backup is 246h old (max 30h)"),
        refresh=_cp(0, out=REFRESH_OUT),
        verified=_cp(0, out="backup_ready:true\n"),
    )

    backup.ensure_recent_verified_base_backup(runner, env=_env(), commit=COMMIT)

    for _command, env in runner.calls:
        assert "ALPACA_API_KEY" not in env
        assert "ALPACA_SECRET_KEY" not in env
        assert "SENTINEL_PAPER_ACCOUNT_ID" not in env
        assert env[backup.go_lock.RUN_TOKEN_ENV] == TOKEN


def test_checkout_identity_is_rechecked_after_refresh():
    runner = FakeRunner(
        _status("BASE_BACKUP_STALE", "latest base backup is 246h old (max 30h)"),
        refresh=_cp(0, out=REFRESH_OUT),
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


def test_local_audit_retains_exact_path_and_publicly_bindable_digest(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        backup.phase, "_atomic_write",
        lambda path, payload: captured.update(path=path, payload=payload))
    result = backup.BackupRefreshResult(
        refreshed=True,
        reason_code="WAL_ARCHIVE_UNRESOLVED_FAILURE",
        backup_path=BACKUP_PATH,
        recovery_marker_database_mutation=True,
        post_refresh_exact_path_verified=True,
        checkout_identity_verified=True,
    )

    digest = backup._write_refresh_audit(commit=COMMIT, result=result)

    assert captured["path"] == backup._AUDIT_PATH
    assert captured["payload"]["verified_backup_path"] == BACKUP_PATH
    assert captured["payload"]["verified_backup_path_sha256"] == (
        result.backup_path_sha256)
    assert captured["payload"]["recovery_marker_database_mutation"] is True
    assert captured["payload"]["post_refresh_exact_path_verified"] is True
    assert captured["payload"]["evidence_sha256"] == digest


def test_backup_audit_digest_is_folded_into_preparation_evidence():
    base = backup.go.PreparationSummary(
        status=backup.go.PASS,
        runtime_image_digest=RUNTIME_REF,
        schema_migration_attempted=True,
        bounded_sharadar_daily_attempted=True,
        broker_mutation_attempts=0,
        evidence_sha256="1" * 64,
        elapsed_milliseconds=123,
    )
    audit = "2" * 64

    bound = backup._bind_backup_audit(base, audit_sha256=audit)

    assert bound.complete
    assert bound.elapsed_milliseconds == 123
    assert bound.evidence_sha256 == backup.go._evidence_digest({
        "base_preparation_evidence_sha256": "1" * 64,
        "backup_refresh_audit_sha256": audit,
        "authorized_database_mutation_scopes": [
            "VERIFIED_BASE_BACKUP_RECOVERY_MARKER",
            "SCHEMA_MIGRATION",
            "BOUNDED_SHARADAR_DAILY_INGEST",
        ],
    })


def test_certified_overlay_missing_call_contract_fails_closed(monkeypatch):
    called = []
    monkeypatch.setattr(
        backup, "_ORIGINAL_PREPARATION",
        lambda *args, **kwargs: called.append((args, kwargs)))
    monkeypatch.setattr(
        backup, "_write_refresh_audit", lambda **_kwargs: "3" * 64)

    result = backup._preparation_with_backup_refresh(
        env=_env(), commit=COMMIT, runtime_ref=RUNTIME_REF)

    assert result.status == backup.go.NOT_PROVEN
    assert called == []


def test_certified_overlay_mismatched_run_token_cannot_fall_through(monkeypatch):
    called = []
    monkeypatch.setattr(
        backup, "_ORIGINAL_PREPARATION",
        lambda *args, **kwargs: called.append((args, kwargs)))
    monkeypatch.setattr(
        backup, "_write_refresh_audit", lambda **_kwargs: "4" * 64)
    env = _env()
    env[backup.go_lock.RUN_TOKEN_ENV] = "d" * 64

    result = backup._preparation_with_backup_refresh(
        object(), env=env, commit=COMMIT, runtime_ref=RUNTIME_REF)

    assert result.status == backup.go.NOT_PROVEN
    assert called == []


def test_verified_entry_installs_backup_refresh_after_phase_guard():
    source = (ROOT / "scripts" / "sentinel_go_verified_entry.py").read_text(
        encoding="utf-8")
    phase_install = source.index("phase.install()")
    backup_install = source.index("backup_refresh.install()")
    observability = source.index("observability.install", backup_install)
    assert phase_install < backup_install < observability
    assert "if not development:" in source[phase_install:backup_install]


def test_overlay_requires_exact_capability_and_machine_status_contract():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'phase._PHASE.get("certified")' in source
    assert "go_lock.lifecycle_lock_is_held(env)" in source
    assert "go_lock.current_run_token(env)" in source
    assert "hmac.compare_digest(process_token, env_token)" in source
    assert "SENTINEL_BACKUP_STATUS_REASON=" in source
    assert "WAL_ARCHIVE_UNRESOLVED_FAILURE" in source
    assert "BASE_BACKUP_RECOVERY_MARKER_MISSING" in source
    assert "BACKUP_REFRESH_CALL_CONTRACT_INVALID" in source
    assert "scripts/sentinel-backup-status.sh" in source
    assert "scripts/sentinel-base-backup.sh" in source
