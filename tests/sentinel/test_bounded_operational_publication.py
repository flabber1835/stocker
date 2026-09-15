"""Operational replacement is scoped, atomic, and preserves older authority."""
from datetime import date
import json

import pytest

from sentinel.feed import operational_source as source, publication as P
from sentinel.feed import identity_rebuild as IR, recovery as R, store as S
from sentinel.feed import maintenance as M, maintenance_impl as MI
from tests.sentinel.test_issue_246_identity_rebuild import (
    pg, conn, _publish_base, _candidate_rows, _bar,
)


@pytest.fixture()
def capture(monkeypatch):
    value = source.OperationalCapture(*source.price_window("2026-08-21"))
    monkeypatch.setattr(source, "current", lambda: value)
    try:
        yield value
    finally:
        value.close()


def old_bar(conn, owner, *, split=1):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id,session,ticker,close_signal,"
            "close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share,"
            "last_written_run_id) VALUES ('P2','2006-08-21','LBRDK',10,10,10,1000,%s,0,%s)",
            (split, owner))
    conn.commit()


def test_bounded_recovery_does_not_widen_to_failed_old_rows(conn, capture):
    _publish_base(conn)
    failed = S.IngestRun(conn, "daily", date_from="2006-08-21", date_to="2006-08-21")
    old_bar(conn, failed.progress.run_id)
    failed.finish("failed")
    from sentinel.feed import ingest
    assert ingest._single_failed_live_candidate(conn) is None
    with S.corpus_write_lock(conn):
        plan = R.prepare_full_reseed(conn, date_from=capture.start, date_to=capture.end)
    assert (plan.date_from, plan.date_to) == (capture.start, capture.end)
    assert plan.retired_run_ids == (failed.progress.run_id,)
    assert P.operational_coherence(conn, frontier=capture.end).coherent
    assert not P.full_historical_coherence(conn).coherent


@pytest.mark.parametrize("split", [1, 2])
def test_bounded_publication_retains_history_but_never_ignores_old_split(
        conn, capture, split):
    base = _publish_base(conn)
    failed = S.IngestRun(conn, "daily", date_from="2006-08-21", date_to="2006-08-21")
    old_bar(conn, failed.progress.run_id, split=split)
    failed.finish("failed")
    from sentinel.feed import ingest
    candidate = ingest._single_failed_live_candidate(conn)
    assert (candidate is None) == (split == 1)
    run = S.IngestRun(conn, "daily", date_from="2026-08-20", date_to=capture.end)
    run.finish("success")
    if split == 2:
        with pytest.raises(P.CorpusIncoherent, match="unresolved operational inputs"):
            P.publish(conn, run_id=run.progress.run_id,
                      window_start="2026-08-20", window_end=capture.end)
        assert P.require_current(conn).version == base.version
    else:
        result = P.publish(conn, run_id=run.progress.run_id,
                           window_start="2026-08-20", window_end=capture.end)
        assert result.previous_version == base.version
        assert P.operational_coherence(conn, frontier=capture.end).coherent
    with conn.cursor() as cur:
        cur.execute("SELECT last_written_run_id::text FROM sentinel_bars WHERE session='2006-08-21'")
        assert cur.fetchone()[0] == failed.progress.run_id


def test_bounded_identity_replacement_keeps_old_published_keys(conn, capture):
    base = _publish_base(conn)
    old_bar(conn, base.run_id)
    with S.corpus_write_lock(conn):
        plan = IR.prepare(conn, date_from=capture.start, date_to=capture.end,
                          observed_on="2026-08-24")
        assert plan.scope == "OPERATIONAL"
        run = S.IngestRun(conn, "seed", date_from=plan.market_start, date_to=plan.market_end)
        IR.record_plan(conn, run_id=run.progress.run_id, plan=plan)
        assert IR.load_plan(conn, run_id=run.progress.run_id) == plan
        rows = IR.verify_candidate(conn, run_id=run.progress.run_id, plan=plan,
                                   rows=_candidate_rows())
        IR.write_bars_claiming(conn, [_bar("P1", "BTLN"), _bar("P3", "KEEP"), _bar("P4", "NEW")],
                              run_id=run.progress.run_id, batch_size=2)
        result = IR.publish_completed_run(conn, run=run, rows=rows, plan=plan)
    assert result.previous_version == base.version
    with conn.cursor() as cur:
        cur.execute("SELECT ticker,last_written_run_id::text FROM sentinel_bars "
                    "WHERE security_id='P2' ORDER BY session")
        assert cur.fetchall() == [("LBRDK", base.run_id)]
    assert P.operational_coherence(conn, frontier=capture.end).coherent


