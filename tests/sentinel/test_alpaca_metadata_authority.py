"""Enrollment/renewal read the published acquisition contract, without a broker."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from sentinel import observation_authority as observation
from sentinel.authority import AuthorityRefused
from sentinel.core import rolling_inputs
from sentinel.feed import operational_snapshot, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest


@pytest.fixture
def published(monkeypatch):
    # Exact split component shape emitted by AlpacaSource._part, including
    # OpenFIGI metadata reuse. The real producer is exercised separately below.
    source = {"schema": "sentinel.alpaca-openfigi-operational-source/1",
              "components": [
                  {"component": "TICKERS.ASSETS", "evidence": {
                      "observed_at": "2026-10-03T17:13:07.551210+00:00"}},
                  {"component": "TICKERS.PLAN", "evidence": {"policy": "fixture"}},
                  {"component": "TICKERS", "evidence": {"policy": "fixture"}}]}
    refs = SimpleNamespace(manifest=SimpleNamespace(
        provider="ALPACA_OPENFIGI", source_evidence_sha256=digest(source)),
        tickers=[{"ticker": "BBB", "permaticker": "asset-b"},
                 {"ticker": "AAA", "permaticker": "asset-a"}])
    monkeypatch.setattr(operational_snapshot, "_bound", lambda *_: {
        "candidate_id": "candidate", "snapshot_id": "snapshot"})
    monkeypatch.setattr(rolling_inputs, "SnapshotReferences", lambda *_a, **_k: refs)
    monkeypatch.setattr(rolling_store, "load_evidence", lambda *_: source)
    return source, refs


def read():
    return observation._rolling_metadata_snapshot_identity(None, None)


def test_metadata_binds_inventory_observation_and_exact_published_content(published):
    source, refs = published
    assert read() == {"snapshot_date": "2026-10-03", "row_count": 2,
                      "sha256": digest(sorted(refs.tickers, key=canonical_json))}
    before = read()
    refs.tickers.reverse()
    assert read() == before
    source["components"][0]["evidence"]["observed_at"] = "2026-10-04T01:10:00+02:00"
    assert read()["snapshot_date"] == "2026-10-03"  # UTC, never the replay date.
    source["components"][0]["evidence"]["observed_at"] = "2026-10-04T03:10:00+02:00"
    assert observation.metadata_matches_claim(before, read())  # same content, later GET
    refs.tickers[0]["ticker"] = "CHANGED"
    assert not observation.metadata_matches_claim(before, read())


@pytest.mark.parametrize("at", [None, "invalid", "2026-10-03", "2026-10-03T01:00:00", 42])
def test_invalid_inventory_time_refuses_even_when_aggregate_has_nested_timestamp(published, at):
    source, _ = published
    source["components"][0]["evidence"]["observed_at"] = at
    source["components"][-1]["evidence"]["assets"] = {
        "observed_at": "2026-10-03T17:13:07+00:00"}
    with pytest.raises(AuthorityRefused, match="observation time is invalid"):
        read()


@pytest.mark.parametrize("component", ["TICKERS.ASSETS", "TICKERS"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_inventory_and_classification_components_must_be_unique(published, component, duplicate):
    source, _ = published
    record = next(item for item in source["components"] if item["component"] == component)
    if duplicate:
        source["components"].append(deepcopy(record))
    else:
        source["components"].remove(record)
    with pytest.raises(AuthorityRefused, match="evidence is missing"):
        read()


def test_metadata_requires_identified_alpaca_source(published):
    source, _ = published
    source["schema"] = "unknown"
    with pytest.raises(AuthorityRefused, match="source identity is missing"):
        read()
