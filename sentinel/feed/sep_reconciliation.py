"""Canonical complete SEP reconciliation with causal source-update authority."""
from __future__ import annotations

import datetime as dt

from sentinel.feed import maintenance, seed_coherence, sep_negative_space_guarded
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


def _production_source_ceiling(fetch, market_ceiling: dt.date) -> dt.date:
    """Use one caller-independent vendor-observation boundary for production."""
    from sentinel.feed import snapshot_source

    if fetch is not snapshot_source.fetch_table:
        return market_ceiling
    source_day = _strict_ceiling(seed_coherence.capture_update_ceiling())
    if source_day < market_ceiling:
        raise SepReconciliationStateInvalid(
            f"current source observation date {source_day} is behind market "
            f"reconciliation boundary {market_ceiling}")
    return source_day


def _source_fingerprint(
        conn, *, fetch, start: str, end: str, observation_ceiling):
    """Fingerprint one source partition behind the explicit observation ceiling."""
    ceiling = _strict_ceiling(observation_ceiling)
    guarded = CanonicalSourceFetch(
        fetch, sep_update_envelope=SepUpdateEnvelope.through(
            ceiling, context="complete SEP value/key reconciliation"))
    return _core._source_fingerprint(
        conn, fetch=guarded, start=start, end=end)


def _complete_export_source(*, start: str, end: str):
    """Return one fresh bounded Exporter snapshot plus its durable authority."""
    from sentinel.feed import sharadar, snapshot_export

    rows, evidence = snapshot_export.fetch_complete_sep(start=start, end=end)
    frozen = tuple(dict(row) for row in rows)
    expected = sharadar.date_params(start, end)

    def export_fetch(table, params=None, **_kwargs):
        if table != sharadar.SEP or dict(params or {}) != expected:
            raise ValueError(
                "SEP retirement export may be replayed only for its exact bounded "
                "partition")
        return iter(dict(row) for row in frozen)

    return export_fetch, dict(evidence)


def _fresh_actions_retirement_authority(conn, *, through: dt.date) -> dict:
    """Prove current ACTIONS state immediately before destructive SEP repair.

    A cadence cursor proves an earlier complete observation, not that the current
    source still agrees when a historical SEP row is about to be deleted. Force a
    complete ACTIONS reconciliation, then independently re-export the same bounded
    source and require its exact canonical row set to equal the active projection.
    The second export evidence is persisted with any retirement plan.
    """
    from sentinel.feed import action_source, snapshot_export

    maintenance.reconcile_actions_if_due(
        conn, through=through.isoformat(), force=True)
    rows, evidence = snapshot_export.fetch_complete_actions(
        through=through.isoformat())
    source = {
        identity: payload
        for identity, payload, _row in action_source.distinct_rows(rows)
    }
    active = maintenance._active_action_rows(conn)
    local = {
        identity: action_source.canonical_payload(row)
        for identity, row in active.items()
    }
    if source != local:
        missing = sorted(set(source) - set(local))
        extra = sorted(set(local) - set(source))
        changed = sorted(
            identity for identity in set(source).intersection(local)
            if source[identity] != local[identity])
        raise maintenance.SharadarMutationRefused(
            "fresh complete ACTIONS authority disagrees with the active "
            "published projection after forced reconciliation: "
            f"missing={missing[:8]}, extra={extra[:8]}, changed={changed[:8]}")
    current = _core.publication.require_current(conn)
    bound = dict(evidence)
    bound.update({
        "verified_through": through.isoformat(),
        "verified_publication_version": int(current.version),
        "verified_distinct_rows": len(source),
    })
    return bound


def _repair_local_only_if_proved(
        conn, *, fetch, start: str, end: str, observation_ceiling,
        source, local, require_complete_export: bool = False,
        actions_authority_evidence=None):
    """Repair only a bounded source-stable local-only key set."""
    if int(local.rows) <= int(source.rows):
        return local
    repair_fetch = fetch
    source_authority_evidence = None
    if require_complete_export:
        if actions_authority_evidence is None:
            _lo, market_hi = _visible_bounds(conn)
            actions_authority_evidence = _fresh_actions_retirement_authority(
                conn, through=market_hi)
            # Forced ACTIONS reconciliation may have published corrected bars.
            # Re-observe local state before a destructive decision.
            local = _local_fingerprint(conn, start=start, end=end)
            if int(local.rows) <= int(source.rows):
                if (local.rows == source.rows
                        and local.key_digest == source.key_digest
                        and local.value_digest == source.value_digest):
                    return local
                raise _core.SepKeysetDrift(
                    "published SEP state changed while establishing fresh ACTIONS "
                    "retirement authority; refusing to continue with stale proof")
        repair_fetch, source_authority_evidence = _complete_export_source(
            start=start, end=end)
    sep_negative_space_guarded.repair_local_only(
        conn, fetch=repair_fetch, start=start, end=end,
        observation_ceiling=_strict_ceiling(observation_ceiling),
        expected_source=source,
        source_authority_evidence=source_authority_evidence,
        actions_authority_evidence=actions_authority_evidence)
    return _local_fingerprint(conn, start=start, end=end)


