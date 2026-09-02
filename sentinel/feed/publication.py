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
RECEIPT_EVIDENCE_KEY = "publication_validation"
_XID_MODULUS = 1 << 32
_TIMELINE_RE = re.compile(r"^[0-9A-F]{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_object_evidence(value, *, where: str) -> dict:
    if value is None:
        raise _core.CorpusIncoherent(
            f"{where} publication evidence must be a JSON object")
    if not isinstance(value, Mapping):
        raise _core.CorpusIncoherent(
            f"{where} publication evidence must be a JSON object")
    return dict(value)


def _candidate_evidence(value) -> dict:
    if value is None:
        return {}
    return _require_object_evidence(value, where="candidate")


def _receipt_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _origin_run_status(conn, run_id) -> str | None:
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
    return origin_status


def _receipt_from_evidence(evidence: Mapping) -> Mapping | None:
    receipt = evidence.get(RECEIPT_EVIDENCE_KEY)
    if receipt is None:
        return None
    if not isinstance(receipt, Mapping):
        raise _core.CorpusIncoherent(
            "publication validation receipt must be a JSON object")
    return receipt


def _add_validation_receipt(
        conn, *, version: int, previous_version, run_id, published_at,
        window_start, window_end, evidence: Mapping,
        previous_receipt_sha256: str | None) -> dict:
    clean_evidence = dict(evidence)
    if RECEIPT_EVIDENCE_KEY in clean_evidence:
        raise _core.CorpusIncoherent(
            "caller may not supply publication validation authority")
    origin_status = _origin_run_status(conn, run_id)
    body = _receipt_body(
        version=version, previous_version=previous_version, run_id=run_id,
        published_at=published_at, window_start=window_start,
        window_end=window_end, evidence=evidence,
        origin_run_status=origin_status,
        previous_receipt_sha256=previous_receipt_sha256)
    digest = _receipt_digest(body)
    clean_evidence[RECEIPT_EVIDENCE_KEY] = {
        "schema": RECEIPT_SCHEMA,
        "previous_receipt_sha256": previous_receipt_sha256,
        "receipt_sha256": digest,
    }
    return clean_evidence


def _verify_receipt_chain(
        conn, *, through_version: int,
        required_after_version: int | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT required_after_version"
            " FROM sentinel_publication_validation_policy")
        policy_rows = cur.fetchall()
        if len(policy_rows) != 1:
            raise _core.CorpusIncoherent(
                "publication validation policy is missing or ambiguous")
        policy_boundary = int(policy_rows[0][0])
        # The durable policy boundary is the exact pre-receipt legacy prefix.
        # A signed root may lie inside that prefix but cannot retroactively make
        # independently authenticated receipts exist for historical rows.
        if (required_after_version is not None
                and int(required_after_version) > int(through_version)):
            raise _core.CorpusIncoherent(
                "publication receipt requirement starts after the pinned version")
        cur.execute(
            "SELECT p.version,p.previous_version,p.run_id,p.published_at,"
            " p.window_start,p.window_end,p.evidence,ir.status,"
            " r.previous_version,r.run_id,r.published_at,r.window_start,"
            " r.window_end,r.evidence,r.origin_run_status,"
            " r.previous_receipt_sha256,r.receipt_sha256"
            " FROM sentinel_corpus_publications p"
            " LEFT JOIN feed_ingest_runs ir ON ir.run_id=p.run_id"
            " LEFT JOIN sentinel_publication_validation_receipts r"
            "   ON r.publication_version=p.version"
            " WHERE p.version > %s AND p.version <= %s ORDER BY p.version",
            (policy_boundary, through_version))
        rows = cur.fetchall()
    previous_receipt = None
    for row in rows:
        (version, previous_version, run_id, published_at, window_start,
         window_end, raw_evidence, live_run_status, receipt_previous_version,
         receipt_run_id, receipt_published_at, receipt_window_start,
         receipt_window_end, receipt_evidence, origin_run_status,
         stored_previous, stored_digest) = row
        evidence = _require_object_evidence(
            raw_evidence, where=f"version {version}")
        embedded = _receipt_from_evidence(evidence)
        if receipt_evidence is None or embedded is None:
            raise _core.CorpusIncoherent(
                f"publication version {version} lacks its validation receipt")
        if embedded.get("schema") != RECEIPT_SCHEMA:
            raise _core.CorpusIncoherent(
                f"publication version {version} has an unknown validation receipt")
        stored_previous_value = (
            str(stored_previous) if stored_previous is not None else None)
        if stored_previous_value != previous_receipt:
            raise _core.CorpusIncoherent(
                "publication validation receipt chain is discontinuous")
        if run_id is not None and str(live_run_status) != "success":
            raise _core.CorpusIncoherent(
                f"publication version {version} lacks successful ingest origin")
        unsigned_evidence = _require_object_evidence(
            receipt_evidence, where=f"version {version} receipt")
        if (receipt_previous_version != previous_version
                or receipt_run_id != run_id
                or receipt_published_at != published_at
                or receipt_window_start != window_start
                or receipt_window_end != window_end
                or unsigned_evidence != {
                    key: value for key, value in evidence.items()
                    if key != RECEIPT_EVIDENCE_KEY}):
            raise _core.CorpusIncoherent(
                f"publication version {version} receipt does not match its row")
        expected_origin = "success" if run_id is not None else None
        if origin_run_status != expected_origin:
            raise _core.CorpusIncoherent(
                f"publication version {version} receipt has invalid origin")
        body = _receipt_body(
            version=int(version), previous_version=previous_version,
            run_id=run_id, published_at=published_at,
            window_start=window_start, window_end=window_end,
            evidence=unsigned_evidence, origin_run_status=expected_origin,
            previous_receipt_sha256=previous_receipt)
        expected = _receipt_digest(body)
        if (not _SHA_RE.fullmatch(str(stored_digest))
                or str(stored_digest) != expected
                or embedded.get("receipt_sha256") != expected
                or embedded.get("previous_receipt_sha256") != previous_receipt):
            raise _core.CorpusIncoherent(
                f"publication version {version} validation receipt changed")
        previous_receipt = str(stored_digest)


def _latest_receipt_sha256(conn, *, through_version: int) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT receipt_sha256"
            " FROM sentinel_publication_validation_receipts"
            " WHERE publication_version <= %s"
            " ORDER BY publication_version DESC LIMIT 1", (through_version,))
        row = cur.fetchone()
    if row is None:
        return None
    digest = str(row[0])
    if not _SHA_RE.fullmatch(digest):
        raise _core.CorpusIncoherent(
            "previous publication validation receipt is malformed")
    return digest


