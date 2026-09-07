"""Production-safe SEP reconciliation facade and destructive repair authority."""
from __future__ import annotations

import datetime as dt

from sentinel.feed import (
    maintenance,
    seed_coherence,
    sep_negative_space_guarded,
    sep_reconciliation_impl as _core,
    snapshot_source,
)
from sentinel.feed.sep_reconciliation_impl import (
    CURSOR_NAME,
    ReconciliationResult,
    SepKeysetDrift,
    SepReconciliationStateInvalid,
    SepValueDrift,
    YEARS_PER_RUN,
)
from sentinel.feed.source_authority import CanonicalSourceFetch, SepUpdateEnvelope


def _strict_ceiling(value) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def _visible_bounds(conn):
    return _core._visible_bounds(conn)


def _source_fingerprint(
        conn, *, fetch, start: str, end: str, observation_ceiling):
    """Fingerprint one source partition behind the explicit observation ceiling."""
    ceiling = _strict_ceiling(observation_ceiling)
    guarded = CanonicalSourceFetch(
        fetch, sep_update_envelope=SepUpdateEnvelope.through(
            ceiling, context="complete SEP value/key reconciliation"))
    return _core._source_fingerprint(
        conn, fetch=guarded, start=start, end=end)


def _local_fingerprint(conn, *, start: str, end: str):
    return _core._local_fingerprint(conn, start=start, end=end)


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
    """Prove current ACTIONS state immediately before destructive SEP repair."""
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
        conn, *, fetch=snapshot_source.fetch_table, year: int,
        start: str, end: str, observation_ceiling,
        require_complete_export: bool = False):
    """Compare one complete normalized SEP partition and repair proven surplus."""
    _core.store._assert_corpus_locked(conn)
    source = _source_fingerprint(
        conn, fetch=fetch, start=start, end=end,
        observation_ceiling=observation_ceiling)
    local = _local_fingerprint(conn, start=start, end=end)
    if source.rows != local.rows or source.key_digest != local.key_digest:
        local = _repair_local_only_if_proved(
            conn, fetch=fetch, start=start, end=end,
            observation_ceiling=observation_ceiling,
            source=source, local=local,
            require_complete_export=require_complete_export)
    if source.rows != local.rows or source.key_digest != local.key_digest:
        raise SepKeysetDrift(
            f"SEP normalized key-set drift for {start}..{end}: "
            f"source rows={source.rows:,} digest={source.key_digest[:16]}, "
            f"local rows={local.rows:,} digest={local.key_digest[:16]}. "
            "Refusing to guess whether the source is incomplete or the local "
            "corpus has stale/missing rows.")
    if source.value_digest != local.value_digest:
        raise SepValueDrift(
            f"SEP normalized strategy values disagree for {start}..{end}: "
            f"source={source.value_digest[:16]}, local={local.value_digest[:16]}")
    publication = _core.publication.require_current(conn)
    return ReconciliationResult(
        year=int(year), start=str(start), end=str(end), rows=source.rows,
        digest=source.key_digest, value_digest=source.value_digest,
        max_lastupdated=source.max_lastupdated,
        publication_version=publication.version)


def _production_source_ceiling(fetch, market_through: dt.date) -> dt.date:
    if fetch is snapshot_source.fetch_table:
        return _strict_ceiling(seed_coherence.capture_update_ceiling())
    return market_through


def _prepare_production_partition_authority(conn, *, fetch, market_through: dt.date):
    """Refresh ACTIONS and SEP CDC before negative-space partition authority."""
    ceiling = _production_source_ceiling(fetch, market_through)
    if fetch is snapshot_source.fetch_table:
        maintenance.reconcile_actions_if_due(
            conn, through=market_through.isoformat())
        maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=ceiling.isoformat(),
            reobserve_equal=True)
    return ceiling


def _next_year(conn):
    return _core._next_year(conn)


def _save_result(conn, result, through):
    return _core._save_result(conn, result, through)


def reconcile_next(conn, *, fetch=snapshot_source.fetch_table, through: str):
    """Rotate complete reconciliation; production retirement is Exporter-backed."""
    _core.store._assert_corpus_locked(conn)
    market_through = dt.date.fromisoformat(str(through))
    ceiling = _prepare_production_partition_authority(
        conn, fetch=fetch, market_through=market_through)
    results = []
    for _ in range(YEARS_PER_RUN):
        selected = _next_year(conn)
        if selected is None:
            break
        year, lo, hi = selected
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=lo.isoformat(), end=hi.isoformat(),
            observation_ceiling=ceiling,
            require_complete_export=(fetch is snapshot_source.fetch_table))
        _save_result(conn, result, market_through)
        results.append(result)
    return results


def reconcile_all(conn, *, fetch=snapshot_source.fetch_table, through: str):
    """Complete launch sweep over every currently published year partition."""
    _core.store._assert_corpus_locked(conn)
    market_through = dt.date.fromisoformat(str(through))
    ceiling = _prepare_production_partition_authority(
        conn, fetch=fetch, market_through=market_through)
    lo, hi = _visible_bounds(conn)
    results = []
    for year in range(lo.year, hi.year + 1):
        start = max(lo, dt.date(year, 1, 1)).isoformat()
        end = min(hi, dt.date(year, 12, 31)).isoformat()
        result = reconcile_year(
            conn, fetch=fetch, year=year, start=start, end=end,
            observation_ceiling=ceiling,
            require_complete_export=(fetch is snapshot_source.fetch_table))
        _save_result(conn, result, market_through)
        results.append(result)
    return results


__all__ = [
    "CURSOR_NAME", "ReconciliationResult", "SepKeysetDrift",
    "SepReconciliationStateInvalid", "SepValueDrift", "YEARS_PER_RUN",
    "reconcile_all", "reconcile_next", "reconcile_year",
]
