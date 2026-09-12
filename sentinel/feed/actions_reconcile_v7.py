"""ACTIONS reconciliation epoch v7 — exceptional cash adjudication migration.

The v6 implementation remains the complete Sharadar ACTIONS source authority.
This public epoch composes that source proof with the A1 semantic migration: a
reviewed disputed cash action is replayed once through the ordinary normalized
bar path before a v7 cursor can be earned.
"""
from __future__ import annotations

import datetime as dt

from sentinel.feed import corporate_action_authority
from sentinel.feed import maintenance_impl as _core

ACTIONS_CURSOR_NAME = "sharadar-actions-export-reconcile:v7"
ACTIONS_CURSOR_KIND = "sharadar-actions-export-reconcile/v7"


def load_actions_cursor(conn):
    """Only v7 may authorize current public ACTIONS semantics."""
    return _core._read_cursor(
        conn, ACTIONS_CURSOR_NAME, ACTIONS_CURSOR_KIND)


def _cash_semantic_migration(conn, *, fetch, through: dt.date):
    """Replay every retained reviewed cash event through canonical ingest logic."""
    market_start, market_end = _core._retained_market_bounds(conn)
    dates = corporate_action_authority.semantic_replay_dates(
        market_start=market_start,
        market_end=min(market_end, through.isoformat()))
    if not dates:
        return _core.publication.require_current(conn)

    windows = _core.renormalize.correction_windows(
        dates, market_start=market_start, market_end=market_end)
    if not windows:
        return _core.publication.require_current(conn)

    run = _core.store.IngestRun(
        conn, "actions_reconcile",
        date_from=windows[0][0], date_to=windows[-1][1],
        chunks_total=len(windows))
    replayed = _core.renormalize.renormalize(
        conn, fetch=fetch, run=run, dates=dates,
        chunk_prefix="cash-adjudication-v7",
        market_start=market_start, market_end=market_end)
    run.finish("success")
    return _core.publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=windows[0][0], window_end=windows[-1][1],
        evidence={
            "kind": "actions_cash_adjudication_v7",
            "semantic_epoch": ACTIONS_CURSOR_KIND,
            "authority": corporate_action_authority.authority_manifest(),
            "affected_action_dates": dates,
            "retained_market_window": [market_start, market_end],
            "replay_windows": [
                {"start": item.start, "end": item.end,
                 "source_rows": item.source_rows,
                 "bars_written": item.bars_written,
                 "rows_dropped": item.rows_dropped}
                for item in replayed],
        })


def reconcile_actions_if_due(conn, *, fetch=_core.sharadar.fetch_table,
                             through: str, force: bool = False):
    """Earn complete source authority plus v7 cash-adjudication semantics."""
    _core.store._assert_corpus_locked(conn)
    hi = dt.date.fromisoformat(str(through))
    prior = load_actions_cursor(conn)
    if prior is not None and prior.processed_through > hi:
        raise _core.SharadarMutationRefused(
            f"ACTIONS v7 reconciliation cursor {prior.processed_through} is "
            f"ahead of requested reconciliation through {hi}")

    # v6 proves the complete current Sharadar ACTIONS snapshot and handles all
    # ordinary changed-row/recovery semantics. v7 may be granted only after it.
    _core.reconcile_actions_if_due(
        conn, fetch=fetch, through=hi.isoformat(), force=force)

    if prior is None:
        current = _cash_semantic_migration(conn, fetch=fetch, through=hi)
    else:
        current = _core.publication.require_current(conn)

    return _core._write_cursor(
        conn, name=ACTIONS_CURSOR_NAME, kind=ACTIONS_CURSOR_KIND,
        through=hi, publication_version=current.version)


__all__ = [
    "ACTIONS_CURSOR_KIND", "ACTIONS_CURSOR_NAME",
    "load_actions_cursor", "reconcile_actions_if_due",
]
