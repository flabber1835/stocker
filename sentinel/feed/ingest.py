"""Canonical Sharadar seed/daily ingestion and PIT/source authority.

The public module owns seed/daily orchestration. Lower-level normalization,
storage and recovery helpers are static dependencies; import order and
monkeypatch location are not part of the production control path.
"""
from __future__ import annotations

import datetime as _dt
from typing import Callable, Iterable, Optional

from sentinel.feed import ingest_authority_impl as _authority
from sentinel.feed import ingest_impl as _impl
from sentinel.feed import source_authority
from sentinel.feed import store as feed_store

coherence = _authority.coherence
identity_rebuild = _authority.identity_rebuild
identity_refresh = _authority.identity_refresh
maintenance = _authority.maintenance
recent_reconciliation = _authority.recent_reconciliation
recovery = _authority.recovery
reseed = _authority.reseed
sep_reconciliation = _authority.sep_reconciliation
sharadar = _authority.sharadar
snapshot_source = _authority.snapshot_source
universe = _authority.universe

domains = _impl.domains
DAILY_OVERLAP_DAYS = _impl.DAILY_OVERLAP_DAYS
DEFAULT_SEED_START = _impl.DEFAULT_SEED_START
SFP_REFERENCE_TICKERS = _impl.SFP_REFERENCE_TICKERS

# Explicit static helper bindings retained for direct behavioral tests and
# adjacent callers.  They do not install module proxies or mutate _impl.
_action_maps = _impl._action_maps
_ordered_sep = _impl._ordered_sep
_resolution_tombstones = _impl._resolution_tombstones

_authoritative_source = _authority._authoritative_source
_actions_reconciliation_source = _authority._actions_reconciliation_source
_recent_reconciliation_source = _authority._recent_reconciliation_source
_validate_source_before_run = _authority._validate_source_before_run
_recover_before_run = _authority._recover_before_run
_recover_before_seed = _authority._recover_before_seed
_finish_publication_or_refuse = _authority._finish_publication_or_refuse
_single_failed_live_candidate = _authority._single_failed_live_candidate
_failed_run_end = _authority._failed_run_end
_require_failed_owner_cleared = _authority._require_failed_owner_cleared
_prove_recent_frontier = _authority._prove_recent_frontier
_today = _impl._today


def _seed_source(fetch, *, final_hi: str, update_ceiling: str | None = None):
    """Return one stable canonical seed observation.

    ``final_hi`` is the market-session boundary used for source corroboration.
    Production supplies an independent vendor ``update_ceiling`` captured before
    the first seed request. Injected/replay seeds omit it and deterministically
    retain their market-end ceiling.

    Exact listing coverage is enabled only for the production snapshot source.
    Injected/replay sources still receive canonical key/date/duplicate and
    stability checks.
    """
    production_snapshot = fetch is snapshot_source.fetch_table
    guarded = source_authority.StableSharadarFetch(
        fetch, protect_sep=lambda _params: True,
        corroborate_reference=(
            lambda params: str(params.get("date.lte") or "") == final_hi),
        after_session=None, seed_mode=production_snapshot)
    ceiling = final_hi if update_ceiling is None else update_ceiling
    tracked = source_authority.LastUpdatedTrackingFetch(
        guarded, update_ceiling=ceiling)
    return tracked, tracked


def _reconcile_sep_for_market_target(
        conn, *, fetch, target: str,
        source_observation_day: _dt.date | str | None = None):
    """Reconcile SEP on its vendor clock while preserving replay determinism.

    Injected/replay callers omit ``source_observation_day`` and keep the explicit
    market target as their only clock. Production supplies the current UTC source
    observation date. Production also re-observes an equal cursor date because
    Sharadar ``lastupdated`` is date-valued and later rows may still appear with
    that same date.
    """
    market_day = _dt.date.fromisoformat(str(target))
    if source_observation_day is None:
        return maintenance.reconcile_sep_mutations(
            conn, fetch=fetch, through=market_day.isoformat())

    source_day = (
        source_observation_day
        if isinstance(source_observation_day, _dt.date)
        else _dt.date.fromisoformat(str(source_observation_day)))
    if source_day < market_day:
        raise maintenance.SharadarMutationRefused(
            f"current source observation date {source_day} is behind market "
            f"target {market_day}; refusing mixed-clock SEP authority")
    return maintenance.reconcile_sep_mutations(
        conn, fetch=fetch, through=source_day.isoformat(),
        reobserve_equal=True)


