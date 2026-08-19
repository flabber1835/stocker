"""Sharadar ingest authority facade.

The implementation stays in :mod:`sentinel.feed.ingest_impl`; this boundary
adds the properties a transport client cannot provide by itself:

* source snapshots must be stable before absence/new frontier is authority;
* a validated-success candidate left by a crash must publish before another run;
* a failed physical frontier may never shorten the next retry below the
  published authority frontier;
* SEP's vendor-update clock is maintained independently from market-session
  freshness; and
* a caller never receives ``success`` for a generation whose rows are still
  unpublished/invisible.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable, Iterable, Optional

from sentinel.feed import (
    coherence, ingest_impl as _impl, maintenance, recovery, sharadar)

# Preserve the established module API, including private helpers used by focused
# regression tests and operational diagnostics. Public entry points are replaced
# below; implementation functions retain their original module globals.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


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


def seed(conn, *, date_from: str = _impl.DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None):
    """Seed, publish, then establish the mutation cursor the complete seed earned."""
    sharadar.validate_config()
    with _impl.feed_store.corpus_write_lock(conn):
        # A prior multi-hour seed may be fully validated with only its tiny
        # publication transaction missing. Finish that exact transition before
        # a new candidate is allowed to exist.
        recovery.resume_pending_publication(conn)

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
    sharadar.validate_config()
    resolved_today = today or _today()
    today_date = _dt.date.fromisoformat(str(resolved_today))

    with _impl.feed_store.corpus_write_lock(conn):
        # #108: success+unpublished is VALIDATED_PENDING_PUBLICATION, not a dead
        # run and not permission to start another candidate. Publication first.
        recovery.resume_pending_publication(conn)

        # The CDC cursor must have been EARNED by a complete seed/reconciliation.
        # Missing means unknown historical mutation coverage, not permission to
        # initialize it from today's moving price window.
        if maintenance.load_sep_cursor(conn) is None:
            raise maintenance.MutationCursorUnavailable(
                "SEP mutation watermark has not been established. Run one "
                "complete source-stable feed seed/reconciliation before daily "
                "operation; a 14-day session overlap cannot prove old rows current.")

        # First converge any correction interval that was left un-published by a
        # prior crash. Stopping at yesterday avoids asking historical CDC to
        # interpret a genuinely new ticker/session before today's TICKERS/full
        # daily publication has made its identity available.
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch,
            through=(today_date - _dt.timedelta(days=1)).isoformat())

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

        # Now today's TICKERS/session generation is published, so a correction
        # whose vendor-update date is today can safely resolve any just-arrived
        # identity. This second step advances the mutation cursor through today.
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=today_date.isoformat())
        maintenance.reconcile_actions_if_due(
            conn, fetch=fetch, through=today_date.isoformat())
        return progress
