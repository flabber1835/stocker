"""Sharadar ingest authority facade.

The implementation stays in :mod:`sentinel.feed.ingest_impl`; this boundary
adds the properties a transport client cannot provide by itself:

* source snapshots must be stable before absence/new frontier is authority;
* every pre-validation crash is reclaimed before a new candidate can open;
* a validated-success candidate left by a crash must publish before another run;
* ambiguous legacy multi-candidate state has a supported complete-reseed recovery;
* a failed physical frontier may never shorten the next retry below the
  published authority frontier;
* failed daily vs historical-maintenance candidates are retried by the operation
  that can safely supersede their live rows;
* routine SEP maintenance follows the published daily identity refresh so a
  stale listing interval cannot deadlock the refresh that would extend it;
* historical TICKERS corrections can advance only through a complete,
  identity-aware full-history replacement;
* SEP's vendor-update clock is maintained independently from market-session
  freshness;
* recent decision history receives a complete export-backed negative-space proof;
* a rotating complete SEP key-set proof still audits deep history; and
* a caller never receives ``success`` for a generation whose rows are still
  unpublished/invisible.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable, Iterable, Optional

from sentinel.feed import (
    coherence, identity_rebuild, ingest_impl as _impl, maintenance,
    recent_reconciliation, recovery, reseed, sep_reconciliation, sharadar,
    snapshot_source, universe)

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


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
    # Only the production source membrane has an independent whole-export
    # negative-space witness. An injected test/replay fetch can be stable and
    # deterministic, but repetition cannot prove that a missing SEP row was
    # truly absent from Sharadar. Do not mint an export-backed readiness cursor
    # from that weaker source contract.
    if fetch is not snapshot_source.fetch_table:
        return
    frontier = _impl.feed_store.latest_visible_session(conn)
    if frontier is None:
        raise sep_reconciliation.SepReconciliationStateInvalid(
            "published corpus has no SEP frontier for recent complete proof")
    recent_reconciliation.reconcile_recent(
        conn, through=frontier, fetch=_recent_reconciliation_source(fetch))


def _seed_source(fetch, *, final_hi: str):
    tracked = maintenance.LastUpdatedTrackingFetch(fetch)
    guarded = coherence.StableSharadarFetch(
        tracked, protect_sep=lambda _params: True,
        corroborate_reference=(
            lambda params: str(params.get("date.lte") or "") == final_hi),
        after_session=None, seed_mode=True)
    return tracked, guarded


def _run_seed_generation(
        conn, *, recovery_plan: recovery.FullReseedPlan,
        fetch, final_hi: str, resolve_identity=None):
    """Run ordinary recovery, escalating only the named identity mutation."""
    seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
    tracked, guarded = _seed_source(fetch, final_hi=final_hi)
    try:
        if recovery_plan.retired_run_ids:
            progress = reseed.full_reseed_locked(
                conn, date_from=seed_from, date_to=seed_to,
                fetch=guarded, resolve_identity=resolve_identity)
        else:
            progress = _impl._seed_locked(
                conn, date_from=seed_from, date_to=seed_to,
                fetch=guarded, resolve_identity=resolve_identity)
        return progress, tracked
    except universe.HistoricalIdentityMutation:
        # The ordinary guard is correct. Escalation is allowed only because the
        # requested seed already covers the complete physical/published corpus;
        # `prepare` proves that before a second candidate opens.
        plan = identity_rebuild.prepare(
            conn, date_from=seed_from, date_to=seed_to)
        tracked, guarded = _seed_source(fetch, final_hi=final_hi)
        progress = reseed.full_reseed_locked(
            conn, date_from=seed_from, date_to=seed_to,
            fetch=guarded, resolve_identity=resolve_identity,
            identity_rebuild_plan=plan)
        return progress, tracked


def seed(conn, *, date_from: str = _impl.DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None):
    fetch = _authoritative_source(fetch)
    _validate_source_before_run(fetch)
    with _impl.feed_store.corpus_write_lock(conn):
        resolved_to = date_to or _today()
        recovery_plan = _recover_before_seed(
            conn, date_from=date_from, date_to=resolved_to)
        seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
        chunks = sharadar.year_chunks(seed_from, seed_to)
        final_hi = chunks[-1][1]
        progress, tracked = _run_seed_generation(
            conn, recovery_plan=recovery_plan, fetch=fetch,
            final_hi=final_hi, resolve_identity=resolve_identity)
        published = _finish_publication_or_refuse(conn, progress)
        if tracked.max_sep_lastupdated is None:
            raise maintenance.MutationCursorUnavailable(
                "complete seed published but exposed no SEP lastupdated value; "
                "refusing to invent a mutation watermark")
        maintenance.establish_sep_cursor_after_seed(
            conn, through=tracked.max_sep_lastupdated,
            publication_version=published.version)
        maintenance.reconcile_actions_if_due(
            conn, fetch=_actions_reconciliation_source(fetch),
            through=seed_to, force=True)
        _prove_recent_frontier(conn, fetch=fetch)
        return progress


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    # Production callers must bind the entire daily authority chain to one
    # explicit exchange session. Container timezone/wall-clock date is not a
    # source boundary. Validation that the named session is actually closed is
    # performed by the manual CLI or the automation scheduler before this layer;
    # this layer enforces that no caller can silently fall back to ``date.today``.
    if today is None:
        raise ValueError(
            "daily ingest requires an explicit through-session; wall-clock date "
            "fallback is not publication authority")
    fetch = _authoritative_source(fetch)
    _validate_source_before_run(fetch)
    resolved_today = str(today)
    today_date = _dt.date.fromisoformat(resolved_today)
    yesterday = (today_date - _dt.timedelta(days=1)).isoformat()

    with _impl.feed_store.corpus_write_lock(conn):
        _recover_before_run(conn)
        if maintenance.load_sep_cursor(conn) is None:
            raise maintenance.MutationCursorUnavailable(
                "SEP mutation watermark has not been established. Run the "
                "supported complete `feed-seed` (or a complete source-stable "
                "reconciliation) before daily operation; a 14-day session "
                "overlap cannot prove old rows current.")

        failed = _single_failed_live_candidate(conn)
        if failed is not None:
            if failed.kind == "daily":
                # The new daily generation is the only operation whose complete
                # overlap can safely supersede these live rows. Do not open a
                # publication-capable maintenance generation first.
                pass
            elif failed.kind == "sep_mutations":
                # A failed mutation generation already owns historical live rows.
                # Retrying its exact replay contract is the one deliberate
                # pre-daily exception. Identity-interval refusal happens before
                # a mutation run opens, so the YHNAU deadlock has no failed
                # candidate here and cannot enter this branch.
                maintenance.reconcile_sep_mutations(
                    conn, fetch=fetch, through=yesterday)
                still_failed = _single_failed_live_candidate(conn)
                if still_failed is not None:
                    if (still_failed.run_id != failed.run_id
                            or still_failed.kind != "sep_mutations"):
                        raise recovery.PublicationRecoveryRefused(
                            "SEP mutation recovery exposed a different failed "
                            "candidate; refusing to guess retry order")
                    maintenance.reconcile_sep_mutations(
                        conn, fetch=fetch, through=today_date.isoformat())
                _require_failed_owner_cleared(conn, context="SEP mutation retry")
            elif failed.kind == "actions_reconcile":
                retry_through = _failed_run_end(conn, failed.run_id)
                if retry_through is None:
                    raise recovery.PublicationRecoveryRefused(
                        f"failed ACTIONS reconciliation {failed.run_id} has no "
                        "durable date_to boundary; refusing an unbounded retry")
                maintenance.reconcile_actions_if_due(
                    conn, fetch=_actions_reconciliation_source(fetch),
                    through=retry_through, force=True)
                _require_failed_owner_cleared(
                    conn, context="ACTIONS reconciliation retry")
            else:
                raise recovery.PublicationRecoveryRefused(
                    f"failed live candidate {failed.run_id} has kind "
                    f"{failed.kind!r}; daily operation does not know which "
                    "complete source contract can safely supersede it. Run the "
                    "supported complete `feed-seed` recovery.")

        published_frontier = _impl.feed_store.latest_visible_session(conn)

        # Refresh current TICKERS authority before routine historical maintenance.
        # The daily generation itself already resolves its SEP rows against the
        # exact same-run unpublished TICKERS candidate. Source stability,
        # structural TICKERS authority, daily domain checks and historical
        # identity safety all complete before publication. CDC deliberately does
        # NOT consume that unpublished candidate: it starts only after publication
        # and therefore depends exclusively on the refreshed published resolver.
        listing_frontier = (
            published_frontier if fetch is snapshot_source.fetch_table else None)
        guarded = coherence.StableSharadarFetch(
            fetch, after_session=listing_frontier)
        effective_overlap = recovery.extended_overlap_days(conn, overlap_days)
        progress = _impl._daily_locked(
            conn, fetch=guarded, resolve_identity=resolve_identity,
            overlap_days=effective_overlap, today=resolved_today)
        _finish_publication_or_refuse(conn, progress)

        if failed is not None and failed.kind == "daily":
            _require_failed_owner_cleared(conn, context="daily retry")

        # From here on, every historical maintenance operation sees the identity
        # generation that just became published. If daily publication failed, we
        # never reach this point and no maintenance cursor can advance under an
        # unpublished candidate.
        published_frontier = _impl.feed_store.latest_visible_session(conn)
        sep_reconciliation.reconcile_next(
            conn, fetch=fetch, through=published_frontier)
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=today_date.isoformat())
        maintenance.reconcile_actions_if_due(
            conn, fetch=_actions_reconciliation_source(fetch),
            through=today_date.isoformat())
        _prove_recent_frontier(conn, fetch=fetch)
        return progress