class _InjectedSeedAuthority:
    """Non-certifying lifecycle hooks for deterministic injected/replay seeds."""

    def run_started(self, run) -> None:
        return None

    def before_success(self, run, resolver) -> None:
        return None

    def record_identity_plan(self, conn, *, run_id: str, plan) -> None:
        identity_rebuild.record_plan(conn, run_id=run_id, plan=plan)


class _SeedAuthority:
    """Production seed proof state with explicit lifecycle transitions."""

    def __init__(self, *, boundary: str, tracked, source_fetch,
                 market_start: str, market_end: str, resolve_identity):
        self.boundary = boundary
        self.tracked = tracked
        self.source_fetch = source_fetch
        self.market_start = market_start
        self.market_end = market_end
        self.resolve_identity = resolve_identity
        self.run_id: str | None = None
        self.proof = None

    def run_started(self, run) -> None:
        from sentinel.feed import seed_coherence

        self.run_id = str(run.progress.run_id)
        self.proof = None
        try:
            seed_coherence.record_start_boundary(
                run.conn, run_id=run.progress.run_id,
                boundary=self.boundary)
        except BaseException as exc:                         # noqa: BLE001
            run.finish("failed", f"seed start-boundary binding failed: {exc}")
            raise

    def record_identity_plan(self, conn, *, run_id: str, plan) -> None:
        from sentinel.feed import seed_coherence

        identity_rebuild.record_plan(conn, run_id=run_id, plan=plan)
        seed_coherence.record_start_boundary(
            conn, run_id=run_id, boundary=self.boundary)

    def before_success(self, run, resolver) -> None:
        from sentinel.feed import seed_coherence

        if self.proof is not None:
            return
        coverage_evidence = self.tracked.seed_coverage_evidence
        if coverage_evidence is None:
            exc = seed_coherence.SeedCoherenceRefused(
                "seed finalization has no successful exact source-coverage evidence")
            run.finish("failed", f"post-seed coherence failed: {exc}")
            raise exc
        try:
            seed_coherence.record_seed_coverage(
                run.conn, run_id=str(run.progress.run_id),
                evidence=coverage_evidence)
            ceiling = seed_coherence.capture_update_ceiling()
            proof_fetch = source_authority.CanonicalSourceFetch(
                self.source_fetch,
                sep_update_envelope=source_authority.SepUpdateEnvelope.interval(
                    self.boundary, ceiling,
                    context="post-seed mutation observation"))
            self.proof = seed_coherence.prove(
                run.conn, run=run, fetch=proof_fetch,
                market_start=self.market_start, market_end=self.market_end,
                seed_start_update_boundary=self.boundary,
                observed_max_lastupdated=self.tracked.max_sep_lastupdated,
                resolver=resolver, update_through=ceiling)
        except BaseException as exc:                         # noqa: BLE001
            run.finish("failed", f"post-seed coherence failed: {exc}")
            raise


