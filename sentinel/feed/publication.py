"""Canonical corpus publication membrane with mandatory seed coherence."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import re
from typing import Mapping

from sentinel.feed import _publication_impl as _core
from sentinel.feed._publication_impl import (  # noqa: F401
    CORPUS_LOCK_KEY,
    CoherenceReport,
    CorpusBusy,
    CorpusIncoherent,
    NoPublishedVersion,
    Publication,
    assert_coherent,
    assert_full_historical_coherent,
    assert_retry_superseded_prior_candidates,
    chain_gaps,
    coherence,
    effective_nonunit_split_rows,
    effective_split_ratio,
    full_historical_coherence,
    retire_failed_universe_candidates,
    visible_predicate,
)
from sentinel.feed.operational_coherence import (  # noqa: F401
    assert_operationally_coherent,
    operational_boundary,
    operational_coherence,
    persist_report as persist_operational_coherence,
    quarantine_status,
)

_run_producer_identity = _core._run_producer_identity

PITR_EVIDENCE_SCHEMA = "sentinel.corpus-publication-pitr/2"
RECEIPT_SCHEMA = "sentinel.corpus-publication-validation/1"
_XID_MODULUS = 1 << 32
_TIMELINE_RE = re.compile(r"^[0-9A-F]{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_object_evidence(value, *, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _core.CorpusIncoherent(
            f"{where} publication evidence must be a JSON object")
    return dict(value)


def _receipt_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _integrity_schema_ready(conn) -> bool:
    """Fast read-only catalog check for the additive enforcement surface."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
              to_regclass('sentinel_publication_validation_receipts')
                IS NOT NULL,
              EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname='sentinel_corpus_publication_evidence_object_ck'
                   AND conrelid='sentinel_corpus_publications'::regclass
                   AND convalidated
              ),
              EXISTS (
                SELECT 1 FROM pg_trigger
                 WHERE tgname='sentinel_publication_receipt_required'
                   AND NOT tgisinternal
              ),
              EXISTS (
                SELECT 1 FROM pg_trigger
                 WHERE tgname='sentinel_publication_receipts_append_only'
                   AND NOT tgisinternal
              )
        """)
        row = cur.fetchone()
    return bool(row and all(bool(value) for value in row))


def _ensure_integrity_schema(conn) -> None:
    """Install additive DB enforcement only when the catalog lacks it."""
    if _integrity_schema_ready(conn):
        return
    with conn.cursor() as cur:
        cur.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname='sentinel_corpus_publication_evidence_object_ck'
                   AND conrelid='sentinel_corpus_publications'::regclass
              ) THEN
                ALTER TABLE sentinel_corpus_publications
                  ADD CONSTRAINT sentinel_corpus_publication_evidence_object_ck
                  CHECK (jsonb_typeof(evidence) = 'object') NOT VALID;
              END IF;
            END $$
        """)
        cur.execute(
            "ALTER TABLE sentinel_corpus_publications VALIDATE CONSTRAINT "
            "sentinel_corpus_publication_evidence_object_ck")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_publication_validation_receipts (
                publication_version BIGINT PRIMARY KEY REFERENCES
                    sentinel_corpus_publications(version) ON DELETE RESTRICT,
                previous_version BIGINT,
                run_id UUID,
                published_at TIMESTAMPTZ NOT NULL,
                window_start DATE,
                window_end DATE,
                evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence)='object'),
                origin_run_status TEXT,
                previous_receipt_sha256 TEXT,
                receipt_sha256 TEXT NOT NULL UNIQUE,
                validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (previous_receipt_sha256 IS NULL OR
                       previous_receipt_sha256 ~ '^[0-9a-f]{64}$'),
                CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
                CHECK ((run_id IS NULL AND origin_run_status IS NULL) OR
                       (run_id IS NOT NULL AND origin_run_status='success'))
            )
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION sentinel_refuse_publication_receipt_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'publication validation receipts are append-only';
            END $$
        """)
        cur.execute("DROP TRIGGER IF EXISTS sentinel_publication_receipts_append_only "
                    "ON sentinel_publication_validation_receipts")
        cur.execute("""
            CREATE TRIGGER sentinel_publication_receipts_append_only
            BEFORE UPDATE OR DELETE ON sentinel_publication_validation_receipts
            FOR EACH ROW EXECUTE FUNCTION
                sentinel_refuse_publication_receipt_mutation()
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION sentinel_require_publication_receipt()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE r RECORD; ingest_status TEXT;
            BEGIN
              SELECT * INTO r FROM sentinel_publication_validation_receipts
               WHERE publication_version=NEW.version;
              IF NOT FOUND THEN
                RAISE EXCEPTION 'publication % lacks validation receipt', NEW.version;
              END IF;
              IF r.previous_version IS DISTINCT FROM NEW.previous_version OR
                 r.run_id IS DISTINCT FROM NEW.run_id OR
                 r.published_at IS DISTINCT FROM NEW.published_at OR
                 r.window_start IS DISTINCT FROM NEW.window_start OR
                 r.window_end IS DISTINCT FROM NEW.window_end OR
                 r.evidence IS DISTINCT FROM NEW.evidence THEN
                RAISE EXCEPTION 'publication % receipt disagrees with row', NEW.version;
              END IF;
              IF NEW.run_id IS NOT NULL THEN
                SELECT status INTO ingest_status FROM feed_ingest_runs
                 WHERE run_id=NEW.run_id;
                IF ingest_status IS DISTINCT FROM 'success' OR
                   r.origin_run_status IS DISTINCT FROM 'success' THEN
                  RAISE EXCEPTION 'publication % origin ingest is not successful',
                                  NEW.version;
                END IF;
              ELSIF r.origin_run_status IS NOT NULL THEN
                RAISE EXCEPTION 'publication % has spurious run authority', NEW.version;
              END IF;
              RETURN NULL;
            END $$
        """)
        cur.execute("DROP TRIGGER IF EXISTS sentinel_publication_receipt_required "
                    "ON sentinel_corpus_publications")
        cur.execute("""
            CREATE CONSTRAINT TRIGGER sentinel_publication_receipt_required
            AFTER INSERT OR UPDATE ON sentinel_corpus_publications
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION sentinel_require_publication_receipt()
        """)


def _publication_recovery_target(conn) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_current_xact_id()::text,"
            " substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8)")
        row = cur.fetchone()
    if row is None or len(row) < 2:
        raise _core.CorpusIncoherent(
            "PostgreSQL did not return transaction/timeline authority for PITR")
    try:
        source_xid8 = int(str(row[0] or "").strip())
    except ValueError as exc:
        raise _core.CorpusIncoherent(
            "PostgreSQL returned a malformed xid8 for publication PITR") from exc
    timeline_hex = str(row[1] or "").strip().upper()
    if source_xid8 < 3 or not _TIMELINE_RE.fullmatch(timeline_hex):
        raise _core.CorpusIncoherent(
            "PostgreSQL returned invalid transaction/timeline authority for PITR")
    recovery_xid = source_xid8 % _XID_MODULUS
    if recovery_xid < 3:
        raise _core.CorpusIncoherent(
            "publication xid maps to a reserved 32-bit recovery transaction id")
    xid_epoch = source_xid8 // _XID_MODULUS
    return {
        "schema": PITR_EVIDENCE_SCHEMA,
        "source_xid8": str(source_xid8),
        "source_xid_epoch": xid_epoch,
        "recovery_target_xid": str(recovery_xid),
        "recovery_target_timeline": f"0x{timeline_hex}",
        "required_base_xid_epoch": xid_epoch,
        "recovery_target_inclusive": True,
        "recovery_target_action": "promote",
    }


def _receipt_body(*, version: int, previous_version, run_id, published_at,
                  window_start, window_end, evidence: Mapping,
                  origin_run_status, previous_receipt_sha256) -> dict:
    return {
        "schema": RECEIPT_SCHEMA,
        "publication_version": int(version),
        "previous_version": (
            int(previous_version) if previous_version is not None else None),
        "run_id": str(run_id) if run_id is not None else None,
        "published_at": published_at.isoformat(),
        "window_start": str(window_start) if window_start is not None else None,
        "window_end": str(window_end) if window_end is not None else None,
        "evidence": dict(evidence),
        "origin_run_status": origin_run_status,
        "previous_receipt_sha256": previous_receipt_sha256,
    }


def _insert_validation_receipt(conn, *, version: int, previous_version, run_id,
                               published_at, window_start, window_end,
                               evidence: Mapping) -> None:
    origin_status = None
    if run_id is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM feed_ingest_runs WHERE run_id=%s",
                        (run_id,))
            row = cur.fetchone()
        if row is None or str(row[0]) != "success":
            raise _core.CorpusIncoherent(
                "publication origin ingest run is absent or not successful")
        origin_status = "success"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT receipt_sha256 FROM sentinel_publication_validation_receipts"
            " ORDER BY publication_version DESC LIMIT 1")
        row = cur.fetchone()
    previous_receipt = str(row[0]) if row else None
    body = _receipt_body(
        version=version, previous_version=previous_version, run_id=run_id,
        published_at=published_at, window_start=window_start,
        window_end=window_end, evidence=evidence,
        origin_run_status=origin_status,
        previous_receipt_sha256=previous_receipt)
    digest = _receipt_digest(body)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_publication_validation_receipts"
            " (publication_version,previous_version,run_id,published_at,"
            " window_start,window_end,evidence,origin_run_status,"
            " previous_receipt_sha256,receipt_sha256)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
            (version, previous_version, run_id, published_at,
             window_start, window_end,
             json.dumps(dict(evidence), sort_keys=True, default=str),
             origin_status, previous_receipt, digest))


def _verify_receipt_chain(conn, *, through_version: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(publication_version)"
            " FROM sentinel_publication_validation_receipts")
        row = cur.fetchone()
        first = int(row[0]) if row and row[0] is not None else None
    if first is None:
        return
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.version,p.previous_version,p.run_id,p.published_at,"
            " p.window_start,p.window_end,p.evidence,r.origin_run_status,"
            " r.previous_receipt_sha256,r.receipt_sha256,ir.status"
            " FROM sentinel_corpus_publications p"
            " LEFT JOIN sentinel_publication_validation_receipts r"
            "   ON r.publication_version=p.version"
            " LEFT JOIN feed_ingest_runs ir ON ir.run_id=p.run_id"
            " WHERE p.version BETWEEN %s AND %s ORDER BY p.version",
            (first, through_version))
        rows = cur.fetchall()
    previous_receipt = None
    for row in rows:
        (version, previous_version, run_id, published_at, window_start,
         window_end, raw_evidence, origin_status, stored_previous,
         stored_digest, live_run_status) = row
        evidence = _require_object_evidence(
            raw_evidence, where=f"version {version}")
        if stored_digest is None:
            raise _core.CorpusIncoherent(
                f"publication version {version} lacks its validation receipt")
        stored_previous_value = (
            str(stored_previous) if stored_previous is not None else None)
        if stored_previous_value != previous_receipt:
            raise _core.CorpusIncoherent(
                "publication validation receipt chain is discontinuous")
        if run_id is not None and (
                str(origin_status) != "success"
                or str(live_run_status) != "success"):
            raise _core.CorpusIncoherent(
                f"publication version {version} lacks successful ingest origin")
        if run_id is None and origin_status is not None:
            raise _core.CorpusIncoherent(
                f"publication version {version} has spurious ingest authority")
        body = _receipt_body(
            version=int(version), previous_version=previous_version,
            run_id=run_id, published_at=published_at,
            window_start=window_start, window_end=window_end,
            evidence=evidence, origin_run_status=origin_status,
            previous_receipt_sha256=previous_receipt)
        expected = _receipt_digest(body)
        if not _SHA_RE.fullmatch(str(stored_digest)) or str(stored_digest) != expected:
            raise _core.CorpusIncoherent(
                f"publication version {version} validation receipt changed")
        previous_receipt = str(stored_digest)


def _validate_publication(conn, publication: Publication | None):
    if publication is None:
        return None
    _require_object_evidence(
        publication.evidence, where=f"version {publication.version}")
    _verify_receipt_chain(conn, through_version=int(publication.version))
    return publication


def current(conn):
    _ensure_integrity_schema(conn)
    return _validate_publication(conn, _core.current(conn))


def require_current(conn):
    publication = current(conn)
    if publication is None:
        raise _core.NoPublishedVersion("no corpus generation has been published")
    return publication


@contextmanager
def pinned(conn):
    _ensure_integrity_schema(conn)
    with _core.pinned(conn) as publication:
        yield _validate_publication(conn, publication)


def _publish_atomic(conn, *, run_id=None, window_start=None, window_end=None,
                    evidence=None):
    """Commit one publication transaction through canonical public dependencies."""
    _ensure_integrity_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_core.CORPUS_LOCK_KEY,))
        if not bool(cur.fetchone()[0]):
            raise _core.CorpusBusy(
                "a session currently has the corpus PINNED; refusing to "
                "publish. Moving the corpus midway through a decision would "
                "make that decision's recorded data_version a lie.")
    try:
        if run_id is not None:
            producer = _run_producer_identity(conn, str(run_id))
            retired_universe = _core.retire_failed_universe_candidates(
                conn, run_id=str(run_id))
            from sentinel.feed import recovery
            action_reconcile_retirement = (
                recovery.load_action_reconcile_retirement_plan(
                    conn, run_id=str(run_id)))
            if action_reconcile_retirement is not None:
                retired_action_bars = (
                    recovery.retire_failed_action_reconcile_bars_for_publication(
                        conn, run_id=str(run_id),
                        plan=action_reconcile_retirement))
            else:
                retired_action_bars = None
            assert_retry_superseded_prior_candidates(conn, run_id=str(run_id))
            from sentinel.feed import actions as action_store
            action_store.publish_run(conn, run_id=str(run_id))
            from sentinel.feed import anomalies as anomaly_store
            anomaly_store.publish_run(conn, run_id=str(run_id))
            from sentinel.feed.universe_projection import project_run
            project_run(conn, run_id=str(run_id))
        else:
            retired_universe = {}
            retired_action_bars = None
        previous = current(conn)
        publication_evidence = _require_object_evidence(
            evidence, where="candidate")
        if "pitr" in publication_evidence:
            raise _core.CorpusIncoherent(
                "caller may not supply publication PITR authority")
        publication_evidence["pitr"] = _publication_recovery_target(conn)
        if run_id is not None:
            supplied_producer = publication_evidence.get("producer")
            if supplied_producer is not None and supplied_producer != producer:
                raise _core.CorpusIncoherent(
                    "caller-supplied publication producer conflicts with the "
                    "durable ingest run")
            publication_evidence["producer"] = producer
        if retired_universe:
            publication_evidence["retired_failed_universe_candidates"] = [
                {"run_id": candidate, "rows": retired_universe[candidate]}
                for candidate in sorted(retired_universe)]
        if retired_action_bars is not None:
            publication_evidence["retired_failed_bars_in_replay"] = (
                retired_action_bars["inside_replay"])
            publication_evidence["retired_failed_bars_outside_market"] = (
                retired_action_bars["outside_market"])
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_corpus_publications (previous_version,"
                " run_id, window_start, window_end, evidence)"
                " VALUES (%s,%s,%s,%s,%s::jsonb)"
                " RETURNING version,published_at",
                (previous.version if previous else None, run_id,
                 window_start, window_end,
                 json.dumps(publication_evidence,
                            sort_keys=True, default=str)))
            version, published_at = cur.fetchone()
        _insert_validation_receipt(
            conn, version=int(version),
            previous_version=previous.version if previous else None,
            run_id=run_id, published_at=published_at,
            window_start=window_start, window_end=window_end,
            evidence=publication_evidence)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_core.CORPUS_LOCK_KEY,))
        conn.commit()
    return require_current(conn)


def publish(conn, *, run_id=None, window_start=None, window_end=None,
            evidence=None):
    """Publish one coherent corpus generation with all durable seed evidence."""
    merged = _require_object_evidence(evidence, where="candidate")
    if run_id is not None:
        from sentinel.feed import seed_coherence

        proof = seed_coherence.require_for_publication(
            conn, run_id=str(run_id), window_start=window_start,
            window_end=window_end)
        if proof is not None:
            supplied = merged.get("seed_coherence")
            if supplied is not None and supplied != proof:
                raise _core.CorpusIncoherent(
                    "caller-supplied seed coherence evidence conflicts with the "
                    "durable ingest run")
            merged["seed_coherence"] = proof
    return _publish_atomic(
        conn, run_id=run_id, window_start=window_start,
        window_end=window_end, evidence=merged)


__all__ = [
    "PITR_EVIDENCE_SCHEMA", "RECEIPT_SCHEMA", "publish", "current",
    "require_current", "pinned", "coherence", "assert_coherent",
    "full_historical_coherence", "assert_full_historical_coherent",
    "operational_boundary", "operational_coherence",
    "assert_operationally_coherent", "persist_operational_coherence",
    "quarantine_status",
]
