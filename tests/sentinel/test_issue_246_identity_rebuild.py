"""#246: complete seed can replace a corrected historical identity projection."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel.feed import identity_rebuild as IR
from sentinel.feed import ingest as I
from sentinel.feed import publication as P
from sentinel.feed import recovery as R
from sentinel.feed import store as S
from sentinel.feed import universe as U
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = S.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    connection.commit()
    S.migrate_schema(connection)
    yield connection
    connection.close()


def _row(ticker: str, permaticker: str) -> dict:
    return {
        "table": "SEP", "ticker": ticker, "permaticker": permaticker,
        "category": "Domestic Common Stock", "sector": "Technology",
        "relatedtickers": "", "firstpricedate": "2026-08-20",
        "lastpricedate": "2026-08-21", "isdelisted": "N",
    }


def _publish_base(conn):
    rows = [_row("GGRP", "P1"), _row("LBRDK", "P2"), _row("KEEP", "P3")]
    run = S.IngestRun(
        conn, "seed", date_from="2026-08-20", date_to="2026-08-21")
    run_id = run.progress.run_id
    U.write_universe(conn, rows, "2026-08-21", run_id=run_id)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sentinel_bars"
            " (security_id,session,ticker,close_signal,close_unadjusted,"
            "  open_unadjusted,volume,split_ratio,dividend_per_share,"
            "  last_written_run_id)"
            " VALUES (%s,'2026-08-20',%s,10,10,10,1000,1,0,%s)",
            [("P1", "GGRP", run_id), ("P2", "LBRDK", run_id),
             ("P3", "KEEP", run_id)])
    conn.commit()
    run.finish("success")
    return P.publish(
        conn, run_id=run_id, window_start="2026-08-20",
        window_end="2026-08-21")


def _bar(security_id: str, ticker: str):
    vendor = SimpleNamespace(
        security_id=security_id, session="2026-08-20", ticker=ticker,
        raw_close=10.0, raw_open=10.0, volume=1000.0,
        split_ratio=1.0, dividend_per_share=0.0)
    return SimpleNamespace(vendor=vendor, close_signal=10.0)


def _candidate_rows():
    # P1 was historically named GGRP and is now BTLN; P2/LBRDK disappears;
    # P3 is economically unchanged; P4 is a newly reconstructed historical pair.
    return [_row("BTLN", "P1"), _row("KEEP", "P3"), _row("NEW", "P4")]


def _prepare_candidate(conn):
    plan = IR.prepare(
        conn, date_from="2026-08-20", date_to="2026-08-21",
        observed_on="2026-08-24")
    run = S.IngestRun(
        conn, "seed", date_from=plan.market_start, date_to=plan.market_end)
    IR.record_plan(conn, run_id=run.progress.run_id, plan=plan)
    rows = IR.verify_candidate(
        conn, run_id=run.progress.run_id, plan=plan,
        rows=_candidate_rows())
    IR.write_bars_claiming(
        conn, [_bar("P1", "BTLN"), _bar("P3", "KEEP"),
               _bar("P4", "NEW")],
        run_id=run.progress.run_id, batch_size=2)
    return plan, run, rows


def test_seed_generation_escalates_only_the_named_identity_mutation(monkeypatch):
    calls = []
    recovery_plan = R.FullReseedPlan("1998-01-01", "2026-08-21", ())
    identity_plan = IR.IdentityRebuildPlan(
        "1998-01-01", "2026-08-21", 12,
        "2025-07-01", "2026-08-21", "2026-08-24")
    trackers = [object(), object()]
    guarded = [object(), object()]
    source_calls = 0

    def source(_fetch, *, final_hi):
        nonlocal source_calls
        index = source_calls
        source_calls += 1
        calls.append(("source", final_hi))
        return trackers[index], guarded[index]

    monkeypatch.setattr(I, "_seed_source", source)
    monkeypatch.setattr(
        I, "_ordinary_seed_generation",
        lambda *a, **k: (_ for _ in ()).throw(
            U.HistoricalIdentityMutation("historical correction")))
    monkeypatch.setattr(
        IR, "prepare",
        lambda conn, **kwargs: calls.append(("prepare", kwargs)) or identity_plan)
    progress = SimpleNamespace(run_id="replacement")

    def full(conn, **kwargs):
        calls.append(("full", kwargs))
        return progress

    monkeypatch.setattr(I.reseed, "full_reseed_locked", full)

    got, tracker = I._run_seed_generation(
        object(), recovery_plan=recovery_plan, fetch=object(),
        final_hi="2026-08-21")

    assert got is progress and tracker is trackers[1]
    assert calls[1] == ("prepare", {
        "date_from": "1998-01-01", "date_to": "2026-08-21"})
    assert calls[3][0] == "full"
    assert calls[3][1]["identity_rebuild_plan"] == identity_plan
    assert calls[3][1]["fetch"] is guarded[1]


def test_identity_rebuild_rekeys_claims_and_tombstones_atomically(conn):
    base = _publish_base(conn)
    with S.corpus_write_lock(conn):
        plan, run, rows = _prepare_candidate(conn)
        replacement = IR.publish_completed_run(
            conn, run=run, rows=rows, plan=plan)

    assert replacement.previous_version == base.version
    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id,ticker,last_written_run_id::text"
            " FROM sentinel_bars ORDER BY security_id")
        bars = cur.fetchall()
        cur.execute(
            "SELECT permaticker,ticker FROM feed_universe_current"
            " ORDER BY permaticker,ticker")
        pairs = cur.fetchall()
    assert [(str(s), str(t)) for s, t, _owner in bars] == [
        ("P1", "BTLN"), ("P3", "KEEP"), ("P4", "NEW")]
    assert all(str(owner) == run.progress.run_id for _s, _t, owner in bars)
    assert [(str(p), str(t)) for p, t in pairs] == [
        ("P1", "BTLN"), ("P3", "KEEP"), ("P4", "NEW")]
    assert replacement.evidence["identity_rebuild"]["retired_obsolete_bars"] == 1

    # Rebuilding the derived projection from raw snapshots must not resurrect
    # GGRP or LBRDK from pre-replacement evidence.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO feed_universe_current"
            " (permaticker,ticker,snapshot_date)"
            " VALUES ('P2','LBRDK','2026-08-21')")
    conn.commit()
    S.migrate_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT permaticker,ticker FROM feed_universe_current"
            " ORDER BY permaticker,ticker")
        rebuilt = [(str(p), str(t)) for p, t in cur.fetchall()]
    assert rebuilt == [("P1", "BTLN"), ("P3", "KEEP"), ("P4", "NEW")]


def test_publication_failure_rolls_back_tombstones_and_projection(conn, monkeypatch):
    base = _publish_base(conn)
    with S.corpus_write_lock(conn):
        plan, run, rows = _prepare_candidate(conn)
        monkeypatch.setattr(
            IR.publication, "publish",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError, match="boom"):
            IR.publish_completed_run(conn, run=run, rows=rows, plan=plan)

    assert P.require_current(conn).version == base.version
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_bars"
            " WHERE security_id='P2' AND ticker='LBRDK'")
        assert cur.fetchone()[0] == 1, "negative-space delete escaped rollback"
        cur.execute(
            "SELECT COUNT(*) FROM feed_universe_current"
            " WHERE permaticker='P2' AND ticker='LBRDK'")
        assert cur.fetchone()[0] == 1, "projection delete escaped rollback"
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_universe"
            " WHERE last_written_run_id=%s", (run.progress.run_id,))
        assert cur.fetchone()[0] == 0, "candidate TICKERS rows escaped rollback"
        cur.execute(
            "SELECT status FROM feed_ingest_runs WHERE run_id=%s",
            (run.progress.run_id,))
        assert cur.fetchone()[0] == "failed"
