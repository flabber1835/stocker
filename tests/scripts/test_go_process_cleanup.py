import subprocess
import os
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace

import pytest

import sentinel_go_process as owned

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])


@pytest.mark.parametrize("interrupt", [False, True])
def test_exact_owned_container_cleanup_on_completion_and_interrupt(monkeypatch, interrupt):
    calls = []
    monkeypatch.setattr(owned.subprocess, "run", lambda argv, **kw:
                        calls.append(argv) or SimpleNamespace(returncode=0))
    command = ["docker", "compose", "-f", "compose.yml", "run", "--rm", "sentinel"]
    try:
        with owned.owned_command(command) as owner:
            name = owner["command"][owner["command"].index("--name") + 1]
            assert name.startswith("sentinel-go-owned-")
            if interrupt:
                raise KeyboardInterrupt()
    except KeyboardInterrupt:
        assert interrupt
    assert calls == [["docker", "rm", "-f", name]]
    assert "--name" not in command


def test_cleanup_cannot_claim_success_when_docker_is_unavailable(monkeypatch):
    monkeypatch.setattr(owned.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(RuntimeError, match="could not verify cleanup"):
        with owned.owned_command(["docker", "run", "--rm", "test"]):
            pass


def test_cleanup_commands_are_isolated_from_terminal_group_signals(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1 if argv[1] == "rm" else 0, stdout="")
    monkeypatch.setattr(owned.subprocess, "run", run)
    owned._remove_owned("sentinel-go-owned-test")
    assert len(calls) == 2
    assert all(kwargs["start_new_session"] is True for _, kwargs in calls)
    assert all(kwargs["timeout"] == owned.DOCKER_CLEANUP_SECONDS for _, kwargs in calls)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("timing", ["client", "repeated", "during-removal"])
def test_guard_allows_owned_cleanup_and_restart_after_cancellation(tmp_path, signum, timing):
    """Real process signals; the file models state held outside the Docker CLI.

    A CLI that ignores termination uses the real five-second client deadline.
    Slow removal then crosses the old guard deadline. Killing just that CLI
    cannot clear the independent worker state, just as with the Docker daemon.
    """
    docker = tmp_path / "docker"
    docker.write_text("#!" + sys.executable + "\n" + '''
import os, pathlib, signal, sys, time
root = pathlib.Path(os.environ['FAKE_DOCKER_STATE'])
args = sys.argv[1:]
if args[0] == 'run':
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    name = args[args.index('--name') + 1]
    (root / name).touch()
    (root / 'ready').write_text(name)
    if os.environ['CANCEL_TIMING'] != 'during-removal':
        time.sleep(60)
elif args[0] == 'rm':
    assert args[1] == '-f' and args[2].startswith('sentinel-go-owned-')
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    (root / 'removing').touch()
    time.sleep(1)
    (root / args[2]).unlink()
else:
    raise SystemExit('unexpected Docker command')
''', encoding="utf-8")
    docker.chmod(0o755)
    unrelated = tmp_path / "unrelated-worker"
    unrelated.touch()
    env = dict(os.environ, FAKE_DOCKER_STATE=str(tmp_path), CANCEL_TIMING=timing)
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    child = '''
import os, pathlib, subprocess, sys
sys.path.insert(0, 'scripts')
from sentinel_go_process import owned_command
try:
    with owned_command(['docker', 'run', '--rm', 'fixture']) as owner:
        owner['process'] = subprocess.Popen(owner['command'])
        owner['process'].wait()
except KeyboardInterrupt:
    pass
(pathlib.Path(os.environ['FAKE_DOCKER_STATE']) / 'owner-finished').touch()
'''
    guard = ROOT / "scripts" / "sentinel_go_output_guard.py"
    proc = subprocess.Popen([sys.executable, str(guard), sys.executable, "-c", child],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    def wait_for(path):
        deadline = time.monotonic() + 20
        while not path.exists():
            assert proc.poll() is None, proc.communicate()
            assert time.monotonic() < deadline, "worker did not reach expected stage"
            time.sleep(.02)
    try:
        wait_for(tmp_path / "ready")
        name = (tmp_path / "ready").read_text()
        if timing == "during-removal":
            wait_for(tmp_path / "removing")
        proc.send_signal(signum)
        if timing == "repeated":
            wait_for(tmp_path / "removing")
            proc.send_signal(signum)
        out, err = proc.communicate(timeout=20)
        assert proc.returncode == 128 + signum, (out, err)
        assert (tmp_path / "owner-finished").exists(), "guard killed cleanup owner early"
        assert not (tmp_path / name).exists(), "cancelled GO orphaned its worker"
        assert unrelated.exists(), "cleanup touched an unrelated worker"
        # A new guarded invocation can run after the cancelled owner is reaped.
        restarted = subprocess.run([sys.executable, str(guard), sys.executable,
                                    "-c", "print('RESTARTED')"], cwd=ROOT, env=env,
                                   capture_output=True, text=True, timeout=10)
        assert restarted.returncode == 0, restarted.stderr
        assert "RESTARTED" in restarted.stdout
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.communicate(timeout=60)
