"""Authenticated rolling display metadata; no financial corpus admission."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
import time

from sentinel.feed import operational_snapshot as snapshots, readers
from sentinel.feed import readiness, rolling_jobs as jobs, rolling_store


@dataclass(frozen=True)
class _ByteProof:
    started: float
    deadline: float
    observed_at: datetime
    valid_until: datetime

    def current(self, instant, clock):
        return (self.started <= clock < self.deadline
                and self.observed_at <= instant < self.valid_until)


_BYTE_PROOFS: dict[str, _ByteProof] = {}
_PROOF_LOCK = Lock()
_MAX_PROOFS = 16


def _now():
    return datetime.now(timezone.utc)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _byte_context(conn):
    """Fresh small context; absent independent DDL evidence grants no reuse."""
    present = conn.execute(
        "SELECT to_regclass('public.sentinel_operational_ddl_epoch') IS NOT NULL").fetchone()[0]
    if not present:
        return None
    from sentinel.panel import read_projection, authority_reader
    physical, installation, epoch, _ = read_projection._subject_facts(conn)
    info = conn.info
    sources = [Path(__file__), Path(rolling_store.__file__)]
    return _digest(['sentinel.display-evidence-byte-proof/1',
        [info.host, info.port, info.dbname, info.user], list(physical),
        installation['installation_id'] if installation is not None else None,
        epoch, sorted(os.environ.items()),
        [(str(path), hashlib.sha256(path.read_bytes()).hexdigest()) for path in sources],
        rolling_store.MAX_EVIDENCE_BYTES, authority_reader.FRESH_SECONDS])


def _byte_subject(conn, identity, context):
    row = conn.execute(
        "SELECT d.oid::text,pg_postmaster_start_time()::text,"
        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric/4294967296)::bigint,"
        "e.tableoid::text,pg_relation_filenode(e.tableoid)::text,c.reltoastrelid::text,"
        "pg_relation_filenode(c.reltoastrelid)::text,e.xmin::text,e.ctid::text,"
        "e.payload IS NULL,e.canonical_payload IS NOT NULL,octet_length(e.canonical_payload) "
        "FROM sentinel_snapshot_evidence e JOIN pg_class c ON c.oid=e.tableoid "
        "JOIN pg_database d ON d.datname=current_database() WHERE e.evidence_sha256=%s",
        (identity,)).fetchone()
    # Legacy JSON remains with the original canonical decoder/verifier.
    if row is None or row[-3] is not True or row[-2] is not True:
        return None
    return _digest([os.getpid(), context, identity, list(row)])


def _verify_evidence(conn, identity, *, context):
    """Reuse only successful bytes under this caller's immutable MVCC frame."""
    if context is None:
        rolling_store.verify_evidence(conn, identity)
        return
    from sentinel.panel import authority_reader
    started, instant = time.monotonic(), _now()
    subject = _byte_subject(conn, identity, context)
    if subject is not None:
        with _PROOF_LOCK:
            proof = _BYTE_PROOFS.get(subject)
        if proof is not None and proof.current(_now(), time.monotonic()):
            return
    rolling_store.verify_evidence(conn, identity)
    proof = _ByteProof(started, started + authority_reader.FRESH_SECONDS,
        instant, instant + timedelta(seconds=authority_reader.FRESH_SECONDS))
    if subject is not None and proof.current(_now(), time.monotonic()):
        with _PROOF_LOCK:
            if subject not in _BYTE_PROOFS and len(_BYTE_PROOFS) >= _MAX_PROOFS:
                _BYTE_PROOFS.pop(next(iter(_BYTE_PROOFS)))
            _BYTE_PROOFS[subject] = proof


def status_snapshot(conn, *, include_publication=False):
    """Read one fresh, read-only MVCC frame; caller owns its rollback."""
    if conn.autocommit:
        raise ValueError('DISPLAY_STATUS_REQUIRES_CALLER_TRANSACTION')
    with conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    pub = _current(conn)
    if pub is None or not readers.is_rolling(pub):
        return readers.status_snapshot(conn, include_publication=include_publication)
    snapshot = readiness.latest_snapshot(conn)
    result = pub.window_end, snapshot if readers.snapshot_matches(pub, snapshot) else None
    return (*result, pub.version) if include_publication else result


