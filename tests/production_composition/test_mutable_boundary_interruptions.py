from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_backup_refresh as backup  # noqa: E402
import sentinel_go_phase_entry as phase  # noqa: E402
import sentinel_go_validate_entry as entry  # noqa: E402
import sentinel_go_verified_entry as verified  # noqa: E402

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64


class SequenceRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        self.calls.append([str(x) for x in argv])
        if not self.results:
            raise AssertionError(self.calls)
        return self.results.pop(0)


def cp(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["fixture"], rc, stdout=stdout, stderr=stderr)


def test_kill_during_base_backup_refresh_is_fail_closed(monkeypatch):
    runner = SequenceRunner([
        cp(4, stdout="SENTINEL_BACKUP_STATUS_REASON=WAL_ARCHIVE_STALE\n"),
        cp(137, stderr="Killed"),
    ])
    monkeypatch.setattr(backup, "_require_go_authority", lambda _env: None)
    monkeypatch.setattr(backup, "_require_checkout_exact", lambda *_a, **_k: None)

    with pytest.raises(backup.BackupRefreshRefused) as caught:
        backup.ensure_recent_verified_base_backup(
            runner, env={}, commit=COMMIT)

    assert caught.value.reason_code == "BASE_BACKUP_REFRESH_FAILED"
    assert len(runner.calls) == 2
    assert runner.calls[1][-1] == "scripts/sentinel-base-backup.sh"


def test_kill_after_backup_refresh_before_audit_cannot_enter_schema_or_ingest(monkeypatch):
    result = backup.BackupRefreshResult(
        refreshed=True,
        reason_code="WAL_ARCHIVE_STALE",
        backup_path="/tmp/verified-backup",
        recovery_marker_database_mutation=True,
        post_refresh_exact_path_verified=True,
        checkout_identity_verified=True,
    )
    mutations = []
    monkeypatch.setitem(backup.phase._PHASE, "certified", True)
    monkeypatch.setattr(backup, "_require_go_authority", lambda _env: None)
    monkeypatch.setattr(backup, "ensure_recent_verified_base_backup", lambda *_a, **_k: result)
    monkeypatch.setattr(
        backup, "_write_refresh_audit",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("simulated crash")))
    monkeypatch.setattr(
        backup, "_ORIGINAL_PREPARATION",
        lambda *_a, **_k: mutations.append("schema-or-ingest"))

    summary = backup._preparation_with_backup_refresh(
        SequenceRunner([]), env={}, commit=COMMIT, runtime_ref=DIGEST)

    assert summary.status == backup.go.NOT_PROVEN
    assert summary.schema_migration_attempted is False
    assert summary.bounded_sharadar_daily_attempted is False
    assert mutations == []


def test_schema_migration_precedes_ingest_and_publication_observation_in_production_code():
    code = entry.go._PREPARATION_CODE
    schema_at = code.index("schema.ensure_schema(c)")
    migration_at = code.index("store.migrate_schema(c)")
    ingest_at = code.index("ingest.daily(c, today=target)")
    publication_at = code.index("publication.current(c)", ingest_at)
    assert schema_at < migration_at < ingest_at < publication_at


@pytest.mark.parametrize("signal_rc", [137, 143])
def test_kill_inside_schema_ingest_preparation_child_is_not_converted_to_success(
        monkeypatch, signal_rc):
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)
    monkeypatch.setattr(entry.go_lock, "lifecycle_lock_is_held", lambda env=None: True)

    def killed(*_args, **_kwargs):
        raise SystemExit(signal_rc)

    monkeypatch.setattr(entry, "_CORE_PREPARATION_PROBE", killed)
    with pytest.raises(SystemExit) as caught:
        entry.probe_prevalidation_preparation(
            object(), env={}, runtime_ref=DIGEST, commit=COMMIT)
    assert caught.value.code == signal_rc


def _configure_verified_main(monkeypatch, *, controller_rc: int, written: list):
    monkeypatch.setattr(verified.phase, "_strict_target", lambda _raw: None)
    monkeypatch.setattr(
        verified.controller, "_target_from_argv",
        lambda _raw: ("DUAL_RUN_OBSERVATION", []))
    monkeypatch.setattr(verified.go_lock, "lifecycle_lock_is_held", lambda: True)
    monkeypatch.setattr(verified.go_lock, "current_run_token", lambda: "1" * 64)
    monkeypatch.setattr(verified, "_clean_run_pass_path", lambda: None)
    monkeypatch.setattr(
        verified.controller.entry, "authorize_verified_orchestration", lambda: None)
    monkeypatch.setattr(
        verified, "_install_wallclock_independent_dual_overlay", lambda **_k: None)
    monkeypatch.setattr(verified.phase, "install", lambda: None)
    monkeypatch.setattr(verified, "_install_software_certifier", lambda **_k: None)
    monkeypatch.setattr(backup, "install", lambda: None)
    monkeypatch.setattr(verified.probe_contract, "install", lambda **_k: None)
    monkeypatch.setattr(verified.actual_deadline_guard, "install", lambda: None)
    monkeypatch.setattr(verified.observability, "install", lambda **_k: None)
    monkeypatch.setattr(verified.controller, "main", lambda _raw: controller_rc)
    monkeypatch.setattr(verified, "_write_run_pass", lambda **_k: written.append(True))


def test_nonzero_controller_result_cannot_create_requested_target_pass(monkeypatch):
    written = []
    _configure_verified_main(monkeypatch, controller_rc=137, written=written)

    rc = verified.main([])

    assert rc == 137
    assert written == []


def test_run_pass_is_created_only_after_successful_controller_completion(monkeypatch):
    written = []
    _configure_verified_main(monkeypatch, controller_rc=0, written=written)

    rc = verified.main([])

    assert rc == 0
    assert written == [True]


def test_bundle_emission_exception_cannot_be_misrepresented_as_completed_evidence(monkeypatch):
    sentinel = RuntimeError("simulated bundle emission crash")
    monkeypatch.setattr(
        phase, "_ORIGINAL_EMIT",
        lambda *_a, **_k: (_ for _ in ()).throw(sentinel))
    with pytest.raises(RuntimeError, match="bundle emission crash"):
        phase._emit_at_completion(object(), created_at=None)
