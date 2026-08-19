"""Sharadar ingest orchestration with current-source CDC and convergent retry.

This module deliberately reuses the mature normalization/evidence helpers in
``ingest_impl`` while owning the state transitions #185 changes:

* daily fetch range starts from the PUBLISHED/visible session frontier, never a
  farther physical frontier left by an unpublished candidate;
* SEP historical mutations are discovered by an inclusive ``lastupdated``
  watermark stored only in publication evidence;
* a historical mutation triggers a complete source-stable refetch of its year;
* one closed historical year is completely source-key reconciled per successful
  daily run, so upstream removals cannot remain undetectable forever;
* ACTIONS receives a complete corpus-history reconciliation at least weekly;
* a durably successful unpublished candidate is first resumed exactly when safe;
  otherwise the next complete retry supersedes it without manual SQL.

Certification/golden-output regeneration is intentionally not in this module.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable, Iterable, Optional

from sentinel.feed import domains, ingest_impl as impl, publication, sharadar
from sentinel.feed import source_state, staging, universe
from sentinel.feed import store as feed_store

log = logging.getLogger(__name__)


def _source_publication_evidence(state: dict, *, kind: str, rows_written: int,
                                 rows_dropped: int, chunks: int,
                                 reconciliation: list[dict] | None = None,
                                 resumed: bool = False) -> dict:
    evidence = {
        "kind": kind,
        "rows_written": int(rows_written),
        "rows_dropped": int(rows_dropped),
        "chunks": int(chunks),
        source_state.STATE_KEY: dict(state),
    }
    if reconciliation:
        evidence["sep_source_reconciliation"] = reconciliation
    if resumed:
        evidence["publication_resumed_after_restart"] = True
    return evidence


def _retire_superseded_universe_candidates(conn, *, run_id: str) -> dict[str, int]:
    """Retire older unpublished TICKERS snapshots proven covered by this run.

    TICKERS uses ``snapshot_date`` in its primary key, so a next-day retry cannot
    take ownership of yesterday's candidate by upsert. A successfully validated
    current run has one complete stable TICKERS snapshot; that is proof a prior
    unpublished SUCCESS or FAILED snapshot through the same date is superseded.
    Published history is never touched.

    The DELETE stays uncommitted here. ``publication.publish`` either commits it
    atomically with the new version or rolls it back with the publication.
    """
    writer = str(run_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.status,COUNT(u.permaticker),MIN(u.snapshot_date),"
            " MAX(u.snapshot_date) FROM feed_ingest_runs r"
            " LEFT JOIN sentinel_universe u ON u.last_written_run_id=r.run_id"
            " WHERE r.run_id=%s GROUP BY r.status", (writer,))
        current = cur.fetchone()
    if current is None:
        raise RuntimeError(f"ingest run {writer} does not exist")
    status, count, first_snapshot, last_snapshot = current
    if status != "success":
        raise RuntimeError(
            f"cannot supersede TICKERS candidates from non-success run {writer}: "
            f"status={status!r}")
    if not int(count):
        return {}
    if first_snapshot != last_snapshot:
        raise RuntimeError(
            f"current TICKERS candidate is not one complete dated snapshot: "
            f"{first_snapshot}..{last_snapshot}")
    with conn.cursor() as cur:
        cur.execute(
            "WITH deleted AS (DELETE FROM sentinel_universe old"
            " USING feed_ingest_runs r"
            " WHERE old.last_written_run_id=r.run_id"
            "   AND old.last_written_run_id<>%s"
            "   AND r.status IN ('failed','success')"
            "   AND old.snapshot_date<=%s"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=old.last_written_run_id)"
            " RETURNING old.last_written_run_id)"
            " SELECT last_written_run_id,COUNT(*) FROM deleted"
            " GROUP BY last_written_run_id ORDER BY last_written_run_id",
            (writer, last_snapshot))
        return {str(candidate): int(rows)
                for candidate, rows in cur.fetchall()}


def resume_validated_publication(conn) -> Optional[publication.Publication]:
    """Publish the newest exact SUCCESS/unpublished candidate when still safe.

    ``finish('success')`` is the durable validation boundary in the existing
    ingest. If the process dies immediately afterwards, the bytes are already a
    validated candidate; replaying the vendor is unnecessary if none of those
    bytes has been superseded. Publication's existing coherence guards prove
    that condition. If they reject, the normal retry path starts from the
    *visible* frontier and produces a complete newer generation instead.

    Source cursors are conservative on resumed publication: a daily candidate
    retains the preceding published watermark so the next run replays its CDC
    overlap; a seed uses its durable start date as a safe inclusive watermark.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.run_id,r.kind,r.date_from,r.date_to,r.started_at,"
            " r.rows_written,r.rows_dropped,r.chunks_done"
            " FROM feed_ingest_runs r"
            " WHERE r.status='success'"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=r.run_id)"
            " ORDER BY r.started_at DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    run_id, kind, date_from, date_to, started_at, written, dropped, chunks = row
    previous = source_state.state_from_publication(publication.current(conn))
    if str(kind) == "seed":
        started_day = str(started_at.date() if hasattr(started_at, "date")
                          else str(started_at)[:10])
        state = source_state.published_state(
            previous, sep_watermark=started_day,
            reconciliation_year=(int(str(date_to)[:4]) - 1 if date_to else None),
            actions_full_reconciled_on=str(date_to) if date_to else None)
    else:
        # Daily could have discovered a newer watermark, but that in-memory fact
        # died before publication. Reusing the preceding cursor is conservative:
        # the next run replays the same mutation boundary rather than skipping it.
        watermark = source_state.require_sep_watermark(previous)
        state = source_state.published_state(
            previous, sep_watermark=watermark, reconciliation_year=None,
            actions_full_reconciled_on=None)
    evidence = _source_publication_evidence(
        state, kind=str(kind), rows_written=int(written), rows_dropped=int(dropped),
        chunks=int(chunks), resumed=True)
    try:
        published = publication.publish(
            conn, run_id=str(run_id),
            window_start=str(date_from) if date_from else None,
            window_end=str(date_to) if date_to else None,
            evidence=evidence)
    except publication.CorpusIncoherent:
        # The candidate is valid but no longer complete enough to publish alone.
        # A fresh run can safely supersede it; do not mutate/guess its authority.
        conn.rollback()
        return None
    log.warning("sentinel: resumed validated unpublished ingest %s as corpus v%d",
                run_id, published.version)
    return published


