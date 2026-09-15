"""Restated historical ACTIONS through real HTTP adapters and seed capture."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from research.sharadar_replay.model import Corpus, Step
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.runtime import simulated_runtime
from sentinel.feed import (coherence, ingest, seed_capture, sharadar, snapshot_source,
                           source_authority, source_probe)
from test_historical_symbol_identity import HISTORICAL_RENAMES, THROUGH
from test_seed_symbol_transition import OLD_LISTINGS
from test_reused_symbol_identity import REUSED_LISTING, COMPLETED_REUSED_ACTIONS

HISTORICAL_DAY = "2025-07-01"


def nas_provider(*, days=(HISTORICAL_DAY,), fault=None):
    # Synthetic ordinary names meet the unmodified production population floor.
    # Include the reused listing missing from the first two regressions. The
    # final XNDU/to/XNDU completion and all prices are explicitly synthetic.
    listings = [dict(OLD_LISTINGS[0], ticker=f"T{i}", permaticker=i + 1,
                     relatedtickers="", firstpricedate=days[0], lastpricedate=THROUGH)
                for i in range(5603)] + [dict(r) for r in (*OLD_LISTINGS, REUSED_LISTING)]
    labels = [f"T{i}" for i in range(5603)] + ["KRSA", "HLSQ"]
    if fault == "overlapping-reuse":
        listings[-1]["firstpricedate"] = "2018-12-14"
    bars = [dict(ticker=ticker, date=day, open=10, close=10, closeunadj=10,
                 volume=1000, lastupdated="2026-09-13") for day in days for ticker in labels
            if not (ticker == "KRSA" and (
                (fault == "missing-price" and day == days[0])
                or (fault == "missing-last-price" and day == days[-1])))]
    bars.extend(dict(bars[0], ticker="CHACU", date=day) for day in days
                if REUSED_LISTING["firstpricedate"] <= day <= REUSED_LISTING["lastpricedate"])
    if fault == "duplicate-alias":
        bars.append(dict(bars[0], ticker="CYCN"))
    actions = [dict(row) for row in HISTORICAL_RENAMES + COMPLETED_REUSED_ACTIONS
               if not (fault == "missing-older-pair" and row["date"] == "2019-04-02"
                       and row["action"] == "tickerchangeto")]
    provider = Provider(page_size=4000, variation_seed=19)
    provider.advance(Step(
        name="nas_history", at=dt.datetime(2026, 9, 14, 6, tzinfo=dt.timezone.utc),
        through=dt.date.fromisoformat(THROUGH),
        tables={"TICKERS": tuple(listings), "ACTIONS": tuple(actions), "SEP": tuple(bars),
                "SFP": tuple(dict(ticker=ticker, date=day, open=100, close=100,
                                  closeadj=100, closeunadj=100)
                             for day in days for ticker in ("SPY", "BIL"))},
        # This capture fixture asserts source/SQL results directly, not the
        # strategy replay oracle. No production normalizer builds expectations.
        expected=Corpus(bars=(), actions=(), identities=(), spy=(), defensive=())))
    return provider


@pytest.mark.parametrize("fault", [None, "missing-price", "missing-older-pair", "duplicate-alias"])
def test_exported_full_history_covers_the_exact_nas_failed_session(fault):
    provider = nas_provider(fault=fault)
    params = sharadar.date_params(HISTORICAL_DAY, HISTORICAL_DAY)
    actions_params = sharadar.date_params("1900-01-01", THROUGH)
    with simulated_runtime(provider, commit="a" * 40):
        source = seed_capture.ActionsSnapshotSource(snapshot_source.fetch_table)
        tracked, guarded = ingest._seed_source(
            snapshot_source.fetch_table, final_hi=HISTORICAL_DAY,
            update_ceiling="2026-09-14", acquisition_fetch=source)
        with seed_capture.CapturedRows() as captured:
            captured.capture(guarded, sharadar.TICKERS)
            captured.capture(guarded, sharadar.ACTIONS, actions_params)
            exported = list(captured(sharadar.ACTIONS, actions_params))
            assert len(exported) == (13 if fault == "missing-older-pair" else 14)
            assert any(row["date"] == "2019-10-29" and row["ticker"] == "HLSQ"
                       and row["contraticker"] == "PHGE" for row in exported)
            assert all(row["value"] is None for row in exported)  # Real CSV decoding.
            captured.capture(guarded, sharadar.SFP, params)
            if fault:
                error = (source_authority.SourceAuthorityRefused if fault == "duplicate-alias"
                         else coherence.SeedHistoryIncomplete)
                with pytest.raises(error) as caught:
                    captured.capture(guarded, sharadar.SEP, params)
                assert all(key[0] != sharadar.SEP for key in captured.files)
                assert tracked.seed_coverage_evidence is None
                if fault != "duplicate-alias":
                    detail = json.loads(str(caught.value).split(": ", 1)[1])
                    assert detail["session"] == HISTORICAL_DAY
                    assert detail["expected_eligible"] == 5606
                    assert detail["received_eligible"] == 5605
                    assert detail["missing_eligible"] == [{"permaticker": "111101", "ticker": "CYCN"}]
            else:
                captured.capture(guarded, sharadar.SEP, params)
                rows = list(captured(sharadar.SEP, params))
                assert len(rows) == 5606
                assert {r["ticker"] for r in rows if r["ticker"] in {"KRSA", "HLSQ"}} == {"KRSA", "HLSQ"}
                assert all(r["closeunadj"] == 10 for r in rows)
                assert tracked.seed_coverage_evidence["received_eligible_total"] == 5606
                assert tracked.seed_coverage_evidence["missing_eligible_total"] == 0
        assert source.evidence["source_rows"] == len(exported)
    actions_requests = [r for r in provider.transcript if r.get("table") == sharadar.ACTIONS]
    assert len(actions_requests) == 2  # Initial whole export and independent refresh.
    assert all(r["channel"] == "export" for r in actions_requests)
    assert len([r for r in provider.transcript if r["channel"] == "download"]) == 3


def test_cheap_retry_probe_follows_all_historical_labels_over_filtered_http():
    provider = nas_provider()
    with simulated_runtime(provider, commit="a" * 40):
        source_probe.require_recovery_probe(
            {"session": HISTORICAL_DAY, "identities": ["111101", "113467"]}, through=THROUGH)
    requests = [r["query"] for r in provider.transcript if r.get("table") == sharadar.SEP]
    assert len(requests) == 2
    assert requests[0] == requests[1]
    assert requests[0]["date.gte"] == requests[0]["date.lte"] == HISTORICAL_DAY
    assert set(requests[0]["ticker"].split(",")) == {
        "CYCNV", "CYCN", "KRSA", "PHGE", "HLSQ"}
    metadata = [r["query"] for r in provider.transcript if r.get("table") == sharadar.TICKERS]
    assert any("CHACU" in r.get("ticker", "").split(",") for r in metadata)
    assert any("XNDU" in r.get("ticker", "").split(",") for r in metadata)


def test_cheap_retry_cannot_hide_conflicting_context_from_full_projection():
    from sentinel.automation.model import SourceDataPending
    provider = nas_provider(fault="overlapping-reuse")
    with simulated_runtime(provider, commit="a" * 40):
        with pytest.raises(SourceDataPending, match="incomplete or ambiguous"):
            source_probe.require_recovery_probe(
                {"session": HISTORICAL_DAY, "identities": ["111101", "113467"]}, through=THROUGH)


@pytest.mark.parametrize("fault", [None, "missing-older-pair", "missing-last-price"])
def test_production_capture_rebuild_and_publication_with_complete_history(fault, monkeypatch):
    from sentinel.feed import actions, domains, publication, recovery, seed_coherence, store, universe
    from tests.support.postgres import _EphemeralPostgres

    # Four market sessions / 5,605 active identities keep this seed bounded;
    # CHACU is delisted by September. The separate
    # capture regression above uses the NAS's actual failed historical session.
    # Only HTTP transport, clock and test producer identity are substituted;
    # coverage, rebuild, normalization, post-seed proof and publication all run.
    days = ("2026-09-08", "2026-09-09", "2026-09-10", THROUGH)
    provider = nas_provider(days=days, fault=fault)
    server = _EphemeralPostgres()
    try:
        server.start()  # Required integration dependency: unavailable is failure.
        with simulated_runtime(provider, commit="a" * 40), store.connect(server.sync_dsn) as conn:
            store.migrate_schema(conn)
            universe.write_universe(conn, OLD_LISTINGS, days[0])
            old_bars = [dict(ticker=r["ticker"], date=days[0], open=10, close=10,
                             closeunadj=10, volume=1000) for r in OLD_LISTINGS]
            store.write_bars(conn, domains.normalise_sep_rows(
                old_bars, resolve_identity=universe.IdentityResolver(
                    universe.listings_from_rows(OLD_LISTINGS)).resolve))
            baseline = publication.publish(conn, window_start=days[0], window_end=days[0])
            assert universe.load_resolver(conn).resolve("KRSA", days[0]) is None

            # Observe candidate isolation at the real final publication boundary.
            # Forward to the real publisher; no readiness or authority is injected.
            publish = publication.publish
            observed = []
            def observe_publication(connection, **kwargs):
                candidate = universe.load_resolver(connection, include_run_id=kwargs["run_id"])
                assert candidate.resolve("KRSA", days[0]) == "111101"
                with store.connect(server.sync_dsn) as reader:
                    assert publication.require_current(reader).version == baseline.version
                    assert universe.load_resolver(reader).resolve("KRSA", days[0]) is None
                observed.append(kwargs["run_id"])
                return publish(connection, **kwargs)
            monkeypatch.setattr(publication, "publish", observe_publication)

            with store.corpus_write_lock(conn):
                plan = recovery.prepare_full_reseed(conn, date_from=days[0], date_to=THROUGH)
                if fault:
                    with pytest.raises(coherence.SeedHistoryIncomplete, match="CYCN"):
                        ingest._run_seed_generation(conn, recovery_plan=plan,
                            fetch=snapshot_source.fetch_table, final_hi=THROUGH, boundary="2026-09-14")
                    assert not observed
                    assert publication.require_current(conn).version == baseline.version
                    assert conn.execute("SELECT COUNT(*) FROM feed_ingest_runs").fetchone()[0] == 0
                    assert conn.execute("SELECT COUNT(*) FROM sentinel_bars").fetchone()[0] == 2
                    sep_requests = [r["query"] for r in provider.transcript
                                    if r.get("table") == sharadar.SEP]
                    assert sep_requests and all(r["date.gte"] == r["date.lte"]
                                                for r in sep_requests)
                    expected_days = {days[0], THROUGH}
                    assert {r["date.gte"] for r in sep_requests} == expected_days
                    return
                result, _ = ingest._run_seed_generation(conn, recovery_plan=plan,
                    fetch=snapshot_source.fetch_table, final_hi=THROUGH, boundary="2026-09-14")
            assert observed == [result.run_id]
            assert result.rows_dropped == 0
            assert publication.require_current(conn).version > baseline.version
            proof = seed_coherence.require_for_publication(
                conn, run_id=result.run_id, window_start=days[0], window_end=THROUGH)
            assert proof["phase"] == "complete"
            assert proof["normalized_source"] == proof["normalized_local"]
        # A new connection must derive the same identities from durable rows.
        with store.connect(server.sync_dsn) as conn:
            resolver = universe.load_resolver(conn)
            for sid, old, new in (("111101", "CYCN", "KRSA"), ("113467", "PHGE", "HLSQ")):
                assert resolver.resolve(new, days[0]) == sid
                assert resolver.ticker_for_security(sid, "2025-07-01") == old
                assert resolver.ticker_for_security(sid, THROUGH) == new
                rows = conn.execute("SELECT session,ticker,close_unadjusted FROM sentinel_bars "
                                    "WHERE security_id=%s ORDER BY session", (sid,)).fetchall()
                assert [(str(day), ticker, float(close)) for day, ticker, close in rows] == [
                    (day, new, 10.0) for day in days]
            assert resolver.resolve("CHACU", "2025-07-01") == "644444"
            assert resolver.resolve("CHAC", "2025-07-01") != "113467"
            assert len(actions.active_rows(conn, start="1900-01-01", end=THROUGH)) == 14
            assert conn.execute("SELECT COUNT(*) FROM sentinel_bars").fetchone()[0] == 4 * 5605
    finally:
        server.stop()
