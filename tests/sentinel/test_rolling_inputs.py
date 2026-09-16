"""Cold-start material with no prior GO, checkpoint or legacy corpus."""
from __future__ import annotations

import pytest

from sentinel.core import rolling_inputs as inputs
from sentinel.feed import rolling_store, source_aliases
from sentinel.feed.rolling_builder import NORMALIZATION_VERSION
from sentinel.feed.rolling_contract import (
    CanonicalBar, CanonicalBenchmark, PriceWindow, RestartRequirement, digest,
)
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


def candidate(conn, *, actions=(), reference_change=None, proof_change=None, bar_change=None):
    window = PriceWindow.through("2026-09-14")
    tickers = [{"table": "SEP", "permaticker": str(i), "ticker": f"S{i:02}",
                "category": "Domestic Common Stock", "sector": "Technology",
                "relatedtickers": None, "firstpricedate": str(window.start),
                "lastpricedate": str(window.end), "isdelisted": "N"}
               for i in range(1, 26)]
    reference = {"schema": "sentinel.rolling-sharadar-references/1",
                 "tickers": tickers, "actions": list(actions)}
    if reference_change:
        reference_change(reference)
    cid = rolling_store.begin(
        conn, window=window, reference_sha256=rolling_store.put_evidence(conn, reference),
        source_evidence_sha256=rolling_store.put_evidence(conn, {"fixture": True}),
        expected_publication_version=None, dependencies_sha256=digest({}))
    bars = [CanonicalBar(
        session=day, security_id=str(i), ticker=f"S{i:02}",
        close_signal=(50 + index * .2 + i * .03),
        close_unadjusted=(50 + index * .2 + i * .03) * 2,
        open_unadjusted=(50 + index * .2 + i * .03) * 1.9,
        volume=1_000_000, split_ratio=1, dividend_per_share=0)
        for index, day in enumerate(window.sessions) for i in range(1, 26)]
    if bar_change:
        bars = bar_change(bars, window)
    rolling_store.write_bars(conn, cid, bars)
    rolling_store.write_benchmarks(conn, cid, [CanonicalBenchmark(
        session=day, spy_total_return=600 + i, bil_open_signal=91,
        bil_close_signal=92, bil_close_adjusted=95, bil_close_unadjusted=94)
        for i, day in enumerate(window.sessions)])
    manifest = rolling_store.seal(
        conn, cid, expected_keys=sorted((str(b.session), b.security_id) for b in bars),
        normalization_version=NORMALIZATION_VERSION, requirements=RestartRequirement())
    proof = {"schema": "sentinel.rolling-comparison-validation/1", "scope": "COMPARISON_ONLY",
             "snapshot_id": manifest.snapshot_id, "alias_rejections": source_aliases.evidence()}
    if proof_change:
        proof_change(proof)
    sha = rolling_store.put_evidence(conn, proof)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_snapshot_validations VALUES (%s,%s)", (cid, sha))
    return cid, manifest.snapshot_id


def action(*, ticker="S01", day="2026-09-14", kind="delisted", value=None, child=None):
    return {"date": day, "ticker": ticker, "action": kind, "value": value,
            "name": "fixture", "contraticker": child, "contraname": None}


def load(conn, key):
    return inputs.cold_start_inputs(conn, candidate_id=key[0], snapshot_id=key[1])


def refs(conn, key):
    return inputs.SnapshotReferences(conn, candidate_id=key[0], snapshot_id=key[1])