def test_operational_cdc_watermark_cannot_authorize_manual_full_history(conn, capture, monkeypatch):
    base = _publish_base(conn)
    cursor = MI.establish_sep_cursor_after_seed(
        conn, through=date(2026, 8, 24), publication_version=base.version)
    assert cursor.price_window == (capture.start, capture.end)
    assert M.load_sep_cursor(conn) == cursor
    monkeypatch.setattr(source, "current", lambda: None)
    with S.corpus_write_lock(conn):
        with pytest.raises(M.SharadarMutationRefused, match="not full retained history"):
            M.reconcile_sep_mutations(
                conn, through="2026-08-24", fetch=lambda *a: pytest.fail("unscoped source read"))
    complete = MI.establish_sep_cursor_after_seed(
        conn, through=date(2026, 8, 24), publication_version=base.version)
    assert complete.price_window is None
    assert M.load_sep_cursor(conn).price_window is None


@pytest.mark.parametrize("cold", [False, True])
def test_real_go_readonly_probe_never_downloads_sep_twice(conn, monkeypatch, capsys, cold):
    from tests.sentinel.test_go_readonly_data_preflight import preflight
    from tests.sentinel.test_bounded_operational_feed import install_source
    from sentinel.feed import calendar
    if not cold:
        _publish_base(conn)
    calls = install_source(monkeypatch)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://isolated-test")
    monkeypatch.setattr(calendar, "latest_closed_session", lambda: "2026-08-21")
    class BorrowedConnection:
        cursor = conn.cursor
        rollback = conn.rollback
        def close(self):
            pass
    monkeypatch.setattr(S, "connect", lambda *a: BorrowedConnection())
    conn.rollback()  # The probe must start on a fresh read-only transaction.
    exec(preflight._READ_ONLY_CODE, {})
    assert '"status": "RECOVERY_REQUIRED"' in capsys.readouterr().out
    assert any(c[0] == "probe" for c in calls)
    assert not any(c[0] == "download" for c in calls)


@pytest.mark.parametrize("scope", [None, ["2006-01-01"], ["2026-02-30", "2026-09-14"],
                                 ["2026-09-14", "2026-09-01"]])
def test_malformed_operational_scope_refuses(scope):
    with pytest.raises(M.SharadarMutationRefused, match="invalid price scope"):
        MI._cursor_price_window({"price_window": scope}, name=MI.SEP_CURSOR_NAME)


@pytest.mark.parametrize("status,expected,reason", [
    ("fresh", "RECOVERY_REQUIRED", "CORPUS_SCHEMA_NOT_INSTALLED"),
    ("creating", "REFUSED", "SOURCE_EXPORT_UNAVAILABLE"),
])
def test_container_probe_export_fixture_preserves_cold_preflight(
        conn, monkeypatch, capsys, status, expected, reason):
    import httpx
    from tests.sentinel.test_go_readonly_data_preflight import ROOT
    # Host scripts are mirrored under the inspection root, not /work/scripts.
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import test_go_probe_runtime_integration as driver
    from sentinel.feed import calendar, snapshot_export

    monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://isolated-test")
    monkeypatch.setattr(calendar, "latest_closed_session", lambda: "2026-08-21")
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("CI probe contacted a vendor"))
    monkeypatch.setattr(snapshot_export, "probe_snapshot", snapshot_export.probe_snapshot)
    monkeypatch.setattr(snapshot_export, "download_snapshot", lambda *a, **kw: pytest.fail("CI probe downloaded a file"))
    class BorrowedConnection:
        cursor = conn.cursor
        rollback = conn.rollback
        def close(self):
            pass
    monkeypatch.setattr(S, "connect", lambda *a: BorrowedConnection())
    conn.rollback()
    exec(driver._source_export_fixture(driver.preflight._READ_ONLY_CODE, status), {})
    output = capsys.readouterr().out
    report = json.loads(next(line[len(driver.preflight.MARKER):]
                             for line in output.splitlines() if line.startswith(driver.preflight.MARKER)))
    assert report["status"] == expected
    assert report["reason_code"] == reason
    assert P.current(conn) is None