def _validate_publication(conn, publication: Publication | None):
    if publication is None:
        return None
    _require_object_evidence(
        publication.evidence, where=f"version {publication.version}")
    _verify_receipt_chain(conn, through_version=int(publication.version))
    return publication


def current(conn):
    return _validate_publication(conn, _core.current(conn))


def require_current(conn):
    publication = current(conn)
    if publication is None:
        raise _core.NoPublishedVersion("no corpus generation has been published")
    return publication


@contextmanager
def pinned(conn, *, commit: bool = True):
    with _core.pinned(conn, commit=commit) as publication:
        yield _validate_publication(conn, publication)


def _publish_atomic(conn, *, run_id=None, window_start=None, window_end=None,
                    evidence=None):
    """Commit one publication transaction through canonical public dependencies."""
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
        publication_evidence = _candidate_evidence(evidence)
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
            cur.execute("SELECT clock_timestamp()")
            published_at = cur.fetchone()[0]
        # PostgreSQL sequences are intentionally non-transactional: a rejected
        # insert consumes a value even though no publication row commits.  Name
        # the exact candidate version before hashing its receipt, then insert
        # that allocated value explicitly.  Chain continuity is carried by the
        # predecessor link, not by gapless sequence arithmetic.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nextval(pg_get_serial_sequence("
                "'sentinel_corpus_publications','version'))")
            next_version = int(cur.fetchone()[0])
        previous_receipt = (
            _latest_receipt_sha256(conn, through_version=previous.version)
            if previous is not None else None)
        unsigned_publication_evidence = dict(publication_evidence)
        publication_evidence = _add_validation_receipt(
            conn, version=next_version,
            previous_version=previous.version if previous else None,
            run_id=run_id, published_at=published_at,
            window_start=window_start, window_end=window_end,
            evidence=publication_evidence,
            previous_receipt_sha256=previous_receipt)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_corpus_publications (version,"
                " previous_version,run_id,published_at,window_start,window_end,"
                " evidence) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)"
                " RETURNING version,published_at",
                (next_version, previous.version if previous else None,
                 run_id, published_at,
                 window_start, window_end,
                 json.dumps(publication_evidence,
                            sort_keys=True, default=str)))
            version, _stored_published_at = cur.fetchone()
            if int(version) != next_version:  # pragma: no cover - DB contract
                raise _core.CorpusIncoherent(
                    "database stored a different publication version than allocated")
            receipt = publication_evidence[RECEIPT_EVIDENCE_KEY]
            cur.execute(
                "INSERT INTO sentinel_publication_validation_receipts ("
                " publication_version,previous_version,run_id,published_at,"
                " window_start,window_end,evidence,origin_run_status,"
                " previous_receipt_sha256,receipt_sha256)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (next_version, previous.version if previous else None, run_id,
                 published_at, window_start, window_end,
                 json.dumps(unsigned_publication_evidence,
                            sort_keys=True, default=str),
                 "success" if run_id is not None else None,
                 previous_receipt, receipt["receipt_sha256"]))
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
    merged = _candidate_evidence(evidence)
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
    "PITR_EVIDENCE_SCHEMA", "RECEIPT_SCHEMA", "RECEIPT_EVIDENCE_KEY",
    "publish", "current",
    "require_current", "pinned", "coherence", "assert_coherent",
    "full_historical_coherence", "assert_full_historical_coherent",
    "operational_boundary", "operational_coherence",
    "assert_operationally_coherent", "persist_operational_coherence",
    "quarantine_status",
]
