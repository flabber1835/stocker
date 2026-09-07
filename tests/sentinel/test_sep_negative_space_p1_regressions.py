"""Regression coverage for PR 330 negative-space retirement safety findings."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import domains
from sentinel.feed import sep_negative_space as neg
from sentinel.feed import sep_reconciliation as recon


def _proof(rows, key="a", value="b"):
    return recon._PartitionProof(
        rows=rows, key_digest=key * 64, value_digest=value * 64,
        max_lastupdated=dt.date(2026, 9, 4))


@pytest.mark.parametrize(
    ("field", "rejection"),
    [
        ("dropped_no_raw_close", {"ticker": "OLD", "session": "2026-04-01", "reason": "NO_RAW_CLOSE"}),
        ("dropped_no_identity", {"ticker": "OLD", "session": "2026-04-01", "reason": "NO_IDENTITY"}),
    ],
)
def test_retirement_refuses_source_rows_rejected_by_normalisation(field, rejection):
    report = domains.NormalisationReport()
    setattr(report, field, 1)
    report.rejections.append(rejection)

    with pytest.raises(
            neg.SepNegativeSpaceRefused,
            match="source rows were rejected during normalization"):
        neg._assert_lossless_source_normalisation(report)


def test_retirement_accepts_lossless_source_normalisation():
    neg._assert_lossless_source_normalisation(domains.NormalisationReport())


def test_post_commit_publish_exception_preserves_successful_origin_run(monkeypatch):
    source = _proof(10, "a", "b")
    keys = [{"security_id": "P:OLD", "session": "2026-04-01", "ticker": "OLD"}]

    class Conn:
        def __init__(self):
            self.rollbacks = 0

        def rollback(self):
            self.rollbacks += 1

    class Run:
        def __init__(self):
            self.progress = SimpleNamespace(
                run_id="22222222-2222-2222-2222-222222222222")
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
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("post-commit fault")))
    monkeypatch.setattr(neg, "_publication_committed_for_run", lambda *a, **k: True)

    with pytest.raises(RuntimeError, match="post-commit fault"):
        neg.repair_local_only(
            conn, fetch="source", start="2026-03-06", end="2026-09-04",
            observation_ceiling="2026-09-06", expected_source=source)

    assert conn.rollbacks == 1
    assert run.finished == []
