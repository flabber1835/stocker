"""Complete source-stable reseed used only for ambiguous legacy recovery.

Ordinary seed and daily ingestion remain in :mod:`sentinel.feed.ingest_impl`.
This module exists for one state that old deployments could accumulate before
#108 recovery was implemented: several overlapping unpublished in-place
candidates. There is no honest local ordering for those bytes, so recovery must
replace them from complete provider evidence rather than choose a winner.

The important detail is *when* old rows are retired. Hidden failed bars are kept
until the corresponding SEP year has been double-observed, normalized, and
written by the replacement seed. Then residual old-owner rows in that completed
window are authoritative absences and may be removed. This also prevents hidden
failed rows from becoming predecessor evidence for the next seed year.

ACTIONS has its own complete source contract from 1900 through the reseed end.
That range is deliberately independent of the SEP/SFP market-data range: a very
old corporate action must be reconciled without forcing Wealth Core price-history
validation into decades the retained market corpus does not model. A stable
empty/materially collapsed ACTIONS response is still refused: two observations
prove repeatability, not that a mass removal is economically credible.

If the process dies after any retirement, the replacement seed already owns
candidate rows and coherence stays blocked. A restart therefore cannot mistake a
partially reconstructed old publication for READY.
"""
from __future__ import annotations

from typing import Callable, Iterable

from sentinel.feed import (
    action_source, domains, identity_rebuild, identity_rebuild_writer,
    maintenance, recovery, sharadar, universe)
from sentinel.feed import store as feed_store


def _fail_finalization_if_running(conn, run, exc: BaseException) -> None:
    """Make a post-chunk failure durable without masking an already-failed run."""
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM feed_ingest_runs WHERE run_id=%s",
            (str(run.progress.run_id),))
        row = cur.fetchone()
    if row is not None and str(row[0]) == "running":
        run.finish("failed", f"identity rebuild finalization failed: {exc}")


