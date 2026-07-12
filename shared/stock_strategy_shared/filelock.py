"""Cross-process (and cross-CONTAINER) advisory file lock via flock.

Audit finding F1: artifacts/bt/proposals.json has TWO writers — the evaluator
(harvest after each review) and bt-scheduler (lifecycle marking at sweep fire /
export) — each doing read-modify-write with atomic replace. Unsynchronized,
a collision loses one side's update. Both containers bind-mount the same host
./artifacts directory, so an flock on a sibling lock file is held on the same
inode by the same kernel — it serializes them even across containers.

Blocking by design: every guarded critical section is a milliseconds-long
read-modify-write of a small JSON file. Separate-machine deploys move these
files by rsync/scp, where a lock cannot help — the transport serializes instead.
"""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager


@contextmanager
def file_lock(lock_path: str):
    """Exclusive advisory lock held for the duration of the with-block."""
    d = os.path.dirname(lock_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(lock_path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
