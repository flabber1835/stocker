"""Sharadar ingest authority facade.

The implementation stays in :mod:`sentinel.feed.ingest_impl`; this boundary
adds the properties a transport client cannot provide by itself:

* source snapshots must be stable before absence/new frontier is authority;
* every pre-validation crash is reclaimed before a new candidate can open;
* a validated-success candidate left by a crash must publish before another run;
* a failed physical frontier may never shorten the next retry below the
  published authority frontier;
* failed daily vs historical-maintenance candidates are retried in the order
  that can actually supersede their physical rows;
* SEP's vendor-update clock is maintained independently from market-session
  freshness;
* a rotating complete SEP key-set proof detects removals a mutation cursor
  cannot reveal; and
* a caller never receives ``success`` for a generation whose rows are still
  unpublished/invisible.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable, Iterable, Optional

from sentinel.feed import (
    coherence, ingest_impl as _impl, maintenance, recovery,
    sep_reconciliation, sharadar)

# Preserve the established module API, including private helpers used by focused
# regression tests and operational diagnostics. Public entry points are replaced
# below; implementation functions retain their original module globals.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


def _validate_source_before_run(fetch) -> None:
    """Fail production transport/config/credentials before durable ingest state.

    Injected fetch functions are the established test/simulation seam and do not
    require a real Sharadar credential. The production adapter does.
    """
    sharadar.validate_config()
    if fetch is sharadar.fetch_table:
        sharadar._api_key()


def _recover_before_run(conn) -> None:
    """Converge every durable pre-run crash state while holding writer authority.

    ``reclaim_orphans`` retires only runs that were still RUNNING when their
    process died; it deliberately leaves validated SUCCESS rows intact. The
    second step then resumes publication for exactly such a SUCCESS candidate.
    The nested advisory-lock acquisition inside ``reclaim_orphans`` is safe and
    intentional: PostgreSQL session advisory locks are re-entrant/counting, so
    its matching unlock leaves this facade's outer writer hold in force.
    """
    _impl.feed_store.reclaim_orphans(conn)
    recovery.resume_pending_publication(conn)


def _finish_publication_or_refuse(conn, progress):
    """Close the deliberate finish->publish crash window before returning."""
    try:
        return recovery.require_published(conn, progress.run_id)
    except recovery.PublicationRecoveryRefused:
        # `_impl._publish_version` is intentionally non-fatal for its historical
        # callers. The authority facade is stricter: while we still own the
        # writer lock, retry the tiny publication transaction immediately. If it
        # cannot publish, the exception escapes and the daily operation is not
        # reported as successful.
        recovery.resume_pending_publication(conn)
        return recovery.require_published(conn, progress.run_id)


def _single_failed_live_candidate(conn):
    candidates = recovery.failed_live_candidates(conn)
    if len(candidates) > 1:
        raise recovery.PublicationRecoveryRefused(
            f"{len(candidates)} failed unpublished candidates still own live "
            f"rows: {[(c.run_id, c.kind) for c in candidates]}. Their coverage "
            "ordering is ambiguous; refusing to create a third candidate.")
    return candidates[0] if candidates else None


def _failed_run_end(conn, run_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date_to FROM feed_ingest_runs WHERE run_id=%s",
            (str(run_id),))
        row = cur.fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _require_failed_owner_cleared(conn, *, context: str) -> None:
    candidate = _single_failed_live_candidate(conn)
    if candidate is not None:
        raise recovery.PublicationRecoveryRefused(
            f"{context} did not supersede failed live candidate "
            f"{candidate.run_id}/{candidate.kind}; refusing to open another run")


def seed(conn, *, date_from: str = _impl.DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None):
    """Seed, publish, then establish the mutation cursor the complete seed earned."""
    _validate_source_before_run(fetch)
    with _impl.feed_store.corpus_write_lock(conn):
        # This is the supported restart path for all #108 boundaries: an
        # interrupted pre-validation run is failed/retired; a fully validated
        # run whose publication transaction never completed is published now.
        _recover_before_run(conn)

        # Use the re-exported seam rather than _impl._today directly so focused
        # tests/operators that replace ingest._today keep the pre-facade behavior.
        resolved_to = date_to or _today()
        chunks = sharadar.year_chunks(date_from, resolved_to)
        final_hi = chunks[-1][1]

        # A complete seed is the only cheap point at which every SEP row already
        # crosses the source boundary. Track the vendor update clock there rather
        # than guessing an initial CDC watermark from a later 14-day price window.
        tracked = maintenance.LastUpdatedTrackingFetch(fetch)
        guarded = coherence.StableSharadarFetch(
            tracked,
            # Every historical SEP traversal can be paginated and therefore
            # every chunk needs two-observation proof. TICKERS/SFP are held open
            # across the whole seed and corroborated only after the final chunk,
            # so one source generation brackets the complete cross-table join.
            protect_sep=lambda _params: True,
            corroborate_reference=(
                lambda params: str(params.get("date.lte") or "") == final_hi),
            after_session=None,
            seed_mode=True,
        )
        # ``resolve_identity`` remains the established normalization test seam.
        # Source completeness above is intentionally tied only to the stable
        # TICKERS snapshot, so a caller cannot make a partial identity domain
        # look complete by supplying an optimistic resolver callback.
        progress = _impl._seed_locked(
            conn, date_from=date_from, date_to=resolved_to,
            fetch=guarded, resolve_identity=resolve_identity)
        published = _finish_publication_or_refuse(conn, progress)
        if tracked.max_sep_lastupdated is None:
            raise maintenance.MutationCursorUnavailable(
                "complete seed published but exposed no SEP lastupdated value; "
                "refusing to invent a mutation watermark")
        maintenance.establish_sep_cursor_after_seed(
            conn, through=tracked.max_sep_lastupdated,
            publication_version=published.version)
        # ACTIONS does not have a mutation timestamp. Establish its independent
        # complete-source checkpoint now so later daily runs can use the cheap
        # cadence gate rather than assuming the seed's event-date window was a
        # permanent reconciliation mechanism.
        maintenance.reconcile_actions_if_due(
            conn, fetch=fetch, through=resolved_to, force=True)
        return progress


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Daily source maintenance with independent session and mutation clocks."""
    _validate_source_before_run(fetch)
    resolved_today = today or _today()
    today_date = _dt.date.fromisoformat(str(resolved_today))
    yesterday = (today_date - _dt.timedelta(days=1)).isoformat()

    with _impl.feed_store.corpus_write_lock(conn):
        _recover_before_run(conn)

        # The CDC cursor must have been EARNED by a complete seed/reconciliation.
        # Missing means unknown historical mutation coverage, not permission to
        # initialize it from today's moving price window.
        if maintenance.load_sep_cursor(conn) is None:
            raise maintenance.MutationCursorUnavailable(
                "SEP mutation watermark has not been established. Run one "
                "complete source-stable feed seed/reconciliation before daily "
                "operation; a 14-day session overlap cannot prove old rows current.")

        # There can be at most one failed run that still owns physical rows in
        # normal operation because the writer lock serializes every feed run and
        # we refuse to open another until the prior owner is superseded. Which
        # operation failed matters: opening the wrong kind of retry can itself be
        # blocked by the old owner and strand recovery forever.
        failed = _single_failed_live_candidate(conn)
        retry_daily_first = False
        if failed is not None:
            if failed.kind == "daily":
                # Its recent TICKERS/SEP/SFP keys can only be superseded by a
                # complete daily retry. Historical maintenance is deferred until
                # after that publication; the writer lock prevents any reader
                # from consuming the intermediate state and readiness remains
                # fenced until the mutation cursor catches the new frontier.
                retry_daily_first = True
            elif failed.kind == "sep_mutations":
                # Normal pre-daily maintenance covers through yesterday. A
                # same-day retry can instead be recovering the post-daily CDC
                # phase; if yesterday is a no-op and the failed owner remains,
                # today's TICKERS generation is already published, so replaying
                # through today is safe and is the only operation that can take
                # ownership of those historical bar keys.
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
                _require_failed_owner_cleared(
                    conn, context="SEP mutation retry")
            elif failed.kind == "actions_reconcile":
                retry_through = _failed_run_end(conn, failed.run_id)
                if retry_through is None:
                    raise recovery.PublicationRecoveryRefused(
                        f"failed ACTIONS reconciliation {failed.run_id} has no "
                        "durable date_to boundary; refusing an unbounded retry")
                maintenance.reconcile_actions_if_due(
                    conn, fetch=fetch, through=retry_through, force=True)
                _require_failed_owner_cleared(
                    conn, context="ACTIONS reconciliation retry")
            else:
                raise recovery.PublicationRecoveryRefused(
                    f"failed live candidate {failed.run_id} has kind "
                    f"{failed.kind!r}; daily operation does not know which "
                    "complete source contract can safely supersede it")

        if not retry_daily_first:
            # First converge any correction interval that was left un-published
            # by a prior crash. Stopping at yesterday avoids asking historical
            # CDC to interpret a genuinely new ticker/session before today's
            # TICKERS/full daily publication has made its identity available.
            maintenance.reconcile_sep_mutations(
                conn, fetch=fetch, through=yesterday)

            # `lastupdated` cannot reveal a row that disappeared from the
            # provider. Reconcile one complete stable historical year BEFORE
            # today's frontier is allowed to publish. If key-set/value drift is
            # found, the still-stale visible frontier remains the durable
            # readiness fence.
            sep_reconciliation.reconcile_next(
                conn, fetch=fetch, through=resolved_today)

        # The PUBLISHED frontier is the authority boundary. Rows from a failed,
        # unpublished candidate do not excuse a retry from proving that session.
        published_frontier = _impl.feed_store.latest_visible_session(conn)
        guarded = coherence.StableSharadarFetch(
            fetch, after_session=published_frontier)

        # `_daily_locked` computes its start from the physical MAX(session). If a
        # failed candidate advanced that frontier beyond the visible one, expand
        # its nominal overlap by exactly the physical/visible gap so every old
        # candidate-owned leading-edge key is revisited and can be superseded.
        effective_overlap = recovery.extended_overlap_days(conn, overlap_days)
        progress = _impl._daily_locked(
            conn, fetch=guarded, resolve_identity=resolve_identity,
            overlap_days=effective_overlap, today=resolved_today)
        _finish_publication_or_refuse(conn, progress)

        if retry_daily_first:
            # The ordinary retry has now taken ownership of the failed daily
            # generation. Run the deletion/value-drift proof before advancing
            # the CDC cursor. If it refuses, the cursor is still behind the newly
            # published frontier, so readiness remains fail-closed after the
            # writer lock is released.
            _require_failed_owner_cleared(conn, context="daily retry")
            sep_reconciliation.reconcile_next(
                conn, fetch=fetch, through=resolved_today)

        # Now today's TICKERS/session generation is published, so a correction
        # whose vendor-update date is today can safely resolve any just-arrived
        # identity. This second step advances the mutation cursor through today.
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=today_date.isoformat())
        maintenance.reconcile_actions_if_due(
            conn, fetch=fetch, through=today_date.isoformat())
        return progress
