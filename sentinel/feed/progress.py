"""Credential-free feed progress protocol for operator diagnostics."""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

PREFIX = "SENTINEL_FEED_PROGRESS="
COST_STAGES = frozenset({"rolling_identity", "rolling_normalization", "rolling_seal",
    "rolling_operational_validation", "rolling_source_corroboration",
    "rolling_operational_publication"})
_observer = ContextVar("feed_progress_observer", default=None)


@contextmanager
def observing(observer):
    """The operational publisher may observe its own closed diagnostic stages."""
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def emit(stage: str, status: str, *, rows: int = 0, elapsed_ms: int = 0,
         refreshed_at: str = "", snapshot_at: str = "", **details) -> None:
    value = {
        "stage": stage, "status": status, "rows": int(rows),
        "elapsed_ms": int(elapsed_ms),
    }
    if refreshed_at or snapshot_at:
        value.update(refreshed_at=refreshed_at, snapshot_at=snapshot_at)
    value.update(details)
    print(PREFIX + json.dumps(value, sort_keys=True), file=sys.stderr, flush=True)
    observer = _observer.get()
    if observer is not None:
        observer(value)


@contextmanager
def phase(stage: str, **details):
    start = time.monotonic_ns()
    cpu_started = time.process_time_ns() if stage in COST_STAGES else None
    counter = [0]
    emit(stage, "started", **details)
    measure = nullcontext()
    if stage == "rolling_source_corroboration":
        from sentinel.feed.alpaca_transport import measure_requests
        measure = measure_requests()

    with measure as requests:
        def finish(status):
            costs = dict(details)
            if cpu_started is not None:
                costs["cpu_ms"] = (time.process_time_ns() - cpu_started) // 1_000_000
            if requests is not None:
                costs.update(requests.fields())
            emit(stage, status, rows=counter[0],
                 elapsed_ms=(time.monotonic_ns() - start) // 1_000_000, **costs)

        try:
            yield counter
        except BaseException:
            finish("failed")
            raise
        else:
            finish("completed")
