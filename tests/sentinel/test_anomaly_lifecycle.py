"""PostgreSQL falsifiers for publication-scoped anomaly dispositions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import anomalies, publication as P  # noqa: E402
from sentinel.feed import rejection_audit as RA  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

START, END, EVENT = "2024-01-01", "2024-12-31", "2024-06-03"
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
        for table in ("sentinel_bar_split_repairs", "sentinel_bars",
                      "sentinel_actions", "sentinel_universe",
                      "sentinel_corpus_publications", "feed_ingest_runs",
                      "sentinel_corpus_anomalies"):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def observation(kind, detail="evidence"):
    return {"kind": kind, "ticker": "AAA", "session": EVENT,
            "detail": detail}


def publish_observation(conn, kind, detail="evidence"):
    run = S.IngestRun(conn, "test-anomaly-publication")
    with S.corpus_write_lock(conn):
        S.write_anomalies(conn, [observation(kind, detail)],
                          run_id=run.progress.run_id, require_lock=True)
        run.finish("success")
        P.publish(conn, run_id=run.progress.run_id,
                  window_start=START, window_end=END)
    return run.progress.run_id


def active(conn):
    return anomalies.active_rows(
        conn, start=START, end=END, kinds=anomalies.SPLIT_DISPOSITION_KINDS)


class TestPublishedSupersession:
    def test_disagreement_then_corroborated_retains_history(self, conn):
        S.write_anomalies(conn, [observation("SPLIT_DISAGREEMENT", "old")])
        publish_observation(conn, "SPLIT_CORROBORATED_DERIVED", "current")

        with conn.cursor() as cur:
            cur.execute("SELECT kind FROM sentinel_corpus_anomalies"
                        " ORDER BY observation_id")
            assert [r[0] for r in cur.fetchall()] == [
                "SPLIT_DISAGREEMENT", "SPLIT_CORROBORATED_DERIVED"]
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_CORROBORATED_DERIVED"]
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable

    @pytest.mark.parametrize("old", [
        "SPLIT_ONLY_DERIVED", "SEAM_SPLIT_UNCORROBORATED",
    ])
    def test_uncertain_then_authoritative_activates_only_authoritative(
            self, conn, old):
        S.write_anomalies(conn, [observation(old, "old")])
        publish_observation(conn, "SPLIT_AUTHORITATIVE_APPLIED", "current")
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_AUTHORITATIVE_APPLIED"]
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable

    def test_certification_never_combines_stale_and_current(self, conn):
        S.write_anomalies(conn, [observation("SPLIT_DISAGREEMENT", "stale")])
        publish_observation(conn, "SPLIT_CORROBORATED_DERIVED", "current")
        report = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert len(report.split_dispositions) == 1
        assert report.split_dispositions[0]["kind"] == \
            "SPLIT_CORROBORATED_DERIVED"
        assert report.gating_anomalies == []


class TestFailedCandidate:
    def test_unpublished_correction_leaves_old_blocker_active(self, conn):
        publish_observation(conn, "SPLIT_DISAGREEMENT", "published blocker")
        candidate = S.IngestRun(conn, "failed-correction")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_CORROBORATED_DERIVED", "candidate")],
                run_id=candidate.progress.run_id, require_lock=True)
            candidate.finish("failed", "publication never occurred")

        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_DISAGREEMENT"]
        assert not RA.audit(conn, start=START, end=END,
                            **EMPTY_BOOK).certifiable
        coherence = P.coherence(conn)
        assert not coherence.coherent
        assert coherence.unpublished_anomalies == 1

    def test_repeated_identical_candidate_writes_are_idempotent(self, conn):
        candidate = S.IngestRun(conn, "repeated-candidate")
        with S.corpus_write_lock(conn):
            for _ in range(2):
                S.write_anomalies(
                    conn, [observation("SPLIT_ONLY_DERIVED", "same")],
                    run_id=candidate.progress.run_id, require_lock=True)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_corpus_anomalies"
                        " WHERE last_written_run_id = %s",
                        (candidate.progress.run_id,))
            assert cur.fetchone()[0] == 1

    def test_repeated_identical_published_ingests_have_one_active_disposition(
            self, conn):
        publish_observation(conn, "SPLIT_CORROBORATED_DERIVED", "same")
        publish_observation(conn, "SPLIT_CORROBORATED_DERIVED", "same")
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_CORROBORATED_DERIVED"]
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_corpus_anomalies")
            assert cur.fetchone()[0] == 2, (
                "both ingest observations remain as history, while only the "
                "newest publication is active")
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable


def test_legacy_schema_upgrade_retains_ambiguous_evidence_fail_closed(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE sentinel_corpus_anomalies")
        cur.execute("CREATE TABLE sentinel_corpus_anomalies ("
                    " kind TEXT NOT NULL, ticker TEXT NOT NULL,"
                    " session DATE NOT NULL, detail TEXT,"
                    " first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                    " PRIMARY KEY(kind,ticker,session))")
        cur.execute("INSERT INTO sentinel_corpus_anomalies"
                    " (kind,ticker,session,detail) VALUES"
                    " ('SPLIT_DISAGREEMENT','AAA',%s,'legacy blocker'),"
                    " ('SPLIT_CORROBORATED_DERIVED','AAA',%s,'legacy tie')",
                    (EVENT, EVENT))
    conn.commit()

    S.ensure_schema(conn)
    rows = active(conn)
    assert {row["kind"] for row in rows} == {
        "SPLIT_DISAGREEMENT", "SPLIT_CORROBORATED_DERIVED"}
    assert all(row["last_written_run_id"] is None for row in rows)
    assert not RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable
