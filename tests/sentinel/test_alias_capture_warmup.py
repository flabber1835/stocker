"""Whole-capture projection freeze and feature-only initial warmup."""
import datetime as dt

import pytest

from research.sharadar_replay.runtime import simulated_runtime
from sentinel.feed import (calendar, coherence, domains, ingest, publication, seed_capture,
                           sharadar, snapshot_source, source_aliases, store, symbol_identity, universe)
from test_concurrent_source_symbols import DAY, source
from test_exported_symbol_identity import nas_provider
from tests.support.postgres import _EphemeralPostgres


@pytest.mark.parametrize("missing_native", [False, True])
def test_middle_collision_freezes_and_revalidates_every_capture_chunk(missing_native):
    days = ("2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05")
    provider = nas_provider(days=days)
    data, _, _ = source()
    native = dict(data["tickers"][0], ticker="UNITA", permaticker=800000,
                  firstpricedate=days[0], lastpricedate=days[-1])
    listings = [dict(r, firstpricedate=days[0], lastpricedate=days[-1])
                for r in provider.step.tables["TICKERS"] if r["ticker"].startswith("T")]
    bars = [dict(r, lastupdated="2026-01-06") for r in provider.step.tables["SEP"]
            if r["ticker"].startswith("T")]
    bars.extend(dict(data["sep"][0], ticker="SHAREA" if missing_native and day == days[0] else "UNITA",
                     date=day, lastupdated="2026-01-06") for day in days)
    bars.append(dict(data["sep"][1], ticker="SHAREA", date=days[1], lastupdated="2026-01-06"))
    actions = [dict(date=days[1], ticker="SHAREA", action=kind, contraticker=contra, value=None)
               for kind, contra in (("tickerchangeto", "SHAREA"), ("tickerchangefrom", "UNITA"))]
    step = provider.step
    provider = type(provider)(page_size=4000, variation_seed=19)
    provider.advance(step.model_copy(update={"name": "middle_capture_collision",
        "at": dt.datetime(2026, 1, 6, tzinfo=dt.timezone.utc), "through": dt.date.fromisoformat(days[-1]),
        "tables": {**step.tables, "TICKERS": (*listings, native), "ACTIONS": tuple(actions),
                   "SEP": tuple(bars)}}))
    with simulated_runtime(provider, commit="a" * 40):
        adapter = seed_capture.ActionsSnapshotSource(snapshot_source.fetch_table)
        tracked, guard = ingest._seed_source(snapshot_source.fetch_table, final_hi=days[-1],
            update_ceiling="2026-01-06", acquisition_fetch=adapter)
        with seed_capture.CapturedRows() as captured:
            guard.begin_seed_capture()
            captured.capture(guard, sharadar.TICKERS)
            guard.preflight_seed_identity(tickers=captured(sharadar.TICKERS), fetch=snapshot_source.fetch_table,
                                          date_from=days[0], date_to=days[-1])
            assert guard.alias_rejections["records"] == []  # Both endpoints look healthy.
            captured.capture(guard, sharadar.ACTIONS, sharadar.date_params("1900-01-01", days[-1]))
            captured.capture(guard, sharadar.SFP, sharadar.date_params(days[0], days[-1]))
            for lo, hi in sharadar.year_chunks(days[0], days[-1]):
                captured.capture(guard, sharadar.SEP, sharadar.date_params(lo, hi))
            assert len(guard.alias_rejections["records"]) == 1
            assert guard.seed_coverage_evidence is None
            if missing_native:
                with pytest.raises(coherence.SeedHistoryIncomplete, match="800000"):
                    guard.finalize_seed_capture(captured, date_from=days[0], date_to=days[-1])
            else:
                guard.finalize_seed_capture(captured, date_from=days[0], date_to=days[-1])
                proof = guard.seed_coverage_evidence
                assert proof["sessions_checked"] == 4
                assert proof["expected_eligible_total"] == proof["received_eligible_total"] == 5604 * 4
                assert proof["missing_eligible_total"] == proof["unresolved_eligible_risk_total"] == 0


