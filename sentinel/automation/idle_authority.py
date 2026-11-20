"""One bounded, broker-free idle authority observation outside the main loop."""
from __future__ import annotations

import json
import multiprocessing
import os
import queue
import socket
import threading
import time
from typing import Any

from sentinel import supervisor_io


STAGES = (
    "STARTING",
    "CONNECT",
    "FENCE_AND_CONTROL",
    "INPUT_AND_ROLLOUT",
    "RUNTIME_SOURCE_PACKAGES",
    "SIGNED_AUTHORITY_PUBLICATION",
    "COMPLETE",
)


_REQUEST_LIMIT = 1024
_RESULT_LIMIT = 16384


def _serve(channel, parent_pid, function, args, progress):
    from sentinel.automation.model import LeaderPermit

    supervisor_io._parent_death(parent_pid)
    with channel:
        while raw := channel.recv(_REQUEST_LIMIT+1):
            if len(raw) > _REQUEST_LIMIT:
                raise ValueError('idle authority request exceeds limit')
            permit = LeaderPermit.model_validate_json(raw)
            value = function(*args, permit, progress)
            response = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
            if len(response) > _RESULT_LIMIT or channel.send(response) != len(response):
                raise ValueError('idle authority result exceeds limit')


class IdleAuthorityObserver:
    """Warm imports only. Each request recomputes the original full proof."""

    def __init__(self, function, *args):
        self.function = function
        self.args = args
        self.context = multiprocessing.get_context('spawn')
        self.progress = self.context.Array('i', [0, 0], lock=False)
        self.process = None
        self.channel = None
        self.requests = queue.Queue(maxsize=1)
        self.stopping = False
        # Linux delivers the parent-death signal when the spawning thread
        # exits, even if other threads in its process are still running.
        self.owner = threading.Thread(
            target=self._run, name='sentinel-idle-authority', daemon=True)
        self.owner.start()

    def submit(self, flight, permit):
        if self.stopping or not self.owner.is_alive():
            raise RuntimeError('idle authority observer owner unavailable')
        self.requests.put_nowait((flight, permit))

    def _run(self):
        try:
            while (request := self.requests.get()) is not None:
                flight, permit = request
                try:
                    flight.value = self._read(
                        permit,
                        deadline=flight.started_monotonic+flight.timeout_seconds,
                        cancelled=flight.cancelled.is_set)
                except BaseException as exc:  # noqa: BLE001
                    flight.error = exc
                finally:
                    flight.finished.set()
        finally:
            self._reap()

    def _start(self):
        # A packet is indivisible. A dead or wedged child cannot leave half
        # a length prefix that stalls the parent's deadline or cancellation.
        parent, child = socket.socketpair(type=socket.SOCK_SEQPACKET)
        try:
            process = self.context.Process(
                target=_serve, name='sentinel-idle-authority-reader',
                args=(child, os.getpid(), self.function, self.args, self.progress))
            process.start()
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        self.channel, self.process = parent, process

    def _read(self, permit, *, deadline, cancelled):
        try:
            if cancelled() or time.monotonic() >= deadline:
                raise TimeoutError('idle authority observation expired before admission')
            if self.process is not None and (self.channel is None or not self.process.is_alive()):
                if not self._reap():
                    raise TimeoutError('prior idle authority observer is not reaped')
            if self.process is None:
                self._start()
            raw = permit.model_dump_json().encode()
            remaining = deadline-time.monotonic()
            if cancelled() or remaining <= 0:
                raise TimeoutError('idle authority observation expired before request')
            self.channel.settimeout(remaining)
            if len(raw) > _REQUEST_LIMIT or self.channel.send(raw) != len(raw):
                raise ValueError('idle authority request exceeds limit')
            while not cancelled():
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                self.channel.settimeout(min(.1, remaining))
                try:
                    response = self.channel.recv(_RESULT_LIMIT+1)
                except socket.timeout:
                    continue
                if cancelled() or time.monotonic() >= deadline:
                    break
                if not response or len(response) > _RESULT_LIMIT:
                    raise RuntimeError('idle authority observer result unavailable')
                return json.loads(response)
            raise TimeoutError('idle authority observer exceeded its deadline or was cancelled')
        except BaseException:
            self._reap()
            raise

    def close(self):
        if not self.stopping:
            self.stopping = True
            self.requests.put_nowait(None)
        self.owner.join(timeout=1.2)
        return not self.owner.is_alive() and self._reap()

    def _reap(self):
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.process is None:
            return True
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=1)
        if self.process.is_alive():
            return False
        self.process.join(timeout=0)
        self.process.close()
        self.process = None
        return True


class IdleAuthorityFlight:
    """Own a single killable proof; completion never publishes authority."""

    def __init__(self, observer: IdleAuthorityObserver, permit,
                 *, timeout_seconds: float) -> None:
        self.started_monotonic = time.monotonic()
        self.timeout_seconds = timeout_seconds
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        # Diagnostic fields are independent, fixed-width integers. A killed
        # child must never strand a process-shared lock in the parent logger.
        self.progress = observer.progress
        self.progress[0] = self.progress[1] = 0
        self.value: Any = None
        self.error: BaseException | None = None

        observer.submit(self, permit)

    @property
    def stage(self) -> str:
        code = self.progress[1]
        return STAGES[code] if 0 <= code < len(STAGES) else "UNKNOWN"

    @property
    def backend_pid(self) -> int | None:
        pid = self.progress[0]
        return pid if pid > 0 else None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_monotonic)

    def stop(self, *, timeout_seconds: float = 2.0) -> bool:
        """Cancel and reap before a callback fork or handover."""
        self.cancelled.set()
        return self.finished.wait(timeout_seconds)


def set_progress(progress, *, stage: int | None = None,
                 backend_pid: int | None = None) -> None:
    """Best-effort closed diagnostics; a broken sink cannot change authority."""
    try:
        if stage is not None:
            progress[1] = stage
        if backend_pid is not None and backend_pid > 0:
            progress[0] = backend_pid
    except Exception:  # noqa: BLE001
        pass