def reconcile_year(
        conn, *, fetch=None,
        year: int, start: str, end: str,
        observation_ceiling, require_complete_export: bool | None = None,
        actions_authority_evidence=None):
    """Prove one stable source year equals published keys and strategy values."""
    from sentinel.feed import snapshot_source

    production = fetch is None
    if production:
        fetch = snapshot_source.fetch_table
    if require_complete_export is None:
        require_complete_export = production or fetch is snapshot_source.fetch_table

    _core.store._assert_corpus_locked(conn)
    if not (str(start).startswith(f"{int(year):04d}-")
            and str(end).startswith(f"{int(year):04d}-")):
        raise ValueError("SEP reconciliation window must stay within one year")
    source = _source_fingerprint(
        conn, fetch=fetch, start=start, end=end,
        observation_ceiling=observation_ceiling)
    local = _local_fingerprint(conn, start=start, end=end)
    if source.rows != local.rows or source.key_digest != local.key_digest:
        local = _repair_local_only_if_proved(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=observation_ceiling,
            source=source, local=local,
            require_complete_export=bool(require_complete_export),
            actions_authority_evidence=actions_authority_evidence)
    if source.rows != local.rows or source.key_digest != local.key_digest:
        raise _core.SepKeysetDrift(
            f"stable Sharadar SEP {year} normalized key set disagrees with "
            f"published corpus: source {source.rows:,}/{source.key_digest[:16]}, "
            f"local {local.rows:,}/{local.key_digest[:16]}. This can be a vendor "
            "insertion, identity restatement, lost local row, or an unproved "
            "deletion outside the bounded negative-space contract. Refusing to "
            "guess which side to repair.")
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


def reconcile_all(conn, *, fetch=None, through: str, observation_ceiling=None):
    """Prove every published SEP partition through one market boundary."""
    from sentinel.feed import snapshot_source

    _core.store._assert_corpus_locked(conn)
    production = fetch is None
    if production:
        fetch = snapshot_source.fetch_table
    market_through = _strict_ceiling(through)
    source_ceiling = (
        _strict_ceiling(observation_ceiling)
        if observation_ceiling is not None
        else _production_source_ceiling(fetch, market_through))
    if source_ceiling < market_through:
        raise SepReconciliationStateInvalid(
            f"current source observation date {source_ceiling} is behind market "
            f"reconciliation boundary {market_through}")
    require_complete_export = production or fetch is snapshot_source.fetch_table
    actions_authority_evidence = None
    if require_complete_export:
        actions_authority_evidence = _fresh_actions_retirement_authority(
            conn, through=market_through)
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=source_ceiling.isoformat(),
            reobserve_equal=True)
    lo, hi = _visible_bounds(conn)
    results = []
    for year, start, end in _bounded_years(lo, hi, market_through):
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat(),
            observation_ceiling=source_ceiling,
            require_complete_export=require_complete_export,
            actions_authority_evidence=actions_authority_evidence)
        _save_result(conn, result, checked_on=source_ceiling)
        results.append(result)
    return results


def reconcile_next(conn, *, fetch=None, through: str, observation_ceiling=None):
    """Advance rotating proof only after pending production mutations converge."""
    from sentinel.feed import snapshot_source

    _core.store._assert_corpus_locked(conn)
    if YEARS_PER_RUN < 1:
        raise ValueError("SHARADAR_SEP_RECONCILE_YEARS_PER_RUN must be >= 1")
    production = fetch is None
    if production:
        fetch = snapshot_source.fetch_table
    market_through = _strict_ceiling(through)
    source_ceiling = (
        _strict_ceiling(observation_ceiling)
        if observation_ceiling is not None
        else _production_source_ceiling(fetch, market_through))
    if source_ceiling < market_through:
        raise SepReconciliationStateInvalid(
            f"current source observation date {source_ceiling} is behind market "
            f"reconciliation boundary {market_through}")
    production = production or fetch is snapshot_source.fetch_table
    require_complete_export = production

    actions_authority_evidence = None
    if production:
        actions_authority_evidence = _fresh_actions_retirement_authority(
            conn, through=market_through)
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=source_ceiling.isoformat(),
            reobserve_equal=True)

    results = []
    for _ in range(YEARS_PER_RUN):
        year, start, end = _next_year(conn)
        if start > market_through:
            break
        end = min(end, market_through)
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat(),
            observation_ceiling=source_ceiling,
            require_complete_export=require_complete_export,
            actions_authority_evidence=actions_authority_evidence)
        _save_result(conn, result, checked_on=source_ceiling)
        results.append(result)
    return results


__all__ = [
    "CURSOR_NAME", "ReconciliationResult", "SepKeysetDrift", "SepValueDrift",
    "SepReconciliationStateInvalid", "YEARS_PER_RUN", "reconcile_all",
    "reconcile_next", "reconcile_year",
]
