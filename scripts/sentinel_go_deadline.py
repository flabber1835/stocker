"""One host-owned deadline shared by preparation and backup subprocesses."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import time

_DEADLINE = ContextVar("go_preparation_deadline", default=None)
_UTC_DEADLINE = ContextVar("go_preparation_utc_deadline", default=None)
DEADLINE_ENV = "SENTINEL_GO_PREPARATION_DEADLINE"


@contextmanager
def preparation_budget(seconds):
    end = time.monotonic() + seconds
    current = _DEADLINE.get()
    token = _DEADLINE.set(min(end, current) if current is not None else end)
    utc_end = time.time() + seconds
    current_utc = _UTC_DEADLINE.get()
    utc_token = _UTC_DEADLINE.set(min(utc_end, current_utc) if current_utc is not None else utc_end)
    try:
        yield
    finally:
        _UTC_DEADLINE.reset(utc_token)
        _DEADLINE.reset(token)


def job_deadline():
    """Transport the original cutoff, never a new budget on child restart."""
    end = _UTC_DEADLINE.get()
    if end is None:
        raise RuntimeError("GO preparation deadline is not established")
    return datetime.fromtimestamp(end, timezone.utc).isoformat()


def command_timeout(seconds):
    end = _DEADLINE.get()
    return seconds if end is None else max(0, min(seconds, end - time.monotonic()))
