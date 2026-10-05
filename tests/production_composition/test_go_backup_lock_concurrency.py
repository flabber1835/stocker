from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import selectors

import pytest

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
GO_LOCK = ROOT / "scripts" / "sentinel_go_lock.py"
BACKUP_LOCK = ROOT / "scripts" / "sentinel_backup_lock.py"


def _env(backup_root: Path):
    env = dict(os.environ)
    for key in (
        "SENTINEL_GO_LOCK_HELD", "SENTINEL_GO_LOCK_FD", "SENTINEL_GO_RUN_TOKEN",
        "SENTINEL_BASE_BACKUP_LOCK_HELD", "SENTINEL_BASE_BACKUP_LOCK_FD",
    ):
        env.pop(key, None)
    env["SENTINEL_BASE_BACKUP_LOCK_ROOT"] = str(backup_root.resolve())
    return env


def _backup_holder(tmp_path: Path, backup_root: Path):
    marker = tmp_path / "backup.ready"
    release = tmp_path / "backup.release"
    code = (
        "from pathlib import Path\nimport time\n"
        f"Path({str(marker)!r}).write_text('ready')\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(.01)\n"
        f"Path({str(marker)!r}).unlink()\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(BACKUP_LOCK), "hold", sys.executable, "-c", code],
        cwd=ROOT, env=_env(backup_root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not marker.exists():
        release.touch()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        raise AssertionError("backup lock did not start: " + stdout + stderr)
    process.release_path = release
    return process


def _release_holder(process):
    process.release_path.touch()
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stdout + stderr


def _go_then_backup(backup_root: Path):
    child = (
        "import os,subprocess,sys; "
        f"cmd=[sys.executable,{str(BACKUP_LOCK)!r},'hold',sys.executable,'-c','raise SystemExit(0)']; "
        "raise SystemExit(subprocess.run(cmd,env=os.environ,check=False).returncode)"
    )
    return subprocess.run(
        [sys.executable, str(GO_LOCK), sys.executable, "-c", child],
        cwd=ROOT, env=_env(backup_root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=10, check=False,
    )


def test_external_base_backup_contention_refuses_nested_go_backup_without_deadlock(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    holder = _backup_holder(tmp_path, backup_root)
    try:
        started = time.monotonic()
        blocked = _go_then_backup(backup_root)
        elapsed = time.monotonic() - started
        assert blocked.returncode == 2
        assert elapsed < 5
        assert "another Sentinel base backup is already running" in blocked.stderr
    finally:
        _release_holder(holder)


def test_go_backup_path_recovers_immediately_after_external_backup_finishes(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    holder = _backup_holder(tmp_path, backup_root)
    _release_holder(holder)

    retried = _go_then_backup(backup_root)

    assert retried.returncode == 0, retried.stderr


def test_go_and_backup_authorities_use_distinct_lock_resources(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    marker = tmp_path / "lock-resources.txt"
    nested = (
        "import os,subprocess,sys; from pathlib import Path; "
        f"out=Path({str(marker)!r}); "
        "go=os.fstat(int(os.environ['SENTINEL_GO_LOCK_FD'])); "
        "out.write_text(str(go.st_dev)+':'+str(go.st_ino)); "
        "code=\"import os; from pathlib import Path; "
        f"out=Path({str(marker)!r}); "
        "backup=os.fstat(int(os.environ['SENTINEL_BASE_BACKUP_LOCK_FD'])); "
        "out.write_text(out.read_text()+'|'+str(backup.st_dev)+':'+str(backup.st_ino))\"; "
        f"cmd=[sys.executable,{str(BACKUP_LOCK)!r},'hold',sys.executable,'-c',code]; "
        "raise SystemExit(subprocess.run(cmd,env=os.environ,check=False).returncode)"
    )
    completed = subprocess.run(
        [sys.executable, str(GO_LOCK), sys.executable, "-c", nested],
        cwd=ROOT, env=_env(backup_root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
    assert completed.returncode == 0, completed.stderr
    go_resource, backup_resource = marker.read_text().split("|")
    assert all(part.isdigit() for part in go_resource.split(":"))
    assert all(part.isdigit() for part in backup_resource.split(":"))
    assert go_resource != backup_resource


def test_deployment_waits_for_backup_owner_before_entering_child(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    holder = _backup_holder(tmp_path, backup_root)
    marker = tmp_path / "backup.ready"
    code = f"from pathlib import Path; assert not Path({str(marker)!r}).exists()"
    try:
        waited = subprocess.Popen(
            [sys.executable, str(BACKUP_LOCK), "hold", "--wait-seconds", "5",
             sys.executable, "-c", code], cwd=ROOT, env=_env(backup_root),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with selectors.DefaultSelector() as selector:
            selector.register(waited.stderr, selectors.EVENT_READ)
            assert selector.select(timeout=5), "contender never reported waiting"
            announcement = waited.stderr.readline()
        assert "[WAIT]" in announcement
        _release_holder(holder)
        stdout, stderr = waited.communicate(timeout=10)
        assert waited.returncode == 0, waited.stderr
        assert stdout == "", stderr
    finally:
        if holder.poll() is None:
            _release_holder(holder)
        if 'waited' in locals():
            if waited.poll() is None:
                waited.terminate()
            waited.communicate(timeout=10)


def test_deployment_wait_exhaustion_never_starts_backup_child(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    holder = _backup_holder(tmp_path, backup_root)
    entered = tmp_path / "second-backup"
    code = f"from pathlib import Path; Path({str(entered)!r}).touch()"
    try:
        started = time.monotonic()
        refused = subprocess.run(
            [sys.executable, str(BACKUP_LOCK), "hold", "--wait-seconds", "1",
             sys.executable, "-c", code], cwd=ROOT, env=_env(backup_root),
            capture_output=True, text=True, timeout=10, check=False)
        assert refused.returncode == 2, refused.stderr
        assert time.monotonic() - started < 5
        assert not entered.exists()
    finally:
        _release_holder(holder)


@pytest.mark.parametrize("wait", ["-1", "3661", "1.5", "NaN", "9" * 100, "١"])
def test_invalid_backup_wait_never_starts_child(tmp_path, wait):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    entered = tmp_path / "second-backup"
    code = f"from pathlib import Path; Path({str(entered)!r}).touch()"
    refused = subprocess.run(
        [sys.executable, str(BACKUP_LOCK), "hold", "--wait-seconds", wait,
         sys.executable, "-c", code], cwd=ROOT, env=_env(backup_root),
        capture_output=True, text=True, timeout=10, check=False)
    assert refused.returncode == 2
    assert not entered.exists()
