"""Canonical normalization into immutable private candidates. No provider I/O."""
from __future__ import annotations

import hashlib
from contextlib import closing
from itertools import islice

from sentinel.feed import (
    actions_map, calendar, coherence, domains, progress, rolling_jobs as jobs, rolling_store,
    source_aliases, staging, symbol_identity,
)
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark, RestartRequirement, digest
from sentinel.feed.source_authority import SeedCoverageAccumulator, SeedListingProjection
from sentinel.regime.spy import SPY_PRICE_COLUMN

NORMALIZATION_VERSION = "sentinel.sharadar-rolling-comparison/1"
CHUNK = "rolling-window"


def _rows(conn, lease):
    return staging.staged(conn, run_id=lease.owner, chunk=CHUNK)


def _coverage(identity, source_digest):
    projection = SeedListingProjection((*identity.rows, *identity.alias_rows),
                                       source_digest=identity.digest(source_digest))
    return SeedCoverageAccumulator(projection, identity.resolver().resolve)


def _populate(conn, lease, coverage, *, pulse, subphase):
    counts = {}
    with progress.phase("rolling_identity", subphase=subphase, job_id=lease.job_id) as counter, \
            closing(_rows(conn, lease)) as rows:
        for index, row in enumerate(rows, 1):
            counter[0] = index
            resolved = coverage.add(row)
            day = row["date"]
            counts[day] = counts.get(day, coherence.SeedSessionCounts()).add(row, resolved=resolved)
            if index % 5000 == 0:
                pulse()
                progress.emit("rolling_identity", "working", subphase=subphase,
                              rows=index, job_id=lease.job_id)
    return counts


def benchmarks(window, rows):
    by_key = {}
    for row in rows:
        key = (str(row["date"]), str(row["ticker"]))
        if key in by_key or key[1] not in {"SPY", "BIL"}:
            raise ValueError("duplicate or unexpected benchmark identity")
        by_key[key] = row
    expected = {(str(day), ticker) for day in window.sessions for ticker in ("SPY", "BIL")}
    if set(by_key) != expected:
        raise ValueError("SPY/BIL must cover every session exactly")
    for day in window.sessions:
        spy, bil = by_key[(str(day), "SPY")], by_key[(str(day), "BIL")]
        # Same mandatory BIL fields as the existing dedicated defensive writer.
        yield CanonicalBenchmark(
            session=day, spy_total_return=float(spy[SPY_PRICE_COLUMN]),
            bil_open_signal=float(bil["open"]), bil_close_signal=float(bil["close"]),
            bil_close_adjusted=float(bil[SPY_PRICE_COLUMN]),
            bil_close_unadjusted=float(bil["closeunadj"]))


