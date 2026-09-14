"""Actual NAS rename shapes through source capture and publication scopes."""
from __future__ import annotations

import copy

import pytest

from sentinel.feed import (authority, coherence, seed_capture, sharadar,
                           source_authority, source_probe, symbol_identity)
from test_seed_symbol_transition import OLD_LISTINGS, RESTATED_BARS

THROUGH = "2026-09-11"
RENAMES = [
    {"date": day, "action": kind, "ticker": new, "name": name,
     "value": None, "contraticker": contra, "contraname": "N/A"}
    for day, old, new, name in (
        ("2026-09-09", "CYCN", "KRSA", "KORSANA BIOSCIENCES INC"),
        ("2026-09-11", "PHGE", "HLSQ", "TESSERA DEFENSE AND HOMELAND SECURITY INC"))
    for kind, contra in (("tickerchangeto", new), ("tickerchangefrom", old))]


def test_nas_restated_actions_join_identity_and_keep_transport_labels_dated():
    before = copy.deepcopy((OLD_LISTINGS, RENAMES, RESTATED_BARS))
    projection = symbol_identity.SymbolProjection(OLD_LISTINGS, RENAMES, through=THROUGH)
    resolver = projection.resolver()
    for old, bar in zip(OLD_LISTINGS, RESTATED_BARS):
        for day in ("2026-09-01", "2026-09-08", THROUGH):
            assert resolver.resolve(bar["ticker"], day) == str(old["permaticker"])
        assert resolver.ticker_for_security(str(old["permaticker"]), "2026-09-08") == old["ticker"]
        assert resolver.ticker_for_security(str(old["permaticker"]), THROUGH) == bar["ticker"]
    assert len(projection.evidence["renames"]) == 2
    assert all(len(item["source_ids"]) == 2 for item in projection.evidence["renames"])
    assert projection.digest("a" * 64) != "a" * 64
    assert (OLD_LISTINGS, RENAMES, RESTATED_BARS) == before


@pytest.mark.parametrize("fault", ["missing-to", "missing-from", "different-date", "relation",
                                  "conflicting-id", "delisted", "gap", "branch", "to-branch", "cycle"])
def test_unproven_identity_never_gets_an_alias(fault):
    rows = [dict(OLD_LISTINGS[0])]
    actions = copy.deepcopy(RENAMES[:2])
    if fault == "missing-to":
        actions.pop(0)
    elif fault == "missing-from":
        actions.pop(1)
    elif fault == "different-date":
        actions[0]["date"] = "2026-09-10"
    elif fault == "relation":
        actions[1]["action"] = "relation"
    elif fault == "conflicting-id":
        rows.append(dict(rows[0], ticker="KRSA", permaticker=999999))
    elif fault == "delisted":
        rows[0]["isdelisted"] = "Y"
    elif fault == "gap":
        rows[0]["lastpricedate"] = "2026-09-04"
    elif fault == "branch":
        actions.append(dict(actions[1], ticker="OTHER"))
    elif fault == "to-branch":
        actions.append(dict(actions[0], ticker="CYCN", contraticker="OTHER"))
    elif fault == "cycle":
        actions.extend([dict(actions[0], date="2026-09-10", ticker="CYCN", contraticker="CYCN"),
                        dict(actions[1], date="2026-09-10", ticker="CYCN", contraticker="KRSA")])
    projected = symbol_identity.SymbolProjection(rows, actions, through=THROUGH)
    assert projected.chains == {}
    assert projected.resolver().resolve("KRSA", "2026-09-08") != "111101"


