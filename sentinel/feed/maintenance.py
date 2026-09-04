"""Canonical SEP/ACTIONS maintenance authority."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sentinel.feed import maintenance_impl as _core
from sentinel.feed.maintenance_impl import (
    MutationCursorUnavailable,
    SharadarMutationRefused,
    SourceCursor,
    establish_sep_cursor_after_complete_reconciliation,
    establish_sep_cursor_after_seed,
    load_actions_cursor,
    load_sep_cursor,
    reconcile_actions_if_due,
)
from sentinel.feed.identity_refresh import validate_sep_mutation_rows

# Keep the public maintenance module as the canonical static authority for
# callers, readiness/certification gates, and deterministic test seams. Bind
# every retained helper explicitly so implementation-module namespace changes
# cannot silently expand this production surface.
SEP_CURSOR_NAME = _core.SEP_CURSOR_NAME
ACTIONS_CURSOR_NAME = _core.ACTIONS_CURSOR_NAME
ACTIONS_CURSOR_KIND = _core.ACTIONS_CURSOR_KIND
ACTIONS_RECONCILE_DAYS = _core.ACTIONS_RECONCILE_DAYS
ACTIONS_FULL_WINDOW_START = _core.ACTIONS_FULL_WINDOW_START

_read_cursor = _core._read_cursor
_write_cursor = _core._write_cursor
_active_action_rows = _core._active_action_rows
_stable_rows = _core._stable_rows
_mutation_digest = _core._mutation_digest
_action_change_dates = _core._action_change_dates
_retained_market_bounds = _core._retained_market_bounds
_failed_action_reconcile_bar_footprint = _core._failed_action_reconcile_bar_footprint
_semantic_upgrade_replay_dates = _core._semantic_upgrade_replay_dates
_validate_sep_mutation_rows = validate_sep_mutation_rows


def _reconcile_sep_mutations_core(conn, *, fetch=_core.sharadar.fetch_table,
                                  through: str,
                                  reobserve_equal: bool = False
                                  ) -> Optional[_core.SourceCursor]:
    """Apply SEP CDC rows through the canonical typed identity boundary.

    Direct callers keep equal-cursor reconciliation terminal. Production daily
    may explicitly request one same-date re-observation because Sharadar
    ``lastupdated`` has date granularity: a row can appear later on the same UTC
    vendor date after an earlier complete observation of that date.
    """
    _core.store._assert_corpus_locked(conn)
    cursor = load_sep_cursor(conn)  # noqa: F405
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
    if cursor.processed_through == hi and not reobserve_equal:
        return cursor
    lo = cursor.processed_through - dt.timedelta(days=1)
    params = {"lastupdated.gte": lo.isoformat(),
              "lastupdated.lte": hi.isoformat()}
    rows = _stable_rows(fetch, _core.sharadar.SEP, params)
    market_start, market_end = _retained_market_bounds(conn)
    published_from = dt.date.fromisoformat(market_start)
    published_through = dt.date.fromisoformat(market_end)
    dates = _validate_sep_mutation_rows(
        conn, rows, lo=lo, hi=hi, published_from=published_from,
        published_through=published_through)

    if not dates:
        current = _core.publication.require_current(conn)
        return _write_cursor(
            conn, name=SEP_CURSOR_NAME,
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
    return _write_cursor(
        conn, name=SEP_CURSOR_NAME,
        kind="sharadar-sep-lastupdated/v1", through=hi,
        publication_version=published.version)


from sentinel.feed.source_authority import (  # noqa: E402
    LastUpdatedTrackingFetch,
    reconcile_sep_mutations,
)


__all__ = [
    "ACTIONS_RECONCILE_DAYS", "LastUpdatedTrackingFetch",
    "MutationCursorUnavailable", "SEP_CURSOR_NAME", "SharadarMutationRefused",
    "SourceCursor", "establish_sep_cursor_after_complete_reconciliation",
    "establish_sep_cursor_after_seed", "load_actions_cursor", "load_sep_cursor",
    "reconcile_actions_if_due", "reconcile_sep_mutations",
]
