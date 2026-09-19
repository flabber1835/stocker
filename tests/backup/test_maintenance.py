"""Host maintenance decisions and real process/physical-copy exclusion."""
from __future__ import annotations

import fcntl
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

from lab import ROOT
from test_shell_lifecycle import ShellLab

sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_backup_maintenance as maintenance


def healthy(age=0, segments=1, size=16 * 1024 * 1024):
    return maintenance.Result(0, "backup_maintenance: age_seconds=%d wal_segments=%d "
                              "wal_segment_bytes=%d\n" % (age, segments, size))


@pytest.mark.parametrize("age,segments,size,expected", [
    (86399, 31, 16 * 1024**2, None),
    (86400, 1, 16 * 1024**2, "DAILY_RENEWAL"),
    (0, 32, 16 * 1024**2, "PROACTIVE_WAL_ROLLOVER"),
    (0, 2, 256 * 1024**2, "PROACTIVE_WAL_ROLLOVER"),
    (0, 512, 1024**2, "PROACTIVE_WAL_ROLLOVER"),
])
def test_renew_before_runtime_age_and_byte_limits(age, segments, size, expected):
    assert maintenance.reason_for_renewal(healthy(age, segments, size)) == expected


def test_renewal_limits_keep_half_runtime_headroom():
    from sentinel import backup_runtime_authority as runtime
    assert maintenance.RENEW_WAL_BYTES * 2 == runtime.RUNTIME_MAX_VERIFIED_BYTES
    assert maintenance.RENEW_WAL_OBJECTS * 2 == runtime.RUNTIME_MAX_ARCHIVE_OBJECTS


@pytest.mark.parametrize("record", [
    maintenance.Result(0, "backup_ready:true\n"),
    maintenance.Result(0, healthy().stdout * 2),
    healthy(0, 0), healthy(0, 1, 3),
    maintenance.Result(4, "SENTINEL_BACKUP_STATUS_REASON=BASE_BACKUP_RECOVERY_EVIDENCE_INVALID\n"),
    maintenance.Result(4, "SENTINEL_BACKUP_STATUS_REASON=BASE_BACKUP_STALE\n" * 2),
    maintenance.Result(1, "SENTINEL_BACKUP_STATUS_REASON=BASE_BACKUP_STALE\n"),
])
def test_malformed_or_contradictory_status_never_creates_a_backup(record):
    calls = []
    def run(command):
        calls.append(command)
        return record
    with pytest.raises(ValueError):
        maintenance.maintain(run, backup_root="/durable")
    assert len(calls) == 1


def test_renewal_requires_exact_new_generation_and_recomputes_on_restart():
    path = "/durable/base/base-20260920T120000Z"
    calls = []
    results = iter([healthy(86400), maintenance.Result(0, "verified_base_backup:" + path + "\n"), healthy()])
    def run(command):
        calls.append(command)
        return next(results)
    assert maintenance.maintain(run, backup_root="/durable").returncode == 0
    assert calls[-1] == ["bash", "scripts/sentinel-backup-status.sh", "--backup", path]
    calls.clear()
    def restarted(command):
        calls.append(command)
        return healthy()
    assert maintenance.maintain(restarted, backup_root="/durable").returncode == 0
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [maintenance.Result(4, "copy failed"), maintenance.Result(124, "deadline")])
def test_failed_creation_never_verifies_or_claims_success(failure):
    results = iter([healthy(86400), failure])
    result = maintenance.maintain(lambda _: next(results), backup_root="/durable")
    assert result.returncode == failure.returncode
    assert "RENEWED" not in result.stdout


def test_no_success_when_exact_path_verification_fails():
    results = iter([healthy(86400), maintenance.Result(0, "verified_base_backup:/durable/base/base-20260920T120000Z\n"),
                    maintenance.Result(4, "checksum mismatch")])
    result = maintenance.maintain(lambda _: next(results), backup_root="/durable")
    assert result.returncode == 4
    assert "VERIFICATION_FAILED" in result.stdout


@pytest.mark.parametrize("code", [
    "import time; time.sleep(20)",
    "import os,time; os.write(1,b'partial'); time.sleep(20)",
    "import os,time; os.close(1); os.close(2); time.sleep(20)",
    "import os,time; p=os.fork(); time.sleep(20) if p == 0 else None",
])
def test_silent_partial_closed_and_inherited_pipes_are_bounded(code):
    start = time.monotonic()
    result = maintenance.run_bounded([sys.executable, "-c", code], timeout=0.2)
    assert result.returncode == 124
    assert time.monotonic() - start < 4


def test_timeout_kills_descendant_before_late_write(tmp_path):
    target = tmp_path / "late"
    code = ("import os,time,pathlib; p=os.fork(); "
            "time.sleep(1); pathlib.Path(%r).write_text('late')" % str(target))
    assert maintenance.run_bounded([sys.executable, "-c", code], timeout=0.1).returncode == 124
    time.sleep(1.1)
    assert not target.exists()


def test_output_is_bounded():
    result = maintenance.run_bounded([sys.executable, "-c", "print('x'*300000)"], timeout=5)
    assert result.returncode == 125
    assert len(result.stdout) < maintenance.MAX_OUTPUT