def _ordinary_seed_generation(conn, *, date_from: str, date_to: str,
                              fetch, resolve_identity, seed_authority):
    """Canonical ordinary seed engine used by every source seam."""
    chunks = sharadar.year_chunks(date_from, date_to)
    run = feed_store.IngestRun(
        conn, "seed", date_from=date_from, date_to=date_to,
        chunks_total=len(chunks) + 3)
    seed_authority.run_started(run)

    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(
            conn, rows, date_to, run_id=run.progress.run_id)

    with run.chunk("actions"):
        from sentinel.feed import calendar
        action_start, _ = calendar.action_date_window(date_from, date_to)
        action_source_rows = list(fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, date_to)))
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=date_to)

    with run.chunk("spy"):
        params = {"ticker": SFP_REFERENCE_TICKERS,
                  **sharadar.date_params(date_from, date_to)}
        rows = fetch(sharadar.SFP, params)
        run.progress.rows_written += _impl._write_sfp_reference_rows(
            conn, rows, run_id=run.progress.run_id)

    resolver = resolve_identity or universe.load_resolver(
        conn, include_run_id=run.progress.run_id).resolve

    for lo, hi in chunks:
        with run.chunk(lo[:4]):
            report = domains.NormalisationReport()
            splits, divs, action_rows, ambiguous_splits = _impl._action_maps(
                conn, lo, hi, include_run_id=run.progress.run_id)
            bars = domains.normalise_sep_rows(
                _impl._ordered_sep(
                    conn, fetch(sharadar.SEP, sharadar.date_params(lo, hi)),
                    run_id=run.progress.run_id, chunk=lo[:4]),
                resolve_identity=resolver,
                authoritative_splits=splits, dividends=divs,
                prior_observations=feed_store.previous_observations(conn, lo),
                report=report)
            written = feed_store.write_bars(
                conn, bars, run_id=run.progress.run_id, require_lock=True)
            _impl._persist_chunk_evidence(
                conn, run, lo[:4], lo, hi, report, splits,
                action_rows, action_rows, ambiguous_splits)
            run.progress.rows_written += written
            run.progress.rows_dropped += (
                report.dropped_no_raw_close + report.dropped_no_identity)

    seed_authority.before_success(run, resolver)
    run.finish("success")
    _impl._publish_version(conn, run, date_from, date_to)
    return run.progress


def _seed_authority(*, boundary, tracked, source_fetch, market_start,
                    market_end, resolve_identity):
    if boundary is None:
        return _InjectedSeedAuthority()
    return _SeedAuthority(
        boundary=boundary, tracked=tracked, source_fetch=source_fetch,
        market_start=market_start, market_end=market_end,
        resolve_identity=resolve_identity)


def _run_seed_generation(conn, *, recovery_plan, fetch, final_hi: str,
                         boundary: str | None = None, resolve_identity=None):
    """Run one seed/reseed engine with source-specific proof hooks."""
    seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
    if boundary is None:
        tracked, guarded = _seed_source(fetch, final_hi=final_hi)
    else:
        tracked, guarded = _seed_source(
            fetch, final_hi=final_hi, update_ceiling=boundary)
    authority = _seed_authority(
        boundary=boundary, tracked=tracked, source_fetch=fetch,
        market_start=seed_from, market_end=seed_to,
        resolve_identity=resolve_identity)
    try:
        if recovery_plan.retired_run_ids:
            progress = reseed.full_reseed_locked(
                conn, date_from=seed_from, date_to=seed_to,
                fetch=guarded, resolve_identity=resolve_identity,
                on_run_started=authority.run_started,
                before_success=authority.before_success)
        else:
            progress = _ordinary_seed_generation(
                conn, date_from=seed_from, date_to=seed_to,
                fetch=guarded, resolve_identity=resolve_identity,
                seed_authority=authority)
        return progress, tracked
    except universe.HistoricalIdentityMutation:
        plan = identity_rebuild.prepare(
            conn, date_from=seed_from, date_to=seed_to)
        if boundary is None:
            tracked, guarded = _seed_source(fetch, final_hi=final_hi)
        else:
            tracked, guarded = _seed_source(
                fetch, final_hi=final_hi, update_ceiling=boundary)
        authority = _seed_authority(
            boundary=boundary, tracked=tracked, source_fetch=fetch,
            market_start=seed_from, market_end=seed_to,
            resolve_identity=resolve_identity)
        progress = reseed.full_reseed_locked(
            conn, date_from=seed_from, date_to=seed_to,
            fetch=guarded, resolve_identity=resolve_identity,
            identity_rebuild_plan=plan,
            on_run_started=authority.run_started,
            before_success=authority.before_success,
            record_identity_plan=authority.record_identity_plan)
        return progress, tracked


