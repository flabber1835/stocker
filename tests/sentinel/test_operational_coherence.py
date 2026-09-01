"""Operational causal closure versus full retained-history coherence."""
from __future__ import annotations

import json

import pytest

from tests.support.postgres import _EphemeralPostgres, drop_public_tables

from sentinel import schema as behavioral_schema
from sentinel.core import loader
from sentinel.feed import publication as P
from sentinel.feed import store as S
from sentinel.feed import universe as U
from sentinel.feed import operational_coherence as O
from sentinel.feed.operational_coherence import OPERATIONAL_HISTORY_SESSIONS
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES

FRONTIER = "2026-08-31"
OLD = "2018-08-31"
CURRENT_SID = "P-CURRENT"


def test_operational_margin_is_source_derived_and_exceeds_strategy_minimum():
    assert OPERATIONAL_HISTORY_SESSIONS >= REQUIRED_CLOSES
    assert OPERATIONAL_HISTORY_SESSIONS == max(
        O.PREFERRED_SESSIONS, REQUIRED_CLOSES, O.FEED_RESTART_SESSIONS,
        O.REQUIRED_SPY_SESSIONS, O.WITNESS_HISTORY_SESSIONS)


def test_missed_session_cursor_expands_boundary(monkeypatch):
    monkeypatch.setattr(O, "_frontier", lambda _conn: "S0300")
    monkeypatch.setattr(O, "_cursor", lambda _conn: "S0010")

    def previous(end, count):
        if (end, count) == ("S0300", OPERATIONAL_HISTORY_SESSIONS + 1):
            return ["S0048", *[f"X{i:04d}" for i in range(1, 252)], "S0300"]
        if (end, count) == ("S0010", 2):
            return ["S0009", "S0010"]
        return []

    monkeypatch.setattr(O.calendar, "previous_sessions", previous)
    boundary = O.operational_boundary(object())
    assert boundary.start == "S0009"
    assert boundary.cursor == "S0010"


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
    connection = S.connect(pg.sync_dsn)
    drop_public_tables(connection)
    S.migrate_schema(connection)
    behavioral_schema.ensure_schema(connection)
    U.write_universe(connection, [{
        "permaticker": CURRENT_SID, "ticker": "CURRENT", "table": "SEP",
        "firstpricedate": "2000-01-01", "lastpricedate": FRONTIER,
    }], FRONTIER)
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id,session,ticker,close_signal,"
            "close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share)"
            " VALUES (%s,%s,'CURRENT',100,100,99,1000000,1,0),"
            " ('P-HIST',%s,'HIST',10,10,10,1000,1,0)",
            (CURRENT_SID, FRONTIER, OLD))
    connection.commit()
    P.publish(connection)
    yield connection
    connection.close()


def _run(conn, *, status="running") -> str:
    run = S.IngestRun(conn, "daily")
    if status != "running":
        run.finish(status)
    return run.progress.run_id


def _restamp_bar(conn, *, run_id: str, sid: str, session: str,
                 ticker: str, split: float = 1.0) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_bars SET close_unadjusted=close_unadjusted+1,"
            " close_signal=close_signal+1,split_ratio=%s,last_written_run_id=%s"
            " WHERE security_id=%s AND session=%s",
            (split, run_id, sid, session))
    conn.commit()


def _action_candidate(conn, *, run_id: str, ticker: str, action: str) -> None:
    payload = {"date": OLD, "ticker": ticker, "action": action, "value": "0"}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_action_generations "
            "(last_written_run_id,window_start,window_end,source_rows)"
            " VALUES (%s,%s,%s,1)", (run_id, OLD, OLD))
        cur.execute(
            "INSERT INTO sentinel_action_generation_events "
            "(generation_run_id,state,actor_run_id,reason)"
            " VALUES (%s,'PENDING',%s,'test unresolved candidate')",
            (run_id, run_id))
        cur.execute(
            "INSERT INTO sentinel_action_observations "
            "(source_row_id,source_payload,ticker,session,action,value,"
            "disposition,last_written_run_id)"
            " VALUES ('old-event',%s,%s,%s,%s,0,'PRESENT',%s)",
            (json.dumps(payload), ticker, OLD, action, run_id))
    conn.commit()


def test_eight_year_old_unrelated_price_is_historical_only_and_invisible(conn):
    run_id = _run(conn)
    _restamp_bar(
        conn, run_id=run_id, sid="P-HIST", session=OLD, ticker="HIST")

    report = P.operational_coherence(conn, persist=True)
    conn.commit()

    assert report.coherent
    assert report.boundary.history_sessions == OPERATIONAL_HISTORY_SESSIONS
    assert [item.run_id for item in report.historical_only] == [run_id]
    assert report.historical_only[0].evidence_kinds == ("BAR_PRICE",)
    assert loader.load_window(conn, start=OLD, end=OLD).sessions == []
    status = P.quarantine_status(conn)
    assert status[0]["run_id"] == run_id
    assert status[0]["production_blocking"] is False
    assert status[0]["affected_start"].isoformat() == OLD


