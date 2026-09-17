"""Opt-in direct Sharadar comparison publisher. Never grants corpus/GO authority."""
from __future__ import annotations

import math

from sentinel import backup_runtime_authority, identity
from sentinel.feed import (
    acquisition_work, authority, progress, rolling_builder, rolling_jobs as jobs,
    rolling_store, runtime_schema, sharadar, snapshot_export, staging, store,
)
from sentinel.feed.rolling_contract import digest
from sentinel.feed.rolling_source import SharadarSource
from sentinel.feed.publication import CorpusBusy


class ComparisonRefused(RuntimeError):
    pass


def _latest(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT p.version,c.window_end FROM sentinel_snapshot_comparisons p "
                    "JOIN sentinel_price_candidates c USING(candidate_id) ORDER BY version DESC LIMIT 1")
        return cur.fetchone()


def _legacy_version(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(version) FROM sentinel_corpus_publications")
        return cur.fetchone()[0]


def published(conn, job_id):
    """Idempotent read, including after an uncertain commit acknowledgement."""
    with conn.cursor() as cur:
        cur.execute("SELECT version,candidate_id,validation_sha256,producer_sha256 "
                    "FROM sentinel_snapshot_comparisons WHERE job_id=%s", (job_id,))
        row = cur.fetchone()
    if row is None:
        return None
    manifest = rolling_store.manifest(conn, str(row[1]))
    validation = rolling_store.load_evidence(conn, row[2])
    rolling_store.load_evidence(conn, row[3])
    request = jobs.PreparationRequest.model_validate(jobs.status(conn, job_id)["request"])
    if (validation.get("snapshot_id") != manifest.snapshot_id
            or validation.get("request_sha256") != request.request_sha256
            or validation.get("scope") != "COMPARISON_ONLY"):
        raise ComparisonRefused("comparison validation is not bound to its snapshot and request")
    return {"scope": "COMPARISON_ONLY", "comparison_version": int(row[0]),
            "candidate_id": str(row[1]), "snapshot_id": manifest.snapshot_id,
            "job_id": str(job_id)}


def freeze(conn, lease, request):
    """Freeze the comparison CAS before acquisition; caller owns writer lock."""
    jobs._owned(conn, lease)
    if _legacy_version(conn) != request.expected_publication_version:
        raise ComparisonRefused("legacy publication changed before acquisition")
    latest = _latest(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_snapshot_attempts VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (lease.job_id, latest[0] if latest else None))


def publish(conn, lease, request, *, producer):
    """Atomic comparison CAS; caller holds writer lock/backup authority. No commit."""
    store._assert_corpus_locked(conn)
    row = jobs._owned(conn, lease)
    if row[0] != "READY":
        raise ComparisonRefused("comparison publication requires READY")
    if jobs.PreparationRequest.model_validate(row[7]) != request:
        raise ComparisonRefused("comparison request differs from its durable job")
    with conn.cursor() as cur:
        cur.execute("SELECT expected_version FROM sentinel_snapshot_attempts WHERE job_id=%s",
                    (lease.job_id,))
        attempt = cur.fetchone()
    latest = _latest(conn)
    if attempt is None or attempt[0] != (latest[0] if latest else None):
        raise ComparisonRefused("comparison publication lost its expected generation")
    if _legacy_version(conn) != request.expected_publication_version:
        raise ComparisonRefused("legacy publication changed during preparation")
    if latest is not None and request.window.end < latest[1]:
        raise ComparisonRefused("older window cannot replace a newer comparison frontier")
    candidate = str(row[6])
    manifest = rolling_store.manifest(conn, candidate)
    with conn.cursor() as cur:
        cur.execute("SELECT validation_sha256 FROM sentinel_snapshot_validations WHERE candidate_id=%s",
                    (candidate,))
        validation = cur.fetchone()
    proof = rolling_store.load_evidence(conn, validation[0]) if validation else {}
    if (proof.get("snapshot_id") != manifest.snapshot_id
            or proof.get("request_sha256") != request.request_sha256
            or proof.get("scope") != "COMPARISON_ONLY"):
        raise ComparisonRefused("candidate lacks bound comparison validation")
    producer_sha = rolling_store.put_evidence(conn, producer)
    jobs._owned(conn, lease)  # Recheck time after proof loading, before visibility.
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_snapshot_comparisons "
                    "(previous_version,job_id,candidate_id,validation_sha256,producer_sha256) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (attempt[0], lease.job_id, candidate, validation[0], producer_sha))
        cur.execute("UPDATE sentinel_snapshot_jobs SET reason='COMPARISON_ONLY',owner=NULL,"
                    "lease_until=NULL,next_retry=NULL,updated_at=clock_timestamp() WHERE job_id=%s",
                    (lease.job_id,))
    return published(conn, lease.job_id)


def _checkpoint(conn, lease, *, ready, component, generation, artifact, rows, bytes_):
    if ready:
        matching = [x for x in jobs.components(conn, lease.job_id) if x["component"] == component]
        expected = {"component": component, "generation_sha256": digest(generation),
                    "artifact_sha256": artifact, "rows": rows, "bytes": bytes_}
        if matching != [expected]:
            raise ComparisonRefused("sealed candidate source checkpoint changed")
    else:
        jobs.checkpoint(conn, lease, component=component, generation_sha256=digest(generation),
                        artifact_sha256=artifact, rows=rows, bytes_=bytes_)
        completed = jobs.components(conn, lease.job_id)
        jobs.progress(conn, lease, rows=sum(x["rows"] for x in completed),
                      bytes_=sum(x["bytes"] for x in completed))
    jobs.heartbeat(conn, lease, lease_seconds=600)
    conn.commit()


def _record_failure(conn, lease, exc, *, operational=False):
    conn.rollback()
    if jobs.expire(conn, lease.job_id):
        conn.commit()
        return
    try:
        remaining = jobs.status(conn, lease.job_id)["remaining_seconds"]
        delay = max(1, math.ceil(exc.delay)) if isinstance(exc, sharadar.SharadarRetryDeferred) else 10
        if isinstance(exc, snapshot_export.ExportPending) and remaining > delay:
            state = jobs.status(conn, lease.job_id)["state"]
            jobs.wait(conn, lease, state="WAIT_SOURCE" if state == "ACQUIRING" else "RETRY_WAIT",
                      reason="EXPORT_GENERATION_PENDING", retry_seconds=delay)
        elif isinstance(exc, (sharadar.SharadarRetryDeferred, ConnectionError, CorpusBusy)) and remaining > delay:
            reason = ("BACKUP_AUTHORITY_WAIT" if isinstance(exc, backup_runtime_authority.BackupRuntimeUnavailable)
                      else "CORPUS_WRITER_BUSY" if isinstance(exc, CorpusBusy) else "SOURCE_RETRY")
            jobs.wait(conn, lease, state="RETRY_WAIT", reason=reason, retry_seconds=delay)
        elif isinstance(exc, (KeyboardInterrupt, SystemExit)) and remaining > 2:
            jobs.wait(conn, lease, state="INTERRUPTED", reason="WORKER_INTERRUPTED", retry_seconds=1)
        else:
            reason = ("SOURCE_GENERATION_CHANGED" if isinstance(exc, authority.VendorPublicationUnstable)
                      else "OPERATIONAL_PREPARATION_REFUSED" if operational
                      else "COMPARISON_PREPARATION_REFUSED")
            jobs.finish(conn, lease, state="REFUSED", reason=reason)
        conn.commit()
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
    try:
        current = jobs.status(conn, job_id)
        request = jobs.PreparationRequest.model_validate(current["request"])
        ready = current["state"] == "READY"
        if current["state"] not in {"ACQUIRING", "READY"}:
            raise ComparisonRefused("unexpected persisted direct-builder stage")
        with store.corpus_write_lock(conn):
            boundary.freeze(conn, lease, request)
            conn.commit()
        source = SharadarSource(request.window)

        def pulse():
            jobs.heartbeat(conn, lease, lease_seconds=600)
            conn.commit()

        def checkpoint(component, generation, artifact, rows, bytes_):
            _checkpoint(conn, lease, ready=ready, component=component, generation=generation,
                        artifact=artifact, rows=rows, bytes_=bytes_)

        # A callback slice cannot outlive its worker lease. All retries retain
        # the server-owned absolute deadline; budget() also caps nested HTTP work.
        with acquisition_work.budget(seconds=min(500, current["remaining_seconds"])):
            source.preflight()
            pulse()
            source.references(checkpoint)
            staging.stage(conn, source.prices(checkpoint, pulse), run_id=lease.owner,
                          chunk=rolling_builder.CHUNK)
        if not ready:
            with store.corpus_write_lock(conn):
                identity.require_feed_producer_identity()
                rolling_builder.build(conn, lease, request, source)
                conn.commit()
        else:
            manifest = rolling_store.manifest(conn, str(current["candidate_id"]))
            if (manifest.reference_sha256 != digest(source.reference_payload())
                    or manifest.source_evidence_sha256 != digest(source.source_payload())):
                raise ComparisonRefused("sealed candidate references/source changed on resume")
            conn.commit()
        with acquisition_work.budget(seconds=min(500, jobs.status(conn, job_id)["remaining_seconds"])):
            conn.commit()
            source.corroborate()
        if operational:
            with progress.phase("rolling_operational_validation", job_id=job_id):
                operational_snapshot.validate(conn, lease, request)
                conn.commit()
        phase = "rolling_operational_publication" if operational else "rolling_comparison_publication"
        with progress.phase(phase, job_id=job_id), store.corpus_write_lock(conn):
            producer = identity.require_feed_producer_identity()
            result = boundary.publish(conn, lease, request, producer=producer)
            conn.commit()
        return result
    except BaseException as exc:
        _record_failure(conn, lease, exc, operational=operational)
        raise
    finally:
        # Scratch only, scoped to this exact owner; sealed evidence is never deleted.
        conn.rollback()
        staging.clear(conn, run_id=lease.owner)
        if operational:
            from sentinel.feed import retention
            conn.commit()
            retention.maintain(conn)
