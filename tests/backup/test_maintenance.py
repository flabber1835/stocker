"""Bounded coordinator transport and real process/physical-copy exclusion."""
from __future__ import annotations

import fcntl
import multiprocessing
import os
import signal
import subprocess
import sys
import time

import pytest

from lab import ROOT
from test_shell_lifecycle import ShellLab

sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_maintenance_process as maintenance


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


def test_receipt_input_and_json_output_remain_separate_from_diagnostics():
    result = maintenance.run_bounded([sys.executable, '-c',
        "import sys; print(sys.stdin.read()); print('diagnostic', file=sys.stderr)"],
        stdin='{"receipt":"fixture"}', timeout=5)
    assert result.returncode == 0
    assert result.stdout.strip() == '{"receipt":"fixture"}'
    assert result.stderr.strip() == 'diagnostic'


def test_combined_output_budget_includes_stderr():
    result = maintenance.run_bounded([sys.executable, '-c',
        "import sys; print('x'*200000); print('y'*200000, file=sys.stderr)"], timeout=5)
    assert result.returncode == 125


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


def test_orphaned_container_copy_fences_staging_cleanup(tmp_path):
    lab = ShellLab(tmp_path)
    staging = lab.base / ".base-20260901T000000Z.part-123"
    staging.mkdir()
    (staging / "copy-in-progress").write_text("preserve")
    with (lab.base / ".sentinel-maintenance.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = lab.run()
        assert result.returncode != 0
        assert (staging / "copy-in-progress").read_text() == "preserve"
        assert "base-copy" not in lab.events()
    # When the in-container owner is gone, ordinary retry cleans and proceeds.
    assert lab.run().returncode == 0
    assert not staging.exists()


def test_scheduler_stop_reaps_private_descendants(tmp_path):
    ready, late = tmp_path / "ready", tmp_path / "late"
    child = ("import pathlib,time; pathlib.Path(%r).touch(); time.sleep(1); "
             "pathlib.Path(%r).touch(); time.sleep(20)" % (str(ready), str(late)))
    code = ("import sys; sys.path.insert(0, %r); import sentinel_maintenance_process as m; "
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
