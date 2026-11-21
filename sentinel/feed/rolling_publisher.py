"""Operational lifecycle for the fixed canonical publication pipeline."""
from __future__ import annotations

import math
from time import monotonic, process_time_ns, sleep
from contextlib import contextmanager
from datetime import datetime, timezone

from sentinel import backup_runtime_authority, identity
from sentinel.dependency_availability import database_unavailable
from sentinel.feed import (
    authority, publisher_pipeline, rolling_jobs as jobs, runtime_schema,
    archive_tables, progress, publication_progress, snapshot_export, staging, store, writer_schedule,
)
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.feed.publisher_pipeline import (
    ComparisonRefused, freeze, publish, published,
)


class PublicationObserver:
    """Only operational contexts and failure-stage observation."""
    def __init__(self, conn, lease, *, operational=False):
        self.conn, self.lease = conn, lease
        self.stage_name = 'SHADOW_ADVANCE'
        self.backup_wait_until = None
        self.seal_started = None
        self.publisher = publication_progress.PublisherProgress.for_worker(
            conn, lease.owner) if operational else None

    def stage(self, name: str) -> None:
        if name == 'CANDIDATE_VALIDATION' and self.seal_started is not None:
            started, cpu_started, rows = self.seal_started
            progress.emit('rolling_candidate_seal', 'completed', job_id=self.lease.job_id, rows=rows,
                          elapsed_ms=round((monotonic() - started) * 1000),
                          cpu_ms=(process_time_ns() - cpu_started) // 1_000_000)
            self.seal_started = None
        self.stage_name = name
        self.backup_wait_until = None
        code = {'SOURCE_REFERENCES': 'R', 'PRICE_ACQUISITION': 'P', 'CANDIDATE_BUILD': 'B',
                'CANDIDATE_VALIDATION': 'V', 'SOURCE_CORROBORATION': 'C',
                'PUBLICATION': 'U'}.get(name)
        if self.publisher is not None and code is not None:
            self.publisher.publish(code)

    def observe(self, event):
        """Advance display-only phases from the builder's existing measured events."""
        if (event.get('job_id') != self.lease.job_id
                or self.stage_name != 'CANDIDATE_BUILD'):
            return
        stage, status, rows = event['stage'], event['status'], event['rows']
        if stage == 'rolling_normalization' and status == 'completed':
            self.seal_started = monotonic(), process_time_ns(), rows
        if self.publisher is None:
            return
        if stage == 'rolling_identity' and event.get('subphase') == 'alpaca_admission':
            if status == 'started' or status == 'working' and rows % 100_000 == 0:
                self.publisher.publish('I', rows or None)
        elif stage == 'rolling_normalization':
            if status == 'started':
                self.publisher.publish('N')
            elif status == 'completed':
                self.publisher.publish('S', rows)

    def close(self):
        if self.publisher is not None:
            self.publisher.close()

    def wait_for_backup(self, exc):
        from sentinel import backup_retry
        from sentinel.feed import progress

        if self.conn.closed or writer_schedule.connection_discarded(exc):
            raise exc
        self.conn.rollback()
        if self.backup_wait_until is None:
            self.backup_wait_until = monotonic() + writer_schedule.MAX_DRAIN_SECONDS

        def remaining():
            try:
                owned = jobs._owned(self.conn, self.lease)
                left = min((owned[2] - owned[10]).total_seconds(),
                           (owned[3] - owned[10]).total_seconds(),
                           self.backup_wait_until - monotonic())
                external = writer_schedule._external_remaining()
            finally:
                self.conn.rollback()  # _owned takes a row lock. Release it before sleeping.
            if external is not None:
                left = min(left, external)
            if left <= 0:
                raise exc
            return left

        seconds = remaining()
        progress.emit('backup_durability', 'working', job_id=self.lease.job_id,
                      reason=backup_retry.busy_reason(exc).value,
                      remaining_seconds=math.ceil(seconds))
        sleep(min(2.0, seconds))
        remaining()

    @contextmanager
    def acquisition(self):
        started = monotonic()
        with writer_schedule.turn(self.conn, self.lease), store.acquisition_write_lock(self.conn):
            admitted_ms = round((monotonic() - started) * 1000)
            yield
        progress.emit('rolling_writer_admission', 'completed', job_id=self.lease.job_id,
                      reason='ACQUISITION', elapsed_ms=admitted_ms)

    @contextmanager
    def reporting(self, phase, job_id):
        from sentinel.feed import progress
        with progress.phase(phase, job_id=job_id):
            yield
        if phase == 'rolling_operational_publication':
            progress.emit('rolling_operational_visibility', 'completed', job_id=job_id,
                          commit_observed_at=datetime.now(timezone.utc).isoformat())

    @contextmanager
    def publication(self, phase, job_id):
        from sentinel.feed import operational_snapshot
        admitted = False
        started = monotonic()
        try:
            with writer_schedule.turn(self.conn, self.lease), store.corpus_write_lock(self.conn):
                admitted = True
                admitted_ms = round((monotonic() - started) * 1000)
                yield
        except backup_runtime_authority.BackupIntegrityBusy as exc:
            if (admitted or phase != 'rolling_operational_publication'
                    or writer_schedule.connection_discarded(exc)):
                raise
            raise operational_snapshot.PublicationAdmissionBusy(str(exc)) from exc
        progress.emit('rolling_writer_admission', 'completed', job_id=job_id,
                      reason='PUBLICATION', elapsed_ms=admitted_ms)


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
        delay = (max(1, math.ceil(exc.delay)) if isinstance(
            exc, (AlpacaTransportUnavailable, archive_tables.RetryDeferred)) else 10)
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
        elif (isinstance(exc, (archive_tables.RetryDeferred,
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
    observer = PublicationObserver(conn, lease, operational=operational)
    discard_connection = False
    try:
        with progress.observing(observer.observe):
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
        observer.close()
        # Scratch only, scoped to this exact owner; sealed evidence is never deleted.
        if not discard_connection and not conn.closed:
            conn.rollback()
            staging.clear(conn, run_id=lease.owner)
            if operational:
                conn.commit()