def test_canonical_cold_seed_publishes_300_sessions_with_one_sep_acquisition(conn, monkeypatch):
    from datetime import datetime, timezone
    from sentinel.feed import coherence, ingest, sharadar, snapshot_export as export
    from sentinel.feed.corporate_action_authority import CASH_ADJUDICATION_AUTHORITIES
    from sentinel import backup_guard
    from tests.sentinel.test_issue_178_seed_reference_bracketing import _ticker, _sep
    start, end = source.price_window("2026-04-30")
    sessions = source.calendar.sessions_in_range(start, end)
    now = datetime.now(timezone.utc)
    ticker = dict(_ticker(), firstpricedate=start, lastpricedate=end)
    calls = []
    def probe(table, *, params=None):
        return export.ExportSnapshot(table, dict(params or {}), "https://unit.invalid/file", now, now)
    def download(snapshot, *, required):
        calls.append((snapshot.table, snapshot.params))
        if snapshot.table == sharadar.TICKERS:
            rows = [ticker]
        elif snapshot.table == sharadar.ACTIONS:
            rows = [{"date": start, "ticker": "AAA", "action": "dividend", "value": "0",
                     "name": None, "contraticker": None, "contraname": None}]
            rows.extend({"date": r["source_action_date"], "ticker": r["ticker"],
                         "action": r["source_action"], "value": r["stale_source_amount"],
                         "name": None, "contraticker": None, "contraname": None}
                        for r in CASH_ADJUDICATION_AUTHORITIES if r["source_action_date"] <= end)
        else:
            rows = [dict(_sep(s), lastupdated=now.date().isoformat()) for s in sessions
                    if snapshot.params["date.gte"] <= s <= snapshot.params["date.lte"]]
        return rows, {"authority": "nasdaq-data-link-table-export/v1", "table": snapshot.table,
                      "file_status": "fresh", "data_snapshot_time": now.isoformat(),
                      "last_refreshed_time": now.isoformat(), "source_rows": len(rows),
                      "file_sha256": "a" * 64, "window": snapshot.params}
    def paged(table, params=None, **kwargs):
        if table == sharadar.TICKERS:
            return [ticker]
        assert table == sharadar.SFP, "SEP and ACTIONS must never paginate"
        return [{"ticker": fund, "date": s, "open": 99, "close": 100, "closeadj": 100, "closeunadj": 100,
                 "volume": 1000000} for fund in ("SPY", "BIL") for s in sessions
                if params["date.gte"] <= s <= params["date.lte"]]
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-key")
    monkeypatch.setattr(export, "probe_snapshot", probe)
    monkeypatch.setattr(export, "download_snapshot", download)
    monkeypatch.setattr(export, "require_actions_refresh",
                        lambda **k: {"last_refreshed_time": now.isoformat(), "data_snapshot_time": now.isoformat()})
    monkeypatch.setattr(sharadar.DEFAULT_SOURCE, "fetch_table", paged)
    # This small deterministic source exercises all production proof plumbing;
    # calibrated 4,000-security floor falsifiers remain separate and unchanged.
    monkeypatch.setattr(coherence, "MIN_SEED_SESSION_ROWS", 1)
    monkeypatch.setattr(backup_guard, "require_writes_permitted", lambda *a, **k: None)
    monkeypatch.setattr(backup_guard, "require_bulk_writes_permitted", lambda *a, **k: None)
    from sentinel.feed import outage_recovery
    result = outage_recovery.catch_up(conn, target_session=end)
    assert result.mode == "BOUNDED_INITIAL_SEED"
    published = P.require_current(conn)
    assert published.evidence["operational_source"]["window"] == [start, end]
    assert M.load_sep_cursor(conn).price_window == (start, end)
    with conn.cursor() as cur:
        cur.execute("SELECT count(distinct session),min(session),max(session) FROM sentinel_bars")
        count, lo, hi = cur.fetchone()
    assert (count, str(lo), str(hi)) == (300, start, end)
    assert len([c for c in calls if c[0] == sharadar.SEP]) == len(list(source._months(start, end)))
    monkeypatch.setattr(ingest.sep_reconciliation, "reconcile_next",
                        lambda *a, **k: pytest.fail("automatic historical-year audit"))
    repeated = outage_recovery.catch_up(conn, target_session=end, reobserve_current=True)
    assert repeated.mode == "ALREADY_CURRENT"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feed_ingest_runs WHERE kind='seed'")
        assert cur.fetchone()[0] == 1, "normal re-observation must not reseed"