@pytest.mark.parametrize("fault", [None, "missing-price", "moving-actions", "duplicate-alias"])
def test_rename_join_obeys_actual_seed_capture_gates(fault):
    days = ["2026-09-08", "2026-09-09", "2026-09-10", THROUGH]
    rows = [dict(OLD_LISTINGS[0], ticker=f"T{i}", permaticker=str(i),
                 firstpricedate=days[0], lastpricedate=THROUGH) for i in range(5604)]
    listings = rows + [dict(row) for row in OLD_LISTINGS]
    bars = [dict(RESTATED_BARS[0], ticker=row["ticker"], date=day)
            for day in days for row in rows]
    bars.extend(dict(row, date=day) for day in days for row in RESTATED_BARS
                if not (fault == "missing-price" and day == THROUGH and row["ticker"] == "KRSA"))
    if fault == "duplicate-alias":
        bars.append(dict(RESTATED_BARS[0], ticker="CYCN"))
    calls = []

    def fetch(table, params=None):
        calls.append(table)
        if table == sharadar.ACTIONS:
            return RENAMES[:-1] if fault == "moving-actions" and calls.count(table) == 2 else RENAMES
        return {sharadar.TICKERS: listings, sharadar.SEP: bars,
                sharadar.SFP: [{"ticker": "SPY", "date": days[0], "closeadj": 600}]}[table]

    guarded = source_authority.StableSharadarFetch(fetch, seed_mode=True)
    params = sharadar.date_params(days[0], THROUGH)
    with seed_capture.CapturedRows() as captured:
        captured.capture(guarded, sharadar.TICKERS)
        captured.capture(guarded, sharadar.ACTIONS, params)
        captured.capture(guarded, sharadar.SFP, params)
        if fault:
            with pytest.raises((coherence.SeedHistoryIncomplete,
                                source_authority.SourceAuthorityRefused,
                                authority.VendorPublicationUnstable)):
                captured.capture(guarded, sharadar.SEP, params)
            assert guarded.seed_coverage_evidence is None
        else:
            captured.capture(guarded, sharadar.SEP, params)
            assert list(captured(sharadar.SEP, params)) == bars
            assert guarded.seed_coverage_evidence["received_eligible_total"] == 4 * 5606


def test_small_probe_follows_restated_actions_but_never_publishes():
    calls = []
    def fetch(table, params):
        calls.append((table, params))
        if table == sharadar.TICKERS:
            return OLD_LISTINGS
        if table == sharadar.ACTIONS:
            field = "ticker" if "ticker" in params else "contraticker"
            wanted = set(params[field].split(","))
            return [row for row in RENAMES if row[field] in wanted]
        assert table == sharadar.SEP
        assert params["date.gte"] == params["date.lte"] == "2026-09-08"
        return RESTATED_BARS
    source_probe.require_recovery_probe(
        {"session": "2026-09-08", "identities": ["111101", "113467"]},
        through=THROUGH, fetch=fetch)
    assert sum(table == sharadar.SEP for table, _ in calls) == 1
    assert all(set(params["ticker"].split(",")) <= {"CYCN", "KRSA", "PHGE", "HLSQ"}
               for table, params in calls if "ticker" in params)


def test_published_resolver_cannot_consume_a_candidate_rename():
    from sentinel.feed import actions, domains, publication, store, universe
    from tests.support.postgres import _EphemeralPostgres
    server = _EphemeralPostgres()
    try:
        server.start()
        with store.connect(server.sync_dsn) as conn:
            store.migrate_schema(conn)
            universe.write_universe(conn, list(OLD_LISTINGS), "2026-09-08")
            baseline = publication.publish(conn, window_start="2026-09-08", window_end="2026-09-08")
            symbol_identity.require_published_history(conn, RENAMES, before="2026-09-01")
            with pytest.raises(universe.HistoricalIdentityMutation, match="historical ACTIONS"):
                symbol_identity.require_published_history(conn, RENAMES, before="2026-09-14")
            with store.corpus_write_lock(conn):
                run = store.IngestRun(conn, "seed", date_from="2026-09-01", date_to=THROUGH)
                store.write_actions(conn, RENAMES, run_id=run.progress.run_id,
                                    window_start="2026-09-08", window_end=THROUGH)
                candidate = universe.load_resolver(conn, include_run_id=run.progress.run_id)
                assert candidate.resolve("KRSA", "2026-09-08") == "111101"
                assert universe.load_resolver(conn).resolve("KRSA", "2026-09-08") is None
                assert publication.require_current(conn).version == baseline.version
                raw = [dict(row, date=day) for day in ("2026-09-01", THROUGH)
                       for row in RESTATED_BARS]
                store.write_bars(conn, domains.normalise_sep_rows(raw, resolve_identity=candidate.resolve),
                                 run_id=run.progress.run_id, require_lock=True)
                run.finish("success")
                publication.publish(conn, run_id=run.progress.run_id,
                                    window_start="2026-09-01", window_end=THROUGH)
            # Reload from another connection to prove publication/restart scope.
        with store.connect(server.sync_dsn) as conn:
            resolved = universe.load_resolver(conn)
            assert resolved.resolve("KRSA", THROUGH) == "111101"
            assert resolved.resolve("HLSQ", THROUGH) == "113467"
            assert resolved.ticker_for_security("111101", THROUGH) == "KRSA"
            assert len(actions.active_rows(conn, start="2026-09-08", end=THROUGH)) == 4
            symbol_identity.require_published_history(conn, RENAMES, before="2026-09-14")
            with pytest.raises(universe.HistoricalIdentityMutation, match="historical ACTIONS"):
                symbol_identity.require_published_history(conn, RENAMES[:-1], before="2026-09-14")
            # A later metadata rebuild cannot delete a renamed price merely
            # because its raw predecessor's endpoint remains stale.
            from sentinel.feed import identity_rebuild, recovery
            current = publication.require_current(conn).version
            with store.corpus_write_lock(conn):
                plan = identity_rebuild.prepare(conn, date_from="2026-09-01", date_to=THROUGH,
                                                observed_on="2026-09-14")
                replacement = store.IngestRun(conn, "seed", date_from="2026-09-01", date_to=THROUGH)
                identity_rebuild.record_plan(conn, run_id=replacement.progress.run_id, plan=plan)
                corrected = [dict(row) for row in OLD_LISTINGS]
                corrected[0]["firstpricedate"] = "2026-09-08"
                candidate = identity_rebuild.verify_candidate(
                    conn, run_id=replacement.progress.run_id, plan=plan, rows=corrected)
                with pytest.raises(recovery.PublicationRecoveryRefused, match="failed to replay"):
                    identity_rebuild.publish_completed_run(
                        conn, run=replacement, rows=candidate, plan=plan)
            assert publication.require_current(conn).version == current
            assert conn.execute("SELECT COUNT(*) FROM sentinel_bars").fetchone()[0] == 4
    finally:
        server.stop()