def test_revision_inside_operational_feature_window_blocks(conn):
    run_id = _run(conn)
    _restamp_bar(
        conn, run_id=run_id, sid=CURRENT_SID, session=FRONTIER,
        ticker="CURRENT")

    report = P.operational_coherence(conn)
    assert not report.coherent
    assert report.blocking[0].run_id == run_id
    with pytest.raises(P.CorpusIncoherent, match="operational coherence"):
        P.assert_operationally_coherent(conn)


def test_falsifier_old_split_for_current_security_blocks(conn):
    """A date-only classifier would incorrectly route this to history."""
    run_id = _run(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id,session,ticker,close_signal,"
            "close_unadjusted,volume,split_ratio,dividend_per_share,"
            "last_written_run_id) VALUES (%s,%s,'CURRENT',50,50,1000,2,0,%s)",
            (CURRENT_SID, OLD, run_id))
    conn.commit()

    report = P.operational_coherence(conn)
    assert not report.coherent
    assert report.blocking[0].evidence_kinds == ("BAR_SPLIT",)
    assert "economic/identity" in report.blocking[0].reasons[-1]


def test_falsifier_old_split_for_durable_held_identity_blocks(conn):
    """Execution/expected-book identity closes the gap beyond current universe."""
    held_sid = "P-HELD-NOT-CURRENT"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_commands (client_key,plan_id,security_id,"
            "deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,"
            "quantity,state,filled_quantity) VALUES "
            "('held-command','held-plan',%s,'deployment','sim','account',1,"
            "'HELD','BUY',10,'FILLED',10)", (held_sid,))
    conn.commit()
    run_id = _run(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id,session,ticker,close_signal,"
            "close_unadjusted,volume,split_ratio,dividend_per_share,"
            "last_written_run_id) VALUES (%s,%s,'HELD',50,50,1000,2,0,%s)",
            (held_sid, OLD, run_id))
    conn.commit()

    report = P.operational_coherence(conn)
    assert not report.coherent
    assert report.blocking[0].evidence_kinds == ("BAR_SPLIT",)


@pytest.mark.parametrize("action", ["delisted", "mergerfrom", "tickerchangefrom"])
def test_old_terminal_or_identity_event_for_current_security_blocks(conn, action):
    run_id = _run(conn)
    _action_candidate(conn, run_id=run_id, ticker="CURRENT", action=action)

    report = P.operational_coherence(conn)
    assert not report.coherent
    assert report.blocking[0].run_id == run_id
    assert any(kind.startswith("ACTION_")
               for kind in report.blocking[0].evidence_kinds)


def test_historical_only_candidate_does_not_change_published_decision_inputs(conn):
    before_version = P.require_current(conn).version
    before = loader.load_window(conn, start=FRONTIER, end=FRONTIER)
    before_hash = json.dumps({
        "sessions": before.sessions,
        "bars": [[bar.security_id, bar.raw_close]
                 for bar in before.bars_by_session[FRONTIER]],
        "version": before_version,
    }, sort_keys=True)
    run_id = _run(conn)
    _restamp_bar(
        conn, run_id=run_id, sid="P-HIST", session=OLD, ticker="HIST")

    P.assert_operationally_coherent(conn)
    after = loader.load_window(conn, start=FRONTIER, end=FRONTIER)
    after_hash = json.dumps({
        "sessions": after.sessions,
        "bars": [[bar.security_id, bar.raw_close]
                 for bar in after.bars_by_session[FRONTIER]],
        "version": P.require_current(conn).version,
    }, sort_keys=True)
    assert after_hash == before_hash


def test_full_historical_certification_remains_strict(conn):
    run_id = _run(conn)
    _restamp_bar(
        conn, run_id=run_id, sid="P-HIST", session=OLD, ticker="HIST")

    assert P.operational_coherence(conn).coherent
    assert not P.full_historical_coherence(conn).coherent
    with pytest.raises(P.CorpusIncoherent, match="unpublished"):
        P.assert_full_historical_coherent(conn)


def test_restart_preserves_historical_classification(conn, pg):
    run_id = _run(conn)
    _restamp_bar(
        conn, run_id=run_id, sid="P-HIST", session=OLD, ticker="HIST")
    first = P.operational_coherence(conn, persist=True)
    conn.commit()

    restarted = S.connect(pg.sync_dsn)
    try:
        second = P.operational_coherence(restarted, persist=True)
        restarted.commit()
        assert second.to_dict() == first.to_dict()
        rows = P.quarantine_status(restarted)
        assert rows[0]["run_id"] == run_id
        assert rows[0]["production_blocking"] is False
    finally:
        restarted.close()


def test_covering_retry_publishes_and_clears_live_quarantine(conn):
    old_run = _run(conn)
    _restamp_bar(
        conn, run_id=old_run, sid="P-HIST", session=OLD, ticker="HIST")
    P.operational_coherence(conn, persist=True)
    conn.commit()

    retry = S.IngestRun(conn, "daily")
    _restamp_bar(
        conn, run_id=retry.progress.run_id, sid="P-HIST", session=OLD,
        ticker="HIST")
    retry.finish("success")
    published = P.publish(conn, run_id=retry.progress.run_id)

    assert P.full_historical_coherence(conn).coherent
    assert loader.load_window(conn, start=OLD, end=OLD).sessions == [OLD]
    assert P.quarantine_status(conn) == []
    assert published.version == 2
