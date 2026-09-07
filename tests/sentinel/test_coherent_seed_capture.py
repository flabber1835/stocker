from types import SimpleNamespace

import pytest

from sentinel.feed import ingest, seed_capture, sharadar, snapshot_export
from sentinel.feed.authority import VendorPublicationUnstable
from tests.sentinel.test_sharadar_snapshot_export import _Http, _Response, _status
from tests.sentinel.test_issue_178_seed_reference_bracketing import _ticker, _sep
from tests.sentinel.test_issue_246_identity_rebuild import (
    pg, conn, _publish_base, _candidate_rows,
)


def evidence():
    return {"authority": "nasdaq-data-link-table-export/v1", "table": "ACTIONS",
            "file_status": "fresh", "data_snapshot_time": "2026-08-19T22:00:00Z",
            "last_refreshed_time": "2026-08-19T21:59:00Z", "source_rows": 1}


@pytest.mark.parametrize("status", [
    _status(refreshed="2026-08-19T22:01:00Z", snapshot="2026-08-19T22:02:00Z"),
    _status(state="regenerating"),
    _status(snapshot="2026-08-19T21:58:00Z"),
])
def test_changed_actions_refresh_refuses(status, monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-key")
    http = _Http([_Response(payload=status)])
    with pytest.raises(VendorPublicationUnstable):
        snapshot_export.require_actions_refresh(
            through="2026-08-19", evidence=evidence(), http=http)
    assert len(http.client.calls) == 1


def test_refresh_corroboration_downloads_no_second_file(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-key")
    http = _Http([_Response(payload=_status())])
    snapshot_export.require_actions_refresh(
        through="2026-08-19", evidence=evidence(), http=http)
    assert len(http.client.calls) == 1
    assert http.client.calls[0][1]["qopts.export"] == "true"


def test_single_actions_file_replayed_after_independent_refresh(monkeypatch):
    calls = []
    def export(**kwargs):
        calls.append("export")
        return [{"date": "2026-08-18", "action": "dividend", "value": "1"}], evidence()
    def refresh(**kwargs):
        calls.append("refresh")
        return evidence()
    monkeypatch.setattr(snapshot_export, "fetch_complete_actions", export)
    monkeypatch.setattr(snapshot_export, "require_actions_refresh", refresh)
    source = seed_capture.ActionsSnapshotSource(lambda *a, **k: pytest.fail("paged ACTIONS"))
    params = sharadar.date_params("1900-01-01", "2026-08-19")
    first = list(source(sharadar.ACTIONS, params))
    first[0]["value"] = "corrupted consumer"
    assert list(source(sharadar.ACTIONS, params))[0]["value"] == "1"
    assert calls == ["export", "refresh"]
    with pytest.raises(ValueError, match="request changed"):
        list(source(sharadar.ACTIONS, sharadar.date_params("1900-01-01", "2026-08-20")))


def test_capture_failure_closes_files_and_refuses_unknown_request():
    with seed_capture.CapturedRows() as captured:
        captured.capture(lambda *a: [{"date": "2026-08-18"}], sharadar.SEP, {"x": "1"})
        spool = next(iter(captured.files.values()))
        with pytest.raises(KeyError):
            list(captured(sharadar.SEP, {"x": "2"}))
    assert spool.closed


def test_real_seed_guard_checks_refresh_before_database_replay(monkeypatch):
    from sentinel.feed import coherence
    events = []
    def raw(table, params=None, **kwargs):
        events.append(table)
        if table == sharadar.TICKERS:
            return [_ticker()]
        if table == sharadar.SFP:
            return [{"ticker": "SPY", "date": "2026-08-18", "closeadj": 100}]
        assert table == sharadar.SEP
        return [_sep("2026-08-18")]
    monkeypatch.setattr(snapshot_export, "fetch_complete_actions", lambda **k: (
        [{"date": "2026-08-18", "ticker": "AAA", "action": "dividend",
          "value": "0.25"}], evidence()))
    def changed(**kwargs):
        events.append("refresh")
        raise VendorPublicationUnstable("changed")
    monkeypatch.setattr(snapshot_export, "require_actions_refresh", changed)
    guarded = coherence.StableSharadarFetch(seed_capture.ActionsSnapshotSource(raw))
    with seed_capture.CapturedRows() as captured:
        captured.capture(guarded, sharadar.TICKERS)
        captured.capture(guarded, sharadar.ACTIONS,
                         sharadar.date_params("1900-01-01", "2026-08-19"))
        captured.capture(guarded, sharadar.SFP,
                         sharadar.date_params("2026-08-17", "2026-08-19"))
        with pytest.raises(VendorPublicationUnstable):
            captured.capture(guarded, sharadar.SEP,
                             sharadar.date_params("2026-08-17", "2026-08-19"))
        assert all(key[0] != sharadar.SEP for key in captured.files)
    assert events == ["TICKERS", "SFP", "SEP", "SEP", "refresh"]


def test_postgres_identity_capture_failure_preserves_published_corpus(conn, monkeypatch):
    from sentinel.feed import coherence, publication, store
    base = _publish_base(conn)
    def raw(table, params=None, **kwargs):
        if table == sharadar.TICKERS:
            return _candidate_rows()
        if table == sharadar.SFP:
            return [{"ticker": "SPY", "date": "2026-08-20", "closeadj": 100}]
        return [dict(_sep("2026-08-20"), ticker="BTLN")]
    monkeypatch.setattr(snapshot_export, "fetch_complete_actions", lambda **k: (
        [{"date": "2026-08-20", "ticker": "BTLN", "action": "dividend", "value": "0"}],
        evidence()))
    def changed(**kwargs):
        raise VendorPublicationUnstable("changed during capture")
    monkeypatch.setattr(snapshot_export, "require_actions_refresh", changed)
    # Small fixture exercises real identity preflight and PostgreSQL state;
    # the existing exact-population tests cover the 4,000-security seed floor.
    def guarded_source(fetch, **kwargs):
        guarded = coherence.StableSharadarFetch(kwargs["acquisition_fetch"])
        return object(), guarded
    monkeypatch.setattr(ingest, "_seed_source", guarded_source)
    recovery = SimpleNamespace(date_from="2026-08-20", date_to="2026-08-21",
                               retired_run_ids=())
    with store.corpus_write_lock(conn):
        with pytest.raises(VendorPublicationUnstable, match="during capture"):
            seed_capture.run_generation(
                conn, recovery_plan=recovery, fetch=raw,
                final_hi="2026-08-21", boundary="2026-08-24")
    assert publication.require_current(conn).version == base.version
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feed_ingest_runs")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT ticker FROM sentinel_bars ORDER BY ticker")
        assert [row[0] for row in cur.fetchall()] == ["GGRP", "KEEP", "LBRDK"]


@pytest.mark.parametrize("identity_changed", [False, True])
@pytest.mark.parametrize("capture_fails", [False, True])
def test_acquisition_precedes_candidate_and_identity_reuses_source(
        monkeypatch, identity_changed, capture_fails):
    events = []
    tracked = SimpleNamespace(max_sep_lastupdated=None)
    def guarded(table, params=None):
        events.append("capture_" + table)
        if table == sharadar.SEP and capture_fails:
            raise VendorPublicationUnstable("refresh changed")
        return [{"table": table, "date": "2026-08-18"}]
    monkeypatch.setattr(ingest, "_seed_source", lambda *a, **k: (tracked, guarded))
    def preflight(*args):
        events.append("preflight")
        if identity_changed:
            raise ingest.universe.HistoricalIdentityMutation("changed")
    monkeypatch.setattr(ingest.identity_refresh, "assert_candidate_history_safe", preflight)
    plan = object()
    monkeypatch.setattr(ingest.identity_rebuild, "prepare", lambda *a, **k: plan)
    authority = SimpleNamespace(run_started=None, before_success=None, record_identity_plan=None)
    monkeypatch.setattr(ingest, "_seed_authority", lambda **k: authority)
    def mutate(conn, **kwargs):
        events.append("candidate")
        assert list(kwargs["fetch"](sharadar.TICKERS))[0]["table"] == "TICKERS"
        if identity_changed:
            assert kwargs["identity_rebuild_plan"] is plan
        return "done"
    monkeypatch.setattr(ingest.reseed, "full_reseed_locked", mutate)
    monkeypatch.setattr(ingest, "_ordinary_seed_generation", mutate)
    recovery = SimpleNamespace(date_from="2026-08-17", date_to="2026-08-19", retired_run_ids=())
    def run():
        return seed_capture.run_generation(
            object(), recovery_plan=recovery, fetch=object(),
            final_hi="2026-08-19", boundary="2026-08-19")
    if capture_fails:
        with pytest.raises(VendorPublicationUnstable):
            run()
        assert "candidate" not in events
    else:
        assert run() == ("done", tracked)
        assert events[-1] == "candidate"
    assert events.count("capture_TICKERS") == 1