def full_reseed_locked(
        conn, *, date_from: str, date_to: str,
        fetch: Callable[..., Iterable[dict]], resolve_identity=None,
        identity_rebuild_plan: identity_rebuild.IdentityRebuildPlan | None = None,
        on_run_started=None, before_success=None, record_identity_plan=None,
        publish_identity=None,
        ) -> feed_store.IngestProgress:
    """Refetch and replace a legacy ambiguous unpublished candidate set.

    Caller must hold ``corpus_write_lock`` and must already have called
    :func:`recovery.prepare_full_reseed`, which classifies the old candidates
    FAILED/ABORTED and widens the MARKET-DATA range to cover every destructive
    SEP/SFP candidate row. ``fetch`` is the same seed-mode stable source facade
    used by ordinary seed. ACTIONS independently uses the complete
    ``1900-01-01..date_to`` contract.

    ``identity_rebuild_plan`` is the stronger #246 boundary. It deliberately
    does not publish TICKERS metadata first. The complete candidate snapshot is
    kept in memory, SEP is resolved exclusively against it, and TICKERS rows,
    obsolete-key retirement, projection replacement and corpus publication land
    in one final transaction.

    Lifecycle callbacks are explicit call-bound dependencies used by the
    canonical ingest membrane. ``on_run_started`` executes immediately after the
    durable RUNNING row exists. ``before_success`` executes after every source
    chunk is complete and before SUCCESS/publication. Identity rebuild uses the
    same callback before its atomic finalizer. No process-global method or module
    replacement is required.
    """
    from sentinel.feed import ingest_impl

    feed_store._assert_corpus_locked(conn)
    chunks = sharadar.year_chunks(date_from, date_to)
    run = feed_store.IngestRun(
        conn, "seed", date_from=date_from, date_to=date_to,
        chunks_total=len(chunks) + 3)
    if on_run_started is not None:
        on_run_started(run)
    if identity_rebuild_plan is not None:
        recorder = record_identity_plan or identity_rebuild.record_plan
        recorder(conn, run_id=run.progress.run_id, plan=identity_rebuild_plan)

    candidate_tickers = None
    claim_security_ids = None
    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        if identity_rebuild_plan is None:
            run.progress.rows_written += universe.write_universe(
                conn, rows, date_to, run_id=run.progress.run_id)
        else:
            candidate_tickers = identity_rebuild.verify_candidate(
                conn, run_id=run.progress.run_id,
                plan=identity_rebuild_plan, rows=rows)
            claim_security_ids = identity_rebuild.affected_security_ids(
                conn, run_id=run.progress.run_id)

    action_start = maintenance.ACTIONS_FULL_WINDOW_START
    with run.chunk("actions"):
        action_source_rows = list(fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, date_to)))
        if not action_source_rows:
            raise maintenance.SharadarMutationRefused(
                "complete Sharadar ACTIONS full-reseed returned zero rows; "
                "refusing to turn a suspicious empty source into mass removals")
        prior_active = maintenance._active_action_rows(conn)
        distinct_actions = action_source.distinct_rows(action_source_rows)
        if (prior_active
                and len(distinct_actions) < int(len(prior_active) * 0.90)):
            raise maintenance.SharadarMutationRefused(
                f"complete ACTIONS full-reseed shrank from "
                f"{len(prior_active):,} active rows to "
                f"{len(distinct_actions):,}; refusing mass-removal authority "
                "without inspection")
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=date_to)

    with run.chunk("spy"):
        params = {"ticker": ingest_impl.SFP_REFERENCE_TICKERS,
                  **sharadar.date_params(date_from, date_to)}
        rows = fetch(sharadar.SFP, params)
        run.progress.rows_written += ingest_impl._write_sfp_reference_rows(
            conn, rows, run_id=run.progress.run_id)

    if identity_rebuild_plan is None:
        resolver = resolve_identity or universe.load_resolver(
            conn, include_run_id=run.progress.run_id).resolve
    else:
        if candidate_tickers is None or claim_security_ids is None:
            raise recovery.PublicationRecoveryRefused(
                "identity rebuild lost its candidate TICKERS evidence")
        resolver = universe.IdentityResolver(
            universe.listings_from_rows(candidate_tickers)).resolve

    for index, (lo, hi) in enumerate(chunks):
        final_chunk = index == len(chunks) - 1
        with run.chunk(lo[:4]):
            report = domains.NormalisationReport()
            splits, divs, action_rows, ambiguous_splits = ingest_impl._action_maps(
                conn, lo, hi, include_run_id=run.progress.run_id)
            bars = domains.normalise_sep_rows(
                ingest_impl._ordered_sep(
                    conn, fetch(sharadar.SEP, sharadar.date_params(lo, hi)),
                    run_id=run.progress.run_id, chunk=lo[:4]),
                resolve_identity=resolver,
                authoritative_splits=splits,
                dividends=divs,
                prior_observations=feed_store.previous_observations(conn, lo),
                report=report)
            if identity_rebuild_plan is None:
                written = feed_store.write_bars(
                    conn, bars, run_id=run.progress.run_id, require_lock=True)
            else:
                written = identity_rebuild_writer.write_bars_claiming(
                    conn, bars, run_id=run.progress.run_id,
                    claim_security_ids=claim_security_ids)
            ingest_impl._persist_chunk_evidence(
                conn, run, lo[:4], lo, hi, report, splits,
                action_rows, action_rows, ambiguous_splits)
            run.progress.rows_written += written
            run.progress.rows_dropped += (
                report.dropped_no_raw_close + report.dropped_no_identity)

            recovery.retire_failed_bars_in_stable_seed_window(
                conn, run_id=run.progress.run_id, start=lo, end=hi)

            if final_chunk:
                recovery.assert_full_reseed_covered_live_rows(
                    conn, run_id=run.progress.run_id,
                    market_start=date_from, actions_start=action_start,
                    end=date_to)
                recovery.retire_failed_nonbar_rows_after_full_seed(
                    conn, run_id=run.progress.run_id,
                    market_start=date_from, actions_start=action_start,
                    end=date_to)

    try:
        if before_success is not None:
            before_success(run, resolver)
        if identity_rebuild_plan is None:
            run.finish("success")
            ingest_impl._publish_version(conn, run, date_from, date_to)
        else:
            publisher = publish_identity or identity_rebuild.publish_completed_run
            publisher(
                conn, run=run, rows=candidate_tickers,
                plan=identity_rebuild_plan)
    except BaseException as exc:                              # noqa: BLE001
        _fail_finalization_if_running(conn, run, exc)
        raise
    return run.progress


__all__ = ["full_reseed_locked"]
