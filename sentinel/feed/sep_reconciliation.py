"""Canonical complete SEP reconciliation with causal source-update authority."""
from __future__ import annotations

import datetime as dt

from sentinel.feed import sep_reconciliation_impl as _core
from sentinel.feed.sep_reconciliation_impl import (
    CURSOR_NAME,
    ReconciliationResult,
    SepKeysetDrift,
    SepReconciliationStateInvalid,
    SepValueDrift,
    YEARS_PER_RUN,
)
from sentinel.feed.source_authority import CanonicalSourceFetch, SepUpdateEnvelope

# Explicit static compatibility/test seams. These are ordinary references and do
# not mutate the implementation module or depend on import order.
_Fingerprint = _core._Fingerprint
_ValueFingerprint = _core._ValueFingerprint
_PartitionProof = _core._PartitionProof
_number = _core._number
_local_fingerprint = _core._local_fingerprint
_visible_bounds = _core._visible_bounds
_load_state = _core._load_state
_save_result = _core._save_result
_bounded_years = _core._bounded_years


def _next_year(conn) -> tuple[int, dt.date, dt.date]:
    """Select the next rotation year through canonical public dependencies."""
    lo, hi = _visible_bounds(conn)
    state = _load_state(conn)
    year = lo.year if state is None else int(state["last_completed_year"]) + 1
    if year > hi.year or year < lo.year:
        year = lo.year
    start = max(lo, dt.date(year, 1, 1))
    end = min(hi, dt.date(year, 12, 31))
    return year, start, end


def _strict_ceiling(value) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ValueError("SEP reconciliation observation ceiling must be a date")
    if isinstance(value, dt.date):
        return value
    text = str(value)
    parsed = dt.date.fromisoformat(text)
    if text != parsed.isoformat():
        raise ValueError("SEP reconciliation observation ceiling must use YYYY-MM-DD")
    return parsed


def _source_fingerprint(
        conn, *, fetch, start: str, end: str, observation_ceiling):
    """Fingerprint one source partition behind the explicit observation ceiling."""
    ceiling = _strict_ceiling(observation_ceiling)
    guarded = CanonicalSourceFetch(
        fetch, sep_update_envelope=SepUpdateEnvelope.through(
            ceiling, context="complete SEP value/key reconciliation"))
    return _core._source_fingerprint(
        conn, fetch=guarded, start=start, end=end)


def reconcile_year(
        conn, *, fetch=_core.sharadar.fetch_table,
        year: int, start: str, end: str,
        observation_ceiling):
    """Prove one stable source year equals published keys and strategy values."""
    _core.store._assert_corpus_locked(conn)
    if not (str(start).startswith(f"{int(year):04d}-")
            and str(end).startswith(f"{int(year):04d}-")):
        raise ValueError("SEP reconciliation window must stay within one year")
    source = _source_fingerprint(
        conn, fetch=fetch, start=start, end=end,
        observation_ceiling=observation_ceiling)
    local = _local_fingerprint(conn, start=start, end=end)
    if source.rows != local.rows or source.key_digest != local.key_digest:
        raise _core.SepKeysetDrift(
            f"stable Sharadar SEP {year} normalized key set disagrees with "
            f"published corpus: source {source.rows:,}/{source.key_digest[:16]}, "
            f"local {local.rows:,}/{local.key_digest[:16]}. This can be a vendor "
            "deletion, insertion, identity restatement, or lost local row. "
            "Refusing to guess which side to repair.")
    if source.value_digest != local.value_digest:
        raise _core.SepValueDrift(
            f"stable Sharadar SEP {year} strategy values disagree with published "
            f"corpus despite an identical {source.rows:,}-row key set: source "
            f"{source.value_digest[:16]}, local {local.value_digest[:16]}. "
            "At least one signal/raw/open/volume value is stale or corrupted; "
            "refusing to earn/advance reconciliation authority over it.")
    current = _core.publication.require_current(conn)
    return _core.ReconciliationResult(
        year=int(year), start=str(start), end=str(end), rows=source.rows,
        digest=source.key_digest, value_digest=source.value_digest,
        max_lastupdated=source.max_lastupdated,
        publication_version=current.version)


def reconcile_all(conn, *, fetch=_core.sharadar.fetch_table,
                  through: str):
    """Prove every published SEP partition through one explicit source day."""
    _core.store._assert_corpus_locked(conn)
    checked_on = _strict_ceiling(through)
    lo, hi = _visible_bounds(conn)
    results = []
    for year, start, end in _bounded_years(lo, hi, checked_on):
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat(),
            observation_ceiling=checked_on)
        _save_result(conn, result, checked_on=checked_on)
        results.append(result)
    return results


def reconcile_next(conn, *, fetch=_core.sharadar.fetch_table,
                   through: str):
    """Advance rotating complete SEP proof through one explicit source day."""
    _core.store._assert_corpus_locked(conn)
    if YEARS_PER_RUN < 1:
        raise ValueError("SHARADAR_SEP_RECONCILE_YEARS_PER_RUN must be >= 1")
    checked_on = _strict_ceiling(through)
    results = []
    for _ in range(YEARS_PER_RUN):
        year, start, end = _next_year(conn)
        if start > checked_on:
            break
        end = min(end, checked_on)
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat(),
            observation_ceiling=checked_on)
        _save_result(conn, result, checked_on=checked_on)
        results.append(result)
    return results


__all__ = [
    "CURSOR_NAME", "ReconciliationResult", "SepKeysetDrift", "SepValueDrift",
    "SepReconciliationStateInvalid", "YEARS_PER_RUN", "reconcile_all",
    "reconcile_next", "reconcile_year",
]
