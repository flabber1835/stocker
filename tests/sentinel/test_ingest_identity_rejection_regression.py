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
            "sentinel_processed_sessions",
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
            "sentinel_defensive_bars",
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
            "closeunadj": raw, "open": raw, "volume": 1_000_000,
            "lastupdated": date}


def fetcher(sep_rows):
    tickers = [{"ticker": t, "permaticker": f"P-{t}"}
               for t in sorted({r["ticker"] for r in sep_rows})]

    def fetch(table, params=None, **_kw):
        params = dict(params or {})
        if table == sharadar.TICKERS:
            return list(tickers)
        if table == sharadar.ACTIONS:
            if params.get("date.gte") == "1900-01-01":
                return [{"ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
                         "action": "listed", "value": None,
                         "contraticker": None}]
            return []
        if table == sharadar.SFP:
            return []
        if "lastupdated.gte" in params or "lastupdated.lte" in params:
            lo = params.get("lastupdated.gte", "0000-00-00")
            hi = params.get("lastupdated.lte", "9999-99-99")
            return [r for r in sep_rows
                    if lo <= r.get("lastupdated", "") <= hi]
        lo = params.get("date.gte", "0000-00-00")
        hi = params.get("date.lte", "9999-99-99")
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


def latest_daily(conn):
    return next(row for row in S.run_status(conn) if row["kind"] == "daily")


def assert_run_unpublished(conn, run_id) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_corpus_publications WHERE run_id=%s",
                    (str(run_id),))
        assert cur.fetchone()[0] == 0


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

    def test_two_percent_identity_loss_is_refused(self):
        report = D.NormalisationReport(
            rows_by_session={"2024-02-01": 100},
            dropped_no_identity_by_session={"2024-02-01": 2})
        with pytest.raises(D.IdentityDomainUnavailable, match="need 99%"):
            D.assert_identity_domain(report, "2024-02-01")

    def test_a_session_SEP_has_not_published_is_explicitly_na_not_pass(self):
        report = D.NormalisationReport(rows_by_session={"2024-01-31": 100})
        assert D.assert_identity_domain(report, "2024-02-01") is None


