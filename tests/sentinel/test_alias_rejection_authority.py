"""Falsifiable limits of automatic alias rejection and later source healing."""
import datetime as dt
from copy import deepcopy

import pytest

from sentinel.feed import (identity_refresh, source_aliases, source_authority,
                           symbol_identity, universe, _seed_coherence_impl)
from test_concurrent_source_symbols import DAY, source


def projected(*, healed=False):
    data, fetch, _ = source()
    guard = source_authority.StableSharadarFetch(fetch, seed_mode=True)
    guard.preflight_seed_identity(tickers=data["tickers"], fetch=fetch, date_from=DAY, date_to=DAY)
    if healed:
        data, _, _ = source(healed=True)
    identity = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY,
                                                alias_rejections=guard.alias_rejections)
    return data, identity, guard.alias_rejections


def accumulator(identity):
    return source_authority.SeedCoverageAccumulator(source_authority.SeedListingProjection(
        (*identity.rows, *identity.alias_rows), source_digest="test"), identity.resolver().resolve)


def test_two_native_labels_are_not_repaired_by_choosing_one_price():
    data, _, _ = source()
    data["tickers"].extend(dict(r, ticker=r["ticker"][:-1]) for r in tuple(data["tickers"]))
    identity = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY)
    coverage = accumulator(identity)
    try:
        for row in data["sep"]:
            coverage.add(row)
        assert source_aliases.discover(coverage, identity)["records"] == []
        with pytest.raises(source_authority.SeedIdentityCollision):
            coverage.require_complete(date_from=DAY, date_to=DAY)
    finally:
        coverage.close()


def test_rejection_cannot_excuse_a_missing_native_price():
    data, identity, _ = projected()
    coverage = accumulator(identity)
    try:
        for row in data["sep"]:
            if row["ticker"] != "OCLTU":
                coverage.add(row)
        with pytest.raises(source_authority.SourceAuthorityRefused, match="6401005"):
            coverage.require_complete(date_from=DAY, date_to=DAY)
    finally:
        coverage.close()


@pytest.mark.parametrize("field", ["open", "close", "closeunadj", "volume"])
@pytest.mark.parametrize("bad", [None, -1, "NaN", "Infinity"])
def test_native_economics_cannot_hide_behind_population_tolerance(field, bad):
    data, identity, _ = projected()
    coverage = accumulator(identity)
    try:
        row = next(r for r in data["sep"] if r["ticker"] == "OCLTU")
        with pytest.raises(source_authority.SourceAuthorityRefused, match="native price/volume"):
            coverage.add(dict(row, **{field: bad}))
    finally:
        coverage.close()


def test_corrected_source_requires_replay_and_empty_evidence_restores_native_identities():
    data, identity, payload = projected(healed=True)
    with pytest.raises(universe.HistoricalIdentityMutation, match="retained history replay"):
        source_aliases.require_current(identity, payload)
    healed = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY)
    assert healed.resolver().resolve("OCLT", DAY) == "900000001"
    assert healed.resolver().resolve("BRTM", DAY) == "900000002"
    assert not source_aliases.excludes(healed.resolver(), "OCLT")
    assert source_aliases.changed_identities(payload, source_aliases.evidence()) == ["6399775", "6401005"]


def test_changed_claim_fingerprint_cannot_silently_reapply_old_rejection():
    data, _, payload = projected()
    data["actions"][0]["name"] = "corrected source claim"
    candidate = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY,
                                                  alias_rejections=payload)
    with pytest.raises(universe.HistoricalIdentityMutation):
        source_aliases.require_current(candidate, payload)


def test_mutation_paths_share_the_same_explicit_exclusion_and_keep_unknowns_refused():
    data, identity, _ = projected()
    rows = [dict(r, lastupdated="2026-09-14") for r in data["sep"]]
    boundary = dt.date(2026, 9, 14)
    def cdc(material, resolver=identity.resolver()):
        return identity_refresh.validate_sep_mutation_rows(None, material,
            lo=boundary, hi=boundary, published_from=dt.date.fromisoformat(DAY),
            published_through=dt.date.fromisoformat(DAY), resolver=resolver)
    assert cdc(rows) == [DAY, DAY]
    dates = set()
    for row in rows:
        _seed_coherence_impl._validate_update_row(row, update_start=boundary, update_through=boundary,
            market_sessions={DAY}, resolver=identity.resolver().resolve, collect_dates=dates)
    assert dates == {DAY}
    assert source_aliases.excludes(identity.resolver(), "OCLT")
    assert not source_aliases.excludes(identity.resolver(), "UNOBSERVED")
    with pytest.raises(identity_refresh.SepMutationIdentityRefused):
        cdc([dict(rows[0], ticker="UNOBSERVED")])
    with pytest.raises(identity_refresh.maintenance_impl.SharadarMutationRefused, match="positive raw close"):
        cdc([dict(next(r for r in rows if r["ticker"] == "OCLT"), closeunadj=0)])
    healed_data, _, _ = source(healed=True)
    healed = symbol_identity.SymbolProjection(healed_data["tickers"], healed_data["actions"], through=DAY)
    assert cdc(rows, healed.resolver()) == [DAY] * 4


