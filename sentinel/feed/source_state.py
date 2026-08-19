"""Publication-scoped Sharadar maintenance state.

A trading-session frontier and a vendor-mutation watermark are different facts.
The former says which market dates the local corpus has published; the latter
says which current-source changes have been reconciled.  The mutation watermark
lives in corpus-publication evidence rather than in an independently mutable
row, so it is structurally impossible for a failed/unpublished ingest to advance
what the next run trusts.

SEP ``lastupdated`` is a current-source change cursor, not a historical vendor
vintage.  Queries are inclusive (``gte``) at the last published watermark so
all records sharing a vendor timestamp/day are replayed idempotently.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

STATE_KEY = "sharadar_source_state"
PROVIDER = "nasdaq-data-link-tables-v3"
ACTIONS_FULL_RECONCILE_DAYS = 7


class SharadarSourceStateError(RuntimeError):
    """Current-source maintenance cannot prove a safe next authority state."""


class SepMutationBaselineRequired(SharadarSourceStateError):
    """A legacy publication has no durable SEP mutation cursor."""


class SepSourceRemovalDetected(SharadarSourceStateError):
    """A complete source reconciliation found keys that disappeared upstream."""


@dataclass
class SepMutationScan:
    """Bounded-memory facts learned from one stable ``lastupdated`` traversal."""

    current_overlap_start: str
    corpus_start: str
    rows: int = 0
    max_lastupdated: Optional[str] = None
    historical_years: set[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.historical_years is None:
            self.historical_years = set()

    def observe(self, row: Mapping) -> None:
        self.rows += 1
        updated = _iso_date(row.get("lastupdated"), field="SEP.lastupdated")
        session = _iso_date(row.get("date"), field="SEP.date")
        if self.max_lastupdated is None or updated > self.max_lastupdated:
            self.max_lastupdated = updated
        if session < self.corpus_start:
            return
        if session < self.current_overlap_start:
            self.historical_years.add(int(session[:4]))


def _iso_date(value, *, field: str) -> str:
    text = str(value or "").strip()
    try:
        return _dt.date.fromisoformat(text[:10]).isoformat()
    except (TypeError, ValueError):
        raise SharadarSourceStateError(
            f"{field} must be a valid ISO date, got {value!r}") from None


def state_from_publication(published) -> dict:
    """Return a defensive copy of the last PUBLISHED Sharadar source state."""
    if published is None:
        return {}
    evidence = getattr(published, "evidence", None) or {}
    state = evidence.get(STATE_KEY) if isinstance(evidence, Mapping) else None
    return dict(state) if isinstance(state, Mapping) else {}


def require_sep_watermark(state: Mapping) -> str:
    value = state.get("sep_lastupdated_watermark")
    if not value:
        raise SepMutationBaselineRequired(
            "the published corpus predates the durable Sharadar SEP mutation "
            "watermark. Re-run the Sharadar seed/re-backfill with this build "
            "before daily operation; guessing a watermark could permanently "
            "skip an older vendor correction")
    return _iso_date(value, field="published SEP mutation watermark")


def mutation_params(watermark: str, through: str) -> dict[str, str]:
    """Inclusive vendor mutation query; equal-watermark rows are never skipped."""
    lo = _iso_date(watermark, field="SEP mutation watermark")
    hi = _iso_date(through, field="SEP mutation upper bound")
    if lo > hi:
        raise SharadarSourceStateError(
            f"SEP mutation watermark {lo} is after requested upper bound {hi}")
    return {"lastupdated.gte": lo, "lastupdated.lte": hi}


def track_mutations(rows: Iterable[Mapping], *, current_overlap_start: str,
                    corpus_start: str) -> tuple[Iterable[Mapping], SepMutationScan]:
    """Wrap a stream so consuming it records mutation years/watermark facts."""
    scan = SepMutationScan(
        current_overlap_start=_iso_date(current_overlap_start,
                                        field="current overlap start"),
        corpus_start=_iso_date(corpus_start, field="corpus start"))

    def replay():
        for row in rows:
            scan.observe(row)
            yield row

    return replay(), scan


def consume_mutations(rows: Iterable[Mapping], *, current_overlap_start: str,
                      corpus_start: str) -> SepMutationScan:
    """Consume a discovery-only mutation traversal without retaining its rows."""
    scan = SepMutationScan(
        current_overlap_start=_iso_date(current_overlap_start,
                                        field="current overlap start"),
        corpus_start=_iso_date(corpus_start, field="corpus start"))
    for row in rows:
        scan.observe(row)
    return scan


def next_reconciliation_year(state: Mapping, *, corpus_start: str,
                             through: str) -> int:
    """Rotate one COMPLETE historical SEP year per successful daily ingest.

    Current-year rows are already traversed by the normal session overlap and
    mutation path. Rotating the closed years bounds daily work while ensuring a
    complete key-set pass over the historical corpus roughly once per month.
    Because the cursor is publication evidence, a failed run repeats the same
    year instead of silently advancing the schedule.
    """
    first = int(_iso_date(corpus_start, field="corpus start")[:4])
    last = int(_iso_date(through, field="reconciliation through")[:4]) - 1
    if last < first:
        return first
    previous = state.get("sep_reconciliation_last_year")
    try:
        previous_year = int(previous) if previous is not None else first - 1
    except (TypeError, ValueError):
        previous_year = first - 1
    candidate = previous_year + 1
    if candidate < first or candidate > last:
        candidate = first
    return candidate


def actions_full_reconciliation_due(state: Mapping, *, through: str) -> bool:
    """Complete ACTIONS snapshot weekly; missing legacy evidence is due now."""
    today = _dt.date.fromisoformat(_iso_date(through, field="ACTIONS through"))
    value = state.get("actions_full_reconciled_on")
    if not value:
        return True
    try:
        previous = _dt.date.fromisoformat(_iso_date(
            value, field="ACTIONS full-reconciliation date"))
    except SharadarSourceStateError:
        return True
    return (today - previous).days >= ACTIONS_FULL_RECONCILE_DAYS


def published_state(previous: Mapping, *, sep_watermark: str,
                    reconciliation_year: int | None,
                    actions_full_reconciled_on: str | None) -> dict:
    """Construct the next state; caller embeds it in the publication transaction."""
    out = dict(previous or {})
    out["provider"] = PROVIDER
    out["sep_lastupdated_watermark"] = _iso_date(
        sep_watermark, field="SEP publication watermark")
    if reconciliation_year is not None:
        out["sep_reconciliation_last_year"] = int(reconciliation_year)
    if actions_full_reconciled_on is not None:
        out["actions_full_reconciled_on"] = _iso_date(
            actions_full_reconciled_on, field="ACTIONS reconciliation date")
    return out


__all__ = [
    "ACTIONS_FULL_RECONCILE_DAYS", "PROVIDER", "STATE_KEY",
    "SepMutationBaselineRequired", "SepMutationScan", "SepSourceRemovalDetected",
    "SharadarSourceStateError", "actions_full_reconciliation_due",
    "consume_mutations", "mutation_params", "next_reconciliation_year",
    "published_state", "require_sep_watermark", "state_from_publication",
    "track_mutations",
]
