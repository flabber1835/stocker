from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
BASE = ROOT / "scripts" / "sentinel-base-backup.sh"
STATUS = ROOT / "scripts" / "sentinel-backup-status.sh"
LOCK = ROOT / "scripts" / "sentinel_backup_lock.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backup_shell_contracts_are_syntax_valid():
    if os.name == "nt":
        return
    for path in (BASE, STATUS):
        completed = subprocess.run(
            ["bash", "-n", str(path)], cwd=ROOT,
            capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr


def test_completed_backup_namespace_is_published_only_after_recovery_proof():
    source = _read(BASE)
    pg_verify = source.index("pg_verifybackup")
    wal_proof = source.index('test -f "/sentinel-backup/wal/$wal"')
    marker_publish = source.index(
        '> "/sentinel-backup/base/$name/sentinel-recovery-marker"')
    final_publish = source.index(
        'mv "/sentinel-backup/base/$staging" "/sentinel-backup/base/$final"')

    assert 'STAGING=".$NAME.part-$$"' in source
    assert pg_verify < wal_proof < marker_publish < final_publish
    assert 'test ! -e "/sentinel-backup/base/$final"' in source
    assert 'test ! -e "/sentinel-backup/base/$staging"' in source
    assert "SENTINEL_BASE_BACKUP_DB_MUTATION=RECOVERY_MARKER_SCHEMA_AND_ROW" in source


def test_status_considers_only_exact_completed_backup_names():
    source = _read(STATUS)
    assert "COMPLETED_NAME_RE='^base-[0-9]{8}T[0-9]{6}Z$'" in source
    assert 'grep -E "$COMPLETED_NAME_RE"' in source
    assert "SENTINEL_BACKUP_STATUS_REASON=" in source
    assert "BASE_BACKUP_MANIFEST_MISSING" in source
    assert "BASE_BACKUP_RECOVERY_MARKER_MISSING" in source
    assert "WAL_ARCHIVE_UNRESOLVED_FAILURE" in source


def test_base_backup_requires_kernel_backed_dedicated_lock():
    base = _read(BASE)
    helper = _read(LOCK)
    assert "sentinel_backup_lock.py verify" in base
    assert "sentinel_backup_lock.py hold" in base
    assert "fcntl.flock" in helper
    assert "LOCK_EX | fcntl.LOCK_NB" in helper
    assert "os.set_inheritable" in helper
    assert "pass_fds=(handle.fileno(),)" in helper
    assert "inherited.st_dev" in helper and "inherited.st_ino" in helper


@pytest.mark.skipif(os.name == "nt", reason="fcntl host lock is a Linux contract")
def test_base_backup_lock_serializes_two_processes():
    child = (
        "import time; print('LOCKED', flush=True); time.sleep(1.5)")
    first = subprocess.Popen(
        [sys.executable, str(LOCK), "hold", sys.executable, "-c", child],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert first.stdout is not None
    assert first.stdout.readline().strip() == "LOCKED"

    second = subprocess.run(
        [sys.executable, str(LOCK), "hold", sys.executable, "-c", "print('SECOND')"],
        cwd=ROOT, capture_output=True, text=True, check=False)

    assert second.returncode == 2
    assert "another Sentinel base backup is already running" in second.stderr
    assert first.wait(timeout=5) == 0
