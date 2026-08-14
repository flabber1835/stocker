"""PostgreSQL falsifiers for publication-scoped anomaly dispositions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import anomalies, domains, ingest, publication as P  # noqa: E402
from sentinel.feed import rejection_audit as RA  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

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
        for table in ("sentinel_anomaly_observation_events",
                      "sentinel_bar_split_repairs", "sentinel_bars",
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


def lifecycle(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT e.state FROM sentinel_anomaly_observation_events e"
            " JOIN sentinel_corpus_anomalies a"
            "   ON a.observation_id=e.observation_id"
            " WHERE a.last_written_run_id=%s ORDER BY e.event_id", (run_id,))
        return [row[0] for row in cur.fetchall()]


def current_bar():
    return VendorBar(
        session=EVENT, security_id="SEC-AAA", ticker="AAA",
        raw_close=100.0, raw_open=99.0, volume=1_000_000.0,
        split_ratio=1.0, dividend_per_share=0.0)


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
    def test_failed_correction_keeps_old_blocker_and_is_durably_aborted(
            self, conn):
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
        assert coherence.coherent
        assert coherence.unpublished_anomalies == 0
        assert lifecycle(conn, candidate.progress.run_id) == [
            anomalies.PENDING, anomalies.ABORTED]
        with S.corpus_write_lock(conn):
            with pytest.raises(RuntimeError, match="durably successful"):
                P.publish(conn, run_id=candidate.progress.run_id,
                          window_start=START, window_end=END)
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_DISAGREEMENT"]

    def test_published_blocker_failed_correction_successful_retry_recovers(
            self, conn):
        publish_observation(conn, "SPLIT_DISAGREEMENT", "published blocker")
        failed = S.IngestRun(conn, "failed-correction")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_CORROBORATED_DERIVED", "failed")],
                run_id=failed.progress.run_id, require_lock=True)
            failed.finish("failed", "transient failure")

        retry = publish_observation(
            conn, "SPLIT_CORROBORATED_DERIVED", "successful retry")
        assert P.coherence(conn).coherent
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_CORROBORATED_DERIVED"]
        assert RA.audit(conn, start=START, end=END, **EMPTY_BOOK).certifiable
        assert lifecycle(conn, failed.progress.run_id) == [
            anomalies.PENDING, anomalies.ABORTED]
        assert lifecycle(conn, retry) == [anomalies.PENDING, anomalies.PUBLISHED]
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_corpus_anomalies")
            assert cur.fetchone()[0] == 3, "all observations remain as history"

    def test_running_candidate_blocks_until_durably_aborted(self, conn):
        candidate = S.IngestRun(conn, "unresolved-candidate")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_ONLY_DERIVED", "still running")],
                run_id=candidate.progress.run_id, require_lock=True)
            assert not P.coherence(conn).coherent
            with pytest.raises(RuntimeError, match="durably successful"):
                P.publish(conn, run_id=candidate.progress.run_id,
                          window_start=START, window_end=END)
            candidate.finish("failed", "validated failure")
        assert P.coherence(conn).coherent

    def test_failed_publication_rolls_back_lifecycle_activation(self, conn):
        candidate = S.IngestRun(conn, "publication-rollback")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_CORROBORATED_DERIVED", "candidate")],
                run_id=candidate.progress.run_id, require_lock=True)
            candidate.finish("success")
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE FUNCTION reject_test_publication() RETURNS trigger"
                    " LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION"
                    " 'test publication rejection'; END $$")
                cur.execute(
                    "CREATE TRIGGER reject_test_publication BEFORE INSERT ON"
                    " sentinel_corpus_publications FOR EACH ROW EXECUTE FUNCTION"
                    " reject_test_publication()")
            conn.commit()
            with pytest.raises(Exception, match="test publication rejection"):
                P.publish(conn, run_id=candidate.progress.run_id,
                          window_start=START, window_end=END)
            assert lifecycle(conn, candidate.progress.run_id) == [
                anomalies.PENDING]
            assert not P.coherence(conn).coherent
            with conn.cursor() as cur:
                cur.execute("DROP TRIGGER reject_test_publication ON"
                            " sentinel_corpus_publications")
                cur.execute("DROP FUNCTION reject_test_publication()")
            conn.commit()
            P.publish(conn, run_id=candidate.progress.run_id,
                      window_start=START, window_end=END)
        assert lifecycle(conn, candidate.progress.run_id) == [
            anomalies.PENDING, anomalies.PUBLISHED]
        assert P.coherence(conn).coherent

    def test_successful_retry_supersedes_unresolved_publication_candidate(
            self, conn):
        unresolved = S.IngestRun(conn, "publication-failed")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_CORROBORATED_DERIVED", "pending")],
                run_id=unresolved.progress.run_id, require_lock=True)
            unresolved.finish("success")
        assert not P.coherence(conn).coherent

        retry = publish_observation(
            conn, "SPLIT_CORROBORATED_DERIVED", "retry published")
        assert P.coherence(conn).coherent
        assert lifecycle(conn, unresolved.progress.run_id) == [
            anomalies.PENDING, anomalies.SUPERSEDED]
        assert lifecycle(conn, retry) == [anomalies.PENDING, anomalies.PUBLISHED]

    def test_crash_reclaim_then_retry_keeps_history_and_recovers(self, conn):
        crashed = S.IngestRun(conn, "crashed-correction")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_CORROBORATED_DERIVED", "crashed")],
                run_id=crashed.progress.run_id, require_lock=True)
        assert not P.coherence(conn).coherent
        assert S.reclaim_orphans(conn) == 1
        assert S.reclaim_orphans(conn) == 0
        assert lifecycle(conn, crashed.progress.run_id) == [
            anomalies.PENDING, anomalies.ABORTED]

        publish_observation(conn, "SPLIT_CORROBORATED_DERIVED", "retry")
        assert P.coherence(conn).coherent
        assert RA.audit(conn, start=START, end=END, **EMPTY_BOOK).certifiable

    def test_repeated_identical_candidate_writes_are_idempotent(self, conn):
        candidate = S.IngestRun(conn, "repeated-candidate")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_ONLY_DERIVED", "first immutable")],
                run_id=candidate.progress.run_id, require_lock=True)
            S.write_anomalies(
                conn, [observation("SPLIT_ONLY_DERIVED", "later duplicate")],
                run_id=candidate.progress.run_id, require_lock=True)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*),MIN(detail)"
                        " FROM sentinel_corpus_anomalies"
                        " WHERE last_written_run_id = %s",
                        (candidate.progress.run_id,))
            assert cur.fetchone() == (1, "first immutable")
        assert lifecycle(conn, candidate.progress.run_id) == [anomalies.PENDING]

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

    def test_reclaim_cannot_supersede_a_newer_publication(self, conn):
        orphan = S.IngestRun(conn, "orphan-before-new-publication")
        with S.corpus_write_lock(conn):
            S.write_anomalies(
                conn, [observation("SPLIT_ONLY_DERIVED", "orphan")],
                run_id=orphan.progress.run_id, require_lock=True)
        publish_observation(conn, "SPLIT_AUTHORITATIVE_APPLIED", "newer")
        assert lifecycle(conn, orphan.progress.run_id) == [
            anomalies.PENDING, anomalies.SUPERSEDED]
        assert S.reclaim_orphans(conn) == 1
        assert S.reclaim_orphans(conn) == 0
        assert lifecycle(conn, orphan.progress.run_id) == [
            anomalies.PENDING, anomalies.SUPERSEDED]
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_AUTHORITATIVE_APPLIED"]


class TestExplicitResolvedDispositions:
    def test_corrected_unusable_dividend_emits_published_tombstone(self, conn):
        S.write_anomalies(conn, [{
            "kind": "UNUSABLE_DIVIDEND", "ticker": "AAA",
            "session": EVENT, "detail": "old missing amount"}])
        retry = S.IngestRun(conn, "corrected-dividend")
        source = [{"ticker": "AAA", "date": EVENT,
                   "action": "dividend", "value": 1.25}]
        with S.corpus_write_lock(conn):
            S.write_actions(conn, source, run_id=retry.progress.run_id)
            tombstones = ingest._resolution_tombstones(
                conn, retry, lo=START, hi=END,
                report=domains.NormalisationReport(), emitted=[],
                current_action_rows=source)
            assert [row["kind"] for row in tombstones] == [
                "DIVIDEND_RESOLVED"]
            S.write_anomalies(
                conn, tombstones, run_id=retry.progress.run_id,
                require_lock=True)
            retry.finish("success")
            P.publish(conn, run_id=retry.progress.run_id,
                      window_start=START, window_end=END)

        history = anomalies.active_rows(
            conn, start=START, end=END,
            kinds=anomalies.DIVIDEND_DISPOSITION_KINDS)
        assert [row["kind"] for row in history] == ["DIVIDEND_RESOLVED"]
        assert RA.audit(conn, start=START, end=END, **EMPTY_BOOK).certifiable
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_corpus_anomalies")
            assert cur.fetchone()[0] == 2

    def test_removed_split_emits_no_event_tombstone_only_with_sep_coverage(
            self, conn):
        publish_observation(conn, "SPLIT_ONLY_DERIVED", "old split")
        retry = S.IngestRun(conn, "split-removed")
        with S.corpus_write_lock(conn):
            S.write_bars(conn, [current_bar()], run_id=retry.progress.run_id,
                         require_lock=True)
            tombstones = ingest._resolution_tombstones(
                conn, retry, lo=START, hi=END,
                report=domains.NormalisationReport(), emitted=[],
                current_action_rows=[])
            assert [row["kind"] for row in tombstones] == [
                "SPLIT_RESOLVED_NO_EVENT"]
            S.write_anomalies(
                conn, tombstones, run_id=retry.progress.run_id,
                require_lock=True)
            retry.finish("success")
            P.publish(conn, run_id=retry.progress.run_id,
                      window_start=START, window_end=END)

        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_RESOLVED_NO_EVENT"]
        assert RA.audit(conn, start=START, end=END, **EMPTY_BOOK).certifiable

    def test_missing_current_sep_coverage_cannot_resolve_by_silence(self, conn):
        publish_observation(conn, "SPLIT_ONLY_DERIVED", "old split")
        retry = S.IngestRun(conn, "split-uncovered")
        with S.corpus_write_lock(conn):
            assert ingest._resolution_tombstones(
                conn, retry, lo=START, hi=END,
                report=domains.NormalisationReport(), emitted=[],
                current_action_rows=[]) == []
            retry.finish("success")
            P.publish(conn, run_id=retry.progress.run_id,
                      window_start=START, window_end=END)
        assert [row["kind"] for row in active(conn)] == [
            "SPLIT_ONLY_DERIVED"]
        assert not RA.audit(conn, start=START, end=END,
                            **EMPTY_BOOK).certifiable


def test_legacy_schema_upgrade_retains_ambiguous_evidence_fail_closed(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE sentinel_anomaly_observation_events")
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


def test_schema_upgrade_classifies_stamped_legacy_rows_deterministically(conn):
    published = publish_observation(
        conn, "SPLIT_CORROBORATED_DERIVED", "legacy published")
    failed = S.IngestRun(conn, "legacy-failed")
    running = S.IngestRun(conn, "legacy-running")
    with S.corpus_write_lock(conn):
        S.write_anomalies(
            conn, [{**observation("SPLIT_ONLY_DERIVED", "legacy failed"),
                    "ticker": "BBB"}],
            run_id=failed.progress.run_id, require_lock=True)
        failed.finish("failed", "legacy durable failure")
        S.write_anomalies(
            conn, [{**observation("SEAM_SPLIT_UNCORROBORATED",
                                  "legacy unresolved"), "ticker": "CCC"}],
            run_id=running.progress.run_id, require_lock=True)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_anomaly_observation_events")
    conn.commit()

    S.ensure_schema(conn)

    assert lifecycle(conn, published) == [anomalies.PUBLISHED]
    assert lifecycle(conn, failed.progress.run_id) == [anomalies.ABORTED]
    assert lifecycle(conn, running.progress.run_id) == [anomalies.PENDING]
    report = P.coherence(conn)
    assert not report.coherent
    assert report.unpublished_anomalies == 1
