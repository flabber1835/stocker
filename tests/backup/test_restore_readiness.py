"""Real log-client processes: no PostgreSQL probes before copy/verify finish."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_restore_readiness as readiness

TOKEN = 'qualification-123'
CONTAINER = 'sentinel-restore-drill-' + TOKEN


def client(monkeypatch, program):
    original = subprocess.Popen
    processes, calls = [], []
    def start(argv, **kwargs):
        calls.append(argv)
        assert argv == ['docker', 'logs', '--follow', CONTAINER]
        process = original([sys.executable, '-u', '-c', program], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(readiness.subprocess, 'Popen', start)
    return processes, calls


def phase(name):
    return f"print('SENTINEL_RESTORE_PHASE={TOKEN}:{name}',flush=True)"


def qualification(monkeypatch, tmp_path):
    started = tmp_path/'postgres-started'
    program = ('import time;from pathlib import Path;' + phase('COPYING')
        + ';time.sleep(.1);' + phase('VERIFYING')
        + f';Path({str(started)!r}).touch();' + phase('STARTING') + ';time.sleep(30)')
    processes, calls = client(monkeypatch, program)
    probes = []
    def probe(argv, **kwargs):
        assert started.exists(), 'probe ran while copy/verification had not finished'
        probes.append(argv)
        return SimpleNamespace(returncode=0)
    readiness.wait_ready(CONTAINER, TOKEN, seconds=2, probe=probe)
    assert len(calls) == 1 and len(probes) == 1
    assert all(p.poll() is not None for p in processes), 'log client was not reaped'


def test_slow_copy_uses_one_stream_and_no_premature_probe(monkeypatch, tmp_path):
    qualification(monkeypatch, tmp_path)


def test_removed_phase_gate_is_detected_by_actual_probe_qualification(monkeypatch, tmp_path):
    monkeypatch.setattr(readiness, 'wait_starting', lambda *a, **k: None)
    with pytest.raises(AssertionError, match='probe ran while'):
        qualification(monkeypatch, tmp_path)


@pytest.mark.parametrize('record', ['VERIFYING', 'STARTING', 'BAD'])
def test_out_of_order_or_malformed_own_phase_refuses_without_probe(monkeypatch, record):
    processes, _ = client(monkeypatch, phase(record))
    with pytest.raises(RuntimeError, match='phase sequence'):
        readiness.wait_ready(CONTAINER, TOKEN, seconds=2,
            probe=lambda *a, **k: pytest.fail('unqualified readiness probe'))
    assert all(p.poll() is not None for p in processes)


def test_worker_failure_before_verify_never_probes(monkeypatch):
    processes, _ = client(monkeypatch, phase('COPYING') + ';raise SystemExit(4)')
    with pytest.raises(RuntimeError, match='ended before'):
        readiness.wait_ready(CONTAINER, TOKEN, seconds=2,
            probe=lambda *a, **k: pytest.fail('failed copy reached readiness'))
    assert all(p.poll() is not None for p in processes)


def test_silent_copy_has_finite_deadline_and_reaps_client(monkeypatch):
    processes, _ = client(monkeypatch, 'import time;' + phase('COPYING') + ';time.sleep(30)')
    with pytest.raises(RuntimeError, match='deadline exhausted'):
        readiness.wait_ready(CONTAINER, TOKEN, seconds=.08,
            probe=lambda *a, **k: pytest.fail('silent copy reached readiness'))
    assert all(p.poll() is not None for p in processes)


def test_copy_consumes_the_same_original_readiness_budget(monkeypatch):
    clock = [0]
    def copying(*a, **kwargs):
        assert kwargs['deadline'] == 1200
        clock[0] = 1199.75
    monkeypatch.setattr(readiness, 'wait_starting', copying)
    def probe(argv, **kwargs):
        assert kwargs['timeout'] == .25
        clock[0] = 1200
        return SimpleNamespace(returncode=0)
    with pytest.raises(RuntimeError, match='deadline exhausted'):
        readiness.wait_ready(CONTAINER, TOKEN, clock=lambda: clock[0], probe=probe)


def test_unrelated_log_lines_cannot_skip_worker_phase(monkeypatch):
    program = "print('SENTINEL_RESTORE_PHASE=other:STARTING',flush=True);" + phase('COPYING')
    client(monkeypatch, program)
    with pytest.raises(RuntimeError, match='ended before'):
        readiness.wait_ready(CONTAINER, TOKEN, seconds=2,
            probe=lambda *a, **k: pytest.fail('foreign log started readiness'))


def test_worker_and_public_drill_preserve_phase_order_and_actual_replay():
    root = Path(__file__).resolve().parents[2]
    worker = (root/'scripts/sentinel-restore-worker.sh').read_text()
    assert worker.index('phase COPYING') < worker.index('cp -a /source/')
    assert worker.index('phase VERIFYING') < worker.index('pg_verifybackup')
    assert worker.index('pg_verifybackup') < worker.index('phase STARTING') < worker.index('exec docker-entrypoint.sh')
    drill = (root/'scripts/sentinel-restore-drill.sh').read_text()
    assert 'seq 1 1200' not in drill
    assert drill.index('sentinel_restore_readiness.py') < drill.index('pg_last_wal_replay_lsn()')
    assert "pg_get_wal_replay_pause_state() = 'paused'" in drill
    assert 'sentinel_backup_recovery_markers' in drill
