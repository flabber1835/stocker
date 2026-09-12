from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
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
    code = (
        "from pathlib import Path; import time; "
        f"Path({str(marker)!r}).write_text('ready'); time.sleep(0.8)"
    )
    process = subprocess.Popen(
        [sys.executable, str(BACKUP_LOCK), "hold", sys.executable, "-c", code],
        cwd=ROOT, env=_env(backup_root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), process.stderr.read() if process.stderr else "backup lock did not start"
    return process


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
        holder.wait(timeout=10)


def test_go_backup_path_recovers_immediately_after_external_backup_finishes(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    holder = _backup_holder(tmp_path, backup_root)
    holder.wait(timeout=10)

    retried = _go_then_backup(backup_root)

    assert retried.returncode == 0, retried.stderr


def test_go_and_backup_authorities_are_distinct_file_descriptors(tmp_path):
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()
    marker = tmp_path / "fds.txt"
    nested = (
        "import os,subprocess,sys; from pathlib import Path; "
        f"out=Path({str(marker)!r}); "
        "code=\"import os; from pathlib import Path; "
        f"Path({str(marker)!r}).write_text(os.environ['SENTINEL_GO_LOCK_FD']+','+os.environ['SENTINEL_BASE_BACKUP_LOCK_FD'])\"; "
        f"cmd=[sys.executable,{str(BACKUP_LOCK)!r},'hold',sys.executable,'-c',code]; "
        "raise SystemExit(subprocess.run(cmd,env=os.environ,check=False).returncode)"
    )
    completed = subprocess.run(
        [sys.executable, str(GO_LOCK), sys.executable, "-c", nested],
        cwd=ROOT, env=_env(backup_root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
    assert completed.returncode == 0, completed.stderr
    go_fd, backup_fd = marker.read_text().split(",")
    assert go_fd.isdigit() and backup_fd.isdigit()
    assert go_fd != backup_fd