def test_durable_witness_tampering_refuses_instead_of_changing_identity():
    _, _, payload = projected()
    changed = deepcopy(payload)
    changed["records"][0]["native_ticker"] = "OCLT"
    with pytest.raises(universe.HistoricalIdentityMutation):
        source_aliases.validate(changed)


def test_new_daily_contradiction_requires_retained_replay_before_publication():
    from sentinel.feed import coherence
    data, _, _ = source()
    identity = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY)
    guard = coherence.StableSharadarFetch(lambda *_a, **_k: (), after_session="2026-09-10")
    guard.identity_projection = identity
    guard._tickers_listings = tuple(universe.listings_from_rows((*identity.rows, *identity.alias_rows)))
    with pytest.raises(universe.HistoricalIdentityMutation, match="retained history replay"):
        guard._validated_daily_listing_replay(iter(data["sep"]))


@pytest.mark.parametrize("missing_native", [False, True])
def test_daily_tolerance_cannot_replace_a_native_unit_with_its_unanchored_share(missing_native):
    from sentinel.feed import coherence
    data, _, payload = projected()
    data["tickers"].extend(dict(data["tickers"][0], permaticker=i + 1, ticker=f"T{i}") for i in range(2000))
    data["sep"].extend(dict(data["sep"][0], ticker=f"T{i}") for i in range(2000))
    identity = symbol_identity.SymbolProjection(data["tickers"], data["actions"], through=DAY,
                                                alias_rejections=payload)
    rows = [row for row in data["sep"] if not missing_native or row["ticker"] != "OCLTU"]
    guard = coherence.StableSharadarFetch(lambda *_a, **_k: (), after_session="2026-09-10")
    guard.identity_projection = identity
    guard._tickers_listings = tuple(universe.listings_from_rows(identity.rows))
    # The generic population rule permits this one absent label. The identity
    # authority guard must independently reject its replacement by share prices.
    coherence.assert_daily_sep_listing_population({DAY: {r["ticker"] for r in rows}}, guard._tickers_listings)
    if missing_native:
        with pytest.raises(coherence.SepListingPopulationIncomplete, match="OCLTU"):
            guard._validated_daily_listing_replay(iter(rows))
    else:
        assert list(guard._validated_daily_listing_replay(iter(rows))) == rows


@pytest.mark.parametrize("fault", [None, "proof_hash", "caller_evidence", "missing_seed_proof", "missing_alias_hash"])
def test_publication_binds_the_exact_alias_evidence_proven_by_seed(monkeypatch, fault):
    from sentinel.feed import publication, seed_coherence
    from test_issue_259_seed_coherence import _proof
    _, _, payload = projected()
    proof = _proof()
    proof["source_alias_rejections_sha256"] = "0" * 64 if fault == "proof_hash" else payload["sha256"]
    if fault == "missing_seed_proof":
        proof = None
    elif fault == "missing_alias_hash":
        del proof["source_alias_rejections_sha256"]
    monkeypatch.setattr(seed_coherence, "require_for_publication", lambda *_a, **_k: proof)
    monkeypatch.setattr(source_aliases, "load", lambda *_a, **_k: payload)
    observed = {}
    def atomic(_conn, **kwargs):
        observed.update(kwargs)
        return "published"
    monkeypatch.setattr(publication, "_publish_atomic", atomic)
    supplied = {source_aliases.KEY: source_aliases.evidence()} if fault == "caller_evidence" else {}
    if fault in {"missing_seed_proof", "missing_alias_hash"}:
        supplied = {source_aliases.KEY: payload}
    if fault is not None:
        with pytest.raises(publication.CorpusIncoherent, match="alias evidence"):
            publication.publish("conn", run_id="seed-1", evidence=supplied)
        assert observed == {}
    else:
        assert publication.publish("conn", run_id="seed-1", evidence=supplied) == "published"
        assert observed["evidence"][source_aliases.KEY] == payload
