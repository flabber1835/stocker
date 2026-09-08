"""Credential-free feed progress protocol for operator diagnostics."""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager

PREFIX = "SENTINEL_FEED_PROGRESS="


def emit(stage: str, status: str, *, rows: int = 0, elapsed_ms: int = 0,
         refreshed_at: str = "", snapshot_at: str = "") -> None:
    value = {
        "stage": stage, "status": status, "rows": int(rows),
        "elapsed_ms": int(elapsed_ms),
    }
    if refreshed_at or snapshot_at:
        value.update(refreshed_at=refreshed_at, snapshot_at=snapshot_at)
    print(PREFIX + json.dumps(value, sort_keys=True), file=sys.stderr, flush=True)


@contextmanager
def phase(stage: str):
    start = time.monotonic()
    counter = [0]
    emit(stage, "started")
    try:
        yield counter
    except BaseException:
        emit(stage, "failed", rows=counter[0],
             elapsed_ms=int((time.monotonic() - start) * 1000))
        raise
    else:
        emit(stage, "completed", rows=counter[0],
             elapsed_ms=int((time.monotonic() - start) * 1000))
