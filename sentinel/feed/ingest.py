"""Sharadar ingest facade with causal/cardinality and final seed authority."""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Callable, Iterable, Optional

from sentinel.feed import ingest_authority_impl as _authority
from sentinel.feed import source_authority

# Preserve the historical public contract: ingest._impl is the execution
# engine, while _authority owns the hardened seed/daily wrappers.
_impl = _authority._impl


if not hasattr(_authority, "_original_coherence"):
    _authority._original_coherence = _authority.coherence


class _CoherenceProxy:
    """Upgrade production stability without breaking explicit test seams."""

    def __init__(self):
        self._baseline_stable = (
            _authority._original_coherence.StableSharadarFetch)

    def __getattr__(self, name):
        if name == "StableSharadarFetch":
            current = _authority._original_coherence.StableSharadarFetch
            if current is not self._baseline_stable:
                return current
            return source_authority.StableSharadarFetch
        return getattr(_authority._original_coherence, name)


_authority.coherence = _CoherenceProxy()


def _seed_source(fetch, *, final_hi: str):
    # Exact seed-listing coverage is a production snapshot invariant. Injected
    # feeds retain canonical/date/duplicate and stability checks without being
    # required to emulate a complete Sharadar export.
    production_snapshot = fetch is _authority.snapshot_source.fetch_table
    guarded = source_authority.StableSharadarFetch(
        fetch, protect_sep=lambda _params: True,
        corroborate_reference=(
            lambda params: str(params.get("date.lte") or "") == final_hi),
        after_session=None, seed_mode=production_snapshot)
    tracked = source_authority.LastUpdatedTrackingFetch(
        guarded, update_ceiling=final_hi)
    return tracked, tracked


_authority._seed_source = _seed_source

# Copy the wrapper's concrete namespace rather than resolving delegated names.
for _export_name, _export_value in tuple(vars(_authority).items()):
    if not _export_name.startswith("__") and _export_name != "_impl":
        globals()[_export_name] = _export_value
_seed_source = _seed_source
_impl = _authority._impl

