"""Canonical normalization into immutable private candidates. No provider I/O."""
from __future__ import annotations

import hashlib
from contextlib import closing
from itertools import islice

from sentinel.feed import (
    action_quarantine, actions_map, calendar, coherence, domains, progress, rolling_jobs as jobs, rolling_store,
    source_aliases, symbol_identity,
)
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark, RestartRequirement, digest
from sentinel.feed.source_authority import SeedCoverageAccumulator, SeedListingProjection

NORMALIZATION_VERSION = "sentinel.sharadar-rolling-comparison/1"
CHUNK = "rolling-window"
# SFP transports this vendor field; it remains forbidden for SEP equity signals.
# Reuse the feed's column spelling without depending on the controller's sensor.
_SFP_TOTAL_RETURN_COLUMN = domains.SEP_FORBIDDEN_COLUMNS[0]


def _rows(conn, lease, *, tickers=None, verifier=None):
    from sentinel.feed.acquisition_parts import price_rows
    return price_rows(conn, lease.job_id, tickers=tickers, verifier=verifier)


def _coverage(identity, source_digest):
    projection = SeedListingProjection((*identity.rows, *identity.alias_rows),
                                       source_digest=identity.digest(source_digest))
    return SeedCoverageAccumulator(projection, identity.resolver().resolve)


def _populate(conn, lease, coverage, *, pulse, subphase, tickers=None, verifier=None):
    counts = {}
    with progress.phase("rolling_identity", subphase=subphase, job_id=lease.job_id) as counter, \
            closing(_rows(conn, lease, tickers=tickers, verifier=verifier)) as rows:
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
            session=day, spy_total_return=float(spy[_SFP_TOTAL_RETURN_COLUMN]),
            bil_open_signal=float(bil["open"]), bil_close_signal=float(bil["close"]),
            bil_close_adjusted=float(bil[_SFP_TOTAL_RETURN_COLUMN]),
            bil_close_unadjusted=float(bil["closeunadj"]))


def build(conn, lease, request, source):
    if getattr(source, "provider", None) == "ALPACA_OPENFIGI":
        return build_alpaca(conn, lease, request, source)
    from sentinel.feed import source_corrections
    with source_corrections.using(source.corrections):
        return _build(conn, lease, request, source)


