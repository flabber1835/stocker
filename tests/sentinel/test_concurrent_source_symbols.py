"""Observed unit/share collisions must not be repaired by choosing a price."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import source_diagnostic
from sentinel.feed import seed_capture, sharadar, source_authority, source_probe, symbol_identity
from test_go_preparation_identity_reason_codes import source_final, validate_entry

DAY = "2026-09-11"
OBSERVED = json.loads((Path(__file__).parent / "fixtures/concurrent_sep_symbols.json").read_text())


def source(*, healed=False, omit_symbol=None):
    data = copy.deepcopy(OBSERVED)
    if healed:
        # Explicitly synthetic provider healing, never asserted as a real observation.
        for index, old in enumerate(tuple(data["tickers"])):
            data["tickers"].append(dict(old, ticker=old["ticker"][:-1],
                permaticker=900000001 + index, firstpricedate=DAY))
    calls = []
    def fetch(table, params=None):
        params = params or {}
        calls.append((table, dict(params)))
        rows = copy.deepcopy(data[{sharadar.TICKERS: "tickers", sharadar.ACTIONS: "actions", sharadar.SEP: "sep"}[table]])
        for field in ("ticker", "permaticker", "contraticker", "action"):
            if field in params:
                wanted = set(params[field].split(","))
                rows = [r for r in rows if str(r.get(field)) in wanted]
        if table == sharadar.SEP and omit_symbol:
            rows = [r for r in rows if r["ticker"] != omit_symbol]
        return rows
    return data, fetch, calls


def failure(*, reverse=False):
    identity = symbol_identity.SymbolProjection(OBSERVED["tickers"], OBSERVED["actions"], through=DAY)
    coverage = source_authority.SeedCoverageAccumulator(
        source_authority.SeedListingProjection((*identity.rows, *identity.alias_rows), source_digest="a" * 64),
        identity.resolver().resolve)
    try:
        for row in reversed(OBSERVED["sep"]) if reverse else OBSERVED["sep"]:
            coverage.add(row)
        with pytest.raises(source_authority.SeedIdentityCollision) as caught:
            coverage.require_complete(date_from=DAY, date_to=DAY)
        return caught.value
    finally:
        coverage.close()


def test_all_observed_collisions_and_prices_survive_go_and_are_order_independent():
    exc = failure()
    assert str(exc) == str(failure(reverse=True))
    value = source_diagnostic.coverage_diagnostic(str(exc))
    assert value["identity_collision_total"] == 2
    assert value["collision_source_rows_total"] == 4
    groups = {r["permaticker"]: r for r in value["identity_collisions"]}
    assert set(groups) == {"6399775", "6401005"}
    for sid, old, new in (("6399775", "BRTMU", "BRTM"), ("6401005", "OCLTU", "OCLT")):
        group = groups[sid]
        assert group["source_tickers"] == [new, old]
        assert {r["closeunadj"] for r in group["source_bars"]} == (
            {"9.98", "9.87"} if sid == "6399775" else {"10.02", "9.9"})
        assert {r["ticker"] for r in group["native_listings"]} == {old}
        assert new in {r["ticker"] for r in group["derived_aliases"]}
        assert group["rename_events"]
    for code in (source_final._PREPARATION_CODE, validate_entry._RECOVERY_PREPARATION_CODE):
        namespace = {}
        exec(code.split("\ndef emit_failure", 1)[0], namespace)
        assert namespace["reason_code"]("DAILY_CATCHUP", exc) == "SOURCE_IDENTITY_COLLISION"
        diagnostic = namespace["failure_detail"](exc)
        assert len(diagnostic["detail"]) <= 420
        assert source_diagnostic.collect_source_coverage(
            source_diagnostic.FAILURE_MARKER + json.dumps(diagnostic)) == value


def test_early_refusal_does_not_request_actions_export_or_mutate(monkeypatch):
    data, fetch, calls = source()
    guarded = source_authority.StableSharadarFetch(fetch, seed_mode=True)
    # TICKERS are the already captured exact source rows; isolate from unrelated
    # universe population floors. The real wrappers execute all sample requests.
    class CapturedGuard:
        def __call__(self, table, params=None):
            assert table == sharadar.TICKERS
            return data["tickers"]
        preflight_seed_identity = guarded.preflight_seed_identity
    from sentinel.feed import ingest
    monkeypatch.setattr(ingest, "_seed_source", lambda *a, **kw: (None, CapturedGuard()))
    monkeypatch.setattr(ingest.identity_refresh, "assert_candidate_history_safe",
                        lambda *a, **kw: pytest.fail("must refuse before database preflight"))
    with pytest.raises(source_authority.SeedIdentityCollision) as caught:
        seed_capture.run_generation(None, recovery_plan=SimpleNamespace(date_from=DAY, date_to=DAY),
                                    fetch=fetch, final_hi=DAY, boundary="2026-09-14")
    assert source_diagnostic.coverage_diagnostic(str(caught.value))["identity_collision_total"] == 2
    assert calls == [(sharadar.ACTIONS, {"action": "tickerchangeto,tickerchangefrom",
                     "date.gte": "1900-01-01", "date.lte": DAY})] * 2 + [
                     (sharadar.SEP, sharadar.date_params(DAY, DAY))] * 2
    assert guarded.seed_coverage_evidence is None


def test_worker_wait_keeps_all_symbols_and_corrected_metadata_permits_full_retry():
    from sentinel import automation_runtime
    from sentinel.automation.model import SourceDataPending
    exc = failure()
    translated = automation_runtime.classify_dependency_failure(exc)
    assert isinstance(translated, SourceDataPending)
    hint = source_probe.coverage_hint(str(translated))
    assert hint == {"session": DAY, "identities": ["6399775", "6401005"],
                    "symbols": ["BRTM", "BRTMU", "OCLT", "OCLTU"]}
    for healed in (False, True):
        data, fetch, calls = source(healed=healed)
        if healed:
            source_probe.require_recovery_probe(hint, through=DAY, fetch=fetch)
        else:
            with pytest.raises(SourceDataPending, match="incomplete or ambiguous"):
                source_probe.require_recovery_probe(hint, through=DAY, fetch=fetch)
        sep = [params for table, params in calls if table == sharadar.SEP]
        assert len(sep) == 2
        assert all(set(p["ticker"].split(",")) == set(hint["symbols"]) for p in sep)


def test_corrected_metadata_keeps_four_distinct_prices_and_missing_bar_still_refuses():
    data, fetch, _ = source(healed=True)
    identity = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY)
    resolver = identity.resolver()
    expected = {"OCLTU": "6401005", "BRTMU": "6399775", "OCLT": "900000001", "BRTM": "900000002"}
    assert {row["ticker"]: resolver.resolve(row["ticker"], DAY) for row in data["sep"]} == expected
    guarded = source_authority.StableSharadarFetch(fetch, seed_mode=True)
    guarded.preflight_seed_identity(tickers=data["tickers"], fetch=fetch, date_from=DAY, date_to=DAY)
    from sentinel.feed import coherence
    _, missing_fetch, _ = source(healed=True, omit_symbol="OCLT")
    missing = source_authority.StableSharadarFetch(missing_fetch, seed_mode=True)
    with pytest.raises(coherence.SeedHistoryIncomplete, match="900000001"):
        missing.preflight_seed_identity(tickers=data["tickers"], fetch=missing_fetch, date_from=DAY, date_to=DAY)


@pytest.mark.parametrize("bad_price", [0, -1, None, "NaN", "Infinity"])
def test_probe_cannot_hide_a_bad_collision_row(bad_price):
    from sentinel.automation.model import SourceDataPending
    from sentinel.feed.authority import FrontierDomainIncomplete
    data, fetch, _ = source(healed=True)
    data["sep"][1]["closeunadj"] = bad_price
    with pytest.raises((SourceDataPending, FrontierDomainIncomplete)):
        source_probe.require_recovery_probe(source_probe.coverage_hint(str(failure())),
                                            through=DAY, fetch=fetch)


def test_probe_cannot_hide_a_row_from_another_session():
    from sentinel.feed.session_envelope import SourceSessionEnvelopeViolation
    data, fetch, _ = source(healed=True)
    data["sep"][1]["date"] = "2026-09-10"
    with pytest.raises(SourceSessionEnvelopeViolation, match="session_before_request"):
        source_probe.require_recovery_probe(source_probe.coverage_hint(str(failure())),
                                            through=DAY, fetch=fetch)


def test_probe_checks_each_price_even_when_population_domain_floor_passes():
    from sentinel.automation.model import SourceDataPending
    data, fetch, _ = source(healed=True)
    hint = source_probe.coverage_hint(str(failure()))
    for index in range(10):
        ticker, sid = "EXTRA" + str(index), str(910000000 + index)
        data["tickers"].append(dict(data["tickers"][0], ticker=ticker, permaticker=sid))
        data["sep"].append(dict(data["sep"][0], ticker=ticker))
        hint["identities"].append(sid)
        hint["symbols"].append(ticker)
    data["sep"][1]["closeunadj"] = 0  # 13/14 rows still pass the 90% domain floor.
    with pytest.raises(SourceDataPending, match="invalid price row"):
        source_probe.require_recovery_probe(hint, through=DAY, fetch=fetch)


def test_probe_stops_an_oversized_response_before_stability_materialization():
    from sentinel.automation.model import SourceDataPending
    _, fetch, _ = source(healed=True)
    consumed = []
    def oversized(table, params=None):
        if table != sharadar.SEP:
            return fetch(table, params)
        def rows():
            for index in range(1000):
                consumed.append(index)
                yield dict(OBSERVED["sep"][0], ticker="EXTRA" + str(index))
        return rows()
    with pytest.raises(SourceDataPending, match="exceeds its row bound"):
        source_probe.require_recovery_probe(source_probe.coverage_hint(str(failure())),
                                            through=DAY, fetch=oversized)
    assert len(consumed) == 65


def test_collision_witness_bound_keeps_complete_totals_and_rejects_partial_probe():
    identity = symbol_identity.SymbolProjection(OBSERVED["tickers"], OBSERVED["actions"], through=DAY)
    coverage = source_authority.SeedCoverageAccumulator(
        source_authority.SeedListingProjection((*identity.rows, *identity.alias_rows), source_digest="a" * 64),
        identity.resolver().resolve)
    try:
        # Exercise the disk witness/marker bound independently of native IDs.
        rows = [(DAY, str(sid), ticker, json.dumps({"ticker": ticker}))
                for sid in range(10) for ticker in ("ONE", "TWO")]
        coverage._db.executemany("INSERT INTO identity_collisions VALUES (?,?,?,?)", rows)
        with pytest.raises(source_authority.SeedIdentityCollision) as caught:
            coverage.require_no_collisions(date_from=DAY, date_to=DAY)
        value = source_diagnostic.coverage_diagnostic(str(caught.value))
        assert value["identity_collision_total"] == 10
        assert value["collision_source_rows_total"] == 20
        assert len(value["identity_collisions"]) == 8
        assert source_probe.coverage_hint(str(caught.value)) is None
        before = value["collision_sha256"]
        coverage._db.execute("UPDATE identity_collisions SET payload=? WHERE permaticker='9'",
                             (json.dumps({"ticker": "CHANGED"}),))
        with pytest.raises(source_authority.SeedIdentityCollision) as updated:
            coverage.require_no_collisions(date_from=DAY, date_to=DAY)
        assert source_diagnostic.coverage_diagnostic(str(updated.value))["collision_sha256"] != before
    finally:
        coverage.close()


@pytest.mark.parametrize("repeat_index", [0, 1])
def test_repeated_source_key_remains_an_integrity_failure(repeat_index):
    identity = symbol_identity.SymbolProjection(OBSERVED["tickers"], OBSERVED["actions"], through=DAY)
    coverage = source_authority.SeedCoverageAccumulator(
        source_authority.SeedListingProjection((*identity.rows, *identity.alias_rows), source_digest="a" * 64),
        identity.resolver().resolve)
    try:
        for row in OBSERVED["sep"]:
            coverage.add(row)
        with pytest.raises(source_authority.SourceAuthorityRefused, match="repeats source key") as caught:
            coverage.add(OBSERVED["sep"][repeat_index])
        assert not isinstance(caught.value, source_authority.SeedIdentityCollision)
    finally:
        coverage.close()