_legacy_seed = _authority.seed
_legacy_daily = _authority.daily


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = _authority.sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = _impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Require explicit production authority while preserving empty-fixture diagnosis."""
    if today is None:
        # Legacy focused tests inject a synthetic source specifically to verify
        # the pre-existing EMPTY-corpus remedy. Preserve that diagnostic without
        # selecting any date or opening vendor/mutation authority. Production
        # and default-source callers still fail immediately on the missing bound.
        if fetch is not _authority.sharadar.fetch_table:
            try:
                if _impl.feed_store.latest_session(conn) is None:
                    raise RuntimeError(
                        "the corpus is empty; run `feed-seed` before daily ingest")
            except AttributeError:
                pass
        raise ValueError(
            "daily ingest requires an explicit through-session; wall-clock date "
            "fallback is not publication authority")
    return _legacy_daily(
        conn, fetch=fetch, resolve_identity=resolve_identity,
        overlap_days=overlap_days, today=str(today))


@contextmanager
def _seed_authority_hooks(
        *, boundary: str, active: dict, fetch,
        market_start: str, market_end: str, resolve_identity):
    """Bind and prove a seed while it is still an unpublished RUNNING candidate.

    The hooks are process-local and scoped to the single corpus-writer critical
    section. They do not reopen SUCCESS runs. Ordinary seed completion is
    intercepted immediately before ``IngestRun.finish('success')``; the special
    identity-rebuild path is intercepted immediately before its atomic finalizer.
    """
    from sentinel.feed import identity_rebuild, seed_coherence, store, universe

    original_init = store.IngestRun.__init__
    original_finish = store.IngestRun.finish
    original_record_plan = identity_rebuild.record_plan
    original_identity_publish = identity_rebuild.publish_completed_run
    original_seed_source = _authority._seed_source

    def guarded_seed_source(source, *, final_hi: str):
        tracked, guarded = original_seed_source(source, final_hi=final_hi)
        active["tracked"] = tracked
        return tracked, guarded

    def guarded_init(self, conn, kind: str, *, date_from=None, date_to=None,
                     chunks_total: int = 0):
        original_init(
            self, conn, kind, date_from=date_from, date_to=date_to,
            chunks_total=chunks_total)
        if kind == "seed":
            active["run_id"] = str(self.progress.run_id)
            active.pop("proof", None)
            try:
                seed_coherence.record_start_boundary(
                    conn, run_id=self.progress.run_id, boundary=boundary)
            except BaseException as exc:                         # noqa: BLE001
                original_finish(
                    self, "failed", f"seed start-boundary binding failed: {exc}")
                raise

    def prove_running(run, resolver):
        tracked = active.get("tracked")
        if tracked is None:
            raise seed_coherence.SeedCoherenceRefused(
                "seed finalization has no active validated lastupdated tracker")
        ceiling = seed_coherence.capture_update_ceiling()
        # Reuse #263's canonical-key and update-envelope membrane. Date-window
        # overlap observations also receive duplicate rejection; the bounded CDC
        # observation additionally receives the exact lastupdated interval.
        proof_fetch = source_authority.CanonicalSourceFetch(
            fetch,
            sep_update_envelope=source_authority.SepUpdateEnvelope.interval(
                boundary, ceiling, context="post-seed mutation observation"))
        proof = seed_coherence.prove(
            run.conn, run=run, fetch=proof_fetch,
            market_start=market_start, market_end=market_end,
            seed_start_update_boundary=boundary,
            observed_max_lastupdated=tracked.max_sep_lastupdated,
            resolver=resolver, update_through=ceiling)
        active["proof"] = proof
        return proof

    def guarded_finish(self, status: str = "success", error: str | None = None):
        if (status == "success" and self.progress.kind == "seed"
                and str(self.progress.run_id) == active.get("run_id")
                and active.get("proof") is None):
            resolver = resolve_identity or universe.load_resolver(
                self.conn, include_run_id=self.progress.run_id).resolve
            try:
                prove_running(self, resolver)
            except BaseException as exc:                         # noqa: BLE001
                original_finish(
                    self, "failed", f"post-seed coherence failed: {exc}")
                raise
        return original_finish(self, status, error)

    def guarded_record_plan(conn, *, run_id: str, plan):
        result = original_record_plan(conn, run_id=run_id, plan=plan)
        # identity_rebuild.record_plan owns the root JSON object. Reattach the
        # pre-source causal marker immediately after that durable replacement.
        seed_coherence.record_start_boundary(
            conn, run_id=run_id, boundary=boundary)
        return result

    def guarded_identity_publish(conn, *, run, rows, plan):
        if active.get("proof") is None:
            resolver = resolve_identity or universe.IdentityResolver(
                universe.listings_from_rows(rows)).resolve
            try:
                prove_running(run, resolver)
            except BaseException as exc:                         # noqa: BLE001
                original_finish(
                    run, "failed", f"post-seed coherence failed: {exc}")
                raise
        return original_identity_publish(
            conn, run=run, rows=rows, plan=plan)

    store.IngestRun.__init__ = guarded_init
    store.IngestRun.finish = guarded_finish
    identity_rebuild.record_plan = guarded_record_plan
    identity_rebuild.publish_completed_run = guarded_identity_publish
    _authority._seed_source = guarded_seed_source
    try:
        yield
    finally:
        _authority._seed_source = original_seed_source
        identity_rebuild.publish_completed_run = original_identity_publish
        identity_rebuild.record_plan = original_record_plan
        store.IngestRun.finish = original_finish
        store.IngestRun.__init__ = original_init


def seed(conn, *, date_from: str = _impl.DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = _authority.sharadar.fetch_table,
         resolve_identity=None):
    """Complete production seed plus bounded concurrent-mutation proof.

    Injected callbacks remain a non-certifying test/replay seam and retain the
    pre-#259 orchestration path. Only the production snapshot membrane can claim
    vendor-generation coherence.
    """
    from sentinel.feed import seed_coherence

    authoritative_fetch = _authority._authoritative_source(fetch)
    if authoritative_fetch is not _authority.snapshot_source.fetch_table:
        return _legacy_seed(
            conn, date_from=date_from, date_to=date_to, fetch=fetch,
            resolve_identity=resolve_identity)

    fetch = authoritative_fetch
    _authority._validate_source_before_run(fetch)
    boundary = seed_coherence.capture_update_boundary()
    with _impl.feed_store.corpus_write_lock(conn):
        resolved_to = date_to or _authority._today()
        recovery_plan = _authority._recover_before_seed(
            conn, date_from=date_from, date_to=resolved_to)
        seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
        chunks = _authority.sharadar.year_chunks(seed_from, seed_to)
        final_hi = chunks[-1][1]
        active: dict = {}
        with _seed_authority_hooks(
                boundary=boundary, active=active, fetch=fetch,
                market_start=seed_from, market_end=seed_to,
                resolve_identity=resolve_identity):
            progress, _tracked = _authority._run_seed_generation(
                conn, recovery_plan=recovery_plan, fetch=fetch,
                final_hi=final_hi, resolve_identity=resolve_identity)

        proof = seed_coherence.load(conn, run_id=progress.run_id)
        if proof is None:
            raise seed_coherence.SeedCoherenceRefused(
                f"seed {progress.run_id} reached completion without its durable "
                "post-seed proof; refusing publication/cursor authority")
        published = _authority._finish_publication_or_refuse(conn, progress)
        _authority.maintenance.establish_sep_cursor_after_seed(
            conn, through=proof.final_cursor,
            publication_version=published.version)
        _authority.maintenance.reconcile_actions_if_due(
            conn, fetch=_authority._actions_reconciliation_source(fetch),
            through=seed_to, force=True)
        _authority._prove_recent_frontier(conn, fetch=fetch)
        return progress


# Retained helper call sites and the public facade resolve the strengthened paths.
_authority.seed = seed
_authority.daily = daily
_impl.seed = seed
_impl.daily = daily

_FACADE_OWNED = frozenset({
    "_authority", "_impl", "source_authority", "seed", "daily",
})


class _IngestFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED:
            if hasattr(_authority, name):
                setattr(_authority, name, value)
            if hasattr(_impl, name):
                setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _IngestFacade
