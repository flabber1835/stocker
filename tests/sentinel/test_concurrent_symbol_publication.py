"""Observed collision refusal and synthetic source healing through HTTP and SQL."""
from __future__ import annotations

import datetime as dt

import pytest

from research.sharadar_replay.runtime import simulated_runtime
from sentinel.feed import (domains, ingest, publication, recovery, seed_coherence,
                           sharadar, snapshot_source, source_authority, store, universe)
from test_concurrent_source_symbols import DAY, source
from test_exported_symbol_identity import nas_provider
from test_seed_symbol_transition import OLD_LISTINGS
from tests.support.postgres import _EphemeralPostgres


def provider_for(*, healed):
    provider = nas_provider(days=(DAY,))
    data, _, _ = source(healed=healed)
    tables = dict(provider.step.tables)
    for table, name in (("TICKERS", "tickers"), ("ACTIONS", "actions"), ("SEP", "sep")):
        tables[table] = (*tables[table], *data[name])
    provider.advance(provider.step.model_copy(update={
        "name": "separate_instruments" if healed else "observed_collisions",
        "at": provider.step.at + dt.timedelta(seconds=1), "tables": tables}))
    return provider


def test_refusal_preserves_publication_then_corrected_source_publishes_all_four_prices():
    server = _EphemeralPostgres()
    try:
        server.start()
        provider = provider_for(healed=False)
        with simulated_runtime(provider, commit="a" * 40), store.connect(server.sync_dsn) as conn:
            store.migrate_schema(conn)
            universe.write_universe(conn, OLD_LISTINGS, DAY)
            old_bars = [dict(ticker=r["ticker"], date=DAY, open=10, close=10,
                             closeunadj=10, volume=1000) for r in OLD_LISTINGS]
            store.write_bars(conn, domains.normalise_sep_rows(
                old_bars, resolve_identity=universe.IdentityResolver(
                    universe.listings_from_rows(OLD_LISTINGS)).resolve))
            baseline = publication.publish(conn, window_start=DAY, window_end=DAY)
            baseline_rows = conn.execute("SELECT * FROM sentinel_bars ORDER BY security_id,session").fetchall()
            assert baseline_rows  # CYCN's old listing already ended on September 8.
            for healed in (False, True):
                if healed:
                    provider.advance(provider_for(healed=True).step.model_copy(update={
                        "at": provider.step.at + dt.timedelta(seconds=1)}))
                with store.corpus_write_lock(conn):
                    plan = recovery.prepare_full_reseed(conn, date_from=DAY, date_to=DAY)
                    if not healed:
                        with pytest.raises(source_authority.SeedIdentityCollision):
                            ingest._run_seed_generation(conn, recovery_plan=plan,
                                fetch=snapshot_source.fetch_table, final_hi=DAY, boundary="2026-09-14")
                        assert publication.require_current(conn).version == baseline.version
                        assert conn.execute("SELECT COUNT(*) FROM feed_ingest_runs").fetchone()[0] == 0
                        assert conn.execute("SELECT * FROM sentinel_bars ORDER BY security_id,session").fetchall() == baseline_rows
                        assert universe.load_resolver(conn).resolve("OCLT", DAY) is None
                        assert not any(r["channel"] == "export" and r.get("table") == sharadar.ACTIONS
                                       for r in provider.transcript)
                        assert all(r["query"]["date.gte"] == r["query"]["date.lte"]
                                   for r in provider.transcript if r.get("table") == sharadar.SEP)
                        continue
                    result, _ = ingest._run_seed_generation(conn, recovery_plan=plan,
                        fetch=snapshot_source.fetch_table, final_hi=DAY, boundary="2026-09-14")
                    assert result.rows_dropped == 0
                    assert publication.require_current(conn).version > baseline.version
                    proof = seed_coherence.require_for_publication(
                        conn, run_id=result.run_id, window_start=DAY, window_end=DAY)
                    assert proof["phase"] == "complete"
                    assert proof["normalized_source"] == proof["normalized_local"]
        with store.connect(server.sync_dsn) as conn:
            expected = {"OCLTU": ("6401005", 10.02), "BRTMU": ("6399775", 9.98),
                        "OCLT": ("900000001", 9.9), "BRTM": ("900000002", 9.87)}
            rows = conn.execute("SELECT ticker,security_id,close_unadjusted FROM sentinel_bars "
                                "WHERE ticker=ANY(%s)", (list(expected),)).fetchall()
            assert {ticker: (sid, float(price)) for ticker, sid, price in rows} == expected
            assert len(rows) == 4
            resolver = universe.load_resolver(conn)
            assert {ticker: resolver.resolve(ticker, DAY) for ticker in expected} == {
                ticker: sid for ticker, (sid, _) in expected.items()}
    finally:
        server.stop()
