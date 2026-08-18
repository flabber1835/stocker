"""Regression coverage for the 2026-08-17 SEP/TICKERS publication skew.

The incident had two independent failure modes:

* SEP exposed the fresh close before TICKERS advanced its listing intervals, so
  almost the entire new session failed permanent-identity resolution and the
  daily ingest nevertheless published it;
* the later successful retry repaired every bar, but mutable run-less rejection
  rows survived forever and made the repaired interval look uncertifiable.

These tests pin both boundaries: bad candidate generations never publish, while
old rejection observations remain history but stop being CURRENT blockers after
a later published bar proves repair.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import domains as D  # noqa: E402
from sentinel.feed import ingest, publication, rejection_audit as RA, sharadar  # noqa: E402
from sentinel.feed import store as S  # noqa: E402


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
        cur.execute("DROP VIEW IF EXISTS sentinel_active_ingest_rejections CASCADE")
        cur.execute("DROP VIEW IF EXISTS sentinel_active_actions CASCADE")
        for table in (
            "sentinel_anomaly_observation_events",
            "sentinel_action_generation_events",
            "sentinel_action_observations",
            "sentinel_action_generations",
            "sentinel_bar_split_repairs",
            "sentinel_readiness_snapshots",
            "sentinel_sep_staging",
            "sentinel_corpus_anomalies",
            "sentinel_rejection_truncation",
            "sentinel_ingest_rejections",
            "sentinel_spy_total_return",
            "sentinel_bars",
            "sentinel_actions",
            "sentinel_universe",
            "sentinel_corpus_publications",
            "feed_ingest_runs",
        ):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sep_row(ticker: str, date: str, *, raw: float = 100.0) -> dict:
    return {"ticker": ticker, "date": date, "close": raw,
            "closeunadj": raw, "open": raw, "volume": 1_000_000}


def fetcher(sep_rows):
    tickers = [{"ticker": t, "permaticker": f"P-{t}"}
               for t in sorted({r["ticker"] for r in sep_rows})]

    def fetch(table, params=None, **_kw):
        if table == sharadar.TICKERS:
            return list(tickers)
        if table in (sharadar.ACTIONS, sharadar.SFP):
            return []
        lo = (params or {}).get("date.gte", "0000-00-00")
        hi = (params or {}).get("date.lte", "9999-99-99")
        return [r for r in sep_rows if lo <= r["date"] <= hi]

    return fetch


def publish_run(conn, run_id: str, start="2024-01-01", end="2024-12-31") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (run_id,window_start,window_end,evidence)"
            " VALUES (%s,%s,%s,'{}'::jsonb) RETURNING version",
            (run_id, start, end))
        version = int(cur.fetchone()[0])
    conn.commit()
    return version


class TestCurrentSessionIdentityCoverage:
    def test_the_guard_is_SESSION_scoped_and_refuses_a_cross_section_collapse(self):
        rows = [sep_row(f"T{i:03d}", "2024-02-01") for i in range(100)]
        report = D.NormalisationReport()
        list(D.normalise_sep_rows(
            rows,
            resolve_identity=lambda ticker, _session:
                ticker if int(ticker[1:]) < 5 else None,
            report=report))

        # The exact incident shape: the vendor priced the session, but metadata
        # could name only a small fraction of it.
        assert report.rows_by_session["2024-02-01"] == 100
        assert report.dropped_no_identity_by_session["2024-02-01"] == 95
        with pytest.raises(D.IdentityDomainUnavailable, match="publication sync"):
            D.assert_identity_domain(report, "2024-02-01")

    def test_a_small_tail_of_unknown_instruments_is_allowed(self):
        report = D.NormalisationReport(
            rows_by_session={"2024-02-01": 100},
            dropped_no_identity_by_session={"2024-02-01": 1})
        assert D.assert_identity_domain(report, "2024-02-01") == pytest.approx(0.99)

    def test_a_session_SEP_has_not_published_is_owned_by_freshness_not_this_gate(self):
        report = D.NormalisationReport(rows_by_session={"2024-01-31": 100})
        assert D.assert_identity_domain(report, "2024-02-01") == 1.0


class TestDailyPublicationBoundary:
    def test_catastrophic_identity_loss_marks_the_run_failed_and_does_not_publish(
            self, conn):
        ingest.seed(
            conn, date_from="2024-01-01", date_to="2024-01-31",
            fetch=fetcher([sep_row("AAA", "2024-01-15")]))
        before = publication.current(conn)
        assert before is not None

        fresh = [sep_row(f"T{i:03d}", "2024-02-01") for i in range(100)]
        with pytest.raises(D.IdentityDomainUnavailable):
            ingest.daily(
                conn, fetch=fetcher(fresh), today="2024-02-01",
                resolve_identity=lambda ticker, _session:
                    f"P-{ticker}" if int(ticker[1:]) < 5 else None)

        after = publication.current(conn)
        assert after is not None
        assert after.version == before.version
        assert after.run_id == before.run_id

        latest = S.run_status(conn, 1)[0]
        assert latest["status"] == "failed"
        assert "IdentityDomainUnavailable" in (latest["error_message"] or "")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*),COUNT(DISTINCT last_written_run_id)"
                " FROM sentinel_ingest_rejections"
                " WHERE session='2024-02-01' AND reason='NO_IDENTITY'")
            assert cur.fetchone() == (95, 1)
            # The failed candidate remains retained history, but never becomes a
            # current certification blocker because it was never published.
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_active_ingest_rejections"
                " WHERE session='2024-02-01'")
            assert cur.fetchone()[0] == 0


class TestRejectionGenerationLifecycle:
    def test_retries_append_history_and_only_the_latest_unresolved_observation_is_active(
            self, conn):
        run_a, run_b = str(uuid.uuid4()), str(uuid.uuid4())
        S.write_rejections(conn, [{
            "ticker": "AAA", "session": "2024-06-03",
            "reason": RA.NO_IDENTITY, "close": 50.0, "volume": 1_000_000,
        }], run_id=run_a)
        publish_run(conn, run_a)

        S.write_rejections(conn, [{
            "ticker": "AAA", "session": "2024-06-03",
            "reason": RA.NO_IDENTITY, "close": 0.4, "volume": 1_000_000,
        }], run_id=run_b)
        publish_run(conn, run_b)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*),COUNT(DISTINCT last_written_run_id)"
                " FROM sentinel_ingest_rejections WHERE ticker='AAA'")
            assert cur.fetchone() == (2, 2), "retry overwrote rejection history"
            cur.execute(
                "SELECT COUNT(*),MAX(close_unadjusted)"
                " FROM sentinel_active_ingest_rejections WHERE ticker='AAA'")
            assert cur.fetchone() == (1, 0.4)

        audit = RA.audit(
            conn, start="2024-06-03", end="2024-06-03",
            held_tickers=(), pending_terminal_tickers=())
        assert audit.rejected_rows == 1
        assert audit.per_ticker[0].max_close == 0.4

    def test_a_later_published_bar_resolves_rejection_without_deleting_history(
            self, conn):
        rejected_run, repair_run = str(uuid.uuid4()), str(uuid.uuid4())
        S.write_rejections(conn, [{
            "ticker": "AAA", "session": "2024-06-03",
            "reason": RA.NO_IDENTITY, "close": 50.0, "volume": 1_000_000,
        }], run_id=rejected_run)
        publish_run(conn, rejected_run)

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_bars"
                " (security_id,session,ticker,close_signal,close_unadjusted,"
                "  open_unadjusted,volume,last_written_run_id)"
                " VALUES ('P-AAA','2024-06-03','AAA',50,50,49,1000000,%s)",
                (repair_run,))
        conn.commit()
        publish_run(conn, repair_run)

        audit = RA.audit(
            conn, start="2024-06-03", end="2024-06-03",
            held_tickers=(), pending_terminal_tickers=())
        assert audit.rejected_rows == 0
        assert audit.distinct_tickers == 0
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_ingest_rejections"
                " WHERE ticker='AAA' AND session='2024-06-03'")
            assert cur.fetchone()[0] == 1, "repair deleted historical evidence"

    def test_legacy_runless_rejection_is_resolved_only_by_a_later_publication(
            self, conn):
        S.write_rejections(conn, [{
            "ticker": "AAA", "session": "2024-06-03",
            "reason": RA.NO_IDENTITY, "close": 50.0, "volume": 1_000_000,
        }])
        before = RA.audit(
            conn, start="2024-06-03", end="2024-06-03",
            held_tickers=(), pending_terminal_tickers=())
        assert before.rejected_rows == 1

        repair_run = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_bars"
                " (security_id,session,ticker,close_signal,close_unadjusted,"
                "  open_unadjusted,volume,last_written_run_id)"
                " VALUES ('P-AAA','2024-06-03','AAA',50,50,49,1000000,%s)",
                (repair_run,))
        conn.commit()
        publish_run(conn, repair_run)

        after = RA.audit(
            conn, start="2024-06-03", end="2024-06-03",
            held_tickers=(), pending_terminal_tickers=())
        assert after.rejected_rows == 0
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*),COUNT(last_written_run_id)"
                " FROM sentinel_ingest_rejections WHERE ticker='AAA'")
            assert cur.fetchone() == (1, 0), "legacy provenance was guessed"


class TestLegacySchemaMigration:
    def test_old_mutable_rejection_table_is_upgraded_without_losing_evidence(self, pg):
        c = S.connect(pg.sync_dsn)
        try:
            with c.cursor() as cur:
                cur.execute("DROP VIEW IF EXISTS sentinel_active_ingest_rejections CASCADE")
                cur.execute("DROP TABLE IF EXISTS sentinel_ingest_rejections CASCADE")
                cur.execute(
                    "CREATE TABLE sentinel_ingest_rejections ("
                    " ticker TEXT NOT NULL, session DATE NOT NULL, reason TEXT NOT NULL,"
                    " close_unadjusted DOUBLE PRECISION, volume DOUBLE PRECISION,"
                    " first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                    " PRIMARY KEY (ticker,session,reason))")
                cur.execute(
                    "INSERT INTO sentinel_ingest_rejections"
                    " (ticker,session,reason,close_unadjusted,volume)"
                    " VALUES ('AAA','2024-06-03','NO_IDENTITY',50,1000000)")
            c.commit()
            S.ensure_schema(c)

            with c.cursor() as cur:
                cur.execute(
                    "SELECT observation_id,last_written_run_id,ticker,reason"
                    " FROM sentinel_ingest_rejections")
                observation_id, writer, ticker, reason = cur.fetchone()
                assert observation_id is not None
                assert writer is None
                assert (ticker, reason) == ("AAA", "NO_IDENTITY")
                cur.execute(
                    "SELECT a.attname FROM pg_constraint c"
                    " JOIN unnest(c.conkey) WITH ORDINALITY k(attnum,ord) ON TRUE"
                    " JOIN pg_attribute a ON a.attrelid=c.conrelid"
                    "   AND a.attnum=k.attnum"
                    " WHERE c.conrelid='sentinel_ingest_rejections'::regclass"
                    "   AND c.contype='p' ORDER BY k.ord")
                assert [row[0] for row in cur.fetchall()] == ["observation_id"]
        finally:
            c.close()
