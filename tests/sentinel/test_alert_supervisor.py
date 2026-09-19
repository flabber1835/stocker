"""Actual process deadline under a silent dependency; no external services."""
import os
import socket
import sys
import threading
import time

import pytest

from sentinel import alert_supervisor as supervisor


def test_silent_socket_worker_is_killed_and_reaped(tmp_path):
    held = []
    accepted = threading.Event()
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    def accept():
        connection, _ = listener.accept()
        held.append(connection)
        accepted.set()
    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    pidfile = tmp_path / 'worker.pid'
    script = (
        'import os,socket,signal; from pathlib import Path; '
        'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        f'Path({str(pidfile)!r}).write_text(str(os.getpid())); '
        'os.write(int(os.environ["SENTINEL_ALERT_PROGRESS_FD"]), b"."); '
        f's=socket.create_connection({listener.getsockname()!r}); s.settimeout(.8); s.recv(1)')
    started = time.monotonic()
    try:
        with pytest.raises(supervisor.DispatcherStalled):
            supervisor.run_worker([sys.executable, '-c', script], deadline_seconds=.3, grace_seconds=.05)
        assert accepted.is_set()
        assert time.monotonic() - started < 1.5
        with pytest.raises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)
    finally:
        listener.close()
        for connection in held:
            connection.close()
        thread.join(timeout=1)


def test_completed_iterations_renew_only_the_next_iteration_budget():
    script = ('import os,time; fd=int(os.environ["SENTINEL_ALERT_PROGRESS_FD"]); '
              '\nfor _ in range(4):\n os.write(fd,b"."); time.sleep(.1)')
    assert supervisor.run_worker([sys.executable, '-c', script], deadline_seconds=.25) == 0


def test_dispatcher_restarts_after_stall_and_bounds_independent_report(monkeypatch):
    calls = []
    def worker(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise supervisor.DispatcherStalled('silent SQL socket')
        return 0
    monkeypatch.setattr(supervisor, 'run_worker', worker)
    monkeypatch.setattr(supervisor.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(supervisor.supervisor_io, 'report', lambda *a: None)
    reports = []
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, **kwargs: reports.append(kwargs))
    assert supervisor.main() == 0
    assert len(calls) == 2 and calls[0][-1] == '--worker'
    assert reports == [{'timeout': 12}]


def test_public_alert_service_entry_uses_supervisor(monkeypatch):
    from sentinel import alert_service
    monkeypatch.setattr(sys, 'argv', ['sentinel.alert_service'])
    monkeypatch.setattr(supervisor, 'main', lambda: 73)
    assert alert_service.main() == 73
