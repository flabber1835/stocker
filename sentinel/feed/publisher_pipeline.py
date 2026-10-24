"""Fixed publication semantics, separate from operational worker lifecycle.

Source selection, candidate validation, sealed checkpoint evidence and corpus
visibility are economic inputs. Scope drivers only observe stages and provide
finite operational contexts; they never receive or replace economic results.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from sentinel import backup_runtime_authority, identity
from sentinel.feed import (
    acquisition_work, progress, rolling_builder, rolling_jobs as jobs,
    rolling_store, rolling_work, store,
)
from sentinel.feed.rolling_contract import digest
from sentinel.feed.retained_source import RetainedSource


class Observer(Protocol):
    def stage(self, name: str) -> None: ...
    def acquisition(self) -> AbstractContextManager[None]: ...
    def publication(self, phase: str, job_id: str) -> AbstractContextManager[None]: ...


class ComparisonRefused(RuntimeError):
    pass


def _operational_source(window, conn, lease, *, corrections,
                        verify_during_coverage):
    from sentinel.feed.alpaca_source import AlpacaSource
    return AlpacaSource(window, conn, lease,
                        verify_during_coverage=verify_during_coverage)


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
            from sentinel.feed.acquisition_parts import SourceRevision
            raise SourceRevision(component, digest(matching), digest([expected]))
    else:
        jobs.checkpoint(conn, lease, component=component, generation_sha256=digest(generation),
                        artifact_sha256=artifact, rows=rows, bytes_=bytes_)
        completed = jobs.components(conn, lease.job_id)
        jobs.progress(conn, lease, rows=sum(x["rows"] for x in completed),
                      bytes_=sum(x["bytes"] for x in completed))
    jobs.heartbeat(conn, lease, lease_seconds=600)
    conn.commit()


def run(conn, job_id, *, operational, boundary, lease, observer: Observer):
    """Run the fixed pipeline under an already claimed owned job."""
    from sentinel.feed import operational_snapshot

    current = jobs.status(conn, job_id)
    request = jobs.PreparationRequest.model_validate(current["request"])
    ready = current["state"] == "READY"
    if current["state"] not in {"ACQUIRING", "READY"}:
        raise ComparisonRefused("unexpected persisted direct-builder stage")
    observer.stage('ACQUISITION_LOCK')
    with observer.acquisition():
        boundary.freeze(conn, lease, request)
        conn.commit()
    observer.stage('SOURCE_PREFLIGHT')
    corrections = None
    if ready:
        manifest = rolling_store.manifest(conn, str(current["candidate_id"]))
        pinned = rolling_store.load_evidence(conn, manifest.source_evidence_sha256)
        from sentinel.feed import source_corrections
        corrections = pinned.get("source_corrections", source_corrections.bootstrap())
    if operational:
        source = _operational_source(request.window, conn, lease,
                                     corrections=corrections,
                                     verify_during_coverage=not ready)
    else:
        source = RetainedSource(request.window, conn, lease, corrections=corrections,
                                verify_during_coverage=not ready)
    if isinstance(source, RetainedSource):
        source.legacy_source_evidence = ready and "source_corrections" not in pinned

    def pulse():
        jobs.heartbeat(conn, lease, lease_seconds=600)
        conn.commit()

    def checkpoint(component, generation, artifact, rows, bytes_):
        _checkpoint(conn, lease, ready=ready, component=component, generation=generation,
                    artifact=artifact, rows=rows, bytes_=bytes_)

    # A callback slice cannot outlive its worker lease. All retries retain
    # the server-owned absolute deadline; budget() also caps nested HTTP work.
    observer.stage('SOURCE_PREFLIGHT')
    with source.parts.unit():
        source.preflight()
        pulse()
    if not ready and isinstance(source, RetainedSource):
        from sentinel.feed import source_wait
        source_wait.check(conn, lease, request, source)
    observer.stage('SOURCE_REFERENCES')
    source.references(checkpoint)
    observer.stage('PRICE_ACQUISITION')
    source.acquire_prices(checkpoint, pulse)
    observer.stage('CANDIDATE_BUILD')
    if ready and getattr(source, "provider", None) == "ALPACA_OPENFIGI":
        source.tickers = rolling_store.load_evidence(conn, manifest.reference_sha256)["tickers"]
    with rolling_work.renewing(lambda: jobs.heartbeat(conn, lease, lease_seconds=600)):
        if not ready:
            with observer.acquisition():
                identity.require_feed_producer_identity()
                rolling_builder.build(conn, lease, request, source)
                conn.commit()
        else:
            manifest = rolling_store.manifest(conn, str(current["candidate_id"]))
            if (manifest.reference_sha256 != digest(source.reference_payload())
                    or manifest.source_evidence_sha256 != digest(source.source_payload())):
                raise ComparisonRefused("sealed candidate references/source changed on resume")
            conn.commit()
        rolling_work.checkpoint()
        if operational:
            # Catch restore-horizon growth before another full assets/actions
            # observation. A renewed READY candidate still gets both checks.
            observer.stage('CANDIDATE_VALIDATION')
            with progress.phase("rolling_operational_validation", job_id=job_id):
                operational_snapshot.validate(conn, lease, request)
                conn.commit()
            # Staging validation deliberately uses archive health only.
            # Once READY, prove financial durability before the final
            # provider reobservation, so a horizon renewal cannot duplicate
            # that expensive network work. Publication checks again.
            backup_runtime_authority.require(conn, operation="operational publication preflight")
            conn.commit()
        rolling_work.checkpoint()
        observer.stage('SOURCE_CORROBORATION')
        with acquisition_work.budget(seconds=min(500, jobs.status(conn, job_id)["remaining_seconds"])):
            conn.commit()
            with progress.phase('rolling_source_corroboration', job_id=job_id):
                source.corroborate()
        rolling_work.checkpoint()
    phase = "rolling_operational_publication" if operational else "rolling_comparison_publication"
    observer.stage('PUBLICATION')
    with observer.publication(phase, job_id):
        producer = identity.require_feed_producer_identity()
        result = boundary.publish(conn, lease, request, producer=producer)
        conn.commit()
    return result
