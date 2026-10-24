"""Operational lifecycle for the fixed canonical publication pipeline."""
from __future__ import annotations

import math
from contextlib import contextmanager

from sentinel import backup_runtime_authority, identity
from sentinel.dependency_availability import database_unavailable
from sentinel.feed import (
    authority, publisher_pipeline, rolling_jobs as jobs, runtime_schema,
    sharadar, snapshot_export, staging, store, writer_schedule,
)
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.feed.publisher_pipeline import (
    ComparisonRefused, freeze, publish, published,
)


class PublicationObserver:
    """Only operational contexts and failure-stage observation."""
    def __init__(self, conn, lease):
        self.conn, self.lease = conn, lease
        self.stage_name = 'SHADOW_ADVANCE'

    def stage(self, name: str) -> None:
        self.stage_name = name

    @contextmanager
    def acquisition(self):
        with writer_schedule.turn(self.conn, self.lease), store.acquisition_write_lock(self.conn):
            yield

    @contextmanager
    def publication(self, phase, job_id):
        from sentinel.feed import progress
        with progress.phase(phase, job_id=job_id), writer_schedule.turn(self.conn, self.lease), store.corpus_write_lock(self.conn):
            yield


def _record_failure(conn, lease, exc, *, operational=False):
    from sentinel.feed.acquisition_limits import AcquisitionResourceExceeded
    from sentinel.feed.alpaca_transport import AlpacaTransportUnavailable
    from sentinel.feed.source_wait import SourceCoveragePending, record as record_source_wait
    conn.rollback()
    if jobs.expire(conn, lease.job_id):
        conn.commit()
        return
    try:
        remaining = jobs.status(conn, lease.job_id)["remaining_seconds"]
        delay = max(1, math.ceil(exc.delay)) if isinstance(exc, sharadar.SharadarRetryDeferred) else 10
        horizon = isinstance(exc, backup_runtime_authority.BackupHorizonExceeded)
        if isinstance(exc, SourceCoveragePending) and remaining > 1:
            record_source_wait(conn, lease, exc)
            jobs.wait(conn, lease, state="WAIT_SOURCE",
                      reason="SOURCE_COVERAGE_PENDING", retry_seconds=60)
        elif horizon and remaining > 2:
            jobs.wait(conn, lease, state="RETRY_WAIT",
                      reason="BACKUP_HORIZON_EXCEEDED", retry_seconds=1)
        elif isinstance(exc, snapshot_export.ExportPending) and remaining > delay:
            state = jobs.status(conn, lease.job_id)["state"]
            jobs.wait(conn, lease, state="WAIT_SOURCE" if state == "ACQUIRING" else "RETRY_WAIT",
                      reason="EXPORT_GENERATION_PENDING", retry_seconds=delay)
        elif (isinstance(exc, (sharadar.SharadarRetryDeferred,
                               AlpacaTransportUnavailable, ConnectionError,
                               CorpusLockUnavailable))
              or database_unavailable(exc)) and remaining > delay:
            reason = ("BACKUP_AUTHORITY_WAIT" if isinstance(exc, backup_runtime_authority.BackupRuntimeUnavailable)
                      else "DATABASE_UNAVAILABLE" if database_unavailable(exc)
                      else "CORPUS_WRITER_BUSY" if isinstance(exc, CorpusLockUnavailable) else "SOURCE_RETRY")
            jobs.wait(conn, lease, state="RETRY_WAIT", reason=reason, retry_seconds=delay)
        elif isinstance(exc, (KeyboardInterrupt, SystemExit)) and remaining > 2:
            jobs.wait(conn, lease, state="INTERRUPTED", reason="WORKER_INTERRUPTED", retry_seconds=1)
        else:
            reason = ("SOURCE_RESOURCE_LIMIT" if isinstance(exc, AcquisitionResourceExceeded)
                      else "SOURCE_GENERATION_CHANGED" if isinstance(exc, authority.VendorPublicationUnstable)
                      else "OPERATIONAL_PREPARATION_REFUSED" if operational
                      else "COMPARISON_PREPARATION_REFUSED")
            jobs.finish(conn, lease, state="REFUSED", reason=reason)
        conn.commit()
        if horizon and remaining > 2 and operational:
            # Publish a resume capability only after rollback, fenced wait and
            # commit. A lost lease or uncertain commit must not trigger renewal.
            exc.resume_job_id = str(lease.job_id)
    except jobs.JobRefused:
        # Another owner or an expired lease owns the next action, not this worker.
        conn.rollback()


def prepare(conn, job_id):
    """Own an idle connection, prepare/resume once, return a comparison receipt.

    No production CLI calls this entry point. The existing producer/backup gates
    apply, and the caller must explicitly migrate/enqueue first.
    """
    return _prepare(conn, job_id, operational=False)


def _prepare(conn, job_id, *, operational):
    from sentinel.feed import operational_snapshot, rolling_publisher

    runtime_schema.require_feed_schema(conn)
    if operational_snapshot.registered(conn, job_id) != operational:
        raise ComparisonRefused("preparation job belongs to a different publication path")
    boundary = operational_snapshot if operational else rolling_publisher
    result = boundary.published(conn, job_id)
    if result:
        conn.commit()
        return result
    producer = identity.require_feed_producer_identity()
    lease = jobs.claim(conn, job_id, lease_seconds=600)
    conn.commit()
    observer = PublicationObserver(conn, lease)
    discard_connection = False
    try:
        return publisher_pipeline.run(conn, job_id, operational=operational,
            boundary=boundary, lease=lease, observer=observer)
    except BaseException as exc:
        from sentinel import shadow_dependency_notifications as notices
        notices.capture_stage(exc, observer.stage_name)
        discard_connection = writer_schedule.connection_discarded(exc)
        if not discard_connection and not conn.closed:
            _record_failure(conn, lease, exc, operational=operational)
        raise
    finally:
        # Scratch only, scoped to this exact owner; sealed evidence is never deleted.
        if not discard_connection and not conn.closed:
            conn.rollback()
            staging.clear(conn, run_id=lease.owner)
            if operational:
                from sentinel.feed import retention
                conn.commit()
                retention.maintain(conn)
