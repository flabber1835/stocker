"""PostgreSQL falsifiers for complete ACTIONS snapshots and split removal."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import terminal  # noqa: E402
from sentinel.feed import actions, calendar, ingest, maintenance, publication as P  # noqa: E402
from sentinel.feed import readiness  # noqa: E402
from sentinel.feed import rejection_audit as RA  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from sentinel.feed import universe  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

EVENT, PRIOR, END = "2024-06-03", "2024-05-31", "2024-06-03"
EMPTY_BOOK = {"held_tickers": (), "pending_terminal_tickers": ()}
FAILED_PRODUCTION_RUN = "7a0e20f4-9a51-4737-8fd6-ecbfadf39075"
CONTROL_ACTION = {
    "ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
    "action": "listed", "value": None, "contraticker": None,
}


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for table in (
                "sentinel_processed_sessions",
                "sentinel_anomaly_observation_events",
                "sentinel_action_generation_events",
                "sentinel_action_observations", "sentinel_action_generations",
                "sentinel_bar_split_repairs", "sentinel_bars",
                "sentinel_spy_total_return",
                "sentinel_actions", "sentinel_universe",
                "sentinel_corpus_publications", "feed_ingest_runs",
                "sentinel_corpus_anomalies"):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.ensure_schema(c)
    universe.write_universe(
        c,
        [{"permaticker": "SEC-AAA", "ticker": "AAA",
          "firstpricedate": "2020-01-01", "lastpricedate": None}],
        "2026-08-15")
    yield c
    c.close()


def _bar(session, ratio=1.0, close=50.0):
    from sentinel.feed import domains

    vendor = VendorBar(
        session=session, security_id="SEC-AAA", ticker="AAA",
        raw_close=close, raw_open=close, volume=1_000_000,
        split_ratio=ratio, dividend_per_share=0.0)
    return domains.NormalisedBar(close_signal=close, vendor=vendor)


def _establish_sep_cursor(conn, through: str):
    published = P.require_current(conn)
    return maintenance.establish_sep_cursor_after_complete_reconciliation(
        conn, through=dt.date.fromisoformat(through),
        publication_version=published.version)


def _publish_old_split(conn):
    run = S.IngestRun(conn, "old-split", date_from=PRIOR, date_to=END)
    action = [{"ticker": "AAA", "date": EVENT,
               "action": "split", "value": 2.0}]
    with S.corpus_write_lock(conn):
        S.write_actions(conn, action, run_id=run.progress.run_id,
                        window_start=PRIOR, window_end=END)
        S.write_bars(conn, [_bar(PRIOR), _bar(EVENT, ratio=2.0, close=51.0)],
                     run_id=run.progress.run_id, require_lock=True)
        S.write_anomalies(conn, [{
            "kind": "SPLIT_DISAGREEMENT", "ticker": "AAA",
            "session": EVENT, "detail": "old active blocker"}],
            run_id=run.progress.run_id, require_lock=True)
        run.finish("success")
        P.publish(conn, run_id=run.progress.run_id,
                  window_start=PRIOR, window_end=END)
    _establish_sep_cursor(conn, END)
    return run.progress.run_id


def _corrective_fetch(table, params=None):
    from sentinel.feed import sharadar

    params = dict(params or {})
    if table == sharadar.TICKERS:
        return [{"permaticker": "SEC-AAA", "ticker": "AAA",
                 "firstpricedate": "2020-01-01",
                 "lastpricedate": EVENT, "category": "Domestic"}]
    if table == sharadar.ACTIONS:
        return [CONTROL_ACTION] if params.get("date.gte") == "1900-01-01" else []
    if table == sharadar.SFP:
        return [{"ticker": "SPY", "date": EVENT, "closeadj": 500.0}]
    if table == sharadar.SEP:
        # Both domains move together.  EVENT therefore has a real predecessor-
        # based unsnapped ratio of 1.0 rather than the missing-predecessor
        # fallback that caused the reviewed false resolution.
        return [
            {"ticker": "AAA", "date": PRIOR, "close": 50.0,
             "closeunadj": 50.0, "open": 50.0, "volume": 1_000_000,
             "lastupdated": PRIOR},
            {"ticker": "AAA", "date": EVENT, "close": 51.0,
             "closeunadj": 51.0, "open": 51.0, "volume": 1_000_000,
             "lastupdated": EVENT},
        ]
    raise AssertionError(table)


def _active_split_ratio(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT " + P.effective_split_ratio("b") +
            " FROM sentinel_bars b WHERE security_id='SEC-AAA'"
            " AND session=%s AND " + P.visible_predicate("b"), (EVENT,))
        row = cur.fetchone()
    return None if row is None else float(row[0])


class TestPublishedActionReconciliation:
    def test_real_daily_removal_repairs_ratio_before_resolution(self, conn):
        old = _publish_old_split(conn)

        ingest.daily(conn, fetch=_corrective_fetch, today=END)
        assert _active_split_ratio(conn) == 1.0
        assert actions.active_rows(conn, start=PRIOR, end=END) == []

        with conn.cursor() as cur:
            cur.execute(
                "SELECT disposition,last_written_run_id"
                " FROM sentinel_action_observations"
                " WHERE ticker='AAA' AND session=%s AND action='split'"
                " ORDER BY observed_at,last_written_run_id", (EVENT,))
            history = [(d, str(r)) for d, r in cur.fetchall()]
        assert {d for d, _ in history} == {"PRESENT", "REMOVED"}
        assert any(r == old for _, r in history)

        audit = RA.audit(conn, start=PRIOR, end=END, **EMPTY_BOOK)
        assert audit.certifiable
        assert [d["kind"] for d in audit.split_dispositions] == [
            "SPLIT_RESOLVED_NO_EVENT"]

    def test_repeated_corrective_ingest_is_idempotent(self, conn):
        _publish_old_split(conn)
        ingest.daily(conn, fetch=_corrective_fetch, today=END)
        first = actions.active_rows(conn, start=PRIOR, end=END)
        ingest.daily(conn, fetch=_corrective_fetch, today=END)
        assert actions.active_rows(conn, start=PRIOR, end=END) == first == []
        assert _active_split_ratio(conn) == 1.0
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_action_observations"
                        " WHERE disposition='REMOVED'")
            assert cur.fetchone()[0] == 1

    def test_corrected_values_and_ordinary_actions_replace_only_their_keys(
            self, conn):
        old = S.IngestRun(conn, "old-actions")
        source = [
            {"ticker": "AAA", "date": EVENT, "action": "split", "value": 2},
            {"ticker": "BBB", "date": EVENT, "action": "dividend", "value": 1},
            {"ticker": "CCC", "date": "2024-06-01", "action": "acquisitionby",
             "value": None, "contraticker": "DDD"},
        ]
        with S.corpus_write_lock(conn):
            S.write_actions(conn, source, run_id=old.progress.run_id,
                            window_start="2024-06-01", window_end=END)
            old.finish("success")
            P.publish(conn, run_id=old.progress.run_id)

        new = S.IngestRun(conn, "new-actions")
        corrected = [dict(row) for row in source]
        corrected[0]["value"] = 3
        with S.corpus_write_lock(conn):
            S.write_actions(conn, corrected, run_id=new.progress.run_id,
                            window_start="2024-06-01", window_end=END)
            new.finish("success")
            P.publish(conn, run_id=new.progress.run_id)

        active = actions.active_rows(conn, start="2024-06-01", end=END)
        assert {(r["ticker"], r["action"], r["value"]) for r in active} == {
            ("AAA", "split", 3.0), ("BBB", "dividend", 1.0),
            ("CCC", "acquisitionby", None)}
        splits, dividends, _, _ = ingest._action_maps(
            conn, EVENT, EVENT)
        assert splits[("AAA", EVENT)] == 3.0
        assert dividends[("BBB", EVENT)] == 1.0
        terminal_rows = terminal.load_terminal_events(
            conn, start=EVENT, end=EVENT,
            resolve_identity=lambda ticker, session: f"SEC-{ticker}")
        assert any(row.ticker == "CCC" for row in terminal_rows.rows)

    def test_weekend_action_remains_mapped_to_effective_session(self, conn):
        run = S.IngestRun(conn, "weekend-action")
        with S.corpus_write_lock(conn):
            S.write_actions(conn, [{
                "ticker": "AAA", "date": "2024-06-01",
                "action": "split", "value": 2}],
                run_id=run.progress.run_id,
                window_start="2024-06-01", window_end=EVENT)
            run.finish("success")
            P.publish(conn, run_id=run.progress.run_id)
        splits, _, _, _ = ingest._action_maps(conn, EVENT, EVENT)
        assert calendar.session_on_or_after("2024-06-01") == EVENT
        assert splits[("AAA", EVENT)] == 2.0


class TestUnpublishedAndFailedCorrections:
    def test_failed_candidate_keeps_old_action_ratio_and_blocker(self, conn):
        _publish_old_split(conn)
        failed = S.IngestRun(conn, "failed-action-removal")
        with S.corpus_write_lock(conn):
            S.write_actions(conn, [], run_id=failed.progress.run_id,
                            window_start=PRIOR, window_end=END)
            failed.finish("failed", "corrective ingest failed")
            with pytest.raises(RuntimeError, match="cannot be published"):
                P.publish(conn, run_id=failed.progress.run_id)

        assert [(r["ticker"], r["action"]) for r in actions.active_rows(
            conn, start=PRIOR, end=END)] == [("AAA", "split")]
        assert _active_split_ratio(conn) == 2.0
        assert not RA.audit(conn, start=PRIOR, end=END,
                            **EMPTY_BOOK).certifiable

    def test_failed_publication_cannot_activate_removal_repair_or_resolution(
            self, conn):
        _publish_old_split(conn)
        with conn.cursor() as cur:
            cur.execute(
                "CREATE FUNCTION reject_action_publication() RETURNS trigger"
                " LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION"
                " 'test publication rejection'; END $$")
            cur.execute(
                "CREATE TRIGGER reject_action_publication BEFORE INSERT ON"
                " sentinel_corpus_publications FOR EACH ROW EXECUTE FUNCTION"
                " reject_action_publication()")
        conn.commit()

        with pytest.raises(Exception, match="test publication rejection"):
            ingest.daily(conn, fetch=_corrective_fetch, today=END)
        assert [(r["ticker"], r["action"]) for r in actions.active_rows(
            conn, start=PRIOR, end=END)] == [("AAA", "split")]
        with conn.cursor() as cur:
            cur.execute("SELECT " + P.effective_split_ratio("b") +
                        " FROM sentinel_bars b WHERE security_id='SEC-AAA'"
                        " AND session=%s", (EVENT,))
            assert float(cur.fetchone()[0]) == 2.0
        assert not RA.audit(conn, start=PRIOR, end=END,
                            **EMPTY_BOOK).certifiable
        assert not P.coherence(conn).coherent

        with conn.cursor() as cur:
            cur.execute("DROP TRIGGER reject_action_publication ON"
                        " sentinel_corpus_publications")
            cur.execute("DROP FUNCTION reject_action_publication()")
        conn.commit()
        ingest.daily(conn, fetch=_corrective_fetch, today=END)
        assert actions.active_rows(conn, start=PRIOR, end=END) == []
        assert _active_split_ratio(conn) == 1.0
        assert P.coherence(conn).coherent

    def test_same_run_retry_is_immutable_and_idempotent(self, conn):
        _publish_old_split(conn)
        run = S.IngestRun(conn, "same-run-retry")
        with S.corpus_write_lock(conn):
            S.write_actions(conn, [], run_id=run.progress.run_id,
                            window_start=PRIOR, window_end=END)
            S.write_actions(conn, [], run_id=run.progress.run_id,
                            window_start=PRIOR, window_end=END)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_action_observations"
                        " WHERE last_written_run_id=%s", (run.progress.run_id,))
            assert cur.fetchone()[0] == 1


def test_legacy_action_upgrade_retains_evidence_as_active_baseline(conn):
    with conn.cursor() as cur:
        cur.execute("DROP VIEW sentinel_active_actions")
        cur.execute("DROP TABLE sentinel_action_generation_events")
        cur.execute("DROP TABLE sentinel_action_observations")
        cur.execute("DROP TABLE sentinel_action_generations")
        cur.execute("INSERT INTO sentinel_actions"
                    " (ticker,session,action,value) VALUES"
                    " ('AAA',%s,'split',2)", (EVENT,))
    conn.commit()

    S.ensure_schema(conn)
    active = actions.active_rows(conn, start=PRIOR, end=END)
    assert [(r["ticker"], r["action"], r["value"]) for r in active] == [
        ("AAA", "split", 2.0)]
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_actions")
        assert cur.fetchone()[0] == 1


def _publish_actions(conn, rows, *, lo="2026-08-14", hi="2026-08-14"):
    run = S.IngestRun(conn, "actions-fixture", date_from=lo, date_to=hi)
    with S.corpus_write_lock(conn):
        S.write_actions(conn, rows, run_id=run.progress.run_id,
                        window_start=lo, window_end=hi)
        run.finish("success")
        P.publish(conn, run_id=run.progress.run_id,
                  window_start=lo, window_end=hi)
    return run.progress.run_id


def test_source_row_siblings_disappearance_restatement_and_dividends(conn):
    day = "2026-08-14"
    xrn_a = {"ticker": "XRN", "date": day, "action": "relation",
             "name": "XORTX", "value": None, "contraticker": "XRTXF",
             "contraname": None}
    xrn_b = {**xrn_a, "contraticker": "XORT"}
    dividends = [
        {"ticker": "AAA", "date": day, "action": "dividend", "value": .3},
        {"ticker": "AAA", "date": day, "action": "specialdividend",
         "value": 1.2},
    ]
    _publish_actions(conn, [xrn_a, xrn_a.copy(), xrn_b, *dividends])
    active = actions.active_rows(conn, start=day, end=day)
    assert len([row for row in active if row["ticker"] == "XRN"]) == 2
    splits, divs, _, ambiguous = ingest._action_maps(conn, day, day)
    assert splits == {} and ambiguous == []
    assert divs[("AAA", day)] == pytest.approx(1.5)
    terminal_result = terminal.load_terminal_events(
        conn, start=day, end=day,
        resolve_identity=lambda ticker, session: f"SEC-{ticker}")
    assert terminal_result.events == []
    assert len(terminal_result.rows) == 4
    relation_rows = [row for row in terminal_result.rows if row.ticker == "XRN"]
    assert len(relation_rows) == 2
    assert [row.reason for row in relation_rows] == [
        terminal.EXCLUDED_UNSUPPORTED, terminal.EXCLUDED_UNSUPPORTED]

    xrn_restatement = {**xrn_b, "value": 7}
    _publish_actions(conn, [xrn_a, xrn_restatement, *dividends])
    active = actions.active_rows(conn, start=day, end=day)
    xrn = [row for row in active if row["ticker"] == "XRN"]
    assert {(row["contraticker"], row["value"]) for row in xrn} == {
        ("XRTXF", None), ("XORT", 7.0)}
    with conn.cursor() as cur:
        cur.execute("SELECT disposition,COUNT(*) FROM sentinel_action_observations"
                    " WHERE ticker='XRN' GROUP BY disposition")
        history = dict(cur.fetchall())
    assert history["PRESENT"] == 4  # two old + two new; exact repeat was one
    assert history["REMOVED"] == 1  # only the restated old identity disappeared

    _publish_actions(conn, [xrn_a, *dividends])
    xrn = [row for row in actions.active_rows(conn, start=day, end=day)
           if row["ticker"] == "XRN"]
    assert [(row["contraticker"], row["value"]) for row in xrn] == [
        ("XRTXF", None)]


def test_conflicting_terminal_siblings_fail_closed_with_complete_evidence(conn):
    day = "2026-08-14"
    rows = [
        {"ticker": "AAA", "date": day, "action": "acquisitionby",
         "value": None, "contraticker": "BBB", "contraname": "Buyer One"},
        {"ticker": "AAA", "date": day, "action": "acquisitionby",
         "value": None, "contraticker": "CCC", "contraname": "Buyer Two"},
    ]
    _publish_actions(conn, rows)
    result = terminal.load_terminal_events(
        conn, start=day, end=day,
        resolve_identity=lambda ticker, session: "SEC-AAA")
    assert result.events == []
    assert len(result.rows) == 2
    assert result.resolved == [] and result.excluded == []
    assert {row.reason for row in result.unresolved} == {
        terminal.CONFLICTING_TERMINAL_TERMS}
    assert len({row.source_row_id for row in result.unresolved}) == 2
    assert result.conservation_holds()
    active = actions.active_rows(conn, start=day, end=day)
    assert {(row["contraticker"], row["contraname"]) for row in active} == {
        ("BBB", "Buyer One"), ("CCC", "Buyer Two")}


def test_economically_equivalent_terminal_siblings_apply_once_and_stay_audited(
        conn):
    # The production IGMS pair that exposed the defect: one reason-specific
    # row plus the vendor's generic delisting representation of the same event.
    day = "2025-08-13"
    rows = [
        {"ticker": "IGMS", "date": day, "action": "acquisitionby",
         "value": 76.6, "contraticker": "N/A", "contraname": None},
        {"ticker": "IGMS", "date": day, "action": "delisted",
         "value": 76.6, "contraticker": "N/A", "contraname": None},
    ]
    _publish_actions(conn, rows, lo=day, hi=day)
    result = terminal.load_terminal_events(
        conn, start=day, end=day,
        resolve_identity=lambda ticker, session: "110543")
    assert len(result.events) == 1
    assert result.events[0].security_id == "110543"
    assert result.events[0].cash_per_share is None
    assert result.events[0].kind.value != "WRITE_OFF"
    assert result.events[0].reference == (
        "actions/acquisitionby deal_value_musd=76.6")
    assert len(result.rows) == 2 and len(result.resolved) == 1
    assert result.excluded == []
    assert [row.reason for row in result.collapsed] == [
        terminal.COALESCED_TERMINAL_SOURCE]
    assert {row.action for row in result.rows} == {"acquisitionby", "delisted"}
    assert {row.security_id for row in result.rows} == {"110543"}
    assert len({row.source_row_id for row in result.rows}) == 2
    assert result.conservation_holds()
    assert result.normalized_stream_holds()
    active = actions.active_rows(conn, start=day, end=day)
    assert {(row["action"], float(row["value"]), row["contraticker"])
            for row in active} == {
        ("acquisitionby", 76.6, "N/A"), ("delisted", 76.6, "N/A")}

    # Source response order is not allowed to choose a different survivor.
    _publish_actions(conn, list(reversed(rows)), lo=day, hi=day)
    reversed_result = terminal.load_terminal_events(
        conn, start=day, end=day,
        resolve_identity=lambda ticker, session: "110543")
    assert reversed_result.events == result.events
    assert sorted((row.action, row.disposition, row.reason)
                  for row in reversed_result.rows) == sorted(
                      (row.action, row.disposition, row.reason)
                      for row in result.rows)


def test_pr86_observation_schema_upgrade_is_idempotent_and_preserves_history(conn):
    run_id = "00000000-0000-0000-0000-000000000086"
    with conn.cursor() as cur:
        cur.execute("DROP VIEW sentinel_active_actions")
        cur.execute("DROP TABLE sentinel_action_generation_events")
        cur.execute("DROP TABLE sentinel_action_observations")
        cur.execute("DROP TABLE sentinel_action_generations")
        cur.execute("CREATE TABLE sentinel_action_generations ("
                    "last_written_run_id UUID PRIMARY KEY,window_start DATE NOT NULL,"
                    "window_end DATE NOT NULL,source_rows BIGINT NOT NULL,"
                    "observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        cur.execute("CREATE TABLE sentinel_action_observations ("
                    "ticker TEXT NOT NULL,session DATE NOT NULL,action TEXT NOT NULL,"
                    "value DOUBLE PRECISION,contraticker TEXT,disposition TEXT NOT NULL,"
                    "last_written_run_id UUID NOT NULL,observed_at TIMESTAMPTZ NOT NULL "
                    "DEFAULT NOW(),PRIMARY KEY(ticker,session,action,last_written_run_id))")
        cur.execute("INSERT INTO feed_ingest_runs(run_id,kind,status)"
                    " VALUES(%s,'daily','failed')", (run_id,))
        cur.execute("INSERT INTO sentinel_action_generations"
                    "(last_written_run_id,window_start,window_end,source_rows)"
                    " VALUES(%s,%s,%s,1)", (run_id, EVENT, EVENT))
        cur.execute("INSERT INTO sentinel_action_observations"
                    "(ticker,session,action,value,contraticker,disposition,"
                    "last_written_run_id) VALUES('XRN',%s,'relation',NULL,NULL,"
                    "'PRESENT',%s)", (EVENT, run_id))
        cur.execute("INSERT INTO sentinel_actions(ticker,session,action,value,"
                    "contraticker) VALUES('XRN',%s,'relation',NULL,NULL)",
                    (EVENT,))
        cur.execute("CREATE VIEW sentinel_active_actions AS SELECT "
                    "ticker,session,action,value,contraticker,last_written_run_id,"
                    "0::BIGINT AS publication_version "
                    "FROM sentinel_action_observations WHERE disposition='PRESENT'")
    conn.commit()
    S.ensure_schema(conn)
    S.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT source_row_id,source_payload->>'action'"
                    " FROM sentinel_action_observations WHERE last_written_run_id=%s",
                    (run_id,))
        identity, action = cur.fetchone()
        cur.execute("SELECT state FROM sentinel_action_generation_events"
                    " WHERE generation_run_id=%s ORDER BY event_id DESC LIMIT 1",
                    (run_id,))
        state = cur.fetchone()[0]
        cur.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='public'"
                    " AND indexname='idx_sentinel_action_obs_window'")
        window_index = cur.fetchone()[0]
        cur.execute("SELECT source_row_id FROM sentinel_active_actions"
                    " WHERE ticker='XRN' AND session=%s", (EVENT,))
        baseline_identity = cur.fetchone()[0]
    assert identity.startswith("legacy-v1:") and action == "relation"
    assert baseline_identity == identity
    assert state == "ABORTED"
    assert "source_row_id" in window_index


def test_failed_13216_row_daily_candidate_is_retired_by_later_daily_retry(conn):
    # Published v2 at the August 13 frontier.
    S.write_bars(conn, [_bar("2026-08-13")])
    universe.write_universe(
        conn, [{"permaticker": "SEC-AAA", "ticker": "AAA"}],
        "2026-08-13")
    P.publish(conn, run_id=None, window_start="2026-08-13", window_end="2026-08-13")
    P.publish(conn, run_id=None, window_start="2026-08-13", window_end="2026-08-13")
    _establish_sep_cursor(conn, "2026-08-14")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO feed_ingest_runs(run_id,kind,status,date_from,date_to,"
                    "chunks_total,chunks_done,rows_written,error_message) VALUES"
                    "(%s,'daily','failed','2026-07-30','2026-08-14',4,1,13216,%s)",
                    (FAILED_PRODUCTION_RUN,
                     "ValueError at actions: conflicting duplicate ACTIONS rows for "
                     "XRN/2026-08-14/relation in one complete response"))
        cur.execute("INSERT INTO sentinel_universe(permaticker,ticker,snapshot_date,"
                    "last_written_run_id) SELECT 'P:'||g,'T'||g,'2026-08-14',%s"
                    " FROM generate_series(1,13216) g", (FAILED_PRODUCTION_RUN,))
    conn.commit()
    report = P.coherence(conn)
    assert report.version == 2
    assert report.unpublished_rows == 13216
    assert report.unpublished_runs == (FAILED_PRODUCTION_RUN,)
    assert S.reclaim_orphans(conn) == 0  # ordinary cmd_feed startup recovery

    tickers = [{"permaticker": f"P:{i}", "ticker": f"T{i}",
                "firstpricedate": "2020-01-01", "lastpricedate": "2026-08-14"}
               for i in range(1, 13217)]
    tickers.append({"permaticker": "SEC-AAA", "ticker": "AAA",
                    "firstpricedate": "2020-01-01", "lastpricedate": "2026-08-14"})

    def corrected_fetch(table, params=None):
        from sentinel.feed import sharadar
        params = dict(params or {})
        if table == sharadar.TICKERS:
            return tickers
        if table == sharadar.ACTIONS:
            return [
                {"ticker": "XRN", "date": "2026-08-14", "action": "relation",
                 "value": None, "contraticker": "XRTXF"},
                {"ticker": "XRN", "date": "2026-08-14", "action": "relation",
                 "value": None, "contraticker": "XORT"},
            ]
        if table == sharadar.SFP:
            return [{"ticker": "SPY", "date": day, "closeadj": 500.0 + i}
                    for i, day in enumerate(calendar.sessions_in_range(
                        params["date.gte"], params["date.lte"]))]
        if table == sharadar.SEP:
            rows = [
                {"ticker": "AAA", "date": "2026-08-13", "close": 50,
                 "closeunadj": 50, "open": 50, "volume": 1_000_000,
                 "lastupdated": "2026-08-13"},
                {"ticker": "AAA", "date": "2026-08-14", "close": 51,
                 "closeunadj": 51, "open": 51, "volume": 1_000_000,
                 "lastupdated": "2026-08-14"},
            ]
            if "lastupdated.gte" in params or "lastupdated.lte" in params:
                lo = params.get("lastupdated.gte", "0000-00-00")
                hi = params.get("lastupdated.lte", "9999-99-99")
                return [r for r in rows if lo <= r["lastupdated"] <= hi]
            lo = params.get("date.gte", "0000-00-00")
            hi = params.get("date.lte", "9999-99-99")
            return [r for r in rows if lo <= r["date"] <= hi]
        raise AssertionError(table)

    ingest.daily(conn, fetch=corrected_fetch, today="2026-08-15")
    assert P.coherence(conn).coherent
    assert S.latest_visible_session(conn) == "2026-08-14"
    readiness_checks = {
        check.name: check.status
        for check in readiness.check_readiness(conn, today="2026-08-15").checks}
    assert readiness_checks["corpus coherence"] == readiness.PASS
    assert readiness_checks["frontier benchmark"] == readiness.PASS
    assert readiness_checks["freshness"] == readiness.PASS
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_spy_total_return r WHERE "
                    + P.visible_predicate("r"))
        assert cur.fetchone()[0] == 41
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_universe"
            " WHERE last_written_run_id=%s", (FAILED_PRODUCTION_RUN,))
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_universe"
            " WHERE snapshot_date='2026-08-15'")
        assert cur.fetchone()[0] == 13217
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_universe"
            " WHERE snapshot_date='2026-08-13'"
            "   AND last_written_run_id IS NULL")
        assert cur.fetchone()[0] == 1, "published history was preserved"
        # Historical maintenance can complete after the daily retry, so the
        # newest successful run overall is not necessarily the daily operation
        # this assertion owns.
        cur.execute(
            "SELECT date_to FROM feed_ingest_runs"
            " WHERE status='success' AND kind='daily'"
            " ORDER BY completed_at DESC LIMIT 1")
        assert str(cur.fetchone()[0]) == "2026-08-15"
        cur.execute("SELECT COUNT(*) FROM sentinel_action_generation_events e"
                    " JOIN LATERAL (SELECT state FROM sentinel_action_generation_events"
                    " x WHERE x.generation_run_id=e.generation_run_id ORDER BY event_id"
                    " DESC LIMIT 1) latest ON TRUE WHERE latest.state='PENDING'")
        assert cur.fetchone()[0] == 0
    publication = P.require_current(conn)
    assert publication.evidence["retired_failed_universe_candidates"] == [{
        "run_id": FAILED_PRODUCTION_RUN, "rows": 13216}]


def test_later_daily_retry_rewrites_failed_bar_and_spy_owners(conn):
    S.write_bars(conn, [_bar("2026-08-13")])
    P.publish(conn, window_start="2026-08-13", window_end="2026-08-13")
    _establish_sep_cursor(conn, "2026-08-13")
    failed = S.IngestRun(
        conn, "daily", date_from="2026-07-30", date_to="2026-08-14")
    with S.corpus_write_lock(conn):
        S.write_bars(conn, [_bar("2026-08-14", close=51.0)],
                     run_id=failed.progress.run_id, require_lock=True)
        S.write_spy_total_return(
            conn, [{"ticker": "SPY", "date": "2026-08-14",
                    "closeadj": 501.0}],
            run_id=failed.progress.run_id, require_lock=True)
        failed.finish("failed", "fixture stopped after destructive writes")
    assert P.coherence(conn).unpublished_rows == 2

    def corrected_fetch(table, params=None):
        from sentinel.feed import sharadar
        params = dict(params or {})
        if table == sharadar.TICKERS:
            return [{"permaticker": "SEC-AAA", "ticker": "AAA",
                     "firstpricedate": "2020-01-01",
                     "lastpricedate": "2026-08-14"}]
        if table == sharadar.ACTIONS:
            return [CONTROL_ACTION] if params.get("date.gte") == "1900-01-01" else []
        if table == sharadar.SFP:
            return [{"ticker": "SPY", "date": day,
                     "closeadj": 600.0 + i}
                    for i, day in enumerate(calendar.sessions_in_range(
                        params["date.gte"], params["date.lte"]))]
        if table == sharadar.SEP:
            rows = [
                {"ticker": "AAA", "date": "2026-08-13", "close": 50,
                 "closeunadj": 50, "open": 50, "volume": 1_000_000,
                 "lastupdated": "2026-08-13"},
                {"ticker": "AAA", "date": "2026-08-14", "close": 52,
                 "closeunadj": 52, "open": 52, "volume": 1_000_000,
                 "lastupdated": "2026-08-14"},
            ]
            if "lastupdated.gte" in params or "lastupdated.lte" in params:
                lo = params.get("lastupdated.gte", "0000-00-00")
                hi = params.get("lastupdated.lte", "9999-99-99")
                return [r for r in rows if lo <= r["lastupdated"] <= hi]
            lo = params.get("date.gte", "0000-00-00")
            hi = params.get("date.lte", "9999-99-99")
            return [r for r in rows if lo <= r["date"] <= hi]
        raise AssertionError(table)

    ingest.daily(conn, fetch=corrected_fetch, today="2026-08-15")
    assert P.coherence(conn).coherent
    with conn.cursor() as cur:
        for table in ("sentinel_bars", "sentinel_spy_total_return"):
            cur.execute(
                f"SELECT COUNT(*) FROM {table} WHERE last_written_run_id=%s",
                (failed.progress.run_id,))
            assert cur.fetchone()[0] == 0
    assert "retired_failed_universe_candidates" not in P.require_current(
        conn).evidence


def test_universe_retirement_never_deletes_unrewritten_economic_keys(conn):
    failed = S.IngestRun(
        conn, "daily", date_from="2026-07-30", date_to="2026-08-14")
    with S.corpus_write_lock(conn):
        S.write_bars(conn, [_bar("2026-08-14")],
                     run_id=failed.progress.run_id, require_lock=True)
        universe.write_universe(
            conn, [{"permaticker": "FAILED-ONLY", "ticker": "OLD"}],
            "2026-08-14", run_id=failed.progress.run_id)
        failed.finish("failed", "fixture left a destructive bar owner")

    retry = S.IngestRun(
        conn, "daily", date_from="2026-07-31", date_to="2026-08-15")
    with S.corpus_write_lock(conn):
        universe.write_universe(
            conn, [{"permaticker": "SEC-AAA", "ticker": "AAA"}],
            "2026-08-15", run_id=retry.progress.run_id)
        retry.finish("success")
        with pytest.raises(P.CorpusIncoherent, match="bars.*1"):
            P.publish(conn, run_id=retry.progress.run_id,
                      window_start="2026-07-31", window_end="2026-08-15")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_bars"
                    " WHERE last_written_run_id=%s", (failed.progress.run_id,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM sentinel_universe"
                    " WHERE last_written_run_id=%s", (failed.progress.run_id,))
        assert cur.fetchone()[0] == 1, "failed publication rolled retirement back"


def test_feed_startup_durably_aborts_failed_pending_lifecycle(conn):
    run = S.IngestRun(conn, "failed-pending", date_from=EVENT, date_to=EVENT)
    with S.corpus_write_lock(conn):
        S.write_actions(conn, [{"ticker": "XRN", "date": EVENT,
                                "action": "relation", "value": None}],
                        run_id=run.progress.run_id,
                        window_start=EVENT, window_end=EVENT)
        S.write_anomalies(conn, [{"kind": "UNUSABLE_DIVIDEND", "ticker": "XRN",
                                  "session": EVENT, "detail": "fixture"}],
                          run_id=run.progress.run_id, require_lock=True)
        # Model an older/interrupted finisher that persisted status but not the
        # lifecycle terminal events.
        with conn.cursor() as cur:
            cur.execute("UPDATE feed_ingest_runs SET status='failed',"
                        "completed_at=NOW() WHERE run_id=%s",
                        (run.progress.run_id,))
        conn.commit()
    assert S.reclaim_orphans(conn) == 0
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM sentinel_action_generation_events"
                    " WHERE generation_run_id=%s ORDER BY event_id DESC LIMIT 1",
                    (run.progress.run_id,))
        assert cur.fetchone()[0] == "ABORTED"
        cur.execute("SELECT e.state FROM sentinel_anomaly_observation_events e"
                    " JOIN sentinel_corpus_anomalies a"
                    " ON a.observation_id=e.observation_id"
                    " WHERE a.last_written_run_id=%s ORDER BY e.event_id DESC LIMIT 1",
                    (run.progress.run_id,))
        assert cur.fetchone()[0] == "ABORTED"
        cur.execute("SELECT COUNT(*) FROM sentinel_anomaly_observation_events e"
                    " JOIN LATERAL (SELECT state FROM sentinel_anomaly_observation_events"
                    " x WHERE x.observation_id=e.observation_id ORDER BY event_id DESC"
                    " LIMIT 1) latest ON TRUE WHERE latest.state='PENDING'")
        assert cur.fetchone()[0] == 0
