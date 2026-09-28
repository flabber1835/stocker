"""Foreground driver with fixed-request, fixed-deadline revision successors."""
from __future__ import annotations

import time

from sentinel.feed import progress, rolling_jobs as jobs, sharadar
from sentinel.feed.publication import CorpusBusy


def run(conn, job_id, *, prepare, check_target, sleep=None):
    from sentinel.feed.acquisition_parts import SourceRevision, successor
    sleep = sleep or time.sleep
    while True:
        check_target()
        try:
            return prepare(conn, job_id)
        except SourceRevision as exc:
            conn.rollback()
            check_target()
            job_id = successor(conn, job_id, exc.component)
            continue
        except (sharadar.SharadarRetryDeferred, ConnectionError, CorpusBusy,
                jobs.JobWaiting):
            conn.rollback()
            state = jobs.status(conn, job_id)
            conn.rollback()
            if state["state"] == "PUBLISHED":
                continue  # Another worker committed between claim and status.
            if state["state"] in jobs.TERMINAL or state["remaining_seconds"] <= 0:
                raise
            if state["state"] not in jobs.WAITING and not state.get("owner"):
                # A failure before claim has no recorded retry disposition.
                raise
        while True:
            check_target()
            state = jobs.status(conn, job_id)
            conn.rollback()  # No open transaction while sleeping.
            if state["state"] == "PUBLISHED":
                break  # Committed receipts survive the acquisition deadline.
            if state["remaining_seconds"] <= 0:
                jobs.expire(conn, job_id)
                conn.commit()
                raise jobs.JobRefused("preparation deadline exhausted")
            if state["state"] in jobs.TERMINAL:
                raise jobs.JobRefused("preparation ended: " + state["reason"])
            delay = min(state["retry_seconds"], state["remaining_seconds"], 10.0)
            if delay <= 0:
                break
            progress.emit("source_preflight", "working", reason=state["reason"],
                          retry_seconds=int(state["retry_seconds"] + .999),
                          remaining_seconds=int(state["remaining_seconds"]))
            sleep(delay)