def test_full_scheduler_log_cannot_block_completion():
    read_fd, write_fd = os.pipe()
    parent = None
    try:
        os.set_blocking(write_fd, False)
        with pytest.raises(BlockingIOError):
            while True:
                os.write(write_fd, b"x" * 4096)
        os.set_blocking(write_fd, True)
        def report():
            os.dup2(write_fd, 1)
            raise SystemExit(0 if maintenance.emit_result(maintenance.Result(0, 'result')) else 4)
        parent = multiprocessing.get_context('fork').Process(target=report)
        parent.start()
        parent.join(timeout=4)
        assert parent.exitcode == 4
    finally:
        if parent is not None and parent.is_alive():
            parent.kill()
            parent.join(timeout=3)
        if parent is not None:
            parent.close()
        os.close(write_fd)
        os.close(read_fd)


def test_internal_worker_cannot_bypass_host_lock():
    assert maintenance.main(["--worker"]) == 2


def test_orphaned_container_copy_fences_staging_cleanup(tmp_path):
    lab = ShellLab(tmp_path)
    staging = lab.base / ".base-20260901T000000Z.part-123"
    staging.mkdir()
    (staging / "copy-in-progress").write_text("preserve")
    with (lab.base / ".sentinel-producer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = lab.run()
        assert result.returncode != 0
        assert (staging / "copy-in-progress").read_text() == "preserve"
        assert "base-copy" not in lab.events()
    # When the in-container owner is gone, ordinary retry cleans and proceeds.
    assert lab.run().returncode == 0
    assert not staging.exists()


def test_verified_status_emits_exact_maintenance_geometry(tmp_path):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    os.utime(lab.base / "base-20260910T120000Z" / "backup_manifest", (1789041600, 1789041600))
    result = lab.run("sentinel-backup-status.sh")
    assert result.returncode == 0, result.stderr
    assert maintenance.reason_for_renewal(maintenance.Result(0, result.stdout)) is None


def test_real_maintenance_entry_creates_once_then_rechecks_on_restart(tmp_path):
    lab = ShellLab(tmp_path)
    # The adapter's clock is fixed at 2026-09-10 12:00 UTC. Its generated
    # filesystem timestamp must describe that same synthetic observation.
    copy_adapter = tmp_path / "bin" / "pg_basebackup"
    copy_adapter.write_text(copy_adapter.read_text().replace(
        '    (path / "backup_label").write_text',
        '    os.utime(path / "backup_manifest", (1789041600, 1789041600))\n'
        '    (path / "backup_label").write_text'))
    for name in ("sentinel-backup-maintenance.sh", "sentinel-backup-maintenance-entry.sh",
                 "sentinel_backup_maintenance.py"):
        shutil.copy2(ROOT / "scripts" / name, lab.scripts / name)
    first = lab.run("sentinel-backup-maintenance.sh")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "RENEWED" in first.stdout
    assert lab.events().count("base-copy") == 1
    restarted = lab.run("sentinel-backup-maintenance.sh")
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    assert "HEALTHY" in restarted.stdout
    assert lab.events().count("base-copy") == 1


def test_scheduler_stop_reaps_private_descendants(tmp_path):
    ready, late = tmp_path / "ready", tmp_path / "late"
    child = ("import pathlib,time; pathlib.Path(%r).touch(); time.sleep(1); "
             "pathlib.Path(%r).touch(); time.sleep(20)" % (str(ready), str(late)))
    code = ("import sys; sys.path.insert(0, %r); import sentinel_backup_maintenance as m; "
            "original=m.run_bounded; m.run_bounded=lambda *a, **k: "
            "original([sys.executable, '-c', %r], timeout=10); "
            "m.main([])" % (str(ROOT / "scripts"), child))
    parent = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        parent.send_signal(signal.SIGTERM)
        assert parent.wait(timeout=3) == 143
        time.sleep(1.1)
        assert not late.exists()
    finally:
        if parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait(timeout=3)


def test_exhausted_horizon_after_outage_renews_and_preserves_old_media(tmp_path):
    from test_shell_lifecycle import _runtime_horizon_lab, _write_checksum
    lab, base = _runtime_horizon_lab(tmp_path, 65)
    old = base.with_name('base-20260909T120000Z')
    base.rename(old)
    retained = (old / 'backup_manifest').read_bytes()
    checkpoint = lab.namespace / '000000010000000000000044'
    with checkpoint.open('wb') as stream:
        stream.truncate(16 * 1024 * 1024)
    _write_checksum(checkpoint)
    calls = []

    def run(command):
        calls.append(command)
        producer = command[1] == 'scripts/sentinel-base-backup.sh'
        if producer:
            lab.env.update(BACKUP_LAB_CHECKPOINT_WAL=checkpoint.name,
                BACKUP_LAB_CHECKPOINT_LSN='0/44000040', BACKUP_LAB_FRONTIER=checkpoint.name)
        result = subprocess.run(['bash', str(lab.repo / command[1]), *command[2:]],
                                env=lab.env, capture_output=True, text=True, timeout=120)
        if producer and result.returncode == 0:
            os.utime(base / 'backup_manifest', (1789041600, 1789041600))
        return maintenance.Result(result.returncode, result.stdout + result.stderr)

    result = maintenance.maintain(run, backup_root=str(lab.media))
    assert result.returncode == 0, result.stdout
    assert 'RENEWED reason=BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED' in result.stdout
    assert calls[-1] == ['bash', 'scripts/sentinel-backup-status.sh', '--backup', str(base)]
    assert (old / 'backup_manifest').read_bytes() == retained
    calls.clear()
    assert maintenance.maintain(run, backup_root=str(lab.media)).returncode == 0
    assert len(calls) == 1
