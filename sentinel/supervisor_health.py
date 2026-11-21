"""Fresh health transport owned and bounded by an existing supervisor."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path


CLIENT_SECONDS = 4.5
READ_SECONDS = 3.0
LIMIT = 4095


def probe(path, *, client_seconds=CLIENT_SECONDS):
    deadline = time.monotonic()+client_seconds
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(client_seconds)
            client.connect(str(path))
            response = bytearray()
            while b'\n' not in response:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('supervised health observation expired')
                client.settimeout(remaining)
                data = client.recv(LIMIT+1-len(response))
                if not data or len(response)+len(data) > LIMIT:
                    raise ValueError('incomplete supervised health observation')
                response.extend(data)
        if time.monotonic() >= deadline or response[-1:] != b'\n':
            raise TimeoutError('supervised health observation expired')
        status, payload = json.loads(response)
        if type(status) is not int or status not in {0, 1} or not isinstance(payload, dict):
            raise ValueError('malformed supervised health observation')
    except (OSError, ValueError, TypeError) as exc:
        status, payload = 1, {'healthy': False, 'reason': type(exc).__name__}
    print(json.dumps(payload, sort_keys=True))
    return status


def _serve(path, parent_pid, observe, pulse, max_pulse_age, started, read_seconds):
    import os
    import signal

    from sentinel import supervisor_io

    supervisor_io._parent_death(parent_pid)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    def current():
        return 0 <= time.monotonic()-pulse.value <= max_pulse_age

    os.umask(0o077)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(1)
        started.value = 0.0
        while True:
            client, _ = server.accept()
            with client:
                before = time.monotonic()
                started.value = before
                try:
                    if not current():
                        raise TimeoutError('owning supervisor pulse expired')
                    result = observe()
                    remaining = read_seconds-(time.monotonic()-before)
                    if remaining <= 0 or not current():
                        raise TimeoutError('supervised health observation expired')
                    raw = json.dumps(result, default=str, sort_keys=True).encode('ascii')+b'\n'
                    if len(raw) > LIMIT:
                        raise ValueError('supervised health result exceeds limit')
                    client.settimeout(remaining)
                    client.sendall(raw)
                except (OSError, ValueError):
                    # The client receives EOF and refuses a missing result.
                    pass
                finally:
                    started.value = 0.0


class WarmHealthReader:
    """One private reader, with fresh work and no retained health verdict."""

    def __init__(self, observe, *, path, max_pulse_age, read_seconds=READ_SECONDS):
        import multiprocessing

        self.context = multiprocessing.get_context('fork')
        self.path = path
        self.observe = observe
        self.read_seconds = read_seconds
        self.max_pulse_age = max_pulse_age
        self.pulse = self.context.RawValue('d', 0.0)
        self.started = self.context.RawValue('d', 0.0)
        self.process = None

    def tick(self):
        import os

        now = time.monotonic()
        self.pulse.value = now
        process = self.process
        if process is not None:
            started = self.started.value
            if process.is_alive() and (not started or now-started < self.read_seconds):
                return
            if process.is_alive():
                process.kill()
            process.join(timeout=0)
            if process.is_alive():
                return
            process.close()
            self.process = None
        self.path.unlink(missing_ok=True)
        self.started.value = now
        process = self.context.Process(
            target=_serve, name='sentinel-supervised-health-reader',
            args=(self.path, os.getpid(), self.observe, self.pulse, self.max_pulse_age,
                  self.started, self.read_seconds))
        process.start()
        self.process = process

    def close(self):
        self.pulse.value = 0.0
        process = self.process
        if process is not None:
            if process.is_alive():
                process.kill()
            process.join(timeout=1)
            if not process.is_alive():
                process.close()
                self.process = None
        self.path.unlink(missing_ok=True)
