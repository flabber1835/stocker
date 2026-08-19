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

If the process dies after any retirement, the replacement seed already owns
candidate rows and coherence stays blocked. A restart therefore cannot mistake a
partially reconstructed old publication for READY.
"""
from __future__ import annotations

from typing import Callable, Iterable

from sentinel.feed import domains, recovery, sharadar, universe
from sentinel.feed import store as feed_store


def full_reseed_locked(
        conn, *, date_from: str, date_to: str,
        fetch: Callable[..., Iterable[dict]], resolve_identity=None
        ) -> feed_store.IngestProgress:
    """Refetch and replace a legacy ambiguous unpublished candidate set.

    Caller must hold ``corpus_write_lock`` and must already have called
    :func:`recovery.prepare_full_reseed`, which classifies the old candidates
    FAILED/ABORTED and widens the range to cover every destructive candidate row.
    ``fetch`` is the same seed-mode stable source facade used by ordinary seed.
    """
    from sentinel.feed import calendar, ingest_impl

    feed_store._assert_corpus_locked(conn)
    chunks = sharadar.year_chunks(date_from, date_to)
    run = feed_store.IngestRun(
        conn, "seed", date_from=date_from, date_to=date_to,
        chunks_total=len(chunks) + 3)

    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(
            conn, rows, date_to, run_id=run.progress.run_id)

    with run.chunk("actions"):
        action_start, _ = calendar.action_date_window(date_from, date_to)
        action_source_rows = list(fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, date_to)))
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=date_to)

    with run.chunk("spy"):
        params = {"ticker": "SPY", **sharadar.date_params(date_from, date_to)}
        rows = fetch(sharadar.SFP, params)
        run.progress.rows_written += feed_store.write_spy_total_return(
            conn, rows, run_id=run.progress.run_id, require_lock=True)

    resolver = resolve_identity or universe.load_resolver(
        conn, include_run_id=run.progress.run_id).resolve

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
                # prepare_full_reseed widened `date_from` to the earliest old
                # destructive candidate. After every preceding year we delete
                # residual old-owner bars, so this physical predecessor lookup
                # cannot cross into hidden legacy candidate evidence.
                prior_observations=feed_store.previous_observations(conn, lo),
                report=report)
            written = feed_store.write_bars(
                conn, bars, run_id=run.progress.run_id, require_lock=True)
            ingest_impl._persist_chunk_evidence(
                conn, run, lo[:4], lo, hi, report, splits,
                action_rows, action_rows, ambiguous_splits)
            run.progress.rows_written += written
            run.progress.rows_dropped += (
                report.dropped_no_raw_close + report.dropped_no_identity)

            # A stable complete SEP window has now been replayed. Because the
            # bar upsert takes ownership from any unpublished predecessor even
            # when values are unchanged, a row still owned by an older FAILED
            # run is an observed absence/non-normalizable row in current source.
            recovery.retire_failed_bars_in_stable_seed_window(
                conn, run_id=run.progress.run_id, start=lo, end=hi)

            if final_chunk:
                # StableSharadarFetch brackets TICKERS/ACTIONS/SFP through this
                # final SEP traversal. Only now may complete-source recovery
                # retire residual destructive rows from those other families.
                recovery.assert_full_reseed_covered_live_rows(
                    conn, run_id=run.progress.run_id,
                    start=date_from, end=date_to)
                recovery.retire_failed_nonbar_rows_after_full_seed(
                    conn, run_id=run.progress.run_id,
                    start=date_from, end=date_to)

    run.finish("success")
    ingest_impl._publish_version(conn, run, date_from, date_to)
    return run.progress


__all__ = ["full_reseed_locked"]