def seed(conn, *, date_from: str = DEFAULT_SEED_START,
         date_to: Optional[str] = None,
         fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
         resolve_identity=None):
    """Run the canonical seed path; production adds durable source authority."""
    from sentinel.feed import seed_coherence

    fetch = _authoritative_source(fetch)
    _validate_source_before_run(fetch)
    production_snapshot = fetch is snapshot_source.fetch_table
    boundary = (
        seed_coherence.capture_update_boundary() if production_snapshot else None)

    with feed_store.corpus_write_lock(conn):
        resolved_to = date_to or _today()
        recovery_plan = _recover_before_seed(
            conn, date_from=date_from, date_to=resolved_to)
        seed_from, seed_to = recovery_plan.date_from, recovery_plan.date_to
        chunks = sharadar.year_chunks(seed_from, seed_to)
        final_hi = chunks[-1][1]
        progress, tracked = _run_seed_generation(
            conn, recovery_plan=recovery_plan, fetch=fetch,
            final_hi=final_hi, boundary=boundary,
            resolve_identity=resolve_identity)

        published = _finish_publication_or_refuse(conn, progress)
        if production_snapshot:
            proof = seed_coherence.load(conn, run_id=progress.run_id)
            if proof is None:
                raise seed_coherence.SeedCoherenceRefused(
                    f"seed {progress.run_id} reached completion without its durable "
                    "post-seed proof; refusing publication/cursor authority")
            cursor_through = proof.final_cursor
        else:
            if tracked.max_sep_lastupdated is None:
                raise maintenance.MutationCursorUnavailable(
                    "complete seed published but exposed no SEP lastupdated value; "
                    "refusing to invent a mutation watermark")
            cursor_through = tracked.max_sep_lastupdated

        maintenance.establish_sep_cursor_after_seed(
            conn, through=cursor_through,
            publication_version=published.version)
        maintenance.reconcile_actions_if_due(
            conn, fetch=_actions_reconciliation_source(fetch),
            through=seed_to, force=True)
        _prove_recent_frontier(conn, fetch=fetch)
        return progress


