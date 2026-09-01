"""Canonical corpus publication membrane with mandatory seed coherence."""
from __future__ import annotations

import json

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
    current,
    effective_nonunit_split_rows,
    effective_split_ratio,
    full_historical_coherence,
    pinned,
    require_current,
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

# Explicit static seam retained for provenance/certification tests.
_run_producer_identity = _core._run_producer_identity

PITR_EVIDENCE_SCHEMA = "sentinel.corpus-publication-pitr/1"


def _publication_recovery_target(conn) -> dict[str, object]:
    """Bind this publication to the exact PostgreSQL transaction that commits it.

    PostgreSQL physical recovery can target this transaction ID inclusively and
    promote immediately after replaying it. Capturing the current xid inside the
    publication transaction turns the already-required base-backup + continuous
    WAL archive into an exact historical recovery target for this corpus version.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_current_xact_id()::text")
        row = cur.fetchone()
    if row is None or not str(row[0] or "").strip():
        raise _core.CorpusIncoherent(
            "PostgreSQL did not return a transaction id for publication PITR")
    return {
        "schema": PITR_EVIDENCE_SCHEMA,
        "recovery_target_xid": str(row[0]),
        "recovery_target_inclusive": True,
        "recovery_target_action": "promote",
    }


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
        publication_evidence = dict(evidence or {})
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
                " VALUES (%s,%s,%s,%s,%s) RETURNING version",
                (previous.version if previous else None, run_id,
                 window_start, window_end,
                 json.dumps(publication_evidence,
                            sort_keys=True, default=str)))
            cur.fetchone()
        conn.commit()
    except BaseException:  # noqa: BLE001
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
    merged = dict(evidence or {})
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
    "PITR_EVIDENCE_SCHEMA", "publish", "coherence", "assert_coherent",
    "full_historical_coherence", "assert_full_historical_coherent",
    "operational_boundary", "operational_coherence",
    "assert_operationally_coherent", "persist_operational_coherence",
    "quarantine_status",
]
