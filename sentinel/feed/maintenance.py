"""Canonical SEP/ACTIONS maintenance authority."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sentinel.feed import maintenance_impl as _core
from sentinel.feed.maintenance_impl import *  # noqa: F403
from sentinel.feed.identity_refresh import validate_sep_mutation_rows


def _reconcile_sep_mutations_core(conn, *, fetch=_core.sharadar.fetch_table,
                                  through: str) -> Optional[_core.SourceCursor]:
    """Apply SEP CDC rows through the canonical typed identity boundary."""
    _core.store._assert_corpus_locked(conn)
    cursor = _core.load_sep_cursor(conn)
    if cursor is None:
        raise _core.MutationCursorUnavailable(
            "SEP lastupdated cursor is absent. A complete source-stable seed or "
            "complete value/key reconciliation must establish the initial "
            "watermark; a moving price-date window cannot prove old rows current.")
    hi = dt.date.fromisoformat(str(through))
    if cursor.processed_through > hi:
        raise _core.SharadarMutationRefused(
            f"SEP mutation cursor {cursor.processed_through} is ahead of "
            f"requested reconciliation through {hi}; refusing to treat future "
            "durable authority as already current")
    if cursor.processed_through == hi:
        return cursor
    lo = cursor.processed_through - dt.timedelta(days=1)
    params = {"lastupdated.gte": lo.isoformat(),
              "lastupdated.lte": hi.isoformat()}
    rows = _core._stable_rows(fetch, _core.sharadar.SEP, params)
    market_start, market_end = _core._retained_market_bounds(conn)
    published_from = dt.date.fromisoformat(market_start)
    published_through = dt.date.fromisoformat(market_end)
    dates = validate_sep_mutation_rows(
        conn, rows, lo=lo, hi=hi, published_from=published_from,
        published_through=published_through)

    if not dates:
        current = _core.publication.require_current(conn)
        return _core._write_cursor(
            conn, name=_core.SEP_CURSOR_NAME,
            kind="sharadar-sep-lastupdated/v1", through=hi,
            publication_version=current.version)

    windows = _core.renormalize.correction_windows(
        dates, market_start=market_start, market_end=market_end)
    run = _core.store.IngestRun(
        conn, "sep_mutations", date_from=windows[0][0],
        date_to=windows[-1][1], chunks_total=len(windows))
    try:
        replayed = _core.renormalize.renormalize(
            conn, fetch=fetch, run=run, dates=dates,
            chunk_prefix="lastupdated", market_start=market_start,
            market_end=market_end)
    except BaseException:                                      # noqa: BLE001
        if run.progress.chunks_done == 0:
            run.finish("failed", "historical SEP mutation re-normalization failed")
        raise
    run.finish("success")
    published = _core.publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=windows[0][0], window_end=windows[-1][1],
        evidence={
            "kind": "sep_mutations",
            "lastupdated_window": [lo.isoformat(), hi.isoformat()],
            "source_rows": len(rows),
            "affected_source_dates": len(set(dates)),
            "replay_windows": [
                {"start": item.start, "end": item.end,
                 "source_rows": item.source_rows,
                 "bars_written": item.bars_written,
                 "rows_dropped": item.rows_dropped}
                for item in replayed],
        })
    return _core._write_cursor(
        conn, name=_core.SEP_CURSOR_NAME,
        kind="sharadar-sep-lastupdated/v1", through=hi,
        publication_version=published.version)


from sentinel.feed.source_authority import (  # noqa: E402
    LastUpdatedTrackingFetch,
    reconcile_sep_mutations,
)


__all__ = list(getattr(_core, "__all__", ()))
for _name in ("LastUpdatedTrackingFetch", "reconcile_sep_mutations"):
    if _name not in __all__:
        __all__.append(_name)