def test_initial_warmup_and_restart_keep_native_series_and_unaffected_opening_book():
    from sentinel.core import bootstrap, loader
    from sentinel.feed.source_authority import SeedCoverageAccumulator, SeedListingProjection
    data, _, _ = source()
    identity = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY)
    coverage = SeedCoverageAccumulator(SeedListingProjection(
        (*identity.rows, *identity.alias_rows), source_digest="fixture"), identity.resolver().resolve)
    try:
        for row in data["sep"]:
            coverage.add(row)
        rejected = source_aliases.discover(coverage, identity)
    finally:
        coverage.close()
    corrected = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY,
                                                  alias_rejections=rejected)
    sessions = calendar.previous_sessions(DAY, 200)
    ordinary = [dict(table="SEP", ticker=f"LIQ{i}", permaticker=str(700000 + i),
                     category="Domestic Common Stock", sector="Industrials", relatedtickers="",
                     firstpricedate=sessions[0], lastpricedate=DAY, isdelisted="N") for i in range(30)]
    prices = [dict(ticker=r["ticker"], date=day, open=price * .999, close=price,
                   closeunadj=price, volume=2000000)
              for i, r in enumerate(ordinary) for index, day in enumerate(sessions)
              for price in [(50 + i) * (1.0004 + i * .00002) ** index]]
    # Select by explicit source label; the recorded fixture order is not authority.
    native_prices = [dict(next(b for b in data["sep"] if b["ticker"] == listing["ticker"]), date=day)
                     for listing in data["tickers"] for day in sessions if day >= listing["firstpricedate"]]
    server = _EphemeralPostgres()
    try:
        server.start()
        with store.connect(server.sync_dsn) as conn:
            store.migrate_schema(conn)
            universe.write_universe(conn, ordinary, DAY)
            store.write_bars(conn, domains.normalise_sep_rows(sorted(prices, key=lambda r: (r["date"], r["ticker"])), resolve_identity=universe.IdentityResolver(
                universe.listings_from_rows(ordinary)).resolve))
            publication.publish(conn, window_start=sessions[0], window_end=DAY)
            baseline = bootstrap.bootstrap(conn, start=sessions[0], end=DAY, starting_cash=1000000)
            assert baseline.n_positions > 1
            universe.write_universe(conn, data["tickers"], DAY)
            run = store.IngestRun(conn, "daily", date_from=sessions[0], date_to=DAY, chunks_total=1)
            with store.corpus_write_lock(conn):
                store.write_actions(conn, data["actions"], run_id=run.progress.run_id,
                                    window_start="1900-01-01", window_end=DAY)
            store.write_bars(conn, domains.normalise_sep_rows(sorted(native_prices, key=lambda r: (r["date"], r["ticker"])),
                resolve_identity=corrected.resolver().resolve))
            run.finish("success")
            # Construct the loader's published fixture directly. The public
            # membrane correctly refuses alias evidence without a seed proof;
            # test_production_seed_warmup_integration covers that full route.
            publication._publish_atomic(conn, run_id=run.progress.run_id,
                window_start=sessions[0], window_end=DAY, evidence={source_aliases.KEY: rejected})
        with store.connect(server.sync_dsn) as conn:
            window = loader.load_window(conn, start=sessions[0], end=DAY)
            book = bootstrap.bootstrap(conn, start=sessions[0], end=DAY, starting_cash=1000000)
            assert book.warmup_sessions == baseline.warmup_sessions == 199
            assert book.positions == baseline.positions
            assert book.shares == baseline.shares
            assert book.held == baseline.held == {}
            assert book.cash_weight == baseline.cash_weight
            assert book.data_version > baseline.data_version
            resolver = universe.load_resolver(conn)
            assert resolver.ticker_for_security("6401005", DAY) == "OCLTU"
            assert resolver.resolve("OCLT", DAY) is None
            actual = [(b.security_id, b.ticker, b.raw_close) for b in window.bars_by_session[DAY]
                      if b.security_id in {"6401005", "6399775"}]
            assert sorted(actual) == [("6399775", "BRTMU", 9.98), ("6401005", "OCLTU", 10.02)]
    finally:
        server.stop()