def daily(conn, *, fetch: Callable[..., Iterable[dict]] = sharadar.fetch_table,
          resolve_identity=None, overlap_days: int = DAILY_OVERLAP_DAYS,
          today: Optional[str] = None):
    """Run one explicit-session daily ingest and publication-bound maintenance."""
    if today is None:
        if fetch is not sharadar.fetch_table:
            try:
                if feed_store.latest_session(conn) is None:
                    raise RuntimeError(
                        "the corpus is empty; run `feed-seed` before daily ingest")
            except AttributeError:
                pass
        raise ValueError(
            "daily ingest requires an explicit through-session; wall-clock date "
            "fallback is not publication authority")

    fetch = _authoritative_source(fetch)
    _validate_source_before_run(fetch)
    production_snapshot = fetch is snapshot_source.fetch_table
    resolved_today = str(today)
    today_date = _dt.date.fromisoformat(resolved_today)
    yesterday = (today_date - _dt.timedelta(days=1)).isoformat()
    source_observation_day = (
        _dt.datetime.now(_dt.timezone.utc).date()
        if production_snapshot else None)

    with feed_store.corpus_write_lock(conn):
        _recover_before_run(conn)
        if maintenance.load_sep_cursor(conn) is None:
            raise maintenance.MutationCursorUnavailable(
                "SEP mutation watermark has not been established. Run the "
                "supported complete `feed-seed` (or a complete source-stable "
                "reconciliation) before daily operation; a 14-day session "
                "overlap cannot prove old rows current.")

        failed = _single_failed_live_candidate(conn)
        if failed is not None:
            if failed.kind == "daily":
                pass
            elif failed.kind == "sep_mutations":
                if production_snapshot:
                    maintenance.reconcile_sep_mutations(
                        conn, fetch=fetch,
                        through=source_observation_day.isoformat(),
                        reobserve_equal=True)
                else:
                    maintenance.reconcile_sep_mutations(
                        conn, fetch=fetch, through=yesterday)
                still_failed = _single_failed_live_candidate(conn)
                if still_failed is not None:
                    if (still_failed.run_id != failed.run_id
                            or still_failed.kind != "sep_mutations"):
                        raise recovery.PublicationRecoveryRefused(
                            "SEP mutation recovery exposed a different failed "
                            "candidate; refusing to guess retry order")
                    if production_snapshot:
                        maintenance.reconcile_sep_mutations(
                            conn, fetch=fetch,
                            through=source_observation_day.isoformat(),
                            reobserve_equal=True)
                    else:
                        maintenance.reconcile_sep_mutations(
                            conn, fetch=fetch, through=today_date.isoformat())
                _require_failed_owner_cleared(conn, context="SEP mutation retry")
            elif failed.kind == "actions_reconcile":
                retry_through = _failed_run_end(conn, failed.run_id)
                if retry_through is None:
                    raise recovery.PublicationRecoveryRefused(
                        f"failed ACTIONS reconciliation {failed.run_id} has no "
                        "durable date_to boundary; refusing an unbounded retry")
                maintenance.reconcile_actions_if_due(
                    conn, fetch=_actions_reconciliation_source(fetch),
                    through=retry_through, force=True)
                _require_failed_owner_cleared(
                    conn, context="ACTIONS reconciliation retry")
            else:
                raise recovery.PublicationRecoveryRefused(
                    f"failed live candidate {failed.run_id} has kind "
                    f"{failed.kind!r}; daily operation does not know which "
                    "complete source contract can safely supersede it. Run the "
                    "supported complete `feed-seed` recovery.")

        published_frontier = feed_store.latest_visible_session(conn)
        daily_fetch = fetch
        if fetch is snapshot_source.fetch_table and resolve_identity is None:
            tickers_candidate = identity_refresh.stable_current_tickers(fetch)
            identity_refresh.assert_candidate_history_safe(conn, tickers_candidate)
            candidate_resolver = identity_refresh.resolver_with_candidate(
                conn, tickers_candidate)
            identity_refresh.prevalidate_pending_sep_mutations(
                conn, fetch=fetch, through=yesterday,
                resolver=candidate_resolver)
            daily_fetch = identity_refresh.PinnedInitialTickersFetch(
                fetch, tickers_candidate)

        listing_frontier = (
            published_frontier if fetch is snapshot_source.fetch_table else None)
        guarded = source_authority.StableSharadarFetch(
            daily_fetch, after_session=listing_frontier)
        effective_overlap = recovery.extended_overlap_days(conn, overlap_days)
        progress = _impl._daily_locked(
            conn, fetch=guarded, resolve_identity=resolve_identity,
            overlap_days=effective_overlap, today=resolved_today)
        _finish_publication_or_refuse(conn, progress)

        if failed is not None and failed.kind == "daily":
            _require_failed_owner_cleared(conn, context="daily retry")

        published_frontier = feed_store.latest_visible_session(conn)
        sep_reconciliation.reconcile_next(
            conn, fetch=fetch, through=published_frontier)
        _reconcile_sep_for_market_target(
            conn, fetch=fetch, target=today_date.isoformat(),
            source_observation_day=source_observation_day)
        maintenance.reconcile_actions_if_due(
            conn, fetch=_actions_reconciliation_source(fetch),
            through=today_date.isoformat())
        _prove_recent_frontier(conn, fetch=fetch)
        return progress