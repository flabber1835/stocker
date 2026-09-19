"""Bounded economic continuity between two explicitly pinned snapshots."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, field as dataclass_field
from fractions import Fraction
import hashlib
from itertools import zip_longest
from datetime import date, timedelta
from stock_strategy_shared.split_reconciliation import SPLIT_PRICE_QUANTUM

from sentinel.core.history import RollingContinuityProof
from sentinel.core.rolling_inputs import SnapshotReferences, fresh_anchors
from sentinel.core.rolling_reader import RollingPriceReader
from sentinel.core.session import _path_dependent_security_ids
from sentinel.feed import calendar, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest


class RollingContinuityRefused(RuntimeError):
    pass


def _scale_interval(value, prior):
    if value is None or prior is None:
        if value is prior:
            return None
        raise RollingContinuityRefused("OVERLAP_PRICE_AVAILABILITY_CHANGED")
    new, old = Fraction(str(value)), Fraction(str(prior))
    half_quantum = Fraction(str(SPLIT_PRICE_QUANTUM)) / 2
    if min(new, old) <= half_quantum:
        raise RollingContinuityRefused("OVERLAP_PRICE_PRECISION_UNAVAILABLE")
    return ((new - half_quantum) / (old + half_quantum),
            (new + half_quantum) / (old - half_quantum))


def _intersect_scale(scales, key, value, prior, refusal):
    interval = _scale_interval(value, prior)
    if interval is None:
        return
    lower, upper = scales.get(key, interval)
    lower, upper = max(lower, interval[0]), min(upper, interval[1])
    if lower > upper:
        raise RollingContinuityRefused(refusal + key)
    scales[key] = (lower, upper)


def _same_reference(previous, current, cursor):
    old_meta, old_sectors = previous.current_metadata(session=cursor)
    historical_meta, historical_sectors = current.current_metadata(session=cursor)
    for sid, value in old_meta.items():
        if historical_meta.get(sid) != value or historical_sectors.get(sid) != old_sectors[sid]:
            raise RollingContinuityRefused("HISTORICAL_REFERENCE_CHANGED: " + sid)
    boundaries = {cursor}
    for refs in (previous, current):
        for sid in old_meta:
            for item in refs.listings.get(sid, ()):
                for value in (item.first_session, item.last_session):
                    if value and value <= cursor:
                        boundaries.add(value)
                        boundaries.add((date.fromisoformat(value) - timedelta(days=1)).isoformat())
                        if value < cursor:
                            boundaries.add((date.fromisoformat(value) + timedelta(days=1)).isoformat())
    def listing_prefix(refs):
        return [(sid, day, refs.resolver.ticker_for_security(sid, day))
                for sid in sorted(old_meta) for day in sorted(boundaries)]
    listings = listing_prefix(previous)
    if listing_prefix(current) != listings:
        raise RollingContinuityRefused("HISTORICAL_LISTING_IDENTITY_CHANGED")
    old_actions = sorted(canonical_json(p) for _, p, _ in previous.actions if p["date"] <= cursor)
    actions = sorted(canonical_json(p) for _, p, _ in current.actions if p["date"] <= cursor)
    if actions != old_actions:
        raise RollingContinuityRefused("HISTORICAL_ACTIONS_CHANGED")
    meta, sectors = current.current_metadata()
    return meta, sectors, digest({"metadata": {k: asdict(v) for k, v in old_meta.items()},
                                 "sectors": old_sectors, "listings": listings, "actions": actions})


def _overlap(conn, previous, current, refs, cursor):
    start = max(str(previous.manifest.window.start), str(current.manifest.window.start))
    if start > cursor:
        raise RollingContinuityRefused("OVERLAP_UNAVAILABLE")
    factors = {}
    evidence = hashlib.sha256()
    with closing(previous.bars(start=start, end=cursor)) as old, closing(
            current.bars(start=start, end=cursor)) as new:
        for left, right in zip_longest(old, new):
            if (left is None or right is None
                    or (left.session, left.security_id) != (right.session, right.security_id)):
                raise RollingContinuityRefused("OVERLAP_IDENTITY_KEYS_CHANGED")
            a, b = asdict(left), asdict(right)
            new_signal, old_signal = b.pop("signal_close"), a.pop("signal_close")
            if a != b:
                raise RollingContinuityRefused("OVERLAP_RAW_ECONOMICS_CHANGED: " + left.security_id)
            _intersect_scale(factors, left.security_id, new_signal, old_signal,
                             "NONUNIFORM_SIGNAL_REBASE: ")
            if refs.resolver.resolve(right.ticker, right.session) != right.security_id:
                raise RollingContinuityRefused("OVERLAP_REFERENCE_IDENTITY_CHANGED")
            evidence.update(canonical_json([asdict(left), asdict(right)]).encode())
            evidence.update(b"\n")
    scales = {}
    old_benchmarks = (row for row in rolling_store.read_benchmarks(conn, previous.candidate_id)
                      if start <= str(row.session) <= cursor)
    new_benchmarks = (row for row in rolling_store.read_benchmarks(conn, current.candidate_id)
                      if start <= str(row.session) <= cursor)
    with closing(old_benchmarks), closing(new_benchmarks):
        for left, right in zip_longest(old_benchmarks, new_benchmarks):
            if left is None or right is None or left.session != right.session:
                raise RollingContinuityRefused("OVERLAP_BENCHMARK_KEYS_CHANGED")
            a, b = left.model_dump(mode="json"), right.model_dump(mode="json")
            for field in ("spy_total_return", "bil_close_adjusted"):
                new_value, old_value = b.pop(field), a.pop(field)
                if new_value is None or old_value is None:
                    raise RollingContinuityRefused("OVERLAP_BENCHMARK_PRICE_UNAVAILABLE")
                _intersect_scale(scales, field, new_value, old_value,
                                 "NONUNIFORM_BENCHMARK_REBASE: ")
            if a != b:
                raise RollingContinuityRefused("OVERLAP_BIL_RAW_ECONOMICS_CHANGED")
            evidence.update(canonical_json([left.model_dump(mode="json"), right.model_dump(mode="json")]).encode())
    return start, evidence.hexdigest()


@dataclass(frozen=True)
class DailyInputs:
    session: str
    bars: tuple
    meta: dict
    sectors: dict
    benchmarks: tuple
    terminal_events: tuple
    spinoff_distributions: tuple
    feed_anchors: dict = dataclass_field(default_factory=dict)


def prepare(conn, *, prior, previous_binding, publication, binding):
    """Return exact next-session inputs and a state-bound continuity proof."""
    cursor = prior.last_processed_session
    session = publication.window_end
    if not cursor or session != calendar.next_session(cursor):
        raise RollingContinuityRefused("ADJACENT_SOURCE_FINAL_SESSION_REQUIRED")
    old = RollingPriceReader(conn, candidate_id=previous_binding["candidate_id"],
                             snapshot_id=previous_binding["snapshot_id"])
    current = RollingPriceReader(conn, candidate_id=binding["candidate_id"], snapshot_id=binding["snapshot_id"])
    current.require_checkpoint_window(prior)
    for reader in (old, current):
        rolling_store.verify_content(conn, reader.candidate_id)
    previous_refs = SnapshotReferences(conn, candidate_id=old.candidate_id, snapshot_id=old.manifest.snapshot_id)
    refs = SnapshotReferences(conn, candidate_id=current.candidate_id, snapshot_id=current.manifest.snapshot_id)
    meta, sectors, reference_sha = _same_reference(previous_refs, refs, cursor)
    start, overlap_sha = _overlap(conn, old, current, refs, cursor)
    series = prior.feed.get("series", {})
    protected = _path_dependent_security_ids(prior.wealth_core, prior.pending)
    protected.update(prior.median5.get("selected", ()))
    if missing := protected.difference(series):
        raise RollingContinuityRefused("RETURNING_SECURITY_ANCHOR_REQUIRED: " + ",".join(sorted(missing)))
    anchors = {}
    for sid, value in series.items():
        anchor = value.get("signal_basis_anchor")
        if not anchor:
            raise RollingContinuityRefused("LIVE_SIGNAL_ANCHOR_REQUIRED: " + sid)
        anchors[sid] = anchor[0]
    prices = current.prices(session=session, spy_sessions=254, anchor_sessions=anchors)
    for bar in prices.bars:
        if (bar.security_id not in meta
                or refs.resolver.resolve(bar.ticker, session) != bar.security_id):
            raise RollingContinuityRefused("CURRENT_REFERENCE_IDENTITY_CHANGED")
    terminals = refs.terminals(start=session, end=session)
    material = DailyInputs(session, prices.bars, meta, sectors, prices.benchmarks,
                           tuple(terminals.events), refs.distributions(session=session),
                           fresh_anchors(prices.bars, meta, series))
    proof = RollingContinuityProof(
        prior_version=prior.data_version, publication_version=publication.version,
        prior_session=cursor, session=session, prior_state_sha256=prior.state_hash,
        previous_snapshot_sha256=old.manifest.snapshot_id, snapshot_sha256=current.manifest.snapshot_id,
        overlap_start=start, overlap_sha256=overlap_sha, reference_sha256=reference_sha)
    return material, prices.signal_basis_anchors, proof.model_dump(by_alias=True)
