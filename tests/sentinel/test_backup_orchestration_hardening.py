from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
BASE = ROOT / "scripts" / "sentinel-base-backup.sh"
STATUS = ROOT / "scripts" / "sentinel-backup-status.sh"
RESTORE = ROOT / "scripts" / "sentinel-restore-drill.sh"
LOCK = ROOT / "scripts" / "sentinel_backup_lock.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backup_shell_contracts_are_syntax_valid():
    if os.name == "nt":
        return
    for path in (BASE, STATUS, RESTORE):
        completed = subprocess.run(
            ["bash", "-n", str(path)], cwd=ROOT,
            capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr


def test_completed_backup_namespace_is_published_only_after_recovery_proof():
    source = _read(BASE)
    pg_verify = source.index("pg_verifybackup")
    wal_proof = source.index('test -f "/sentinel-backup/wal/$wal"')
    marker_publish = source.index(
        'metadata="/sentinel-backup/base/$name/sentinel-recovery-marker"')
    marker_sync = source.index('sync "$metadata"', marker_publish)
    final_publish = source.index(
        'mv -T --no-clobber -- "/sentinel-backup/base/$staging" '
        '"/sentinel-backup/base/$final"')
    namespace_sync = source.index("sync -f /sentinel-backup/base", final_publish)

    assert 'STAGING=".$NAME.part-$$"' in source
    assert pg_verify < wal_proof < marker_publish < marker_sync < final_publish
    assert final_publish < namespace_sync
    assert 'test ! -e "/sentinel-backup/base/$final"' in source
    assert 'test ! -e "/sentinel-backup/base/$staging"' in source
    assert "SENTINEL_BASE_BACKUP_DB_MUTATION=RECOVERY_MARKER_SCHEMA_AND_ROW" in source


def test_hidden_staging_is_ignored_and_reaped_under_the_backup_lock():
    source = _read(BASE)
    assert '-name ".base-*.part-*" -exec rm -rf -- {} +' in source
    assert source.index("sentinel_backup_lock.py verify") < source.index(
        '-name ".base-*.part-*" -exec rm -rf -- {} +')
    assert 'case "$staging" in .base-*.part-*)' in source


def test_status_selects_newest_complete_backup_only():
    source = _read(STATUS)
    assert "COMPLETED_NAME_RE='^base-[0-9]{8}T[0-9]{6}Z$'" in source
    candidate_sort = 'grep -E "$COMPLETED_NAME_RE" | sort -r'
    manifest = 'test -f "/sentinel-backup/base/$name/backup_manifest"'
    marker = 'test -f "/sentinel-backup/base/$name/sentinel-recovery-marker"'
    assignment = 'NAME="$CANDIDATE"'
    assert candidate_sort in source
    assert manifest in source and marker in source and assignment in source
    assert source.index(candidate_sort) > source.index(manifest)
    assert source.index(manifest) < source.index(assignment)
    assert source.index(marker) < source.index(assignment)
    assert "no complete base backup exists" in source
    assert "SENTINEL_BACKUP_STATUS_REASON=" in source
    assert "WAL_ARCHIVE_UNRESOLVED_FAILURE" in source


def test_restore_selects_newest_complete_backup_only():
    source = _read(RESTORE)
    assert "COMPLETED_NAME_RE='^base-[0-9]{8}T[0-9]{6}Z$'" in source
    assert '[[ "$NAME" =~ $COMPLETED_NAME_RE ]]' in source
    assert 'grep -E "$COMPLETED_NAME_RE" | sort -r' in source
    assert 'test -f "/sentinel-backup/base/$name/backup_manifest"' in source
    assert 'test -f "/sentinel-backup/base/$name/sentinel-recovery-marker"' in source
    assert "no complete base backup exists" in source
    assert '-name "base-*"' not in source
    assert 'case "$NAME" in base-*)' not in source


def test_base_backup_requires_target_bound_kernel_lock():
    base = _read(BASE)
    helper = _read(LOCK)
    assert "SENTINEL_BASE_BACKUP_LOCK_ROOT" in base
    assert "sentinel_backup_lock.py verify" in base
    assert "sentinel_backup_lock.py hold" in base
    assert "LOCK_ROOT_ENV" in helper
    assert "hashlib.sha256" in helper
    assert "os.getuid()" in helper
    assert "fcntl.flock" in helper
    assert "LOCK_EX | fcntl.LOCK_NB" in helper
    assert "os.set_inheritable" in helper
    assert "pass_fds=(handle.fileno(),)" in helper
    assert "inherited.st_dev" in helper and "inherited.st_ino" in helper


@pytest.mark.skipif(os.name == "nt", reason="fcntl host lock is a Linux contract")
def test_base_backup_lock_serializes_two_processes_for_same_target(tmp_path):
    target = (tmp_path / "durable-target")
    target.mkdir()
    env = {
        **os.environ,
        "SENTINEL_BASE_BACKUP_LOCK_ROOT": str(target.resolve()),
    }
    child = "import time; print('LOCKED', flush=True); time.sleep(1.5)"
    first = subprocess.Popen(
        [sys.executable, str(LOCK), "hold", sys.executable, "-c", child],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert first.stdout is not None
    assert first.stdout.readline().strip() == "LOCKED"

    second = subprocess.run(
        [sys.executable, str(LOCK), "hold", sys.executable, "-c", "print('SECOND')"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False)

    assert second.returncode == 2
    assert "another Sentinel base backup is already running for this durable target" in second.stderr
    assert first.wait(timeout=5) == 0


@pytest.mark.skipif(os.name == "nt", reason="fcntl host lock is a Linux contract")
def test_different_checkouts_derive_same_lock_from_same_target(tmp_path):
    target = (tmp_path / "durable-target")
    target.mkdir()
    # The lock helper hashes only the canonical durable target into a per-user
    # host lock path; its Git checkout location is absent from that identity.
    source = _read(LOCK)
    assert 'hashlib.sha256(str(canonical).encode("utf-8"))' in source
    assert 'Path("/tmp") / ("sentinel-base-backup-locks-%d" % os.getuid())' in source
    assert 'ROOT / "artifacts"' not in source
