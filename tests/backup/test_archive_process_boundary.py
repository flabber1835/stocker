"""Archive qualification shares the native bounded process/group owner."""
import ctypes
import os
import signal
import sys
import time

import pytest

from lab import Archive, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_maintenance_process as process


def test_archive_default_clock_and_native_transport_are_preserved(tmp_path, monkeypatch):
    lab = Archive(tmp_path)
    observed = []
    expected = process.Result(0, "complete", "diagnostic")
    def bounded(argv, **kwargs):
        observed.append((argv, kwargs))
        return expected
    monkeypatch.setattr(process, "run_bounded", bounded)
    assert lab.run() is expected
    assert observed == [(lab.command(), {"env": lab.env, "timeout": 10})]
    alternate = [sys.executable, "-c", "pass"]
    environment = {"PATH": "/usr/bin:/bin"}
    assert lab.run(alternate, env=environment, timeout=.25) is expected
    assert observed[-1] == (alternate, {"env": environment, "timeout": .25})


def _require_no_descendant_after_timeout(tmp_path):
    # Become a subreaper only for this private test, so the assertion can reap
    # its own killed grandchild rather than depend on the machine's PID 1.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    descendant = None
    try:
        lab = Archive(tmp_path)
        code = ("import os,time; child=os.fork(); "
                "print(child,flush=True) if child else None; time.sleep(20)")
        result = lab.run([sys.executable, "-I", "-B", "-c", code], timeout=.25)
        assert result.returncode == 124
        assert "MAINTENANCE_DEADLINE_EXCEEDED" in result.stdout
        descendant = int(result.stdout.splitlines()[0])
        assert descendant > 1
        deadline = time.monotonic() + 1
        terminated = False
        while time.monotonic() < deadline:
            reaped, status = os.waitpid(descendant, os.WNOHANG)
            if reaped == descendant:
                terminated = os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
                descendant = None
                break
            time.sleep(.01)
        assert terminated, "archive timeout left its known child running"
    finally:
        if descendant is not None:
            try:
                os.kill(descendant, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(descendant, 0)
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def test_archive_timeout_terminates_known_private_descendant(tmp_path):
    _require_no_descendant_after_timeout(tmp_path)


def test_removing_private_group_cleanup_is_detected(tmp_path, monkeypatch):
    original = process.run_bounded
    def without_group(argv, **kwargs):
        return original(argv, private_group=False, **kwargs)
    monkeypatch.setattr(process, "run_bounded", without_group)
    with pytest.raises(AssertionError, match="left its known child running"):
        _require_no_descendant_after_timeout(tmp_path)


def test_archive_timeout_preserves_partial_diagnostics_and_bounds_output(tmp_path):
    lab = Archive(tmp_path)
    result = lab.run([sys.executable, "-I", "-B", "-c",
        "import sys,time;print('archive-progress',flush=True);"
        "print('archive-diagnostic',file=sys.stderr,flush=True);time.sleep(20)"], timeout=.25)
    assert result.returncode == 124
    assert "archive-progress" in result.stdout
    assert "archive-diagnostic" in result.stderr
    excessive = lab.run([sys.executable, "-I", "-B", "-c", "print('x'*300000)"], timeout=5)
    assert excessive.returncode == 125
    assert len(excessive.stdout) <= process.MAX_OUTPUT