def test_empty_legacy_corpus_forms_canonical_initial_pending_book(conn):
    from sentinel.controller.machine import Controller
    from sentinel.core.kernel import advance_session
    from sentinel.core.production import warm_session_state
    from sentinel.core.session import DefensiveBar, PublishedSession, SessionState
    from sentinel.strategy import production_strategy

    key = candidate(conn, actions=[action()])
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
    material = load(conn, key)
    controller, identity = production_strategy()
    fresh = SessionState.fresh(starting_cash=100_000, controller=Controller(controller),
                               strategy_identity=identity)
    # This is a synthetic test publication. The adapter itself cannot assign one.
    warmed = warm_session_state(fresh, material.warmup, publication_version=17,
                                 prospective_concordance_witness=True)
    assert warmed.wealth_core["cash"] == 100_000
    assert not warmed.wealth_core["episodes"] and not warmed.pending
    assert not warmed.ledger["events"] and warmed.last_processed_session is None
    assert material.warmup.metadata_timeline is None
    assert len(material.warmup.sessions) == 252
    assert not hasattr(material, "data_version")
    assert len(material.benchmarks) == 254
    last = material.benchmarks[-1]
    assert material.bars[0].raw_close != material.bars[0].signal_close
    assert material.warmup.median5_spy_closes[material.warmup.sessions[-1]] == 898
    assert last.spy_total_return == 899 and last.bil_close_adjusted == 95

    def defensive(row):
        return DefensiveBar(str(row.session), "SENTINEL:BIL", "BIL", row.bil_open_signal,
                            row.bil_close_signal, row.bil_close_adjusted, row.bil_close_unadjusted)

    axis = tuple(str(row.session) for row in material.benchmarks)
    published = PublishedSession(
        session=material.session, data_version=17, bars=material.bars, meta=material.meta,
        sectors=material.sectors, spy_closeadj=tuple(row.spy_total_return for row in material.benchmarks),
        spy_sessions=axis, spy_expected_sessions=axis, terminal_events=material.terminal_events,
        defensive_bar=defensive(last), defensive_previous_bar=defensive(material.benchmarks[-2]),
        spinoff_distributions=material.spinoff_distributions)
    result = advance_session(warmed, published, controller_config=controller, strategy_identity=identity)
    assert result.pending, "a warmup that cannot form initial instructions is not a cold-start witness"
    assert all(order["signal_session"] == material.session for order in result.pending)
    assert all(order["security_id"] != "1" for order in result.pending)
    assert result.wealth_core["cash"] == 100_000 and not result.wealth_core["episodes"]
    assert result.last_processed_session == material.session
    assert not result.ledger["events"]
    assert not fresh.feed["series"] and not warmed.pending
    for table in ("sentinel_bars", "sentinel_universe", "sentinel_actions",
                  "sentinel_corpus_publications", "feed_universe_current"):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM " + table)
            assert cur.fetchone()[0] == 0, table


def test_independent_reference_generations_and_full_history(conn):
    old = candidate(conn, actions=[action(day="2000-01-03", kind="relation")])
    new = candidate(conn, actions=[action(kind="spinoff", child="S02", value="500")],
                    reference_change=lambda r: r["tickers"][0].update(sector="Industrials", relatedtickers="S01 S02"))
    first, second = load(conn, old), load(conn, new)
    assert first.sectors["1"] == "Technology" and second.sectors["1"] == "Industrials"
    assert first.meta["1"].related_tickers == ()
    assert second.meta["1"].related_tickers == ("S01", "S02")
    assert not first.spinoff_distributions
    event, = second.spinoff_distributions
    assert event.parent_security_id == "1" and event.child_security_id == "2"
    assert event.child_shares_per_parent is None and event.child_price is None
    assert event.value_evidence == "500"
    assert len(refs(conn, old).actions) == 1  # not clipped to 300 price sessions
    assert load(conn, old).reference_sha256 == first.reference_sha256


def test_terminal_siblings_and_weekend_dates_use_canonical_coalescer(conn):
    rows = [action(day="2026-09-12", kind="acquisitionby", value="100", child="S02"),
            action(day="2026-09-13"), action(day="2026-09-13")]
    key = candidate(conn, actions=rows)
    result = refs(conn, key).terminals(start="2026-09-14", end="2026-09-14")
    assert result.discovered == 2 and len(result.events) == 1 and len(result.collapsed) == 1
    assert result.conservation_holds() and result.normalized_stream_holds()
    assert result.events[0].session == "2026-09-14"
    assert result.events[0].security_id == "1"
    assert len(load(conn, key).terminal_events) == 1


def test_unresolved_terminal_cannot_be_excluded_by_bounded_price_absence(conn):
    key = candidate(conn, actions=[action(ticker="UNKNOWN")])
    with pytest.raises(inputs.RollingInputsRefused, match="UNRESOLVED_SNAPSHOT_TERMINALS"):
        load(conn, key)


@pytest.mark.parametrize("field,value", [("schema", "future/1"), ("snapshot_id", digest("other"))],
                         ids=["schema", "snapshot"])
def test_reference_validation_must_name_this_snapshot(conn, field, value):
    key = candidate(conn, proof_change=lambda p: p.update({field: value}))
    with pytest.raises(inputs.RollingInputsRefused, match="UNBOUND_REFERENCE_VALIDATION"):
        load(conn, key)


def test_wrong_snapshot_and_unknown_reference_schema_refuse(conn):
    key = candidate(conn, reference_change=lambda r: r.update(schema="unknown"))
    with pytest.raises(inputs.RollingInputsRefused, match="SNAPSHOT_ID_MISMATCH"):
        refs(conn, (key[0], digest("other")))
    with pytest.raises(inputs.RollingInputsRefused, match="UNSUPPORTED_REFERENCE_BUNDLE"):
        refs(conn, key)


