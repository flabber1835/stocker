"""Sharadar ingest facade with explicit daily and post-seed authority."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterable, Optional

from sentinel.feed import _ingest_authority_impl as _base

for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)

_legacy_daily = _base.daily


def _run_seed_generation_exposed(
        conn, *, recovery_plan, fetch, final_hi: str,
        resolve_identity, active: dict):
    """Retained seed sequencing while exposing the active update tracker."""
    seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
    tracked, guarded = _base._seed_source(fetch, final_hi=final_hi)
    active["tracked"] = tracked
    try:
        if recovery_plan.retired_run_ids:
            progress = _base.reseed.full_reseed_locked(
                conn, date_from=seed_from, date_to=seed_to,
                fetch=guarded, resolve_identity=resolve_identity)
        else:
            progress = _base._impl._seed_locked(
                conn, date_from=seed_from, date_to=seed_to,
                fetch=guarded, resolve_identity=resolve_identity)
        return progress, tracked
    except _base.universe.HistoricalIdentityMutation:
        plan = _base.identity_rebuild.prepare(
            conn, date_from=seed_from, date_to=seed_to)
        tracked, guarded = _base._seed_source(fetch, final_hi=final_hi)
        active["tracked"] = tracked
        progress = _base.reseed.full_reseed_locked(
            conn, date_from=seed_from, date_to=seed_to,
            fetch=guarded, resolve_identity=resolve_identity,
            identity_rebuild_plan=plan)
        return progress, tracked


@contextmanager
def _seed_authority_hooks(
        *, boundary: str, active: dict, fetch,
        market_start: str, market_end: str, resolve_identity):
    """Record the start boundary and finalize identity rebuilds before publish."""
    from sentinel.feed import identity_rebuild, seed_coherence, store, universe

    original_init = store.IngestRun.__init__
    original_record_plan = identity_rebuild.record_plan
    original_identity_publish = identity_rebuild.publish_completed_run

    def guarded_init(self, conn, kind: str, *, date_from=None, date_to=None,
                     chunks_total: int = 0):
        original_init(
            self, conn, kind, date_from=date_from, date_to=date_to,
            chunks_total=chunks_total)
        if kind == "seed":
            try:
                seed_coherence.record_start_boundary(
                    conn, run_id=self.progress.run_id, boundary=boundary)
            except BaseException as exc:                         # noqa: BLE001
                self.finish("failed", f"seed start-boundary binding failed: {exc}")
                raise

    def guarded_record_plan(conn, *, run_id: str, plan):
        result = original_record_plan(conn, run_id=run_id, plan=plan)
        # identity_rebuild.record_plan deliberately replaces its root JSON.
        # Restore the causal seed marker immediately after that durable write.
        seed_coherence.record_start_boundary(
            conn, run_id=run_id, boundary=boundary)
        return result

    def guarded_identity_publish(conn, *, run, rows, plan):
        tracked = active.get("tracked")
        if tracked is None:
            raise seed_coherence.SeedCoherenceRefused(
                "identity rebuild has no active seed update tracker")
        resolver = resolve_identity or universe.IdentityResolver(
            universe.listings_from_rows(rows)).resolve
        proof = seed_coherence.prove(
            conn, run=run, fetch=fetch,
            market_start=market_start, market_end=market_end,
            seed_start_update_boundary=boundary,
            observed_max_lastupdated=tracked.max_sep_lastupdated,
            resolver=resolver)
        active["proof"] = proof
        return original_identity_publish(
            conn, run=run, rows=rows, plan=plan)

    store.IngestRun.__init__ = guarded_init
    identity_rebuild.record_plan = guarded_record_plan
    identity_rebuild.publish_completed_run = guarded_identity_publish
    try:
        yield
    finally:
        identity_rebuild.publish_completed_run = original_identity_publish
        identity_rebuild.record_plan = original_record_plan
        store.IngestRun.__init__ = original_init


def seed(conn, *, date_from: str = _base._impl.DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = _base.sharadar.fetch_table,
         resolve_identity=None):
    """Complete seed plus bounded concurrent-mutation/source-local proof."""
    from sentinel.feed import seed_coherence, universe

    fetch = _base._authoritative_source(fetch)
    _base._validate_source_before_run(fetch)
    boundary = seed_coherence.capture_update_boundary()
    with _base._impl.feed_store.corpus_write_lock(conn):
        resolved_to = date_to or _base._today()
        recovery_plan = _base._recover_before_seed(
            conn, date_from=date_from, date_to=resolved_to)
        seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
        chunks = _base.sharadar.year_chunks(seed_from, seed_to)
        final_hi = chunks[-1][1]
        active: dict = {
            "market_start": seed_from,
            "market_end": seed_to,
        }
        with _seed_authority_hooks(
                boundary=boundary, active=active, fetch=fetch,
                market_start=seed_from, market_end=seed_to,
                resolve_identity=resolve_identity):
            progress, tracked = _run_seed_generation_exposed(
                conn, recovery_plan=recovery_plan, fetch=fetch,
                final_hi=final_hi, resolve_identity=resolve_identity,
                active=active)

        proof = seed_coherence.load(conn, run_id=progress.run_id)
        if proof is None:
            run = seed_coherence.reopen_successful_run(conn, progress)
            resolver = resolve_identity or universe.load_resolver(
                conn, include_run_id=progress.run_id).resolve
            try:
                proof = seed_coherence.prove(
                    conn, run=run, fetch=fetch,
                    market_start=seed_from, market_end=seed_to,
                    seed_start_update_boundary=boundary,
                    observed_max_lastupdated=tracked.max_sep_lastupdated,
                    resolver=resolver)
            except BaseException as exc:                         # noqa: BLE001
                run.finish("failed", f"post-seed coherence failed: {exc}")
                raise
            run.finish("success")

        published = _base._finish_publication_or_refuse(conn, progress)
        _base.maintenance.establish_sep_cursor_after_seed(
            conn, through=proof.final_cursor,
            publication_version=published.version)
        _base.maintenance.reconcile_actions_if_due(
            conn, fetch=_base._actions_reconciliation_source(fetch),
            through=seed_to, force=True)
        _base._prove_recent_frontier(conn, fetch=fetch)
        return progress


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = _base.sharadar.fetch_table,
          resolve_identity=None,
          overlap_days: int = _base._impl.DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Production daily ingestion always receives an explicit session boundary."""
    if today is None:
        raise ValueError(
            "daily ingest requires an explicit through-session; wall-clock date "
            "fallback is not publication authority")
    return _legacy_daily(
        conn, fetch=fetch, resolve_identity=resolve_identity,
        overlap_days=overlap_days, today=str(today))


# Retained helper call sites resolve these names in their defining module.
_base.seed = seed
_base.daily = daily
