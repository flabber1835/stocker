from __future__ import annotations

import contextlib
import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import ingest, maintenance, sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as recon
from sentinel.feed import source_authority


def _proof(rows, key="a", value="b"):
    return recon._PartitionProof(
        rows=rows, key_digest=key * 64, value_digest=value * 64,
        max_lastupdated=dt.date(2026, 9, 7))


def test_public_sep_wrapper_accepts_stronger_cursor_for_frozen_ceiling(monkeypatch):
    cursor = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date(2026, 9, 7),
        publication_version=12)
    monkeypatch.setattr(maintenance, "load_sep_cursor", lambda conn: cursor)
    monkeypatch.setattr(
        maintenance, "_reconcile_sep_mutations_core",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("stronger cursor must terminate in public wrapper")))

    result = source_authority.reconcile_sep_mutations(
        object(), fetch=object(), through="2026-09-06", reobserve_equal=True)

    assert result is cursor


def test_daily_reuses_one_frozen_source_ceiling_for_rotation_and_sep(monkeypatch):
    conn = object()
    cursor = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date(2026, 9, 6),
        publication_version=12)
    progress = SimpleNamespace(run_id="daily-run")
    seen = {}

    monkeypatch.setattr(ingest, "_validate_source_before_run", lambda fetch: None)
    monkeypatch.setattr(
        ingest.feed_store, "corpus_write_lock",
        lambda _conn: contextlib.nullcontext())
    monkeypatch.setattr(ingest, "_recover_before_run", lambda _conn: None)
    monkeypatch.setattr(ingest.maintenance, "load_sep_cursor", lambda _conn: cursor)
    monkeypatch.setattr(ingest, "_single_failed_live_candidate", lambda _conn: None)
    monkeypatch.setattr(
        ingest.feed_store, "latest_visible_session", lambda _conn: "2026-09-04")
    monkeypatch.setattr(
        ingest.source_authority, "StableSharadarFetch",
        lambda fetch, **kwargs: fetch)
    monkeypatch.setattr(
        ingest.recovery, "extended_overlap_days", lambda _conn, days: days)
    monkeypatch.setattr(
        ingest._impl, "_daily_locked", lambda *a, **k: progress)
    monkeypatch.setattr(ingest, "_finish_publication_or_refuse", lambda *a, **k: None)

    def rotation(_conn, **kwargs):
        seen["rotation"] = kwargs["observation_ceiling"]
        return []

    def sep_phase(_conn, **kwargs):
        seen["sep"] = kwargs["source_observation_day"]
        return cursor

    monkeypatch.setattr(ingest.sep_reconciliation, "reconcile_next", rotation)
    monkeypatch.setattr(ingest, "_reconcile_sep_for_market_target", sep_phase)
    monkeypatch.setattr(
        ingest.maintenance, "reconcile_actions_if_due", lambda *a, **k: None)
    monkeypatch.setattr(ingest, "_prove_recent_frontier", lambda *a, **k: None)

    ingest.daily(
        conn, fetch=ingest.snapshot_source.fetch_table,
        resolve_identity=lambda row: row, today="2026-09-04")

    assert isinstance(seen["rotation"], dt.date)
    assert seen["rotation"] == seen["sep"]


def test_complete_sep_export_precedes_actions_authority(monkeypatch):
    source = _proof(10)
    local = _proof(11, "c", "d")
    order = []

    class ExportFetch:
        def __call__(self, *args, **kwargs):
            return iter(())

        def cleanup(self):
            order.append("cleanup")

    export_fetch = ExportFetch()
    monkeypatch.setattr(
        recon, "_complete_export_source",
        lambda **kwargs: (order.append("sep_export") or export_fetch, {"sep": True}))
    monkeypatch.setattr(
        recon, "_visible_bounds",
        lambda conn: (dt.date(2026, 1, 2), dt.date(2026, 9, 4)))
    monkeypatch.setattr(
        recon, "_fresh_actions_retirement_authority",
        lambda conn, **kwargs: order.append("actions") or {"actions": True})
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: local)
    monkeypatch.setattr(
        recon.sep_negative_space_guarded, "repair_local_only",
        lambda *a, **k: order.append("repair"))

    recon._repair_local_only_if_proved(
        object(), fetch=object(), start="2026-01-02", end="2026-09-04",
        observation_ceiling="2026-09-07", source=source, local=local,
        require_complete_export=True)

    assert order[:3] == ["sep_export", "actions", "repair"]
    assert order[-1] == "cleanup"


def test_composite_export_refreshes_actions_at_final_destructive_gate(monkeypatch):
    source = _proof(10)
    keys = [{"security_id": "P:1", "session": "2026-04-02", "ticker": "AAA"}]
    order = []
    final_actions = {"authority": "fresh-actions"}

    monkeypatch.setattr(
        guarded.core.recon, "_visible_bounds",
        lambda conn: (dt.date(2026, 1, 2), dt.date(2026, 9, 4)))
    monkeypatch.setattr(
        recon, "_fresh_actions_retirement_authority",
        lambda conn, **kwargs: order.append("actions") or final_actions)
    monkeypatch.setattr(
        guarded.core, "_source_only_local_proof",
        lambda *a, **k: order.append("local_recheck") or source)
    monkeypatch.setattr(
        guarded.core, "_local_only_keys",
        lambda *a, **k: order.append("key_recheck") or keys)

    evidence, final_keys = guarded._finalize_production_actions_authority(
        object(), source=source, start="2026-01-02", end="2026-09-04",
        keys=keys,
        source_authority_evidence={
            "authority": "nasdaq-data-link-table-export-composite/v1"},
        actions_authority_evidence={"authority": "earlier-actions"})

    assert order == ["actions", "local_recheck", "key_recheck"]
    assert evidence == final_actions
    assert final_keys == keys


def test_post_retirement_source_change_refuses_reconciliation_authority(monkeypatch):
    source_before = _proof(10, "a", "b")
    local_before = _proof(11, "c", "d")
    local_after = _proof(10, "a", "b")
    source_after = _proof(9, "e", "f")
    local_reads = iter([local_before, local_after])
    post = []

    monkeypatch.setattr(recon._core.store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(recon, "_source_fingerprint", lambda *a, **k: source_before)
    monkeypatch.setattr(recon, "_local_fingerprint", lambda *a, **k: next(local_reads))
    monkeypatch.setattr(
        recon, "_repair_local_only_if_proved", lambda *a, **k: local_after)
    monkeypatch.setattr(
        recon, "_post_retirement_source_proof",
        lambda *a, **k: post.append(True) or source_after)

    with pytest.raises(recon.SepKeysetDrift, match="normalized key set disagrees"):
        recon.reconcile_year(
            object(), fetch=object(), year=2026,
            start="2026-01-02", end="2026-09-04",
            observation_ceiling="2026-09-07", require_complete_export=True)

    assert post == [True]
