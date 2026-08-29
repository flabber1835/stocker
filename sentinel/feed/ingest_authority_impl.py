"""Static helper support for canonical Sharadar ingest authority.

Production seed/daily orchestration is owned exclusively by
:mod:`sentinel.feed.ingest`.  This module contains only narrow helper functions
used by that canonical owner; it exposes no seed/daily production entrypoint.
"""
from __future__ import annotations

from sentinel.feed import (
    coherence, identity_rebuild, identity_refresh, ingest_impl as _impl,
    maintenance, recent_reconciliation, recovery, reseed, sep_reconciliation,
    sharadar, snapshot_source, source_authority, universe)


def _authoritative_source(fetch):
    return snapshot_source.fetch_table if fetch is sharadar.fetch_table else fetch


def _actions_reconciliation_source(fetch):
    return sharadar.fetch_table if fetch is snapshot_source.fetch_table else fetch


def _recent_reconciliation_source(fetch):
    """Production uses Exporter authority; injected sources remain injected."""
    return None if fetch is snapshot_source.fetch_table else fetch


def _validate_source_before_run(fetch) -> None:
    sharadar.validate_config()
    if fetch is snapshot_source.fetch_table:
        snapshot_source.validate_config()
        sharadar._api_key()
    elif fetch is sharadar.fetch_table:
        sharadar._api_key()


def _recover_before_run(conn) -> None:
    _impl.feed_store.reclaim_orphans(conn)
    recovery.resume_pending_publication(conn)


def _recover_before_seed(conn, *, date_from: str,
                         date_to: str) -> recovery.FullReseedPlan:
    _impl.feed_store.reclaim_orphans(conn)
    pending = recovery.pending_validated(conn)
    live = recovery.live_candidates(conn)
    pending_ids = {candidate.run_id for candidate in pending}
    simple_pending = (
        len(pending) == 1 and pending[0].complete
        and all(candidate.run_id in pending_ids for candidate in live))
    if simple_pending:
        recovery.resume_pending_publication(conn)
        return recovery.FullReseedPlan(str(date_from), str(date_to), ())
    if not pending and not live:
        return recovery.FullReseedPlan(str(date_from), str(date_to), ())
    return recovery.prepare_full_reseed(
        conn, date_from=str(date_from), date_to=str(date_to))


def _finish_publication_or_refuse(conn, progress):
    try:
        return recovery.require_published(conn, progress.run_id)
    except recovery.PublicationRecoveryRefused:
        recovery.resume_pending_publication(conn)
        return recovery.require_published(conn, progress.run_id)


def _single_failed_live_candidate(conn):
    candidates = recovery.failed_live_candidates(conn)
    if len(candidates) > 1:
        raise recovery.PublicationRecoveryRefused(
            f"{len(candidates)} failed unpublished candidates still own live "
            f"rows: {[(c.run_id, c.kind) for c in candidates]}. Their coverage "
            "ordering is ambiguous. Run the supported complete `feed-seed` "
            "recovery; it refetches authority rather than requiring manual SQL.")
    return candidates[0] if candidates else None


def _failed_run_end(conn, run_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT date_to FROM feed_ingest_runs WHERE run_id=%s",
                    (str(run_id),))
        row = cur.fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _require_failed_owner_cleared(conn, *, context: str) -> None:
    candidate = _single_failed_live_candidate(conn)
    if candidate is not None:
        raise recovery.PublicationRecoveryRefused(
            f"{context} did not supersede failed live candidate "
            f"{candidate.run_id}/{candidate.kind}; refusing to open another run")


def _prove_recent_frontier(conn, *, fetch) -> None:
    if fetch is not snapshot_source.fetch_table:
        return
    frontier = _impl.feed_store.latest_visible_session(conn)
    if frontier is None:
        raise sep_reconciliation.SepReconciliationStateInvalid(
            "published corpus has no SEP frontier for recent complete proof")
    recent_reconciliation.reconcile_recent(
        conn, through=frontier, fetch=_recent_reconciliation_source(fetch))