def test_conflicting_metadata_does_not_depend_on_source_order(conn):
    def conflicting(r):
        r["tickers"].append({**r["tickers"][0], "ticker": "OLD", "sector": "Industrials",
                             "lastpricedate": r["tickers"][0]["firstpricedate"]})
    key = candidate(conn, reference_change=conflicting)
    with pytest.raises(inputs.RollingInputsRefused, match="CONFLICTING_REFERENCE_METADATA"):
        load(conn, key)


def test_bar_identity_must_resolve_in_same_reference_generation(conn):
    key = candidate(conn, reference_change=lambda r: r["tickers"][0].update(permaticker="different"))
    with pytest.raises(inputs.RollingInputsRefused, match="SNAPSHOT_BAR_REFERENCE_MISMATCH"):
        load(conn, key)


def test_returning_security_does_not_get_an_invented_first_observation(conn):
    def gap(bars, window):
        return [bar for bar in bars if bar.security_id != "1" or bar.session == window.end]
    key = candidate(conn, bar_change=gap)
    with pytest.raises(inputs.RollingInputsRefused, match="RETURNING_SECURITY_ANCHOR_REQUIRED"):
        load(conn, key)


def test_genuine_first_day_listing_remains_eligible_for_later_feature_formation(conn):
    key = candidate(conn, reference_change=lambda r: r["tickers"][0].update(firstpricedate="2026-09-14"),
                    bar_change=lambda rows, w: [b for b in rows if b.security_id != "1" or b.session == w.end])
    material = load(conn, key)
    assert "1" in {bar.security_id for bar in material.bars}
    assert all(bar.security_id != "1" for rows in material.warmup.bars_by_session.values() for bar in rows)


def test_ambiguous_active_symbol_refuses_even_when_metadata_agrees(conn):
    key = candidate(conn, reference_change=lambda r: r["tickers"].append(
        {**r["tickers"][0], "ticker": "OTHER"}))
    with pytest.raises(inputs.RollingInputsRefused, match="AMBIGUOUS_REFERENCE_SYMBOL"):
        load(conn, key)


def test_reference_actions_cannot_claim_future_information(conn):
    key = candidate(conn, actions=[action(day="2026-09-15")])
    with pytest.raises(inputs.RollingInputsRefused, match="ACTION_OUTSIDE_REFERENCE_INTERVAL"):
        refs(conn, key)


def test_rename_uses_same_dated_projection_as_price_normalization(conn):
    def rename(r):
        r["tickers"][0]["ticker"] = "NEW"
    key = candidate(conn, reference_change=rename,
                    actions=[action(ticker="NEW", day="2026-09-01", kind="tickerchangefrom", child="S01"),
                             action(ticker="NEW", day="2026-09-01", kind="tickerchangeto", child="NEW")],
                    bar_change=lambda rows, w: [b.model_copy(update={"ticker": "NEW"})
                        if b.security_id == "1" and str(b.session) >= "2026-09-01" else b for b in rows])
    material = load(conn, key)
    assert material.meta["1"].ticker == "NEW"
    reader = refs(conn, key)
    assert reader.resolver.resolve("S01", "2026-08-31") == "1"
    assert reader.resolver.resolve("NEW", "2026-09-01") == "1"


def test_source_bundle_feeds_adapter_without_legacy_publication(conn, monkeypatch):
    # Exercise the real direct builder and source normalization, not only the
    # small manually sealed candidates used by guard tests.
    from tests.sentinel.test_rolling_snapshot_publisher import source, enqueue
    from sentinel.feed import rolling_publisher
    source.__wrapped__(monkeypatch)
    job = enqueue(conn)
    receipt = rolling_publisher.prepare(conn, job)
    material = load(conn, (receipt["candidate_id"], receipt["snapshot_id"]))
    assert material.meta["1"].ticker == "AAA"
    assert material.meta["2"].ticker == "BBB"
    assert material.bars[0].raw_close == 100
    assert material.bars[0].signal_close == 50


def test_cold_start_verifies_restored_payload_not_only_manifest(conn):
    key = candidate(conn)
    with conn.cursor() as cur:
        # Model restore corruption; normal database writes cannot change a seal.
        cur.execute("ALTER TABLE sentinel_snapshot_bars DISABLE TRIGGER USER")
        cur.execute("UPDATE sentinel_snapshot_bars SET close_signal=close_signal+1 WHERE candidate_id=%s", (key[0],))
        cur.execute("ALTER TABLE sentinel_snapshot_bars ENABLE TRIGGER USER")
    with pytest.raises(rolling_store.SnapshotStorageRefused, match="content differs"):
        load(conn, key)
