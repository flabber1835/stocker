"""Crash/restart matrix required by Sharadar umbrella issue #185 / issue #108.

These tests pin the state-machine boundary, not PostgreSQL failure mechanics:
anything that dies before ``finish(success)`` is still RUNNING and is reclaimed;
a complete SUCCESS without a publication is VALIDATED_PENDING_PUBLICATION and is
resumed; once a publication exists there is no candidate to publish again.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel.feed import ingest, publication, recovery, store


def _candidate(*, run_id="run-a", done=4, total=4):
    return recovery.PendingPublication(
        run_id=run_id, kind="daily", date_from="2026-08-17",
        date_to="2026-08-18", chunks_total=total, chunks_done=done,
        rows_written=1234, rows_dropped=0)


def test_after_finish_before_publication_restart_publishes_exact_candidate(monkeypatch):
    candidate = _candidate()
    calls = []
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recovery, "pending_validated", lambda conn: [candidate])

    expected = publication.Publication(
        version=12, previous_version=11, run_id=candidate.run_id,
        window_start=candidate.date_from, window_end=candidate.date_to,
        evidence={"recovered_pending_publication": True})

    def publish(conn, **kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(publication, "publish", publish)
    assert recovery.resume_pending_publication(object()) == expected
    assert calls == [{
        "run_id": "run-a",
        "window_start": "2026-08-17",
        "window_end": "2026-08-18",
        "evidence": {
            "kind": "daily", "rows_written": 1234, "rows_dropped": 0,
            "chunks": 4, "recovered_pending_publication": True,
        },
    }]


def test_during_publication_before_commit_restart_retries_same_transition(monkeypatch):
    """PostgreSQL rollback leaves the same SUCCESS/unpublished durable state."""
    candidate = _candidate()
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recovery, "pending_validated", lambda conn: [candidate])
    calls = []
    monkeypatch.setattr(
        publication, "publish",
        lambda conn, **kwargs: calls.append(kwargs) or "published")
    assert recovery.resume_pending_publication(object()) == "published"
    assert [c["run_id"] for c in calls] == [candidate.run_id]


def test_after_publication_commit_restart_does_not_duplicate(monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recovery, "pending_validated", lambda conn: [])
    monkeypatch.setattr(
        publication, "publish",
        lambda *a, **k: pytest.fail("already-published run must not publish again"))
    assert recovery.resume_pending_publication(object()) is None


def test_success_with_incomplete_chunks_is_impossible_and_not_promoted(monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recovery, "pending_validated", lambda conn: [
        _candidate(done=3, total=4)])
    monkeypatch.setattr(
        publication, "publish",
        lambda *a, **k: pytest.fail("incomplete success must never be published"))
    with pytest.raises(recovery.PublicationRecoveryRefused, match="3/4"):
        recovery.resume_pending_publication(object())


def test_multiple_validated_unpublished_candidates_refuse_guessing(monkeypatch):
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recovery, "pending_validated", lambda conn: [
        _candidate(run_id="run-a"), _candidate(run_id="run-b")])
    monkeypatch.setattr(
        publication, "publish",
        lambda *a, **k: pytest.fail("ambiguous candidates must not be ordered"))
    with pytest.raises(recovery.PublicationRecoveryRefused, match="2 validated"):
        recovery.resume_pending_publication(object())


@pytest.mark.parametrize("crash_boundary", [
    pytest.param("before finish(success) commit", id="before-finish-success"),
    pytest.param("after one or more bar batches before validation",
                 id="after-bar-batches"),
    pytest.param("after TICKERS candidate commit", id="after-tickers"),
    pytest.param("after ACTIONS candidate commit", id="after-actions"),
    pytest.param("after SFP/SPY candidate commit", id="after-spy"),
])
def test_every_prevalidation_crash_is_reclaimed_before_publication_recovery(
        monkeypatch, crash_boundary):
    """Every listed boundary is the same durable RUNNING lifecycle state."""
    calls = []
    monkeypatch.setattr(
        ingest._impl.feed_store, "reclaim_orphans",
        lambda conn: calls.append(("reclaim", crash_boundary)) or 1)
    monkeypatch.setattr(
        recovery, "resume_pending_publication",
        lambda conn: calls.append(("resume", crash_boundary)))
    ingest._recover_before_run(object())
    assert calls == [
        ("reclaim", crash_boundary),
        ("resume", crash_boundary),
    ]


def test_failed_candidate_physical_frontier_cannot_shorten_next_overlap(monkeypatch):
    monkeypatch.setattr(store, "latest_session", lambda conn: "2026-08-20")
    monkeypatch.setattr(store, "latest_visible_session", lambda conn: "2026-08-14")
    # Nominal 14 calendar-day overlap is widened by the entire invisible gap.
    assert recovery.extended_overlap_days(object(), 14) == 20


def test_retry_overlap_never_shrinks_when_physical_frontier_is_not_ahead(monkeypatch):
    monkeypatch.setattr(store, "latest_session", lambda conn: "2026-08-14")
    monkeypatch.setattr(store, "latest_visible_session", lambda conn: "2026-08-18")
    assert recovery.extended_overlap_days(object(), 14) == 14


def test_finish_path_refuses_to_return_success_until_run_is_published(monkeypatch):
    progress = SimpleNamespace(run_id="run-a")
    calls = []

    def require(conn, run_id):
        calls.append(("require", run_id))
        if len([c for c in calls if c[0] == "require"]) == 1:
            raise recovery.PublicationRecoveryRefused("not yet")
        return "publication"

    monkeypatch.setattr(recovery, "require_published", require)
    monkeypatch.setattr(
        recovery, "resume_pending_publication",
        lambda conn: calls.append(("resume", "run-a")))
    assert ingest._finish_publication_or_refuse(object(), progress) == "publication"
    assert calls == [
        ("require", "run-a"), ("resume", "run-a"), ("require", "run-a")]
