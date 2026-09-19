"""Opt-in rolling data publication through ordinary corpus receipts. No GO."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sentinel import backup_runtime_authority, identity
from sentinel.feed import calendar, publication, rolling_jobs as jobs, rolling_store, store
from sentinel.feed.rolling_contract import PriceWindow, digest

SCHEMA = "sentinel.operational-snapshot-publication/1"
VALIDATION_SCHEMA = "sentinel.operational-snapshot-validation/1"


class OperationalSnapshotRefused(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def source_final_session(now=None):
    now = _now() if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise OperationalSnapshotRefused("SOURCE_CLOCK_MUST_BE_AWARE")
    now = now.astimezone(ZoneInfo("America/New_York"))
    latest = calendar.latest_closed_session(now)
    not_before = datetime.combine(datetime.fromisoformat(latest).date(), time(23, 45), now.tzinfo)
    return latest if now >= not_before else calendar.previous_sessions(latest, 2)[0]


def registered(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sentinel_operational_snapshot_jobs WHERE job_id=%s", (job_id,))
        return cur.fetchone() is not None


def _current(conn):
    return publication._validate_publication(conn, publication._core.current(conn), allow_snapshot=True)


def enqueue(conn, *, strategy_sha256, dependencies_sha256, budget_seconds=3600):
    """Freeze the current source-final target and ordinary publication CAS. No commit."""
    current = _current(conn)
    request = jobs.PreparationRequest(
        window=PriceWindow.through(source_final_session()),
        expected_publication_version=current.version if current else None,
        strategy_sha256=strategy_sha256,
        dependencies_sha256=digest({"schema": SCHEMA, "dependencies": dependencies_sha256}))
    job = jobs.enqueue(conn, request, budget_seconds=budget_seconds)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_operational_snapshot_jobs VALUES (%s) ON CONFLICT DO NOTHING", (job,))
    return job


def freeze(conn, lease, request):
    store._assert_corpus_locked(conn)
    jobs._owned(conn, lease)
    if not registered(conn, lease.job_id):
        raise OperationalSnapshotRefused("OPERATIONAL_JOB_REGISTRATION_REQUIRED")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sentinel_snapshot_comparisons WHERE job_id=%s", (lease.job_id,))
        if cur.fetchone():
            raise OperationalSnapshotRefused("COMPARISON_CANNOT_BECOME_OPERATIONAL")
    current = _current(conn)
    if (current.version if current else None) != request.expected_publication_version:
        raise OperationalSnapshotRefused("PUBLICATION_CAS_CHANGED")
    if str(request.window.end) != source_final_session():
        raise OperationalSnapshotRefused("SOURCE_FINAL_TARGET_CHANGED")
    if current and current.window_end and str(request.window.end) < current.window_end:
        raise OperationalSnapshotRefused("PUBLICATION_FRONTIER_REGRESSION")


def validate(conn, lease, request):
    """Expensive immutable content/reference checks outside the publication lock."""
    from sentinel.core.rolling_inputs import readiness_inputs
    row = jobs._owned(conn, lease)
    if row[0] != "READY":
        raise OperationalSnapshotRefused("OPERATIONAL_VALIDATION_REQUIRES_READY")
    candidate = str(row[6])
    manifest = rolling_store.manifest(conn, candidate)
    readiness_inputs(conn, candidate_id=candidate, snapshot_id=manifest.snapshot_id)
    proof = {"schema": VALIDATION_SCHEMA, "scope": "DATA_ONLY",
             "snapshot_id": manifest.snapshot_id, "reference_sha256": manifest.reference_sha256,
             "source_evidence_sha256": manifest.source_evidence_sha256,
             "request_sha256": request.request_sha256}
    backup_runtime_authority.require(conn, operation="operational snapshot validation")
    jobs._owned(conn, lease)
    sha = rolling_store.put_evidence(conn, proof)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_operational_snapshot_validations VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (candidate, sha))
        cur.execute("SELECT validation_sha256 FROM sentinel_operational_snapshot_validations WHERE candidate_id=%s",
                    (candidate,))
        if cur.fetchone()[0] != sha:
            raise OperationalSnapshotRefused("OPERATIONAL_VALIDATION_CHANGED")


def _bound(conn, pub):
    binding = pub.evidence.get("rolling_snapshot")
    if not isinstance(binding, dict) or binding.get("schema") != SCHEMA:
        raise OperationalSnapshotRefused("NOT_AN_OPERATIONAL_SNAPSHOT")
    with conn.cursor() as cur:
        cur.execute("SELECT b.job_id,b.candidate_id,b.validation_sha256,j.state,j.publication_version "
                    "FROM sentinel_operational_snapshots b JOIN sentinel_snapshot_jobs j USING(job_id) "
                    "WHERE b.publication_version=%s", (pub.version,))
        row = cur.fetchone()
    if (row is None or row[3] != "PUBLISHED" or row[4] != pub.version
            or str(row[0]) != binding.get("job_id") or str(row[1]) != binding.get("candidate_id")
            or row[2] != binding.get("validation_sha256")):
        raise OperationalSnapshotRefused("OPERATIONAL_BINDING_MISMATCH")
    manifest = rolling_store.manifest(conn, str(row[1]))
    request = jobs.PreparationRequest.model_validate(jobs.status(conn, str(row[0]))["request"])
    proof = rolling_store.load_evidence(conn, row[2])
    if (binding.get("snapshot_id") != manifest.snapshot_id
            or binding.get("reference_sha256") != manifest.reference_sha256
            or proof.get("schema") != VALIDATION_SCHEMA or proof.get("scope") != "DATA_ONLY"
            or proof.get("snapshot_id") != manifest.snapshot_id
            or proof.get("reference_sha256") != manifest.reference_sha256
            or proof.get("source_evidence_sha256") != manifest.source_evidence_sha256
            or proof.get("request_sha256") != request.request_sha256):
        raise OperationalSnapshotRefused("OPERATIONAL_PROOF_MISMATCH")
    return {"data_version": pub.version, "scope": "DATA_ONLY", "operational_go": False,
            "job_id": str(row[0]), "candidate_id": str(row[1]), "snapshot_id": manifest.snapshot_id}


def published(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT publication_version FROM sentinel_operational_snapshots WHERE job_id=%s", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute("SELECT version,previous_version,run_id,window_start,window_end,evidence "
                    "FROM sentinel_corpus_publications WHERE version=%s", (row[0],))
        p = cur.fetchone()
    pub = publication.Publication(int(p[0]), p[1], str(p[2]) if p[2] else None,
                                  str(p[3]), str(p[4]), p[5])
    publication._validate_publication(conn, pub, allow_snapshot=True)
    return _bound(conn, pub)


def publish(conn, lease, request, *, producer):
    """Atomically append ordinary receipt, snapshot binding and job. Caller commits."""
    freeze(conn, lease, request)
    row = jobs._owned(conn, lease)
    if row[0] != "READY" or jobs.PreparationRequest.model_validate(row[7]) != request:
        raise OperationalSnapshotRefused("OPERATIONAL_PUBLICATION_REQUIRES_BOUND_READY")
    actual_producer = identity.require_feed_producer_identity()
    if producer != actual_producer:
        raise OperationalSnapshotRefused("PUBLICATION_PRODUCER_CHANGED")
    backup_runtime_authority.require(conn, operation="operational snapshot publication")
    candidate = str(row[6])
    manifest = rolling_store.manifest(conn, candidate)
    with conn.cursor() as cur:
        cur.execute("SELECT validation_sha256 FROM sentinel_operational_snapshot_validations WHERE candidate_id=%s", (candidate,))
        validated = cur.fetchone()
    proof = rolling_store.load_evidence(conn, validated[0]) if validated else {}
    if proof != {"schema": VALIDATION_SCHEMA, "scope": "DATA_ONLY",
                 "snapshot_id": manifest.snapshot_id, "reference_sha256": manifest.reference_sha256,
                 "source_evidence_sha256": manifest.source_evidence_sha256,
                 "request_sha256": request.request_sha256}:
        raise OperationalSnapshotRefused("BOUND_OPERATIONAL_VALIDATION_REQUIRED")
    previous = _current(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT clock_timestamp()")
        at = cur.fetchone()[0]
    version = previous.version + 1 if previous else 1
    evidence = {"producer": actual_producer, "pitr": publication._publication_recovery_target(conn),
                "rolling_snapshot": {"schema": SCHEMA, "candidate_id": candidate,
                    "snapshot_id": manifest.snapshot_id, "reference_sha256": manifest.reference_sha256,
                    "job_id": lease.job_id, "validation_sha256": validated[0]},
                "strategy_history": {"schema": "sentinel.strategy-history-mutations/1",
                    "baseline_version": version, "publication_version": version, "changes": []}}
    from sentinel.feed import action_history
    evidence["action_history"] = action_history.append(
        conn, candidate=candidate, version=version, previous=previous)
    jobs._owned(conn, lease)
    publication._insert_receipted_publication(
        conn, previous=previous, next_version=version, run_id=None, published_at=at,
        window_start=str(request.window.start), window_end=str(request.window.end), publication_evidence=evidence)
    jobs._owned(conn, lease)  # Receipt-chain work cannot extend the publication lease.
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_operational_snapshots VALUES (%s,%s,%s,%s)",
                    (version, lease.job_id, candidate, validated[0]))
        cur.execute("UPDATE sentinel_snapshot_jobs SET state='PUBLISHED',reason='OPERATIONAL_DATA_PUBLISHED',"
                    "publication_version=%s,owner=NULL,lease_until=NULL,next_retry=NULL,updated_at=clock_timestamp() "
                    "WHERE job_id=%s", (version, lease.job_id))
    return published(conn, lease.job_id)


@contextmanager
def pinned(conn, *, commit=True):
    with publication._core.pinned(conn, commit=commit) as pub:
        publication._validate_publication(conn, pub, allow_snapshot=True)
        yield pub, _bound(conn, pub)


def prepare(conn, job_id):
    from sentinel.feed.rolling_publisher import _prepare
    return _prepare(conn, job_id, operational=True)
