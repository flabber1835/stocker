"""#185/#108: retry failed owners, then refresh identity before routine maintenance."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sentinel.feed import coherence, ingest, maintenance, recovery, sep_reconciliation


@contextmanager
def _lock(_conn):
    yield


def _base(monkeypatch, events, failed_provider, *, on_publish=None):
    monkeypatch.setattr(ingest, "_validate_source_before_run", lambda fetch: None)
    monkeypatch.setattr(
        ingest._impl.feed_store, "corpus_write_lock", lambda conn: _lock(conn))
    monkeypatch.setattr(ingest, "_recover_before_run", lambda conn: None)
    monkeypatch.setattr(
        maintenance, "load_sep_cursor", lambda conn: object())
    monkeypatch.setattr(recovery, "failed_live_candidates", failed_provider)
    monkeypatch.setattr(
        ingest._impl.feed_store, "latest_visible_session",
        lambda conn: "2026-08-17")
    monkeypatch.setattr(
        coherence, "StableSharadarFetch",
        lambda fetch, after_session=None: fetch)
    monkeypatch.setattr(
        recovery, "extended_overlap_days", lambda conn, requested: requested)

    def daily_locked(conn, **kwargs):
        events.append("daily")
        return SimpleNamespace(run_id="new-daily")

    monkeypatch.setattr(ingest._impl, "_daily_locked", daily_locked)

    def finish(conn, progress):
        events.append("daily-publish")
        if on_publish is not None:
            on_publish()
        return object()

    monkeypatch.setattr(ingest, "_finish_publication_or_refuse", finish)
    monkeypatch.setattr(
        sep_reconciliation, "reconcile_next",
        lambda conn, **kwargs: events.append("sep-keyset"))


def test_failed_daily_is_superseded_before_publication_capable_maintenance(
        monkeypatch):
    events = []
    state = {"cleared": False}
    failed = recovery.FailedLiveCandidate("old-daily", "daily")

    _base(
        monkeypatch, events,
        lambda conn: [] if state["cleared"] else [failed],
        on_publish=lambda: state.__setitem__("cleared", True))
    monkeypatch.setattr(
        maintenance, "reconcile_sep_mutations",
        lambda conn, *, fetch, through: events.append(("sep-cdc", through)))
    monkeypatch.setattr(
        maintenance, "reconcile_actions_if_due",
        lambda conn, *, fetch, through, force=False:
            events.append(("actions", through, force)))

    ingest.daily(
        object(), fetch=lambda *a, **k: (), today="2026-08-18")

    assert events == [
        "daily", "daily-publish", "sep-keyset",
        ("sep-cdc", "2026-08-18"),
        ("actions", "2026-08-18", False),
    ]


def test_failed_actions_reconciliation_is_retried_then_daily_refreshes_identity(
        monkeypatch):
    events = []
    state = {"cleared": False}
    failed = recovery.FailedLiveCandidate("old-actions", "actions_reconcile")

    _base(monkeypatch, events,
          lambda conn: [] if state["cleared"] else [failed])
    monkeypatch.setattr(
        ingest, "_failed_run_end", lambda conn, run_id: "2026-08-17")

    def actions(conn, *, fetch, through, force=False):
        events.append(("actions", through, force))
        if force:
            state["cleared"] = True

    monkeypatch.setattr(maintenance, "reconcile_actions_if_due", actions)
    monkeypatch.setattr(
        maintenance, "reconcile_sep_mutations",
        lambda conn, *, fetch, through: events.append(("sep-cdc", through)))

    ingest.daily(
        object(), fetch=lambda *a, **k: (), today="2026-08-18")

    assert events == [
        ("actions", "2026-08-17", True),
        "daily", "daily-publish", "sep-keyset",
        ("sep-cdc", "2026-08-18"),
        ("actions", "2026-08-18", False),
    ]


def test_same_day_failed_sep_mutation_gets_exact_retry_before_daily(monkeypatch):
    events = []
    state = {"cleared": False}
    failed = recovery.FailedLiveCandidate("old-cdc", "sep_mutations")

    _base(monkeypatch, events,
          lambda conn: [] if state["cleared"] else [failed])

    def sep(conn, *, fetch, through):
        events.append(("sep-cdc", through))
        # Yesterday can be a no-op when the failed run was the post-daily,
        # same-day phase. Retrying through today is what can supersede it.
        if through == "2026-08-18":
            state["cleared"] = True

    monkeypatch.setattr(maintenance, "reconcile_sep_mutations", sep)
    monkeypatch.setattr(
        maintenance, "reconcile_actions_if_due",
        lambda conn, *, fetch, through, force=False:
            events.append(("actions", through, force)))

    ingest.daily(
        object(), fetch=lambda *a, **k: (), today="2026-08-18")

    assert events[:2] == [
        ("sep-cdc", "2026-08-17"),
        ("sep-cdc", "2026-08-18"),
    ]
    assert events.index("daily") < events.index("sep-keyset")
    assert events[-2:] == [
        ("sep-cdc", "2026-08-18"),
        ("actions", "2026-08-18", False),
    ]


def test_unknown_failed_live_candidate_refuses_before_opening_new_run(monkeypatch):
    events = []
    failed = recovery.FailedLiveCandidate("old-unknown", "mystery")
    _base(monkeypatch, events, lambda conn: [failed])
    monkeypatch.setattr(
        maintenance, "reconcile_sep_mutations",
        lambda *a, **k: pytest.fail("must not open maintenance"))
    monkeypatch.setattr(
        maintenance, "reconcile_actions_if_due",
        lambda *a, **k: pytest.fail("must not open maintenance"))

    with pytest.raises(recovery.PublicationRecoveryRefused, match="mystery"):
        ingest.daily(
            object(), fetch=lambda *a, **k: (), today="2026-08-18")
    assert "daily" not in events