def _ordered_sep(conn, rows: Iterable[dict], *, run_id: str, chunk: str,
                 reconcile_window: tuple[str, str] | None = None,
                 reconciliation_evidence: list[dict] | None = None):
    """Stage/sort one SEP window and optionally prove no source key disappeared."""
    staged = staging.stage(conn, rows, run_id=run_id, chunk=chunk)
    log.info("sentinel: staged %d SEP rows for chunk %s", staged, chunk)
    try:
        if reconcile_window is not None:
            lo, hi = reconcile_window
            diff = staging.source_key_diff(
                conn, run_id=run_id, chunk=chunk,
                window_start=lo, window_end=hi)
            item = {"window": [lo, hi], **diff}
            if reconciliation_evidence is not None:
                reconciliation_evidence.append(item)
            if diff["removals"]:
                sample = ", ".join(
                    f"{row['ticker']}@{row['session']}"
                    for row in diff["removal_sample"][:5])
                raise source_state.SepSourceRemovalDetected(
                    f"complete Sharadar SEP reconciliation {lo}..{hi} found "
                    f"{diff['removals']:,} source key(s) that disappeared "
                    f"upstream (e.g. {sample}). Additions/corrections are safe "
                    "to upsert; removing an already-published bar in place is "
                    "not. Candidate remains unpublished for operator review.")
        yield from staging.staged(conn, run_id=run_id, chunk=chunk)
    finally:
        staging.clear(conn, run_id=run_id, chunk=chunk)


def _track_seed_lastupdated(rows: Iterable[dict], scan: source_state.SepMutationScan):
    for row in rows:
        scan.observe(row)
        yield row


def _process_price_window(conn, run, *, fetch, resolver, lo: str, hi: str,
                          chunk: str, validation_frontier: str | None,
                          reconcile: bool,
                          reconciliation_evidence: list[dict]) -> None:
    report = domains.NormalisationReport()
    splits, divs, action_rows, ambiguous_splits = impl._action_maps(
        conn, lo, hi, include_run_id=run.progress.run_id)
    rows = fetch(sharadar.SEP, sharadar.date_params(lo, hi))
    ordered = _ordered_sep(
        conn, rows, run_id=run.progress.run_id, chunk=chunk,
        reconcile_window=(lo, hi) if reconcile else None,
        reconciliation_evidence=reconciliation_evidence)
    bars = domains.normalise_sep_rows(
        ordered, resolve_identity=resolver,
        authoritative_splits=splits, dividends=divs,
        prior_observations=feed_store.previous_observations(conn, lo),
        report=report)
    run.progress.rows_written += feed_store.write_bars(
        conn, bars, run_id=run.progress.run_id, require_lock=True)
    impl._persist_chunk_evidence(
        conn, run, chunk, lo, hi, report, splits, action_rows, action_rows,
        ambiguous_splits)
    run.progress.rows_dropped += (
        report.dropped_no_raw_close + report.dropped_no_identity)
    domains.assert_raw_price_domain(report)
    for session in sorted(report.rows_by_session):
        if validation_frontier is None or session > validation_frontier:
            domains.assert_identity_domain(report, session)


