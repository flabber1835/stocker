"""Real-process acceptance for heartbeat faults while a shadow worker is alive."""
import json
import os
import signal
import subprocess
import sys

import pytest


DRIVER = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace
from sentinel import shadow_supervisor as shadow

root, mode = Path(sys.argv[1]), sys.argv[2]
shadow.ShadowServiceConfig.from_env = lambda: SimpleNamespace(poll_seconds=.01)
shadow.LATCH_FILE = root / 'absent-latch'
shadow.supervisor_io.report = lambda *a, **kw: None
original_spawn, original_terminate = subprocess.Popen, shadow._terminate
children = []
def spawn(*args, **kwargs):
    # Substitute only the worker payload, never supervision or process cleanup.
    child = original_spawn([sys.executable, '-c',
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "Path('worker.pid').write_text(str(os.getpid())); " +
        ("raise SystemExit(2)" if mode == 'terminal' else "time.sleep(60)")], cwd=root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    children.append(child)
    until = time.monotonic() + 2
    while not (root / 'worker.pid').exists():
        if time.monotonic() > until: raise RuntimeError('worker not ready')
        time.sleep(.01)
    if mode == 'terminal':
        child.wait(timeout=1)
    return child
shadow.subprocess.Popen = spawn
# Shorten only the grace period so the tests remain quick; use real termination.
shadow._terminate = lambda child: original_terminate(child, grace_seconds=.1)
class Heartbeat:
    def touch(self, **kwargs):
        if (root / 'worker.pid').exists():
            if mode in {'error', 'terminal'}: raise OSError('injected heartbeat write failure')
            if mode == 'stall':
                (root / 'observer.pid').write_text(str(os.getpid()))
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                time.sleep(60)
            if mode in {'normal', 'cleanup_stall'}: os.kill(parent_pid, signal.SIGTERM)
        (root / 'heartbeat').touch()
    def unlink(self, **kwargs):
        if mode == 'cleanup_stall':
            (root / 'cleanup.pid').write_text(str(os.getpid()))
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            time.sleep(60)
        (root / 'heartbeat').unlink(**kwargs)
parent_pid = os.getpid()
shadow.HEARTBEAT_FILE = Heartbeat()
shadow._enqueue_alert = lambda **kwargs: None
started = time.monotonic()
try:
    result = shadow.run()
    outcome = {'returncode': result}
except Exception as exc:
    outcome = {'error': type(exc).__name__, 'message': str(exc)}
outcome.update(elapsed=time.monotonic()-started, launches=len(children),
               worker_exits=[child.poll() for child in children])
print(json.dumps(outcome), flush=True)
'''


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize('mode', ['error', 'stall', 'normal', 'terminal', 'cleanup_stall'])
def test_heartbeat_fault_never_leaves_an_unsupervised_worker(tmp_path, mode):
    try:
        result = subprocess.run([sys.executable, '-c', DRIVER, str(tmp_path), mode],
                                capture_output=True, text=True, timeout=8)
        assert result.returncode == 0, result.stderr
        evidence = json.loads(result.stdout)
        assert evidence['launches'] == 1
        assert evidence['elapsed'] < 5
        assert evidence['worker_exits'] == ([2] if mode == 'terminal' else [-signal.SIGKILL]), evidence
        if mode in {'normal', 'cleanup_stall'}:
            assert evidence['returncode'] == 0
        else:
            assert 'error' in evidence
            assert 'heartbeat write failure' in evidence.get('message', '') or 'wall-clock' in evidence.get('message', '')
        assert (tmp_path / 'heartbeat').exists() == (mode == 'cleanup_stall')
        # A heartbeat exception disposes of the child without guessing its
        # outcome; the merged restart guard must survive that exceptional exit.
        assert (tmp_path / 'shadow-supervisor-pending.json').exists() == (
            mode in {'error', 'stall', 'terminal'})
        if mode == 'terminal':
            latch = json.loads((tmp_path / 'absent-latch').read_text())
            assert latch['reason'] == 'shadow worker reported terminal integrity refusal'
        for path in tmp_path.glob('*.pid'):
            assert not alive(int(path.read_text())), path.name
    finally:
        # Old code/mutants must not leak fixtures even when acceptance fails.
        for path in tmp_path.glob('*.pid'):
            pid = int(path.read_text())
            if alive(pid):
                os.kill(pid, signal.SIGKILL)