def _build(conn, lease, request, source):
    """Caller holds common writer/backup authority and owns one transaction."""
    pulse = lambda: jobs.heartbeat(conn, lease, lease_seconds=600)
    from sentinel.strategy import production_strategy
    from sentinel.core import window_policy
    _, strategy = production_strategy()
    current_window = window_policy.enabled(strategy) and request.strategy_sha256 == digest(strategy)
    native = digest(source.tickers)
    identity = symbol_identity.SymbolProjection(source.tickers, source.actions,
                                                 through=str(request.window.end))
    symbols = source_aliases.discovery_symbols(identity)
    if symbols:
        with closing(_coverage(identity, native)) as discovery:
            _populate(conn, lease, discovery, pulse=pulse, subphase="alias_discovery",
                      tickers=symbols)
            aliases = source_aliases.discover(discovery, identity)
    else:
        aliases = source_aliases.evidence()
        progress.emit("rolling_identity", "completed", subphase="alias_discovery",
                      reason="NO_INFERRED_ALIASES", rows=0, job_id=lease.job_id)
    source_aliases.apply(identity, aliases)
    source_aliases.require_current(identity, aliases)
    lo, hi = calendar.action_date_window(request.window.start, request.window.end)
    actions = [row for row in source.actions if lo <= row["date"] <= hi]
    sessions = [str(day) for day in request.window.sessions]
    if current_window:
        quarantine = action_quarantine.classify(
            identity, actions, sessions,
            prior=action_quarantine.prior_ids(conn, request.expected_publication_version))
        economic_actions = action_quarantine.safe_actions(actions, identity, quarantine, sessions)
    else:
        quarantine = []
        economic_actions = actions
    splits, ambiguous = actions_map.split_rows_from_actions(economic_actions, sessions)
    if ambiguous or actions_map.unusable_dividend_rows(economic_actions):
        raise ValueError("ambiguous split or unusable dividend source evidence")
    dividends = actions_map.dividends_from_actions(economic_actions, sessions)
    bounds = {"date_from": str(request.window.start), "date_to": str(request.window.end)}
    with closing(_coverage(identity, native)) as coverage:
        from sentinel.feed.acquisition_parts import PricePartVerifier
        manifests = getattr(source, "price_manifests", None)
        verifier = PricePartVerifier(manifests) if manifests is not None and manifests else None
        counts = _populate(conn, lease, coverage, pulse=pulse,
                           subphase="independent_coverage", verifier=verifier)
        coverage_proof = coverage.require_complete(**bounds, current_window=current_window)
        coherence.assert_seed_history(counts, **bounds)
        reference = rolling_store.put_evidence(conn, source.reference_payload())
        source_sha = rolling_store.put_evidence(conn, source.source_payload())
        candidate = rolling_store.begin(
            conn, window=request.window, reference_sha256=reference,
            source_evidence_sha256=source_sha,
            expected_publication_version=request.expected_publication_version,
            dependencies_sha256=request.dependencies_sha256)
        jobs.advance(conn, lease, "STAGING", candidate_id=candidate)
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
        with progress.phase("rolling_seal", job_id=lease.job_id) as counter, \
                closing(coverage.observed_keys()) as expected_keys:
            manifest = rolling_store.seal(
                conn, candidate, expected_keys=expected_keys,
                normalization_version=window_policy.NORMALIZATION if current_window else NORMALIZATION_VERSION,
                requirements=RestartRequirement())
            counter[0] = manifest.bar_count
        validation = rolling_store.put_evidence(conn, {
            "schema": "sentinel.rolling-comparison-validation/1", "scope": "COMPARISON_ONLY",
            "snapshot_id": manifest.snapshot_id, "request_sha256": request.request_sha256,
            "coverage": coverage_proof, "alias_rejections": aliases,
            "action_quarantine": quarantine,
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


ALPACA_NORMALIZATION = "sentinel.alpaca-openfigi-dividend-current-window/2"
MIN_ADMITTED_COMMON_STOCKS = 500
MIN_ALPACA_ADMITTED_PERCENT = 95


def require_alpaca_population(*, selected: int, admitted: int) -> None:
    if admitted < MIN_ADMITTED_COMMON_STOCKS:
        raise ValueError("Alpaca/OpenFIGI admitted common-stock population is below "
                         + str(MIN_ADMITTED_COMMON_STOCKS))
    if admitted * 100 < selected * MIN_ALPACA_ADMITTED_PERCENT:
        raise ValueError("Alpaca/OpenFIGI admitted common-stock population is below "
                         + str(MIN_ALPACA_ADMITTED_PERCENT) + "% of selected candidates")


def _alpaca_rows(conn, lease, *, verifier=None):
    """Stream retained paired bars in global key order, with optional byte proof."""
    import json
    from sentinel.feed import store
    from sentinel.feed.acquisition_parts import PartCorrupt

    query = ("SELECT p.part_id,p.session,p.ticker,p.payload "
             "FROM sentinel_acquisition_prices p "
             "JOIN sentinel_acquisition_bindings b USING(part_id) "
             "WHERE b.job_id=%s AND b.component LIKE 'SEP.%%' "
             'ORDER BY p.session,p.ticker COLLATE "C"')
    previous = None
    with store.streaming_cursor(conn, query, (lease.job_id,), batch=5000, withhold=True) as cur:
        for part_id, day, ticker, encoded in cur:
            row = verifier.add(part_id, encoded, day, ticker) if verifier else json.loads(encoded)
            key = (row["date"], row["ticker"])
            if (key <= previous if previous is not None else False) or key != (str(day), ticker):
                raise PartCorrupt("Alpaca retained price key is duplicate or corrupt")
            previous = key
            yield row
    if verifier:
        verifier.finish()


def build_alpaca(conn, lease, request, source):
    """Seal current-information prices without Sharadar semantics."""
    from sentinel.feed.acquisition_parts import PricePartVerifier
    from sentinel.feed.openfigi import reference_row
    from sentinel.feed.alpaca_observation import admissible_history

    pulse = lambda: jobs.heartbeat(conn, lease, lease_seconds=600)
    selected = {row["ticker"]: row for row in source.selected}
    axis = [str(day) for day in request.window.sessions]
    dividend_dates = {}
    for event in source.dividends:
        dividend_dates.setdefault(event["ticker"], set()).add(event["date"])
    verifier = PricePartVerifier(source.price_manifests) if source.price_manifests else None
    with progress.phase("rolling_identity", subphase="alpaca_admission",
                        selected=len(selected), job_id=lease.job_id) as counter:
        admitted, exclusions = admissible_history(
            _alpaca_rows(conn, lease, verifier=verifier), axis=axis,
            symbols=set(selected), action_affected=source.action_affected,
            pair_absent=source.pair_absent, dividend_dates=dividend_dates,
            reset_after=source.reset_after, split_terms=source.split_terms())
        counter[0] = len(admitted)
    require_alpaca_population(selected=len(selected), admitted=len(admitted))
    source.tickers = [reference_row(selected[symbol], first_session=first,
                                    last_session=axis[-1])
                      for symbol, first in sorted(admitted.items())]
    dividends = source.dividend_totals(admitted)
    splits = source.split_terms()
    reference = rolling_store.put_evidence(conn, source.reference_payload())
    source_sha = rolling_store.put_evidence(conn, source.source_payload())
    candidate = rolling_store.begin(
        conn, window=request.window, reference_sha256=reference,
        source_evidence_sha256=source_sha,
        expected_publication_version=request.expected_publication_version,
        dependencies_sha256=request.dependencies_sha256)
    jobs.advance(conn, lease, "STAGING", candidate_id=candidate)
    count = 0
    with progress.phase("rolling_normalization", job_id=lease.job_id) as counter, \
            closing(_alpaca_rows(conn, lease)) as rows:
        canonical = (CanonicalBar(
            security_id=selected[row["ticker"]]["asset_id"],
            session=row["date"], ticker=row["ticker"],
            close_signal=float(row["adjusted_close"]),
            close_unadjusted=float(row["closeunadj"]),
            open_unadjusted=float(row["open"]), volume=float(row["volume"]),
            split_ratio=float(splits.get((row['ticker'], row['date']), '1')),
            dividend_per_share=float(dividends.get((row["ticker"], row["date"]), "0")))
            for row in rows if row["ticker"] in admitted
            and row["date"] >= admitted[row["ticker"]])
        while batch := list(islice(canonical, rolling_store.BATCH_SIZE)):
            count += rolling_store.write_bars(conn, candidate, batch)
            jobs.progress(conn, lease, rows=count, bytes_=0)
            pulse()
            counter[0] = count
    rolling_store.write_benchmarks(conn, candidate, benchmarks(request.window, source.sfp))
    jobs.advance(conn, lease, "VALIDATING")
    # Derive expected keys from the retained provider prices and the admitted
    # asset map, never from candidate bars. Materialize via SQL: a server-side
    # price cursor cannot be consumed while the same connection is in COPY.
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE alpaca_admitted(ticker text PRIMARY KEY,"
                    "security_id text UNIQUE,first_session date) ON COMMIT DROP")
        with cur.copy("COPY alpaca_admitted(ticker,security_id,first_session) FROM STDIN") as copy:
            for symbol in sorted(admitted):
                copy.write_row((symbol, selected[symbol]["asset_id"], admitted[symbol]))
        cur.execute("CREATE TEMP TABLE alpaca_expected_keys("
                    "session date,security_id text,PRIMARY KEY(session,security_id)) ON COMMIT DROP")
        cur.execute("INSERT INTO alpaca_expected_keys "
                    "SELECT p.session,a.security_id FROM sentinel_acquisition_prices p "
                    "JOIN sentinel_acquisition_bindings b USING(part_id) "
                    "JOIN alpaca_admitted a ON a.ticker=p.ticker "
                    "WHERE b.job_id=%s AND b.component LIKE 'SEP.%%' "
                    "AND p.session>=a.first_session", (lease.job_id,))
    from sentinel.feed import store
    with store.streaming_cursor(conn,
            'SELECT session,security_id FROM alpaca_expected_keys ORDER BY session,security_id COLLATE "C"',
            batch=5000, withhold=True) as cur:
        manifest = rolling_store.seal(
            conn, candidate, expected_keys=((str(day), sid) for day, sid in cur),
            normalization_version=ALPACA_NORMALIZATION,
            requirements=RestartRequirement(), provider="ALPACA_OPENFIGI")
    validation = rolling_store.put_evidence(conn, {
        "schema": "sentinel.alpaca-openfigi-validation/1", "scope": "COMPARISON_ONLY",
        "snapshot_id": manifest.snapshot_id, "request_sha256": request.request_sha256,
        "admitted": len(admitted), "excluded": exclusions,
        "action_evidence": source.action_evidence, "rows": count,
        "alias_rejections": source_aliases.evidence(), "action_quarantine": [],
        "split_dispositions": [{"ticker":event['ticker'],"session":event['date'],
            "disposition":actions_map.SPLIT_CORROBORATED_DIRECT,
            "applied_ratio":float(event['ratio'])} for event in source.splits
            if event['ticker'] in admitted and event['date'] >= admitted[event['ticker']]]})
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_snapshot_validations VALUES (%s,%s)",
                    (candidate, validation))
    jobs.advance(conn, lease, "READY")
    return candidate