def seed_locked(conn, *, date_from: str, date_to: Optional[str],
                fetch: Callable[..., Iterable[dict]], resolve_identity=None):
    """Full seed that establishes the initial SEP mutation watermark."""
    date_to = date_to or impl._today()
    chunks = sharadar.year_chunks(date_from, date_to)
    started_day = _dt.date.today().isoformat()
    run = feed_store.IngestRun(
        conn, "seed", date_from=date_from, date_to=date_to,
        chunks_total=len(chunks) + 3)

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
        params = {"ticker": "SPY", **sharadar.date_params(date_from, date_to)}
        run.progress.rows_written += feed_store.write_spy_total_return(
            conn, fetch(sharadar.SFP, params), run_id=run.progress.run_id,
            require_lock=True)

    resolver = resolve_identity or universe.load_resolver(
        conn, include_run_id=run.progress.run_id).resolve
    scan = source_state.SepMutationScan(
        current_overlap_start=date_from, corpus_start=date_from)
    for lo, hi in chunks:
        with run.chunk(lo[:4]):
            tracked = _track_seed_lastupdated(
                fetch(sharadar.SEP, sharadar.date_params(lo, hi)), scan)
            # Seed defines the initial source key set, so there is no prior set
            # whose removals could be authoritative.
            _process_price_window(
                conn, run, fetch=lambda _table, _params, r=tracked: r,
                resolver=resolver, lo=lo, hi=hi, chunk=lo[:4],
                validation_frontier=None, reconcile=False,
                reconciliation_evidence=[])

    if not scan.max_lastupdated:
        raise source_state.SharadarSourceStateError(
            "full SEP seed produced no usable lastupdated watermark")
    # A multi-hour seed can straddle a vendor mutation. Use the earlier of the
    # observed high-water mark and the seed's wall-clock start day; the next
    # daily query is inclusive and will therefore replay every update that could
    # have raced an already-fetched historical chunk.
    seed_watermark = min(scan.max_lastupdated, started_day)
    state = source_state.published_state(
        {}, sep_watermark=seed_watermark,
        reconciliation_year=max(int(date_from[:4]), int(date_to[:4]) - 1),
        actions_full_reconciled_on=date_to)
    run.finish("success")
    retired = _retire_superseded_universe_candidates(
        conn, run_id=run.progress.run_id)
    evidence = _source_publication_evidence(
        state, kind="seed", rows_written=run.progress.rows_written,
        rows_dropped=run.progress.rows_dropped,
        chunks=run.progress.chunks_done)
    if retired:
        evidence["retired_unpublished_universe_candidates"] = retired
    publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=date_from, window_end=date_to, evidence=evidence)
    return run.progress


