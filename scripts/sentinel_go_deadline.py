"""One host-owned deadline shared by preparation and backup subprocesses."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_DEADLINE = ContextVar("go_preparation_deadline", default=None)


@contextmanager
def preparation_budget(seconds):
    end = time.monotonic() + seconds
    current = _DEADLINE.get()
    token = _DEADLINE.set(min(end, current) if current is not None else end)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def command_timeout(seconds):
    end = _DEADLINE.get()
    return seconds if end is None else max(0, min(seconds, end - time.monotonic()))
