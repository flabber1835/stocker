"""Regression coverage for SEP negative-space economic preservation."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as recon
from sentinel.feed import snapshot_source


class _RowsCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _sql, _params=()):
        self._rows = list(self.rows)

    def fetchall(self):
        return list(self._rows)


class _RowsConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _RowsCursor(self.rows)


class _SequenceCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _sql, _params=()):
        self._row = self.conn.responses.pop(0)

    def fetchone(self):
        return self._row


class _SequenceConn:
    def __init__(self, responses):
        self.responses = list(responses)

    def cursor(self):
        return _SequenceCursor(self)


def _key():
    return [{"security_id": "P:1", "session": "2026-04-02", "ticker": "AAA"}]


def _proof(rows, key="a", value="b"):
    return recon._PartitionProof(
        rows=rows, key_digest=key * 64, value_digest=value * 64,
        max_lastupdated=dt.date(2026, 9, 4))


def test_retirement_refuses_fractional_split_event(monkeypatch):
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _RowsConn([("P:1", dt.date(2026, 4, 2), "AAA", 1.25, 0.0)])

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="carries an effective split event"):
        guarded._assert_retired_rows_have_no_economic_events(conn, _key())


def test_retirement_refuses_dividend_entitlement(monkeypatch):
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _RowsConn([("P:1", dt.date(2026, 4, 2), "AAA", 1.0, 1.0)])

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="carries a dividend entitlement"):
        guarded._assert_retired_rows_have_no_economic_events(conn, _key())


def test_retirement_allows_economically_empty_row(monkeypatch):
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _RowsConn([("P:1", dt.date(2026, 4, 2), "AAA", 1.0, 0.0)])

    guarded._assert_retired_rows_have_no_economic_events(conn, _key())


def test_retirement_refuses_new_current_actions_dividend_on_stale_zero_bar(monkeypatch):
    from sentinel.feed import ingest_impl

    monkeypatch.setattr(
        ingest_impl, "_action_maps",
        lambda *a, **k: ({}, {("AAA", "2026-04-02"): 0.25}, [], []))
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="current authoritative ACTIONS dividend entitlement"):
        guarded._assert_current_actions_have_no_retirement_events(object(), _key())


def test_retirement_refuses_new_current_actions_split_on_stale_unit_bar(monkeypatch):
    from sentinel.feed import ingest_impl

    monkeypatch.setattr(
        ingest_impl, "_action_maps",
        lambda *a, **k: ({("AAA", "2026-04-02"): 2.0}, {}, [], []))
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="current authoritative ACTIONS split event"):
        guarded._assert_current_actions_have_no_retirement_events(object(), _key())


def _patch_bridge_sql(monkeypatch):
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")


def test_small_published_split_must_survive_canonical_bridge_resolution(monkeypatch):
    _patch_bridge_sql(monkeypatch)
    conn = _SequenceConn([
        (100.0, 100.500),
        (100.0, 100.503, 0.995),
    ])

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="canonical bridge resolution is unresolved"):
        guarded._assert_retirement_preserves_split_chain(conn, _key())


def test_unit_split_edge_accepts_bridge_inside_canonical_no_event_band(monkeypatch):
    _patch_bridge_sql(monkeypatch)
    conn = _SequenceConn([
        (100.0, 101.500),
        (100.0, 100.000, 1.0),
    ])

    guarded._assert_retirement_preserves_split_chain(conn, _key())


def test_complete_export_disagreement_refuses_before_retirement(monkeypatch):
    detected = _proof(10, "a", "b")
    exported = _proof(11, "c", "b")
    monkeypatch.setattr(guarded.core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(guarded.core, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(guarded.core, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(
        guarded.core, "_source_proof_and_keys", lambda *a, **k: exported)

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="source changed between mismatch detection"):
        guarded.repair_local_only(
            object(), fetch="complete-export", start="2026-03-06",
            end="2026-09-04", observation_ceiling="2026-09-06",
            expected_source=detected,
            source_authority_evidence={"authority": "export"},
            actions_authority_evidence={"authority": "actions-export"})


def test_production_repair_uses_fresh_complete_export_and_persists_evidence(
        monkeypatch):
    source = _proof(10, "a", "b")
    local = _proof(11, "c", "d")
    export_fetch = object()
    evidence = {
        "authority": "nasdaq-data-link-table-export/v1",
        "table": "SEP",
        "data_snapshot_time": "2026-09-06T20:00:00+00:00",
        "last_refreshed_time": "2026-09-06T19:59:00+00:00",
        "source_rows": 10,
    }
    actions_evidence = {
        "authority": "nasdaq-data-link-table-export/v1", "table": "ACTIONS"}
    captured = {}

    monkeypatch.setattr(
        recon, "_visible_bounds",
        lambda conn: (dt.date(1998, 1, 2), dt.date(2026, 9, 4)))
    monkeypatch.setattr(
        recon, "_fresh_actions_retirement_authority",
        lambda *a, **k: actions_evidence)
    monkeypatch.setattr(
        recon, "_complete_export_source",
        lambda **kwargs: (export_fetch, evidence))
    monkeypatch.setattr(
        recon.sep_negative_space_guarded, "repair_local_only",
        lambda conn, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: local)

    result = recon._repair_local_only_if_proved(
        object(), fetch="paged", start="2026-03-06", end="2026-09-04",
        observation_ceiling="2026-09-06", source=source, local=local,
        require_complete_export=True)

    assert result is local
    assert captured["fetch"] is export_fetch
    assert captured["source_authority_evidence"] == evidence
    assert captured["actions_authority_evidence"] == actions_evidence
    assert captured["expected_source"] is source


def test_guarded_plan_persists_complete_export_authority(monkeypatch):
    source = _proof(10, "a", "b")
    keys = [{"security_id": "P:OLD", "session": "2026-04-01", "ticker": "OLD"}]
    evidence = {"authority": "nasdaq-data-link-table-export/v1", "table": "SEP"}
    actions_evidence = {
        "authority": "nasdaq-data-link-table-export/v1", "table": "ACTIONS"}
    saved = {}

    class Run:
        progress = SimpleNamespace(run_id="33333333-3333-3333-3333-333333333333")

    monkeypatch.setattr(guarded.core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(guarded.core, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(guarded.core, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(guarded.core, "_source_proof_and_keys", lambda *a, **k: source)
    monkeypatch.setattr(guarded.core, "_source_only_local_proof", lambda *a, **k: source)
    monkeypatch.setattr(guarded.core, "_local_only_keys", lambda *a, **k: keys)
    monkeypatch.setattr(
        guarded.core.recon, "_local_fingerprint", lambda *a, **k: _proof(11, "c", "d"))
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded, "_assert_retired_rows_have_no_economic_events", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded, "_assert_current_actions_have_no_retirement_events", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded, "_assert_retirement_preserves_split_chain", lambda *a, **k: None)
    monkeypatch.setattr(guarded.core.store, "IngestRun", lambda *a, **k: Run())
    monkeypatch.setattr(
        guarded.core, "_persist_plan",
        lambda conn, *, run_id, plan: saved.update(plan))
    monkeypatch.setattr(
        guarded.core, "_retire_and_publish", lambda *a, **k: "published")

    result = guarded.repair_local_only(
        object(), fetch="complete-export", start="2026-03-06",
        end="2026-09-04", observation_ceiling="2026-09-06",
        expected_source=source, source_authority_evidence=evidence,
        actions_authority_evidence=actions_evidence)

    assert result["publication"] == "published"
    assert saved["source_authority"] == evidence
    assert saved["actions_authority"] == actions_evidence


def test_production_retirement_refuses_missing_actions_authority():
    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="lacks fresh complete ACTIONS authority"):
        guarded.repair_local_only(
            object(), fetch="complete-export", start="2026-03-06",
            end="2026-09-04", observation_ceiling="2026-09-06",
            expected_source=_proof(10),
            source_authority_evidence={"authority": "export"})


def test_production_rotating_reconciliation_uses_source_day(monkeypatch):
    monkeypatch.setattr(
        recon.seed_coherence, "capture_update_ceiling", lambda: "2026-09-06")
    market = dt.date(2026, 9, 4)
    assert recon._production_source_ceiling(
        snapshot_source.fetch_table, market) == dt.date(2026, 9, 6)


def test_injected_reconciliation_keeps_market_ceiling():
    market = dt.date(2026, 9, 4)

    def injected(*_args, **_kwargs):
        return iter(())

    assert recon._production_source_ceiling(injected, market) == market
