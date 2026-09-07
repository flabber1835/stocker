"""Adversarial coverage for bounded stable-source SEP negative-space repair."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import sep_negative_space as neg
from sentinel.feed import sep_reconciliation as recon


def _proof(rows, key="a", value="b"):
    return recon._PartitionProof(
        rows=rows, key_digest=key * 64, value_digest=value * 64,
        max_lastupdated=dt.date(2026, 9, 4))


def test_reconcile_year_repairs_only_local_row_surplus(monkeypatch):
    source = _proof(10, "a", "b")
    local_before = _proof(17, "c", "d")
    local_after = _proof(10, "a", "b")
    local_reads = iter([local_before, local_after])
    repaired = []

    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "_source_fingerprint", lambda *a, **k: source)
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: next(local_reads))
    monkeypatch.setattr(
        neg, "repair_local_only",
        lambda conn, **kwargs: repaired.append(kwargs) or {"publication": object()})
    monkeypatch.setattr(
        recon._core.publication, "require_current",
        lambda conn: SimpleNamespace(version=42))

    result = recon.reconcile_year(
        object(), fetch="source", year=2026,
        start="2026-03-06", end="2026-09-04",
        observation_ceiling="2026-09-06")

    assert len(repaired) == 1
    assert repaired[0]["expected_source"] is source
    assert repaired[0]["start"] == "2026-03-06"
    assert repaired[0]["end"] == "2026-09-04"
    assert result.rows == 10
    assert result.publication_version == 42


@pytest.mark.parametrize("local", [
    _proof(9, "c", "b"),
    _proof(10, "c", "b"),
])
def test_reconcile_year_never_self_heals_missing_or_substituted_local_keys(
        monkeypatch, local):
    source = _proof(10, "a", "b")
    called = []
    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "_source_fingerprint", lambda *a, **k: source)
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: local)
    monkeypatch.setattr(
        neg, "repair_local_only",
        lambda *a, **k: called.append(True))

    with pytest.raises(recon.SepKeysetDrift, match="Refusing to guess"):
        recon.reconcile_year(
            object(), fetch="source", year=2026,
            start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06")
    assert called == []


def test_reconcile_year_rechecks_values_after_negative_space_repair(monkeypatch):
    source = _proof(10, "a", "b")
    local_before = _proof(11, "c", "b")
    local_after = _proof(10, "a", "f")
    reads = iter([local_before, local_after])
    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "_source_fingerprint", lambda *a, **k: source)
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: next(reads))
    monkeypatch.setattr(neg, "repair_local_only", lambda *a, **k: {})

    with pytest.raises(recon.SepValueDrift, match="strategy values disagree"):
        recon.reconcile_year(
            object(), fetch="source", year=2026,
            start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06")


def test_repair_refuses_if_source_changes_between_detection_and_reobservation(
        monkeypatch):
    expected = _proof(10, "a", "b")
    changed = _proof(9, "c", "b")
    monkeypatch.setattr(neg.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(neg, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(neg, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(
        neg, "_source_proof_and_keys", lambda *a, **k: changed)

    with pytest.raises(
            neg.SepNegativeSpaceRefused,
            match="source changed between mismatch detection"):
        neg.repair_local_only(
            object(), fetch="source", start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06", expected_source=expected)


def test_repair_refuses_if_current_source_key_is_missing_locally(monkeypatch):
    source = _proof(10, "a", "b")
    local_source = _proof(9, "c", "b")
    monkeypatch.setattr(neg.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(neg, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(neg, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(
        neg, "_source_proof_and_keys", lambda *a, **k: source)
    monkeypatch.setattr(
        neg, "_source_only_local_proof", lambda *a, **k: local_source)

    with pytest.raises(
            neg.SepNegativeSpaceRefused,
            match="keys absent from published local state"):
        neg.repair_local_only(
            object(), fetch="source", start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06", expected_source=source)


def test_repair_refuses_value_drift_even_when_source_keys_exist(monkeypatch):
    source = _proof(10, "a", "b")
    local_source = _proof(10, "a", "f")
    monkeypatch.setattr(neg.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(neg, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(neg, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(
        neg, "_source_proof_and_keys", lambda *a, **k: source)
    monkeypatch.setattr(
        neg, "_source_only_local_proof", lambda *a, **k: local_source)

    with pytest.raises(
            neg.SepNegativeSpaceRefused,
            match="source values disagree"):
        neg.repair_local_only(
            object(), fetch="source", start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06", expected_source=source)


def test_bridge_split_ratio_detects_deleted_intermediate_split_bar():
    # A -> B -> C stores the split on B.  If Sharadar retracts B, A -> C needs
    # that same 2:1 edge moved onto C; retaining C's old 1.0 would corrupt the
    # engine's reconstructed signal history.
    prev = (10.0, 20.0)
    successor = (10.0, 10.0, 1.0)
    assert neg._bridge_split_ratio(prev, successor) == 2.0
    assert successor[2] == 1.0


def test_repair_refuses_when_retirement_would_change_split_chain(monkeypatch):
    source = _proof(10, "a", "b")
    keys = [{"security_id": "P:SPLIT", "session": "2026-04-02", "ticker": "SPLT"}]
    reached_run = []

    monkeypatch.setattr(neg.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(neg, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(neg, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(neg, "_source_proof_and_keys", lambda *a, **k: source)
    monkeypatch.setattr(neg, "_source_only_local_proof", lambda *a, **k: source)
    monkeypatch.setattr(neg, "_local_only_keys", lambda *a, **k: keys)
    monkeypatch.setattr(
        neg.recon, "_local_fingerprint", lambda *a, **k: _proof(11, "c", "d"))
    monkeypatch.setattr(neg, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        neg, "_assert_retirement_preserves_split_chain",
        lambda *a, **k: (_ for _ in ()).throw(
            neg.SepNegativeSpaceRefused("would change the effective split chain")))
    monkeypatch.setattr(
        neg.store, "IngestRun",
        lambda *a, **k: reached_run.append(True))

    with pytest.raises(
            neg.SepNegativeSpaceRefused,
            match="effective split chain"):
        neg.repair_local_only(
            object(), fetch="source", start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06", expected_source=source)
    assert reached_run == []


def test_failed_atomic_retirement_marks_repair_run_failed(monkeypatch):
    source = _proof(10, "a", "b")
    keys = [{"security_id": "P:OLD", "session": "2026-04-01", "ticker": "OLD"}]

    class Conn:
        def __init__(self):
            self.rollbacks = 0

        def rollback(self):
            self.rollbacks += 1

    class Run:
        def __init__(self):
            self.progress = SimpleNamespace(run_id="11111111-1111-1111-1111-111111111111")
            self.finished = []

        def finish(self, status, detail=None):
            self.finished.append((status, detail))

    conn = Conn()
    run = Run()
    monkeypatch.setattr(neg.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(neg, "_create_source_table", lambda conn: None)
    monkeypatch.setattr(neg, "_drop_temp", lambda conn, table: None)
    monkeypatch.setattr(neg, "_source_proof_and_keys", lambda *a, **k: source)
    monkeypatch.setattr(neg, "_source_only_local_proof", lambda *a, **k: source)
    monkeypatch.setattr(neg, "_local_only_keys", lambda *a, **k: keys)
    monkeypatch.setattr(
        neg.recon, "_local_fingerprint", lambda *a, **k: _proof(11, "c", "d"))
    monkeypatch.setattr(neg, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        neg, "_assert_retirement_preserves_split_chain", lambda *a, **k: None)
    monkeypatch.setattr(neg.store, "IngestRun", lambda *a, **k: run)
    monkeypatch.setattr(neg, "_persist_plan", lambda *a, **k: None)
    monkeypatch.setattr(
        neg, "_retire_and_publish",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("publish failed")))
    monkeypatch.setattr(
        neg, "_publication_committed_for_run", lambda *a, **k: False)

    with pytest.raises(RuntimeError, match="publish failed"):
        neg.repair_local_only(
            conn, fetch="source", start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06", expected_source=source)
    assert conn.rollbacks == 1
    assert run.finished and run.finished[0][0] == "failed"


def test_retirement_key_digest_is_order_sensitive_to_canonical_plan():
    left = [
        {"security_id": "P:1", "session": "2026-04-01", "ticker": "AAA"},
        {"security_id": "P:2", "session": "2026-04-02", "ticker": "BBB"},
    ]
    assert neg._keys_digest(left) != neg._keys_digest(list(reversed(left)))