class TestDailyPublicationBoundary:
    def test_catastrophic_identity_loss_marks_the_run_failed_and_does_not_publish(
            self, conn):
        baseline = sep_row("AAA", "2024-01-15")
        ingest.seed(
            conn, date_from="2024-01-01", date_to="2024-01-31",
            fetch=fetcher([baseline]))
        before = publication.current(conn)
        assert before is not None

        fresh = [sep_row(f"T{i:03d}", "2024-02-01") for i in range(100)]
        with pytest.raises(D.IdentityDomainUnavailable):
            ingest.daily(
                conn, fetch=fetcher([baseline, *fresh]), today="2024-02-01",
                resolve_identity=lambda ticker, _session:
                    "P-AAA" if ticker == "AAA" else
                    (f"P-{ticker}" if int(ticker[1:]) < 5 else None))

        after = publication.current(conn)
        assert after is not None
        latest = latest_daily(conn)
        assert latest["status"] == "failed"
        assert "IdentityDomainUnavailable" in (latest["error_message"] or "")
        assert_run_unpublished(conn, latest["run_id"])
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

    def test_saturday_catch_up_validates_friday_not_wall_clock_saturday(self, conn):
        baseline = sep_row("AAA", "2024-02-01")
        ingest.seed(
            conn, date_from="2024-01-01", date_to="2024-02-01",
            fetch=fetcher([baseline]))
        before = publication.current(conn)
        assert before is not None

        friday = [sep_row(f"T{i:03d}", "2024-02-02") for i in range(100)]
        source = [baseline, *friday]

        def resolve(ticker, _session):
            if ticker == "AAA":
                return "P-AAA"
            return f"P-{ticker}" if int(ticker[1:]) < 5 else None

        with pytest.raises(D.IdentityDomainUnavailable, match="2024-02-02"):
            ingest.daily(
                conn, fetch=fetcher(source), today="2024-02-03",
                resolve_identity=resolve)

        after = publication.current(conn)
        assert after is not None
        first_failed = latest_daily(conn)
        assert first_failed["status"] == "failed"
        assert_run_unpublished(conn, first_failed["run_id"])

        # The failed candidate physically wrote the five identities it could
        # resolve, so MAX(session) has advanced even though publication has not.
        # A retry must not mistake that physical row for authority and silently
        # waive the Friday guard.
        assert S.latest_session(conn) == "2024-02-02"
        assert S.latest_visible_session(conn) == "2024-02-01"
        with pytest.raises(D.IdentityDomainUnavailable, match="2024-02-02"):
            ingest.daily(
                conn, fetch=fetcher(source), today="2024-02-03",
                resolve_identity=resolve)

        after_retry = publication.current(conn)
        assert after_retry is not None
        retry_failed = latest_daily(conn)
        assert retry_failed["status"] == "failed"
        assert_run_unpublished(conn, retry_failed["run_id"])

    @pytest.mark.parametrize("today", ["2024-02-18", "2024-02-19"])
    def test_weekend_or_holiday_without_new_SEP_session_is_not_identity_failure(
            self, conn, today):
        friday = [sep_row("AAA", "2024-02-16")]
        ingest.seed(
            conn, date_from="2024-02-01", date_to="2024-02-16",
            fetch=fetcher(friday))
        before = publication.current(conn)
        assert before is not None

        ingest.daily(
            conn, fetch=fetcher(friday), today=today,
            resolve_identity=lambda ticker, _session: f"P-{ticker}")

        after = publication.current(conn)
        assert after is not None
        # Historical maintenance may legitimately publish its own generation
        # around the daily run. This test is about identity semantics, not an
        # assumption that a daily invocation creates exactly one version.
        assert after.version > before.version
        assert latest_daily(conn)["status"] == "success"

    def test_intermediate_new_session_collapse_cannot_hide_behind_healthy_latest(
            self, conn):
        baseline = sep_row("AAA", "2024-01-31")
        ingest.seed(
            conn, date_from="2024-01-01", date_to="2024-01-31",
            fetch=fetcher([baseline]))
        before = publication.current(conn)
        assert before is not None

        fresh = [
            sep_row(f"T{i:03d}", session)
            for session in ("2024-02-01", "2024-02-02")
            for i in range(100)
        ]

        def resolve(ticker, session):
            if ticker == "AAA":
                return "P-AAA"
            if session == "2024-02-01" and int(ticker[1:]) >= 5:
                return None
            return f"P-{ticker}"

        with pytest.raises(D.IdentityDomainUnavailable, match="2024-02-01"):
            ingest.daily(
                conn, fetch=fetcher([baseline, *fresh]), today="2024-02-02",
                resolve_identity=resolve)

        after = publication.current(conn)
        assert after is not None
        failed = latest_daily(conn)
        assert failed["status"] == "failed"
        assert_run_unpublished(conn, failed["run_id"])


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

    def test_reject_failed_repair_published_repair_and_rereject_lifecycle(self, conn):
        rejected_run = str(uuid.uuid4())
        failed_repair_run = str(uuid.uuid4())
        repair_run = str(uuid.uuid4())
        rereject_run = str(uuid.uuid4())

        S.write_rejections(conn, [{
            "ticker": "aaa", "session": "2024-06-03",
            "reason": RA.NO_IDENTITY, "close": 50.0, "volume": 1_000_000,
        }], run_id=rejected_run)
        publish_run(conn, rejected_run)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_active_ingest_rejections"
                " WHERE UPPER(ticker)='AAA' AND session='2024-06-03'")
            assert cur.fetchone()[0] == 1

            # A repair candidate wrote a bar but the ingest failed before
            # publication. Unpublished evidence must not resolve a published
            # rejection.
            cur.execute(
                "INSERT INTO feed_ingest_runs (run_id,kind,status,completed_at)"
                " VALUES (%s,'daily','failed',NOW())", (failed_repair_run,))
            cur.execute(
                "INSERT INTO sentinel_bars"
                " (security_id,session,ticker,close_signal,close_unadjusted,"
                "  open_unadjusted,volume,last_written_run_id)"
                " VALUES ('P-AAA','2024-06-03','AAA',50,50,49,1000000,%s)",
                (failed_repair_run,))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_active_ingest_rejections"
                " WHERE UPPER(ticker)='AAA' AND session='2024-06-03'")
            assert cur.fetchone()[0] == 1

            # A later candidate replaces the failed row at the storage key. It
            # becomes authoritative only after its publication is recorded.
            cur.execute(
                "UPDATE sentinel_bars SET last_written_run_id=%s"
                " WHERE security_id='P-AAA' AND session='2024-06-03'",
                (repair_run,))
        conn.commit()
        publish_run(conn, repair_run)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_active_ingest_rejections"
                " WHERE UPPER(ticker)='AAA' AND session='2024-06-03'")
            assert cur.fetchone()[0] == 0

        # A later published rejection is newer than the repair and must become
        # active again. The case variants deliberately pin UPPER(ticker) as the
        # projection's economic identity rather than exact symbol spelling.
        S.write_rejections(conn, [{
            "ticker": "AaA", "session": "2024-06-03",
            "reason": RA.NO_IDENTITY, "close": 75.0, "volume": 1_000_000,
        }], run_id=rereject_run)
        publish_run(conn, rereject_run)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*),MAX(close_unadjusted),MAX(last_written_run_id::text)"
                " FROM sentinel_active_ingest_rejections"
                " WHERE UPPER(ticker)='AAA' AND session='2024-06-03'")
            count, max_close, active_run = cur.fetchone()
            assert count == 1
            assert max_close == 75.0
            assert active_run == rereject_run
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_ingest_rejections"
                " WHERE UPPER(ticker)='AAA' AND session='2024-06-03'")
            assert cur.fetchone()[0] == 2, "repair or rereject erased raw history"

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
                    " (ticker,session,reason,close_unadjusted,volume) VALUES"
                    " ('AAA','2024-06-03','NO_IDENTITY',50,1000000),"
                    " ('BBB','2024-06-03','NO_IDENTITY',25,500000),"
                    " ('AAA','2024-06-04','NO_RAW_CLOSE',NULL,900000)")
            c.commit()
            S.ensure_schema(c)
            S.ensure_schema(c)

            with c.cursor() as cur:
                cur.execute(
                    "SELECT observation_id,last_written_run_id,ticker,session,reason"
                    " FROM sentinel_ingest_rejections"
                    " ORDER BY ticker,session,reason")
                rows = cur.fetchall()
                assert len(rows) == 3
                assert all(row[0] is not None for row in rows)
                assert all(row[1] is None for row in rows)
                assert [(row[2], str(row[3]), row[4]) for row in rows] == [
                    ("AAA", "2024-06-03", "NO_IDENTITY"),
                    ("AAA", "2024-06-04", "NO_RAW_CLOSE"),
                    ("BBB", "2024-06-03", "NO_IDENTITY"),
                ]
                cur.execute(
                    "SELECT a.attname FROM pg_constraint c"
                    " JOIN unnest(c.conkey) WITH ORDINALITY k(attnum,ord) ON TRUE"
                    " JOIN pg_attribute a ON a.attrelid=c.conrelid"
                    "   AND a.attnum=k.attnum"
                    " WHERE c.conrelid='sentinel_ingest_rejections'::regclass"
                    "   AND c.contype='p' ORDER BY k.ord")
                assert [row[0] for row in cur.fetchall()] == ["observation_id"]
                cur.execute(
                    "SELECT indexname FROM pg_indexes"
                    " WHERE schemaname='public'"
                    "   AND tablename='sentinel_ingest_rejections'")
                indexes = {row[0] for row in cur.fetchall()}
                assert "uq_sentinel_rejection_run_observation" in indexes
                assert "uq_sentinel_rejection_legacy_observation" in indexes

                cur.execute(
                    "SELECT indexname,indexdef FROM pg_indexes"
                    " WHERE schemaname='public' AND indexname IN"
                    " ('idx_sentinel_rejections_active_projection_key',"
                    "  'idx_sentinel_bars_active_rejection_lookup')")
                indexdefs = {row[0]: row[1] for row in cur.fetchall()}
                assert set(indexdefs) == {
                    "idx_sentinel_rejections_active_projection_key",
                    "idx_sentinel_bars_active_rejection_lookup",
                }
                for definition in indexdefs.values():
                    folded = definition.lower()
                    assert "upper(" in folded and "ticker" in folded
        finally:
            c.close()
