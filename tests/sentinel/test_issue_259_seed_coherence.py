from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from sentinel.feed import ingest, publication, seed_coherence, sharadar, source_authority


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row = row
        self.cursors = []

    def cursor(self):
        cursor = _Cursor(self.row)
        self.cursors.append(cursor)
        return cursor


def _proof(run_id="seed-1"):
    observation = {"rows": 2, "sha256": "a" * 64}
    normalized = {
        "rows": 2,
        "key_sha256": "b" * 64,
        "value_sha256": "c" * 64,
    }
    return {
        "schema": seed_coherence.SCHEMA,
        "phase": "complete",
        "run_id": run_id,
        "market_interval": ["2026-01-02", "2026-08-24"],
        "seed_start_update_boundary": "2026-08-24",
        "mutation_interval": ["2026-08-24", "2026-08-24"],
        "mutation_source_first": dict(observation),
        "mutation_source_second": dict(observation),
        "overlap": {
            "interval": ["2026-02-20", "2026-08-24"],
            "source_first": dict(observation),
            "source_second": dict(observation),
        },
        "normalized_source": dict(normalized),
        "normalized_local": dict(normalized),
        "final_mutation_cursor": "2026-08-24",
    }


def _seed_row(payload):
    return (
        "seed", "success", "2026-01-02", "2026-08-24",
        {"seed_coherence": payload},
    )


def test_seed_publication_requires_exact_durable_proof():
    payload = _proof()
    assert seed_coherence.require_for_publication(
        _Conn(_seed_row(payload)), run_id="seed-1",
        window_start="2026-01-02", window_end="2026-08-24") == payload


@pytest.mark.parametrize("mutate", [
    lambda payload: payload.pop("normalized_local"),
    lambda payload: payload.update(phase="started"),
    lambda payload: payload["normalized_local"].update(value_sha256="d" * 64),
    lambda payload: payload["mutation_source_second"].update(sha256="d" * 64),
    lambda payload: payload["overlap"]["source_second"].update(sha256="d" * 64),
    lambda payload: payload.update(run_id="other-run"),
])
def test_incomplete_or_mismatched_seed_proof_refuses_publication(mutate):
    payload = copy.deepcopy(_proof())
    mutate(payload)
    with pytest.raises(seed_coherence.SeedCoherenceRefused):
        seed_coherence.require_for_publication(
            _Conn(_seed_row(payload)), run_id="seed-1",
            window_start="2026-01-02", window_end="2026-08-24")


def test_seed_window_mismatch_refuses_and_nonseed_does_not_require_proof():
    with pytest.raises(seed_coherence.SeedCoherenceRefused, match="window"):
        seed_coherence.require_for_publication(
            _Conn(_seed_row(_proof())), run_id="seed-1",
            window_start="2026-01-03", window_end="2026-08-24")
    assert seed_coherence.require_for_publication(
        _Conn(("daily", "success", "2026-08-24", "2026-08-24", {})),
        run_id="daily-1", window_start="2026-08-24",
        window_end="2026-08-24") is None


def _mutation(**changes):
    row = {
        "date": "2026-08-21",
        "ticker": "AAA",
        "open": 99.0,
        "close": 100.0,
        "closeunadj": 100.0,
        "volume": 1000,
        "lastupdated": "2026-08-24",
    }
    row.update(changes)
    return row


def test_historical_mutation_is_double_observed_and_returned_for_replay():
    calls = []

    def fetch(table, params):
        calls.append((table, dict(params)))
        return iter([_mutation()])

    first, second, dates = seed_coherence._observe_mutations(
        fetch, update_start="2026-08-24", update_through="2026-08-24",
        market_start="2026-08-20", market_end="2026-08-24",
        resolver=lambda ticker, session: f"{ticker}:{session}")
    assert first == second
    assert first.rows == 1
    assert dates == {"2026-08-21"}
    assert len(calls) == 2
    assert all(call[1] == {
        "lastupdated.gte": "2026-08-24",
        "lastupdated.lte": "2026-08-24",
    } for call in calls)


def test_post_seed_proof_routes_cdc_and_date_windows_through_distinct_authority():
    calls = []

    def raw_source(_table, params=None, **_kwargs):
        request = dict(params or {})
        calls.append(request)
        if "lastupdated.gte" in request:
            return iter([_mutation(lastupdated="2026-09-05")])
        return iter([_mutation(lastupdated="2026-09-04")])

    fetch = ingest._post_seed_proof_source(
        raw_source, boundary="2026-09-05", ceiling="2026-09-05")
    cdc = {
        "lastupdated.gte": "2026-09-05",
        "lastupdated.lte": "2026-09-05",
    }
    date_window = {"date.gte": "2026-08-01", "date.lte": "2026-08-31"}

    assert len(list(fetch(sharadar.SEP, cdc))) == 1
    assert len(list(fetch(sharadar.SEP, date_window))) == 1
    assert calls == [cdc, date_window]

    with pytest.raises(source_authority.SourceAuthorityRefused,
                       match="request envelope"):
        list(fetch(sharadar.SEP, {"lastupdated.gte": "2026-09-05"}))


