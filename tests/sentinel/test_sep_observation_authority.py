from __future__ import annotations

import datetime as dt

from sentinel.feed import ingest_authority_impl as authority
from sentinel.feed import maintenance
from sentinel.feed import sep_reconciliation as recon
from sentinel.feed import snapshot_source


def test_frozen_daily_ceiling_accepts_already_stronger_sep_cursor(monkeypatch):
    cursor = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date(2026, 9, 7),
        publication_version=12)
    monkeypatch.setattr(
        maintenance._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(maintenance, "load_sep_cursor", lambda conn: cursor)
    monkeypatch.setattr(
        maintenance, "_stable_rows",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("stronger cursor must not traverse source")))

    result = maintenance._reconcile_sep_mutations_core(
        object(), fetch=object(), through="2026-09-06", reobserve_equal=True)

    assert result is cursor


def test_recent_frontier_reuses_established_sep_observation_ceiling(monkeypatch):
    cursor = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date(2026, 9, 7),
        publication_version=12)
    monkeypatch.setattr(
        authority._impl.feed_store, "latest_visible_session",
        lambda conn: "2026-09-04")
    monkeypatch.setattr(authority.maintenance, "load_sep_cursor", lambda conn: cursor)
    seen = {}
    monkeypatch.setattr(
        authority.recent_reconciliation, "reconcile_recent",
        lambda conn, **kwargs: seen.update(kwargs))

    authority._prove_recent_frontier(
        object(), fetch=snapshot_source.fetch_table)

    assert seen["through"] == "2026-09-04"
    assert seen["fetch"] is None
    assert seen["observation_ceiling"] == dt.date(2026, 9, 7)


def test_rotation_uses_explicit_frozen_observation_ceiling(monkeypatch):
    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "YEARS_PER_RUN", 1)
    monkeypatch.setattr(
        recon.seed_coherence, "capture_update_ceiling",
        lambda: (_ for _ in ()).throw(
            AssertionError("explicit ceiling must suppress a new clock capture")))
    monkeypatch.setattr(
        recon.maintenance, "reconcile_actions_if_due", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(
        recon.maintenance, "reconcile_sep_mutations",
        lambda conn, **kwargs: seen.append(("mutations", kwargs["through"])))
    monkeypatch.setattr(
        recon, "_next_year",
        lambda conn: (2026, dt.date(2026, 1, 1), dt.date(2026, 9, 4)))
    monkeypatch.setattr(
        recon, "reconcile_year",
        lambda conn, **kwargs: seen.append(
            ("year", kwargs["observation_ceiling"])) or recon.ReconciliationResult(
                year=2026, start="2026-01-01", end="2026-09-04", rows=1,
                digest="a" * 64, value_digest="b" * 64,
                max_lastupdated=dt.date(2026, 9, 6), publication_version=12))
    monkeypatch.setattr(recon, "_save_result", lambda *a, **k: None)

    recon.reconcile_next(
        object(), fetch=snapshot_source.fetch_table, through="2026-09-04",
        observation_ceiling="2026-09-06")

    assert seen == [
        ("mutations", "2026-09-06"),
        ("year", dt.date(2026, 9, 6)),
    ]