def build(conn, lease, request, source):
    """Caller holds common writer/backup authority and owns one transaction."""
    pulse = lambda: jobs.heartbeat(conn, lease, lease_seconds=600)
    native = digest(source.tickers)
    identity = symbol_identity.SymbolProjection(source.tickers, source.actions,
                                                 through=str(request.window.end))
    with closing(_coverage(identity, native)) as discovery:
        _populate(conn, lease, discovery, pulse=pulse, subphase="alias_discovery")
        aliases = source_aliases.discover(discovery, identity)
    identity = symbol_identity.SymbolProjection(source.tickers, source.actions,
                                                 through=str(request.window.end),
                                                 alias_rejections=aliases)
    source_aliases.require_current(identity, aliases)
    bounds = {"date_from": str(request.window.start), "date_to": str(request.window.end)}
    with closing(_coverage(identity, native)) as coverage:
        counts = _populate(conn, lease, coverage, pulse=pulse, subphase="independent_coverage")
        coverage_proof = coverage.require_complete(**bounds)
        coherence.assert_seed_history(counts, **bounds)
        reference = rolling_store.put_evidence(conn, source.reference_payload())
        source_sha = rolling_store.put_evidence(conn, source.source_payload())
        candidate = rolling_store.begin(
            conn, window=request.window, reference_sha256=reference,
            source_evidence_sha256=source_sha,
            expected_publication_version=request.expected_publication_version,
            dependencies_sha256=request.dependencies_sha256)
        jobs.advance(conn, lease, "STAGING", candidate_id=candidate)
        lo, hi = calendar.action_date_window(request.window.start, request.window.end)
        actions = [row for row in source.actions if lo <= row["date"] <= hi]
        sessions = [str(day) for day in request.window.sessions]
        splits, ambiguous = actions_map.split_rows_from_actions(actions, sessions)
        if ambiguous or actions_map.unusable_dividend_rows(actions):
            raise ValueError("ambiguous split or unusable dividend source evidence")
        dividends = actions_map.dividends_from_actions(actions, sessions)
        report = domains.NormalisationReport()
        no_events, no_event_hash = 0, hashlib.sha256()
        with progress.phase("rolling_normalization", job_id=lease.job_id) as counter, \
                closing(_rows(conn, lease)) as rows:
            normalized = domains.normalise_sep_rows(
                rows, resolve_identity=identity.resolver().resolve, dividends=dividends,
                authoritative_splits=splits, report=report)
            while batch := list(islice(normalized, rolling_store.BATCH_SIZE)):
                bars = [CanonicalBar(
                    security_id=str(item.vendor.security_id), session=item.vendor.session,
                    ticker=item.vendor.ticker, close_signal=item.close_signal,
                    close_unadjusted=item.vendor.raw_close, open_unadjusted=item.vendor.raw_open,
                    volume=item.vendor.volume, split_ratio=item.vendor.split_ratio,
                    dividend_per_share=item.vendor.dividend_per_share) for item in batch]
                rolling_store.write_bars(conn, candidate, bars)
                for key in sorted(report.split_no_event_evidence):
                    rolling_store._fold(no_event_hash, key)
                no_events += len(report.split_no_event_evidence)
                report.split_no_event_evidence.clear()
                jobs.progress(conn, lease, rows=report.bars, bytes_=0)
                pulse()
                counter[0] = report.bars
                progress.emit("rolling_normalization", "working", rows=report.bars, job_id=lease.job_id)
        if (report.dropped_no_raw_close or actions_map.split_disagreements(report, splits)
                or any(item["disposition"] == actions_map.SPLIT_UNRESOLVED
                       for item in report.split_dispositions.values())):
            raise ValueError("normalization has missing raw prices or unresolved split evidence")
        rolling_store.write_benchmarks(conn, candidate, benchmarks(request.window, source.sfp))
        jobs.advance(conn, lease, "VALIDATING")
        with progress.phase("rolling_seal", job_id=lease.job_id) as counter:
            manifest = rolling_store.seal(
                conn, candidate, expected_keys=coverage.observed_keys(),
                normalization_version=NORMALIZATION_VERSION, requirements=RestartRequirement())
            counter[0] = manifest.bar_count
        validation = rolling_store.put_evidence(conn, {
            "schema": "sentinel.rolling-comparison-validation/1", "scope": "COMPARISON_ONLY",
            "snapshot_id": manifest.snapshot_id, "request_sha256": request.request_sha256,
            "coverage": coverage_proof, "alias_rejections": aliases,
            "rows": report.rows, "bars": report.bars,
            "dropped_no_identity": report.dropped_no_identity,
            "rejections": report.rejections, "rejections_truncated": report.rejections_truncated,
            "split_dispositions": [{"ticker": k[0], "session": k[1], **v}
                                   for k, v in sorted(report.split_dispositions.items())],
            "ordinary_no_split_count": no_events,
            "ordinary_no_split_sha256": no_event_hash.hexdigest(),
        })
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sentinel_snapshot_validations VALUES (%s,%s)",
                        (candidate, validation))
        jobs.advance(conn, lease, "READY")
        return candidate