def _current(conn):
    from sentinel.feed import readiness_scope
    readiness_scope.require(conn)
    pub = snapshots._current(conn)
    if pub is not None and readers.is_rolling(pub):
        _binding(conn, pub)
    return pub


def _manifest(conn, candidate_id):
    """Project immutable metadata, retaining the financial reader's validations."""
    if conn.autocommit:
        raise rolling_store.SnapshotStorageRefused('DISPLAY_MANIFEST_REQUIRES_CALLER_TRANSACTION')
    settings = conn.execute(
        "SELECT current_setting('transaction_isolation'),"
        "current_setting('transaction_read_only')").fetchone()
    if settings != ('repeatable read', 'on'):
        raise rolling_store.SnapshotStorageRefused('DISPLAY_MANIFEST_REQUIRES_READ_ONLY_SNAPSHOT')
    row = conn.execute(
        'SELECT snapshot_id,manifest,session_axis,reference_sha256,source_evidence_sha256 '
        'FROM sentinel_price_candidates WHERE candidate_id=%s', (candidate_id,)).fetchone()
    if row is None or row[1] is None:
        raise rolling_store.SnapshotStorageRefused('candidate has no sealed manifest')
    value = rolling_store.SnapshotManifest.model_validate(row[1])
    if value.snapshot_id != row[0]:
        raise rolling_store.SnapshotStorageRefused('snapshot manifest content identity differs')
    if (value.window.model_dump(mode='json')['sessions'] != row[2]
            or value.reference_sha256 != row[3] or value.source_evidence_sha256 != row[4]):
        raise rolling_store.SnapshotStorageRefused('snapshot manifest differs from its candidate')
    from sentinel.feed.normalized_layout import require_layout
    require_layout(conn, candidate_id, value)
    if not rolling_store.retired(conn, candidate_id):
        context = _byte_context(conn)
        for identity in dict.fromkeys((value.reference_sha256, value.source_evidence_sha256)):
            _verify_evidence(conn, identity, context=context)
    return value


def _binding(conn, pub):
    """Project the existing DATA_ONLY binding; never grant operational GO."""
    binding = pub.evidence.get('rolling_snapshot')
    if not isinstance(binding, dict) or binding.get('schema') != snapshots.SCHEMA:
        raise snapshots.OperationalSnapshotRefused('NOT_AN_OPERATIONAL_SNAPSHOT')
    row = conn.execute(
        'SELECT b.job_id,b.candidate_id,b.validation_sha256,j.state,j.publication_version '
        'FROM sentinel_operational_snapshots b JOIN sentinel_snapshot_jobs j USING(job_id) '
        'WHERE b.publication_version=%s', (pub.version,)).fetchone()
    if (row is None or row[3] != 'PUBLISHED' or row[4] != pub.version
            or str(row[0]) != binding.get('job_id') or str(row[1]) != binding.get('candidate_id')
            or row[2] != binding.get('validation_sha256')):
        raise snapshots.OperationalSnapshotRefused('OPERATIONAL_BINDING_MISMATCH')
    manifest = _manifest(conn, str(row[1]))
    request = jobs.PreparationRequest.model_validate(jobs.status(conn, str(row[0]))['request'])
    proof = rolling_store.load_evidence(conn, row[2])
    if (binding.get('snapshot_id') != manifest.snapshot_id
            or binding.get('reference_sha256') != manifest.reference_sha256
            or proof.get('schema') != snapshots.VALIDATION_SCHEMA or proof.get('scope') != 'DATA_ONLY'
            or proof.get('snapshot_id') != manifest.snapshot_id
            or proof.get('reference_sha256') != manifest.reference_sha256
            or proof.get('source_evidence_sha256') != manifest.source_evidence_sha256
            or proof.get('request_sha256') != request.request_sha256):
        raise snapshots.OperationalSnapshotRefused('OPERATIONAL_PROOF_MISMATCH')
    return dict(data_version=pub.version, scope='DATA_ONLY', operational_go=False,
                job_id=str(row[0]), candidate_id=str(row[1]), snapshot_id=manifest.snapshot_id)
