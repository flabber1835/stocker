"""PostgreSQL falsifiers for complete ACTIONS snapshots and split removal."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import terminal  # noqa: E402
from sentinel.feed import actions, calendar, ingest, publication as P  # noqa: E402
from sentinel.feed import rejection_audit as RA  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

EVENT, PRIOR, END = "2024-06-03", "2024-05-31", "2024-06-03"
EMPTY_BOOK = {"held_tickers": (), "pending_terminal_tickers": ()}


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
                "sentinel_anomaly_observation_events",
                "sentinel_action_generation_events",
                "sentinel_action_observations", "sentinel_action_generations",
                "sentinel_bar_split_repairs", "sentinel_bars",
                "sentinel_actions", "sentinel_universe",
                "sentinel_corpus_publications", "feed_ingest_runs",
                "sentinel_corpus_anomalies"):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def _bar(session, ratio=1.0, close=50.0):
    return VendorBar(
        session=session, security_id="SEC-AAA", ticker="AAA",
        raw_close=close, raw_open=close, volume=1_000_000,
        split_ratio=ratio, dividend_per_share=0.0)


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
    return run.progress.run_id


def _corrective_fetch(table, params=None):
    from sentinel.feed import sharadar

    if table == sharadar.TICKERS:
        return [{"permaticker": "SEC-AAA", "ticker": "AAA",
                 "firstpricedate": "2020-01-01",
                 "lastpricedate": EVENT, "category": "Domestic"}]
    if table == sharadar.ACTIONS:
        return []
    if table == sharadar.SFP:
        return [{"ticker": "SPY", "date": EVENT, "closeadj": 500.0}]
    if table == sharadar.SEP:
        # Both domains move together.  EVENT therefore has a real predecessor-
        # based unsnapped ratio of 1.0 rather than the missing-predecessor
        # fallback that caused the reviewed false resolution.
        return [
            {"ticker": "AAA", "date": PRIOR, "close": 50.0,
             "closeunadj": 50.0, "open": 50.0, "volume": 1_000_000},
            {"ticker": "AAA", "date": EVENT, "close": 51.0,
             "closeunadj": 51.0, "open": 51.0, "volume": 1_000_000},
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
        splits, dividends, _ = ingest._action_maps(
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
        splits, _, _ = ingest._action_maps(conn, EVENT, EVENT)
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
