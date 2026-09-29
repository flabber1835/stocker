"""Real Linux child-process deadlines for the final GO handoff runners."""
from pathlib import Path
import signal
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import sentinel_host_command as commands
import sentinel_go_post_validate as post
import sentinel_runtime_selection as selection


@pytest.mark.parametrize("runner", [post.run, selection._run])
def test_final_runners_enforce_timeout_and_kill_descendants(runner, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_GO_COMMAND_TIMEOUT_SECONDS", "1")
    marker = tmp_path / "late-write"
    child = "import time,pathlib;time.sleep(2);pathlib.Path(%r).write_text('escaped')" % str(marker)
    parent = ("import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',%r]);"
              "print('started',flush=True);time.sleep(30)") % child
    started = time.monotonic()
    result = runner([sys.executable, "-c", parent])
    assert result.returncode == 124 and "started" in result.stdout
    assert time.monotonic() - started < 8
    time.sleep(1.2)
    assert not marker.exists()


def test_success_preserves_captured_output_and_signal_handlers(tmp_path):
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    result = commands.run([sys.executable, "-c", "print('ok')"], cwd=tmp_path)
    assert (result.returncode, result.stdout) == (0, "ok\n")
    assert all(signal.getsignal(sig) == value for sig, value in handlers.items())


@pytest.mark.parametrize("value", ["0", "-1", "bad", "1.5"])
def test_invalid_deadline_refuses_without_starting_child(monkeypatch, tmp_path, value):
    monkeypatch.setattr(commands.subprocess, "Popen", lambda *a, **k: pytest.fail("child started"))
    assert commands.run(["unused"], cwd=tmp_path,
                        env={"SENTINEL_GO_COMMAND_TIMEOUT_SECONDS": value}).returncode == 2


def test_interruption_reaps_child_and_restores_handlers(monkeypatch, tmp_path):
    popen = commands.subprocess.Popen
    processes = []
    def interrupted(*a, **kw):
        proc = popen(*a, **kw)
        processes.append(proc)
        monkeypatch.setattr(proc, "communicate", lambda **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
        return proc
    monkeypatch.setattr(commands.subprocess, "Popen", interrupted)
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    with pytest.raises(KeyboardInterrupt):
        commands.run([sys.executable, "-c", "import time;time.sleep(30)"], cwd=tmp_path)
    assert processes[0].poll() is not None
    assert all(signal.getsignal(sig) == value for sig, value in handlers.items())
