"""One bounded, broker-free idle authority observation outside the main loop."""
from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any, Callable

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


class IdleAuthorityFlight:
    """Own a single killable proof; completion never publishes authority."""

    def __init__(self, function: Callable[..., Any], args: tuple,
                 *, timeout_seconds: float) -> None:
        self.started_monotonic = time.monotonic()
        self.timeout_seconds = timeout_seconds
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        # Diagnostic fields are independent, fixed-width integers. A killed
        # child must never strand a process-shared lock in the parent logger.
        self.progress = multiprocessing.get_context("spawn").Array(
            "i", [0, 0], lock=False)
        self.value: Any = None
        self.error: BaseException | None = None

        def observe() -> None:
            try:
                self.value = supervisor_io.run(
                    function, *args, self.progress,
                    timeout=timeout_seconds, start_method="spawn",
                    cancelled=self.cancelled.is_set)
            except BaseException as exc:  # noqa: BLE001
                self.error = exc
            finally:
                self.finished.set()

        self.thread = threading.Thread(
            target=observe, name="sentinel-idle-authority", daemon=True)
        self.thread.start()

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
        self.thread.join(timeout=timeout_seconds)
        return not self.thread.is_alive()


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
