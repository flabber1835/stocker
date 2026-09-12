from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
LOCK_HELPER = ROOT / "scripts" / "sentinel_go_lock.py"
SCRIPTS = ROOT / "scripts"


def _child_probe(extra: str = "") -> str:
    return (
        "import json,os,sys;"
        f"sys.path.insert(0,{str(SCRIPTS)!r});"
        "import sentinel_go_lock as g;"
        "print(json.dumps({"
        "'held':g.lifecycle_lock_is_held(),"
        "'token':bool(g.current_run_token()),"
        "'fd':bool(os.environ.get(g.LOCK_FD_ENV)),"
        "'marker':os.environ.get(g.LOCK_HELD_ENV)"
        "}),flush=True);"
        + extra
    )


def _run_locked(code: str):
    return subprocess.run(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c", code],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=20, check=False,
    )


def _kill_session_leak(process: subprocess.Popen) -> None:
    """Best-effort cleanup for a helper+child session created by this test."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def test_real_lock_parent_passes_kernel_authority_and_one_run_token():
    completed = _run_locked(_child_probe())
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "held": True,
        "token": True,
        "fd": True,
        "marker": "1",
    }


def test_forged_shell_marker_without_inherited_fd_is_not_authority():
    env = dict(os.environ)
    env["SENTINEL_GO_LOCK_HELD"] = "1"
    env["SENTINEL_GO_LOCK_FD"] = "999999"
    completed = subprocess.run(
        [sys.executable, "-c", _child_probe()],
        cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout.strip())
    assert payload["held"] is False


def test_run_token_without_kernel_flock_is_not_lock_authority():
    env = dict(os.environ)
    env["SENTINEL_GO_RUN_TOKEN"] = "a" * 64
    env["SENTINEL_GO_LOCK_HELD"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", _child_probe()],
        cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout.strip())
    assert payload["token"] is True
    assert payload["held"] is False


def test_second_real_go_lock_is_refused_while_first_child_holds_flock():
    # Let the first lifecycle finish naturally. Killing only its small lock parent
    # would intentionally leave the inherited child holding the flock and would
    # contaminate the following test.
    first = subprocess.Popen(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c",
         _child_probe("import time;time.sleep(2)")],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        line = first.stdout.readline().strip()
        assert line, first.stderr.read() if first.poll() is not None else ""
        payload = json.loads(line)
        assert payload["held"] is True
        second = _run_locked("print('unexpected')")
        assert second.returncode == 2
        assert "already running" in second.stderr
        assert first.wait(timeout=6) == 0
    finally:
        if first.poll() is None:
            _kill_session_leak(first)


def test_lock_survives_lock_parent_death_while_inherited_child_lives(tmp_path):
    # Use a test-owned status file for the child handshake. A stdout pipe is not
    # a safe lifecycle signal here because the point of the test is to SIGKILL
    # the parent while the child deliberately outlives it.
    status = tmp_path / "child-status.json"
    code = (
        "import json,os,sys,time;"
        "from pathlib import Path;"
        f"sys.path.insert(0,{str(SCRIPTS)!r});"
        "import sentinel_go_lock as g;"
        f"Path({str(status)!r}).write_text(json.dumps({{'pid':os.getpid(),'held':g.lifecycle_lock_is_held()}}),encoding='utf-8');"
        "time.sleep(30)"
    )
    parent = subprocess.Popen(
        [sys.executable, str(LOCK_HELPER), sys.executable, "-c", code],
        cwd=ROOT, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    child_pid = None
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not status.exists():
            if parent.poll() is not None:
                stderr = parent.stderr.read() if parent.stderr else ""
                raise AssertionError(
                    f"lock helper exited before child handshake rc={parent.returncode}: {stderr}")
            time.sleep(0.05)
        assert status.exists(), "child did not publish lock handshake"
        payload = json.loads(status.read_text(encoding="utf-8"))
        child_pid = int(payload["pid"])
        assert payload["held"] is True

        # Kill only the small lock parent. The child inherited the same open file
        # description through pass_fds and must continue to hold the kernel flock.
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)

        blocked = _run_locked("print('unexpected')")
        assert blocked.returncode == 2
        assert "already running" in blocked.stderr

        os.kill(child_pid, signal.SIGTERM)
        for _ in range(60):
            probe = _run_locked("print('acquired')")
            if probe.returncode == 0:
                assert "acquired" in probe.stdout
                break
            time.sleep(0.1)
        else:
            raise AssertionError("flock remained held after inherited child terminated")
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        _kill_session_leak(parent)
