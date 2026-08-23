"""Bounded historical SEP re-normalization through the ordinary ingest membrane.

A historical correction cannot safely update one stored bar in isolation. The
split ratio on session ``t`` is inferred from ``t-1 -> t`` and changing ``t`` can
also change the inference on ``t+1``. ACTIONS corrections have the same shape:
a changed split/dividend row must update the persisted bar economics that Wealth
Core consumes, not only the action table.

This module deliberately reuses the production normalizer, action maps, staging
sort, evidence persistence and bar upsert. It only decides *which bounded
windows* need replay. For every affected effective date it includes the prior,
effective and following XNYS sessions, then merges overlapping windows.
"""
from __future__ import annotations

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
    try:
        effective = calendar.session_on_or_after(str(day))
        prior = calendar.previous_sessions(effective, 2)
        following = calendar.next_session(effective)
    except Exception as exc:  # calendar/date errors become one typed boundary
        raise HistoricalRenormalizationRefused(
            f"cannot map historical correction date {day!r} to XNYS sessions: "
            f"{exc}") from exc
    # At the calendar's absolute lower bound there may be no predecessor. In
    # that one case replay begins on the effective session; everywhere else the
    # prior observation is mandatory because it establishes the split boundary.
    start = prior[-2] if len(prior) >= 2 else effective
    return start, following


def correction_windows(
        dates: Iterable[str], *, market_start: str | None = None,
        market_end: str | None = None) -> list[tuple[str, str]]:
    """Return deterministic merged replay windows for source dates.

    When a retained market boundary is supplied, a source event participates
    only when its effective XNYS session is inside that boundary.  Its ordinary
    prior/effective/following window is then clipped to the same boundary.  A
    complete ACTIONS history is therefore not permission to widen a deliberately
    shorter SEP corpus.
    """
    if (market_start is None) != (market_end is None):
        raise ValueError("market_start and market_end must be supplied together")
    if market_start is not None and str(market_start) > str(market_end):
        raise ValueError(
            f"reversed retained market boundary: {market_start} > {market_end}")

    raw_market_start = None
    if market_start is not None:
        raw_market_start, _ = calendar.action_date_window(
            str(market_start), str(market_end))
    raw: list[tuple[str, str]] = []
    for day in {str(value) for value in dates}:
        if market_start is not None:
            # Cheap raw-date exclusion comes first. Complete ACTIONS authority
            # can begin before the pinned XNYS calendar itself; those dates are
            # metadata-only for a short retained market corpus.
            if day < str(raw_market_start) or day > str(market_end):
                continue
            effective = calendar.session_on_or_after(day)
            if effective < str(market_start) or effective > str(market_end):
                continue
        start, end = _window_for_date(day)
        if market_start is not None:
            start = max(start, str(market_start))
            end = min(end, str(market_end))
        raw.append((start, end))
    raw.sort()
    if not raw:
        return []
    merged: list[list[str]] = []
    for start, end in raw:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
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
        chunk_prefix: str = "historical",
        market_start: str | None = None,
        market_end: str | None = None,
        ) -> list[RenormalizedWindow]:
    """Replay bounded affected windows into ``run`` using canonical ingest logic.

    ``include_action_run_id`` lets an ACTIONS reconciliation normalize prices
    against the *candidate* action generation before publication. The same run
    id stamps both bar changes and action observations, so one corpus publication
    activates the coherent result atomically.
    """
    # Lazy import avoids making ingest_impl's normal seed/daily path depend on a
    # maintenance helper that itself deliberately reuses its private primitives.
    from sentinel.feed import ingest_impl

    windows = correction_windows(
        dates, market_start=market_start, market_end=market_end)
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
