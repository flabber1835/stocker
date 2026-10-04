"""A live long-running worker is different from an abandoned durable attempt."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sentinel import shadow_supervisor as shadow, shadow_worker_liveness as live


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    monkeypatch.setattr(live, 'ACTIVE_FILE', tmp_path / 'active.json')
    monkeypatch.setattr(shadow, 'service_health', lambda _: {'service_health': 'RECONSTRUCTION_PENDING'})
    shadow.HEARTBEAT_FILE.touch()
    attempt = shadow._arm_worker()
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        live.record(attempt, os.getpid(), child.pid, time.monotonic() + 60)
        yield child
    finally:
        child.kill() if child.poll() is None else None
        child.wait(timeout=3)


def test_real_live_worker_is_healthy_without_financial_attestation(worker):
    assert shadow._health(30, config=object()) == 0
    assert shadow._pending_file().exists()  # Health grants no acknowledgement.


@pytest.mark.parametrize('damage', ['nonce', 'boot', 'supervisor_start', 'child_start',
    'parent', 'expired', 'missing', 'malformed', 'legacy_pending', 'heartbeat', 'critical'])
def test_invalid_or_stale_live_proof_cannot_hide_unacknowledged_work(worker, damage):
    proof = json.loads(live.ACTIVE_FILE.read_text())
    if damage == 'nonce': proof['attempt_id'] = '0' * 32
    elif damage == 'boot': proof['boot_id'] = 'other-boot'
    elif damage == 'supervisor_start': proof['supervisor']['start_ticks'] += 1
    elif damage == 'child_start': proof['worker']['start_ticks'] += 1
    elif damage == 'parent': proof['worker']['parent_pid'] += 1
    elif damage == 'expired': proof['deadline_monotonic'] = time.monotonic() - 1
    live.ACTIVE_FILE.write_text(json.dumps(proof))
    if damage == 'missing': live.ACTIVE_FILE.unlink()
    elif damage == 'malformed': live.ACTIVE_FILE.write_text('{invalid')
    elif damage == 'legacy_pending': shadow._pending_file().write_text('{"schema":"sentinel.shadow-supervisor-pending/1"}')
    elif damage == 'heartbeat': os.utime(shadow.HEARTBEAT_FILE, (0, 0))
    elif damage == 'critical': shadow.LATCH_FILE.write_text('{"reason":"terminal refusal"}')
    assert shadow._health(30, config=object()) == 1
    assert shadow._pending_file().exists()


def test_dead_or_zombie_child_is_not_healthy(worker):
    worker.kill()
    deadline = time.monotonic() + 2
    while True:
        stat = Path(f'/proc/{worker.pid}/stat').read_text()
        if stat[stat.rindex(')') + 2:].split()[0] == 'Z':
            break
        assert time.monotonic() < deadline
        time.sleep(.01)
    assert shadow._health(30, config=object()) == 1
    worker.wait(timeout=3)
    assert shadow._health(30, config=object()) == 1


def test_active_worker_cannot_hide_structural_corruption(worker, monkeypatch):
    def corrupt(_): raise ValueError('corrupt lineage')
    monkeypatch.setattr(shadow, 'service_health', corrupt)
    assert shadow._health(30, config=object()) == 1


def test_recovery_wait_is_live_only_while_exact_worker_is_running(worker, monkeypatch):
    def waiting(_): raise shadow.ShadowServiceWaiting('causal recovery pending')
    monkeypatch.setattr(shadow, 'service_health', waiting)
    assert shadow._health(30, config=object()) == 0
    worker.terminate()
    worker.wait(timeout=3)
    assert shadow._health(30, config=object()) == 1


def test_restart_does_not_adopt_live_proof_from_retained_attempt(worker, monkeypatch):
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env', lambda: object())
    monkeypatch.setattr(shadow.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(shadow, '_latched_wait', lambda *args: 91)
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('replacement worker started'))
    assert shadow.run() == 91
    assert shadow._pending_file().exists()


DRIVER = r'''
import os, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace
from sentinel import shadow_supervisor as s, shadow_worker_liveness as l
root = Path(sys.argv[1])
s.LATCH_FILE, s.HEARTBEAT_FILE = root/'critical.json', root/'heartbeat'
l.ACTIVE_FILE = root/'active.json'
s.ShadowServiceConfig.from_env = lambda: SimpleNamespace(poll_seconds=300)
s.service_health = lambda _: {'service_health':'RECONSTRUCTION_PENDING'}
original = subprocess.Popen
def spawn(*a, **k):
    child = original([sys.executable, '-c', 'import time; time.sleep(90)'])
    (root/'worker.pid').write_text(str(child.pid))
    return child
s.subprocess.Popen = spawn
if len(sys.argv) > 2:
    def broken(*a): raise OSError('proof write failed')
    l.record = broken
(root/'parent.pid').write_text(str(os.getpid()))
raise SystemExit(s.run())
'''


def test_real_supervisor_stays_healthy_past_compose_startup_then_acknowledges_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    monkeypatch.setattr(live, 'ACTIVE_FILE', tmp_path / 'active.json')
    monkeypatch.setattr(shadow, 'service_health', lambda _: {'service_health': 'RECONSTRUCTION_PENDING'})
    parent = subprocess.Popen([sys.executable, '-c', DRIVER, str(tmp_path)])
    try:
        deadline = time.monotonic() + 5
        while not live.ACTIVE_FILE.exists():
            assert parent.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.05)
        until = time.monotonic() + 35
        while time.monotonic() < until:
            assert shadow._health(30, config=object()) == 0
            time.sleep(1)
        parent.send_signal(signal.SIGTERM)
        assert parent.wait(timeout=8) == 0
        assert not shadow._pending_file().exists()
        assert not live.ACTIVE_FILE.exists()
        assert not shadow.HEARTBEAT_FILE.exists()
    finally:
        if parent.poll() is None:
            parent.send_signal(signal.SIGTERM)
            parent.wait(timeout=8)


def test_active_proof_failure_reaps_child_without_guessing_acknowledgement(tmp_path):
    result = subprocess.run([sys.executable, '-c', DRIVER, str(tmp_path), 'proof-failure'],
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == shadow.EXIT_REFUSED, result.stderr
    assert (tmp_path / 'shadow-supervisor-pending.json').exists()
    assert not (tmp_path / 'heartbeat').exists()
    assert not (tmp_path / 'active.json').exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / 'worker.pid').read_text()), 0)
