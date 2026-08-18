"""Sharadar ingest authority facade.

The implementation stays in :mod:`sentinel.feed.ingest_impl`; this boundary
adds the one property a transport client cannot provide by itself: a source
snapshot must be stable before absence or a new frontier can become authority.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from sentinel.feed import authority, ingest_impl as _impl, sharadar

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
    """Seed through a stable ACTIONS snapshot and stable latest SEP generation."""
    with _impl.feed_store.corpus_write_lock(conn):
        resolved_to = date_to or _impl._today()
        chunks = sharadar.year_chunks(date_from, resolved_to)
        final_hi = chunks[-1][1]
        guarded = authority.StableSharadarFetch(
            fetch,
            # Historical years are immutable source history for this purpose;
            # the publication-race risk is the newest vendor generation. Do not
            # double a multi-decade seed merely to prove old calendar years twice.
            protect_sep=lambda params: str(params.get("date.lte") or "") == final_hi,
            after_session=None,
        )
        return _impl._seed_locked(
            conn, date_from=date_from, date_to=resolved_to,
            fetch=guarded, resolve_identity=resolve_identity)


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Daily ingest whose SEP/ACTIONS reads are publication-stable before use."""
    with _impl.feed_store.corpus_write_lock(conn):
        # The PUBLISHED frontier is the authority boundary. Rows from a failed,
        # unpublished candidate do not excuse a retry from proving that session.
        published_frontier = _impl.feed_store.latest_visible_session(conn)
        guarded = authority.StableSharadarFetch(
            fetch, after_session=published_frontier)
        return _impl._daily_locked(
            conn, fetch=guarded, resolve_identity=resolve_identity,
            overlap_days=overlap_days, today=today)