def test_post_seed_date_window_keeps_the_frozen_update_ceiling():
    def future_source(_table, _params=None, **_kwargs):
        return iter([_mutation(lastupdated="2026-09-06")])

    fetch = ingest._post_seed_proof_source(
        future_source, boundary="2026-09-05", ceiling="2026-09-05")
    with pytest.raises(source_authority.SepUpdateEnvelopeViolation,
                       match="causal ceiling"):
        list(fetch(sharadar.SEP, {
            "date.gte": "2026-08-01", "date.lte": "2026-08-31"}))


def test_seed_finalization_exercises_cdc_then_date_window_on_one_proof(monkeypatch):
    calls = []

    def raw_source(_table, params=None, **_kwargs):
        request = dict(params or {})
        calls.append(request)
        if "lastupdated.gte" in request:
            return iter([_mutation(lastupdated="2026-09-05")])
        return iter([_mutation(lastupdated="2026-09-04")])

    monkeypatch.setattr(
        seed_coherence, "record_seed_coverage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        seed_coherence, "capture_update_ceiling", lambda: "2026-09-05")

    def prove(_conn, **kwargs):
        proof_fetch = kwargs["fetch"]
        list(proof_fetch(sharadar.SEP, {
            "lastupdated.gte": "2026-09-05",
            "lastupdated.lte": "2026-09-05",
        }))
        list(proof_fetch(sharadar.SEP, {
            "date.gte": "2026-08-01", "date.lte": "2026-08-31",
        }))
        return "proof-complete"

    monkeypatch.setattr(seed_coherence, "prove", prove)
    tracked = SimpleNamespace(
        seed_coverage_evidence={"schema": "fixture"},
        max_sep_lastupdated="2026-09-04")
    authority = ingest._SeedAuthority(
        boundary="2026-09-05", tracked=tracked, source_fetch=raw_source,
        market_start="2026-01-02", market_end="2026-08-31",
        resolve_identity=None)
    finishes = []
    run = SimpleNamespace(
        conn=object(), progress=SimpleNamespace(run_id="seed-1"),
        finish=lambda *args: finishes.append(args))

    authority.before_success(run, resolver=lambda *_args: "security")

    assert authority.proof == "proof-complete"
    assert finishes == []
    assert calls == [
        {"lastupdated.gte": "2026-09-05", "lastupdated.lte": "2026-09-05"},
        {"date.gte": "2026-08-01", "date.lte": "2026-08-31"},
    ]


def test_unstable_or_out_of_envelope_mutation_refuses_cursor_authority():
    observations = [[_mutation()], [_mutation(close=101.0)]]

    def unstable(_table, _params):
        return iter(observations.pop(0))

    with pytest.raises(seed_coherence.SeedCoherenceRefused, match="changed"):
        seed_coherence._observe_mutations(
            unstable, update_start="2026-08-24",
            update_through="2026-08-24", market_start="2026-08-20",
            market_end="2026-08-24", resolver=lambda *_args: "1")

    def outside(_table, _params):
        return iter([_mutation(lastupdated="2026-08-25")])

    with pytest.raises(seed_coherence.SeedCoherenceRefused, match="outside"):
        seed_coherence._observe_mutations(
            outside, update_start="2026-08-24",
            update_through="2026-08-24", market_start="2026-08-20",
            market_end="2026-08-24", resolver=lambda *_args: "1")


def test_publication_membrane_embeds_exact_durable_proof(monkeypatch):
    proof = _proof()
    observed = {}
    monkeypatch.setattr(
        seed_coherence, "require_for_publication", lambda *_args, **_kwargs: proof)

    def atomic_publish(_conn, **kwargs):
        observed.update(kwargs)
        return "published"

    monkeypatch.setattr(publication, "_publish_atomic", atomic_publish)
    result = publication.publish(
        "conn", run_id="seed-1", window_start="2026-01-02",
        window_end="2026-08-24", evidence={"other": "evidence"})
    assert result == "published"
    assert observed["evidence"] == {
        "other": "evidence", "seed_coherence": proof}
