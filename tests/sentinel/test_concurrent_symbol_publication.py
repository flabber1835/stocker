"""Initial native seed, failed correction isolation, restart and source healing."""
from __future__ import annotations

import datetime as dt

import pytest

from research.sharadar_replay.runtime import simulated_runtime
from sentinel.feed import (ingest, publication, seed_coherence, source_aliases,
                           snapshot_source, store, universe)
from test_concurrent_source_symbols import DAY, source
from test_exported_symbol_identity import nas_provider
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


def seed(conn):
    return ingest.seed(conn, date_from=DAY, date_to=DAY, fetch=snapshot_source.fetch_table)


def test_empty_database_seed_restart_failed_correction_and_automatic_healing(monkeypatch):
    server = _EphemeralPostgres()
    try:
        server.start()
        provider = provider_for(healed=False)
        with simulated_runtime(provider, commit="a" * 40), store.connect(server.sync_dsn) as conn:
            store.migrate_schema(conn)
            initial = seed(conn)
            baseline = publication.require_current(conn).version
            aliases = source_aliases.load(conn)
            assert len(aliases["records"]) == 2
            assert initial.rows_dropped == 2
            for opened in (conn, store.connect(server.sync_dsn)):
                try:
                    resolver = universe.load_resolver(opened)
                    assert resolver.resolve("OCLTU", DAY) == "6401005"
                    assert resolver.resolve("BRTMU", DAY) == "6399775"
                    assert resolver.resolve("OCLT", DAY) is None
                    assert resolver.resolve("BRTM", DAY) is None
                    assert source_aliases.load(opened) == aliases
                finally:
                    if opened is not conn:
                        opened.close()
            provider.advance(provider_for(healed=True).step.model_copy(update={
                "at": provider.step.at + dt.timedelta(seconds=1)}))
            with pytest.raises(universe.HistoricalIdentityMutation):
                ingest.daily(conn, fetch=snapshot_source.fetch_table, today=DAY)
            conn.rollback()
            def fail_before_publication(self, run, resolver):
                assert source_aliases.load(run.conn, include_run_id=run.progress.run_id)["records"] == []
                with store.connect(server.sync_dsn) as other:
                    assert source_aliases.load(other) == aliases
                    assert universe.load_resolver(other).resolve("OCLT", DAY) is None
                run.finish("failed", "injected post-proof failure")
                raise RuntimeError("injected post-proof failure")
            with monkeypatch.context() as patch:
                patch.setattr(ingest._SeedAuthority, "before_success", fail_before_publication)
                with pytest.raises(RuntimeError, match="injected post-proof"):
                    seed(conn)
            assert publication.require_current(conn).version == baseline
            assert source_aliases.load(conn) == aliases
            healed = seed(conn)
            assert healed.rows_dropped == 0
            assert publication.require_current(conn).version > baseline
            assert source_aliases.load(conn)["records"] == []
            proof = seed_coherence.require_for_publication(
                conn, run_id=healed.run_id, window_start=DAY, window_end=DAY)
            assert proof["normalized_source"] == proof["normalized_local"]
            assert proof["source_alias_rejections_sha256"] == source_aliases.evidence()["sha256"]
            with store.connect(server.sync_dsn) as other:
                expected = {"OCLTU": ("6401005", 10.02), "BRTMU": ("6399775", 9.98),
                            "OCLT": ("900000001", 9.9), "BRTM": ("900000002", 9.87)}
                rows = other.execute("SELECT ticker,security_id,close_unadjusted FROM sentinel_bars "
                                     "WHERE ticker=ANY(%s)", (list(expected),)).fetchall()
                assert {ticker: (sid, float(price)) for ticker, sid, price in rows} == expected
                assert len(rows) == 4
                resolver = universe.load_resolver(other)
                assert {ticker: resolver.resolve(ticker, DAY) for ticker in expected} == {
                    ticker: sid for ticker, (sid, _) in expected.items()}
    finally:
        server.stop()
