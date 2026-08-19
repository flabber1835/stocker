"""Bounded historical SEP re-normalization through the ordinary ingest membrane.

A historical correction cannot safely update one stored bar in isolation.  The
split ratio on session ``t`` is inferred from ``t-1 -> t`` and changing ``t`` can
also change the inference on ``t+1``.  ACTIONS corrections have the same shape:
a changed split/dividend row must update the persisted bar economics that Wealth
Core consumes, not only the action table.

This module deliberately reuses the production normalizer, action maps, staging
sort, evidence persistence and bar upsert.  It only decides *which bounded
windows* need replay.  For every affected effective date it includes the prior,
effective and following exchange sessions, then merges overlapping windows.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass
from typing import Iterable

from sentinel.feed import authority, calendar, domains, sharadar, store, universe


class HistoricalRenormalizationRefused(RuntimeError):
    """An affected date cannot be mapped to a bounded market-session window."""


@dataclass(frozen=True)
class RenormalizedWindow:
    start: str
    end: str
    source_rows: int
    bars_written: int
    rows_dropped: int


def _window_for_date(day: str) -> tuple[str, str]:
    """Prior/effective/following XNYS sessions around a source event date."""
    target = dt.date.fromisoformat(str(day))
    lo = (target - dt.timedelta(days=10)).isoformat()
    hi = (target + dt.timedelta(days=10)).isoformat()
    sessions = list(calendar.sessions_in_range(lo, hi))
    if not sessions:
        raise HistoricalRenormalizationRefused(
            f"no exchange sessions around historical correction date {day}")
    labels = [str(session) for session in sessions]
    pos = bisect.bisect_left(labels, target.isoformat())
    if pos >= len(labels):
        raise HistoricalRenormalizationRefused(
            f"no exchange session on/after historical correction date {day}")
    # ACTIONS dates can be weekends/holidays and snap to the first session on or
    # after the source date. SEP dates are already sessions, so pos names itself.
    event = pos
    start = labels[max(0, event - 1)]
    end = labels[min(len(labels) - 1, event + 1)]
    return start, end


def correction_windows(dates: Iterable[str]) -> list[tuple[str, str]]:
    """Return deterministic merged replay windows for source dates."""
    raw = sorted({_window_for_date(str(day)) for day in dates})
    if not raw:
        return []
    merged: list[list[str]] = []
    for start, end in raw:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            if end > merged[-1][1]:
                merged[-1][1] = end
    return [(start, end) for start, end in merged]


def _stable_sep(fetch, start: str, end: str):
    # The generic source membrane double-observes the complete bounded window,
    # validates critical price domains, then replays only after the two source
    # fingerprints agree. ``after_session=end`` means this historical replay has
    # no *new-frontier* session to validate; stability itself remains mandatory.
    guarded = authority.StableSharadarFetch(fetch, after_session=end)
    return guarded(sharadar.SEP, sharadar.date_params(start, end))


def renormalize(
        conn, *, fetch, run, dates: Iterable[str],
        include_action_run_id: str | None = None,
        chunk_prefix: str = "historical") -> list[RenormalizedWindow]:
    """Replay bounded affected windows into ``run`` using canonical ingest logic.

    ``include_action_run_id`` lets an ACTIONS reconciliation normalize prices
    against the *candidate* action generation before publication.  The same run
    id stamps both bar changes and action observations, so one corpus publication
    activates the coherent result atomically.
    """
    # Lazy import avoids making ingest_impl's normal seed/daily path depend on a
    # maintenance helper that itself deliberately reuses its private primitives.
    from sentinel.feed import ingest_impl

    windows = correction_windows(dates)
    if not windows:
        return []
    resolver = universe.load_resolver(conn).resolve
    results: list[RenormalizedWindow] = []
    for index, (start, end) in enumerate(windows, 1):
        label = f"{chunk_prefix}:{index}:{start}:{end}"
        with run.chunk(label):
            report = domains.NormalisationReport()
            splits, divs, action_rows, ambiguous = ingest_impl._action_maps(
                conn, start, end, include_run_id=include_action_run_id)
            stable_rows = _stable_sep(fetch, start, end)
            ordered = ingest_impl._ordered_sep(
                conn, stable_rows, run_id=run.progress.run_id, chunk=label)
            bars = domains.normalise_sep_rows(
                ordered,
                resolve_identity=resolver,
                authoritative_splits=splits,
                dividends=divs,
                prior_observations=store.previous_observations(conn, start),
                report=report)
            written = store.write_bars(
                conn, bars, run_id=run.progress.run_id, require_lock=True)
            ingest_impl._persist_chunk_evidence(
                conn, run, label, start, end, report, splits,
                action_rows, action_rows, ambiguous)
            dropped = report.dropped_no_raw_close + report.dropped_no_identity
            run.progress.rows_written += written
            run.progress.rows_dropped += dropped
            results.append(RenormalizedWindow(
                start=start, end=end, source_rows=report.rows,
                bars_written=written, rows_dropped=dropped))
    return results


__all__ = [
    "HistoricalRenormalizationRefused", "RenormalizedWindow",
    "correction_windows", "renormalize",
]
