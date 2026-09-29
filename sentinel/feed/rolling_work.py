"""Cooperative work checkpoints; only an owning publisher supplies a callback."""
from contextlib import contextmanager
from contextvars import ContextVar

_HEARTBEAT = ContextVar("rolling_worker_heartbeat", default=None)


def checkpoint():
    heartbeat = _HEARTBEAT.get()
    if heartbeat is not None:
        heartbeat()


@contextmanager
def renewing(heartbeat):
    """Use the caller's transaction; never commit or revive an expired lease."""
    token = _HEARTBEAT.set(heartbeat)
    try:
        checkpoint()
        yield
        checkpoint()
    finally:
        _HEARTBEAT.reset(token)