def daily_locked(conn, *, fetch: Callable[..., Iterable[dict]],
                 resolve_identity=None, overlap_days: int,
                 today: Optional[str]):
    """Daily session maintenance + SEP mutation CDC + periodic reconciliation."""
    to = today or impl._today()
    published = publication.current(conn)
    previous_state = source_state.state_from_publication(published)
    watermark = source_state.require_sep_watermark(previous_state)

    # PUBLISHED frontier is the only restart authority. A failed candidate may
    # have moved physical MAX(session) arbitrarily far; using it here is #108.
    visible_frontier = feed_store.latest_visible_session(conn)
    if visible_frontier is None:
        raise RuntimeError(
            "the corpus has no published/visible session frontier. Re-run "
            "feed-seed; physical rows from an unpublished seed are not authority")
    start = (_dt.date.fromisoformat(visible_frontier)
             - _dt.timedelta(days=overlap_days)).isoformat()
    sharadar.validate_date_range(start, to)

    full_actions = source_state.actions_full_reconciliation_due(
        previous_state, through=to)
    reconciliation_year = source_state.next_reconciliation_year(
        previous_state, corpus_start=impl.DEFAULT_SEED_START, through=to)

    # Four fixed source phases plus dynamically discovered price windows.
    run = feed_store.IngestRun(
        conn, "daily", date_from=start, date_to=to, chunks_total=5)

    with run.chunk("tickers"):
        rows = list(fetch(sharadar.TICKERS))
        run.progress.rows_written += universe.write_universe(
            conn, rows, to, run_id=run.progress.run_id)

    with run.chunk("actions"):
        from sentinel.feed import calendar
        if full_actions:
            action_start, _ = calendar.action_date_window(
                impl.DEFAULT_SEED_START, to)
        else:
            action_start, _ = calendar.action_date_window(start, to)
        action_source_rows = list(fetch(
            sharadar.ACTIONS, sharadar.date_params(action_start, to)))
        run.progress.rows_written += feed_store.write_actions(
            conn, action_source_rows, run_id=run.progress.run_id,
            window_start=action_start, window_end=to)

    with run.chunk("spy"):
        from sentinel.feed import calendar, readiness
        spy_start = calendar.previous_sessions(
            to, readiness.REQUIRED_SPY_SESSIONS)[0]
        params = {"ticker": "SPY", **sharadar.date_params(spy_start, to)}
        run.progress.rows_written += feed_store.write_spy_total_return(
            conn, fetch(sharadar.SFP, params), run_id=run.progress.run_id,
            require_lock=True)

    with run.chunk("sep-mutations"):
        mutation_rows = fetch(
            sharadar.SEP, source_state.mutation_params(watermark, to))
        mutation_scan = source_state.consume_mutations(
            mutation_rows, current_overlap_start=start,
            corpus_start=impl.DEFAULT_SEED_START)

    next_watermark = max(
        watermark, mutation_scan.max_lastupdated or watermark)
    years = set(mutation_scan.historical_years)
    # One closed year per successful run provides complete key-set coverage over
    # the historical corpus without turning every evening into a full download.
    if reconciliation_year < int(to[:4]):
        years.add(reconciliation_year)

    windows: list[tuple[str, str, str, bool]] = []
    for year in sorted(years):
        lo = max(f"{year:04d}-01-01", impl.DEFAULT_SEED_START)
        hi = min(f"{year:04d}-12-31", to)
        if lo <= hi:
            windows.append((lo, hi, f"sep-year-{year:04d}", True))
    current_year_covered = any(
        lo <= start and hi >= to for lo, hi, _chunk, _rec in windows)
    if not current_year_covered:
        windows.append((start, to, "prices", False))
    run.progress.chunks_total = 4 + len(windows)
    run.publish()

    resolver = resolve_identity or universe.load_resolver(
        conn, include_run_id=run.progress.run_id).resolve
    reconciliation_evidence: list[dict] = []
    for lo, hi, chunk, reconcile in windows:
        with run.chunk(chunk):
            _process_price_window(
                conn, run, fetch=fetch, resolver=resolver,
                lo=lo, hi=hi, chunk=chunk,
                validation_frontier=visible_frontier,
                reconcile=reconcile,
                reconciliation_evidence=reconciliation_evidence)

    state = source_state.published_state(
        previous_state, sep_watermark=next_watermark,
        reconciliation_year=reconciliation_year,
        actions_full_reconciled_on=to if full_actions else None)
    run.finish("success")
    retired = _retire_superseded_universe_candidates(
        conn, run_id=run.progress.run_id)
    evidence = _source_publication_evidence(
        state, kind="daily", rows_written=run.progress.rows_written,
        rows_dropped=run.progress.rows_dropped,
        chunks=run.progress.chunks_done,
        reconciliation=reconciliation_evidence)
    evidence["sep_mutation_discovery"] = {
        "watermark_from": watermark,
        "watermark_to": next_watermark,
        "rows": mutation_scan.rows,
        "historical_years": sorted(mutation_scan.historical_years),
    }
    evidence["actions_complete_reconciliation"] = bool(full_actions)
    if retired:
        evidence["retired_unpublished_universe_candidates"] = retired
    # Do not swallow publication failure. A success/unpublished candidate is a
    # durable state the startup path knows how to resume or supersede; reporting
    # it as successful operation would strand #108 silently.
    publication.publish(
        conn, run_id=run.progress.run_id,
        window_start=start, window_end=to, evidence=evidence)
    return run.progress


__all__ = ["daily_locked", "resume_validated_publication", "seed_locked"]
