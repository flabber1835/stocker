"""Complete current-window SEP reconciliation for decision authority.

`lastupdated` discovers changed/inserted rows but cannot discover a deleted row.
The rotating year audit eventually proves deep history, but Wealth Core's current
decision depends directly on its trailing close/liquidity window and must not wait
weeks for that year to rotate back into inspection.

This module therefore proves the exact required Wealth Core close window after
all daily SEP/ACTIONS mutation work has finished. Production acquisition uses a
fresh Nasdaq whole-file export, then the existing canonical reconciliation path
normalizes it against permanent identity and compares exact keys and persisted
strategy values with the current published corpus. Injected test/simulation
sources remain injected and are subjected to the existing two-observation source
stability proof rather than unexpectedly reaching the production network.

The dedicated cursor is deliberately separate from the long-history rotation.
Readiness requires it to cover the published decision frontier, so a deletion or
key drift leaves the runtime fenced even if the ordinary `lastupdated` watermark
already advanced.
"""
from __future__ import annotations

import datetime as dt

from sentinel.feed import (
    calendar, maintenance, publication, sep_reconciliation, sharadar,
    snapshot_export, store)
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES

CURSOR_NAME = "sharadar-sep-recent-export-reconcile:v1"
CURSOR_KIND = "sharadar-sep-recent-export-reconcile/v1"


def load_cursor(conn):
    return maintenance._read_cursor(conn, CURSOR_NAME, CURSOR_KIND)


def _export_fetch(table, params=None, **_kwargs):
    if table != sharadar.SEP:
        raise ValueError("recent SEP reconciliation export fetch accepts only SEP")
    params = dict(params or {})
    start = str(params.get("date.gte") or "")
    end = str(params.get("date.lte") or "")
    if not start or not end:
        raise ValueError("recent SEP export requires explicit date.gte/date.lte")
    rows, _evidence = snapshot_export.fetch_complete_sep(start=start, end=end)
    return rows


def _year_windows(start: str, end: str):
    lo = dt.date.fromisoformat(start)
    hi = dt.date.fromisoformat(end)
    for year in range(lo.year, hi.year + 1):
        first = max(lo, dt.date(year, 1, 1))
        last = min(hi, dt.date(year, 12, 31))
        if first <= last:
            yield year, first.isoformat(), last.isoformat()


def reconcile_recent(conn, *, through: str, fetch=None):
    """Prove the complete current Wealth Core history window against source.

    ``fetch=None`` is the production contract and uses the fresh whole-export
    membrane. An explicit injected fetch stays deterministic/offline; the normal
    reconciliation layer still observes it twice before trusting its content.
    """
    store._assert_corpus_locked(conn)
    requested = dt.date.fromisoformat(str(through))
    prior_cursor = load_cursor(conn)
    if prior_cursor is not None and prior_cursor.processed_through > requested:
        raise maintenance.SharadarMutationRefused(
            f"recent SEP reconciliation cursor {prior_cursor.processed_through} "
            f"is ahead of requested reconciliation through {requested}; refusing "
            "to traverse source under future durable authority")

    source_fetch = _export_fetch if fetch is None else fetch
    sessions = calendar.previous_sessions(str(through), REQUIRED_CLOSES)
    if len(sessions) < REQUIRED_CLOSES:
        raise sep_reconciliation.SepReconciliationStateInvalid(
            f"recent SEP proof needs {REQUIRED_CLOSES} XNYS sessions through "
            f"{through}, calendar exposed only {len(sessions)}")
    start, end = sessions[0], sessions[-1]
    if end != str(through):
        raise sep_reconciliation.SepReconciliationStateInvalid(
            f"recent SEP proof frontier {end} disagrees with requested {through}")

    for year, lo, hi in _year_windows(start, end):
        sep_reconciliation.reconcile_year(
            conn, fetch=source_fetch, year=year, start=lo, end=hi,
            observation_ceiling=through)

    current = publication.require_current(conn)
    return maintenance._write_cursor(
        conn, name=CURSOR_NAME, kind=CURSOR_KIND,
        through=dt.date.fromisoformat(end),
        publication_version=current.version)


__all__ = ["CURSOR_KIND", "CURSOR_NAME", "load_cursor", "reconcile_recent"]
