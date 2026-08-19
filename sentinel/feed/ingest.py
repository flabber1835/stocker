"""Sharadar ingest authority facade.

The implementation stays in :mod:`sentinel.feed.ingest_impl`; this boundary
adds the one property a transport client cannot provide by itself: a source
snapshot must be stable before absence or a new frontier can become authority.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from sentinel.feed import coherence, ingest_impl as _impl, sharadar

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
        # Use the re-exported seam rather than _impl._today directly so focused
        # tests/operators that replace ingest._today keep the pre-facade behavior.
        resolved_to = date_to or _today()
        chunks = sharadar.year_chunks(date_from, resolved_to)
        final_hi = chunks[-1][1]
        guarded = coherence.StableSharadarFetch(
            fetch,
            # Every historical SEP traversal can be paginated and therefore
            # every chunk needs two-observation proof. TICKERS/SFP are held open
            # across the whole seed and corroborated only after the final chunk,
            # so one source generation brackets the complete cross-table join.
            protect_sep=lambda _params: True,
            corroborate_reference=(
                lambda params: str(params.get("date.lte") or "") == final_hi),
            after_session=None,
            seed_mode=True,
            seed_resolve_identity=resolve_identity,
        )
        return _impl._seed_locked(
            conn, date_from=date_from, date_to=resolved_to,
            fetch=guarded, resolve_identity=resolve_identity)


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Daily ingest whose SEP/ACTIONS/TICKERS/SFP reads are source-stable."""
    with _impl.feed_store.corpus_write_lock(conn):
        # The PUBLISHED frontier is the authority boundary. Rows from a failed,
        # unpublished candidate do not excuse a retry from proving that session.
        published_frontier = _impl.feed_store.latest_visible_session(conn)
        guarded = coherence.StableSharadarFetch(
            fetch, after_session=published_frontier)
        return _impl._daily_locked(
            conn, fetch=guarded, resolve_identity=resolve_identity,
            overlap_days=overlap_days, today=today)