@pytest.mark.parametrize("missing", [False, True])
def test_daily_overlap_cannot_forget_an_older_unresolved_rename(missing):
    day = "2026-09-25"
    ordinary = [dict(OLD_LISTINGS[0], ticker=f"T{i}", permaticker=str(i),
                     lastpricedate=day) for i in range(5604)]
    rows = ordinary + list(OLD_LISTINGS)
    bars = [dict(RESTATED_BARS[0], ticker=row["ticker"], date=day, lastupdated=day)
            for row in ordinary]
    if not missing:
        bars.extend(dict(row, date=day, lastupdated=day) for row in RESTATED_BARS)

    def fetch(table, params=None):
        if table == sharadar.ACTIONS:
            return [r for r in RENAMES if params["date.gte"] <= r["date"] <= params["date.lte"]]
        return {sharadar.TICKERS: rows, sharadar.SEP: bars,
                sharadar.SFP: [{"ticker": "SPY", "date": day, "closeadj": 600}]}[table]

    guarded = source_authority.StableSharadarFetch(
        fetch, after_session="2026-09-24", identity_actions=RENAMES,
        identity_through=day, identity_fetch=fetch)
    list(guarded(sharadar.TICKERS))
    list(guarded(sharadar.ACTIONS, sharadar.date_params("2026-09-14", day)))
    list(guarded(sharadar.SFP, sharadar.date_params(day, day)))
    if missing:
        with pytest.raises(coherence.SepListingPopulationIncomplete, match="renamed identities"):
            list(guarded(sharadar.SEP, sharadar.date_params(day, day)))
    else:
        assert list(guarded(sharadar.SEP, sharadar.date_params(day, day))) == bars


def test_nas_split_units_still_use_the_existing_independent_price_check():
    from sentinel.feed import actions_map, domains
    actions = [dict(RENAMES[0], action="split", date="2026-09-09", value=0.14286),
               dict(RENAMES[2], action="split", date="2026-09-09", value=0.1)]
    after = [dict(RESTATED_BARS[0], date="2026-09-09", open=21.2, close=26.2, closeunadj=26.2),
             dict(RESTATED_BARS[1], date="2026-09-09", open=1.6, close=1.62, closeunadj=1.62)]
    resolver = symbol_identity.SymbolProjection(OLD_LISTINGS, RENAMES, through=THROUGH).resolver()
    splits, ambiguous = actions_map.split_rows_from_actions(actions, ["2026-09-08", "2026-09-09"])
    assert not ambiguous
    report = domains.NormalisationReport()
    normalized = list(domains.normalise_sep_rows(
        sorted([*RESTATED_BARS, *after], key=lambda r: (r["date"], r["ticker"])),
        resolve_identity=resolver.resolve, authoritative_splits=splits, report=report))
    ratios = {row.vendor.ticker: row.vendor.split_ratio for row in normalized
              if row.vendor.session == "2026-09-09"}
    assert ratios == {"KRSA": 1 / 7, "HLSQ": 0.1}
    assert actions[0]["value"] == 0.14286
