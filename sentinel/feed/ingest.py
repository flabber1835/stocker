"""Sharadar ingest authority facade.

The source-stability membrane remains above the transport adapter. #185 adds a
CDC/crash-convergent orchestrator underneath it; callers retain the established
``seed``/``daily`` API and test injection seams.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from sentinel.feed import cdc_ingest, coherence, ingest_impl as _impl, sharadar

# Preserve the established module API, including private helpers used by focused
# regression tests and operational diagnostics. Public entry points are replaced
# below; implementation functions retain their original module globals.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


def seed(conn, *, date_from: str = _impl.DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None):
    """Seed only after source stability and session-local completeness proof."""
    with _impl.feed_store.corpus_write_lock(conn):
        # A process can die after durable validation but before publication. Try
        # that exact candidate first; if it is no longer self-contained the new
        # seed below is the complete superseding generation.
        cdc_ingest.resume_validated_publication(conn)
        resolved_to = date_to or _today()
        chunks = sharadar.year_chunks(date_from, resolved_to)
        final_hi = chunks[-1][1]
        guarded = coherence.StableSharadarFetch(
            fetch,
            protect_sep=lambda _params: True,
            corroborate_reference=(
                lambda params: str(params.get("date.lte") or "") == final_hi),
            after_session=None,
            seed_mode=True,
        )
        return cdc_ingest.seed_locked(
            conn, date_from=date_from, date_to=resolved_to,
            fetch=guarded, resolve_identity=resolve_identity)


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Daily ingest with stable-source proof, real SEP CDC and convergent retry."""
    with _impl.feed_store.corpus_write_lock(conn):
        cdc_ingest.resume_validated_publication(conn)
        published_frontier = _impl.feed_store.latest_visible_session(conn)
        guarded = coherence.StableSharadarFetch(
            fetch, after_session=published_frontier)
        return cdc_ingest.daily_locked(
            conn, fetch=guarded, resolve_identity=resolve_identity,
            overlap_days=overlap_days, today=today)
