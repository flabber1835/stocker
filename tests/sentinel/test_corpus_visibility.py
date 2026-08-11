"""#11 — a decision must never read rows newer than the version it records.

THE FAILURE, written before the fix.

Ingest commits bars every 5,000 rows and publishes a corpus version AFTER the
run succeeds. Publication failure is deliberately non-fatal, because a corpus
that loaded correctly is still correct. Both of those are right on their own and
together they produce this:

```text
corpus at v41
daily ingest writes Aug 10 bars, committing as it goes
publication of v42 FAILS  (a session held the pin, the DB blipped, anything)
latest publication still reports v41
        ↓
Wealth Core reads the Aug 10 bars and stamps the decision data_version = 41
```

The physical corpus and the logical version disagree, and every downstream claim
built on that stamp is wrong — including the one thing `data_version` exists
for, which is telling a replay divergence apart from a data restatement.

THE PROPERTY BEING BOUGHT: **published is what readable means.** Rows written by
an ingest no publication represents are invisible, so a reader either sees a
coherent generation or refuses. Not "usually consistent" — a corpus that is
sometimes ahead of its own version number is worse than one that is behind,
because being behind is detectable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402
from tests.support.source import code_of  # noqa: E402

from sentinel.core import loader  # noqa: E402
from sentinel.feed import publication as P  # noqa: E402
from sentinel.feed import store as S  # noqa: E402


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
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for t in ("sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "sentinel_corpus_publications", "feed_ingest_runs",
                  "sentinel_corpus_anomalies", "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def put_bar(conn, session, ticker="AAA", run_id=None, sid=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id, session, ticker,"
            " close_signal, close_unadjusted, volume, last_written_run_id)"
            " VALUES (%s,%s,%s,10,10,1000,%s)"
            " ON CONFLICT (security_id, session) DO UPDATE SET"
            " last_written_run_id = EXCLUDED.last_written_run_id",
            (sid or f"P-{ticker}", session, ticker, run_id))
    conn.commit()


def a_run(conn, kind="daily"):
    """An ingest run row, returning its id — as `IngestRun` would create it."""
    run = S.IngestRun(conn, kind)
    return run.progress.run_id


class TestTheFailure:
    def test_rows_from_an_UNPUBLISHED_ingest_are_INVISIBLE(self, conn):
        """The whole point. The bars are physically present and committed; no
        publication represents them, so no reader may see them."""
        published_run = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=published_run)
        P.publish(conn, run_id=published_run)

        orphan_run = a_run(conn)                 # its publication "failed"
        put_bar(conn, "2026-08-10", run_id=orphan_run, sid="P-AAA2")

        window = loader.load_window(conn, start="2026-08-01", end="2026-08-31")
        assert window.sessions == ["2026-08-09"], (
            "2026-08-10 was written by a run no publication represents; a "
            "decision reading it would stamp itself with the PREVIOUS version")

    def test_the_version_and_the_visible_rows_now_AGREE(self, conn):
        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)
        put_bar(conn, "2026-08-10", run_id=a_run(conn), sid="P-AAA2")

        assert P.require_current(conn).version == 1
        assert loader.load_window(conn, start="2026-08-01",
                                  end="2026-08-31").sessions == ["2026-08-09"]

    def test_publishing_the_run_makes_its_rows_visible(self, conn):
        """Convergence: the fix must not lose data, only sequence it. Once the
        publication lands, the rows appear — no re-ingest required."""
        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)

        run_b = a_run(conn)
        put_bar(conn, "2026-08-10", run_id=run_b, sid="P-AAA2")
        assert loader.load_window(conn, start="2026-08-01",
                                  end="2026-08-31").sessions == ["2026-08-09"]

        P.publish(conn, run_id=run_b)
        assert loader.load_window(conn, start="2026-08-01",
                                  end="2026-08-31").sessions == ["2026-08-09",
                                                                 "2026-08-10"]

    def test_bars_with_NO_run_id_stay_visible(self, conn):
        """Rows predating provenance tracking are legitimate corpus. Hiding them
        would silently empty an existing deployment's history — a migration
        that looks like data loss."""
        put_bar(conn, "2020-01-02", run_id=None)
        P.publish(conn, run_id=a_run(conn))
        assert loader.load_window(conn, start="2020-01-01",
                                  end="2020-12-31").sessions == ["2020-01-02"]


class TestTheCoherenceGate:
    def test_an_unpublished_run_is_REPORTED_not_merely_hidden(self, conn):
        """Hiding alone would be silent. An operator needs to know the corpus
        holds data nothing can read, because the remedy is to publish it."""
        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)
        put_bar(conn, "2026-08-10", run_id=a_run(conn), sid="P-AAA2")

        report = P.coherence(conn)
        assert not report.coherent
        assert report.unpublished_rows == 1
        assert len(report.unpublished_runs) == 1

    def test_a_coherent_corpus_reports_clean(self, conn):
        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)
        assert P.coherence(conn).coherent

    def test_planning_REFUSES_an_incoherent_corpus(self, conn):
        """Fail closed. The alternative is a decision stamped with a version
        that does not describe what it read."""
        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)
        put_bar(conn, "2026-08-10", run_id=a_run(conn), sid="P-AAA2")

        with pytest.raises(P.CorpusIncoherent, match="unpublished"):
            P.assert_coherent(conn)

    def test_an_empty_corpus_is_coherent_rather_than_broken(self, conn):
        assert P.coherence(conn).coherent

    def test_a_run_that_wrote_NOTHING_is_not_an_incoherence(self, conn):
        """An ingest may legitimately open a row, find no new sessions and
        finish. Counting those would fire the alarm on every clean daily, and an
        alarm that fires on the normal case is one nobody reads."""
        put_bar(conn, "2026-08-09", run_id=a_run(conn))
        P.publish(conn)                       # a publication naming no run
        a_run(conn)                           # opened, wrote nothing
        # The BAR's run is still unpublished, so the corpus is incoherent for
        # that reason — but the empty run must not add to the count.
        assert P.coherence(conn).unpublished_rows == 1

    def test_the_EXHAUSTIVE_mode_sees_an_orphaned_run_id(self, conn):
        """The cheap enumeration reads `feed_ingest_runs`, which is exact for
        anything this codebase writes. It cannot see a run id whose run row was
        deleted by hand, and claiming otherwise would be the kind of
        approximately-true provenance this module exists to remove."""
        run = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feed_ingest_runs WHERE run_id = %s", (run,))
        conn.commit()

        assert P.coherence(conn).coherent, "the cheap enumeration cannot see it"
        deep = P.coherence(conn, exhaustive=True)
        assert not deep.coherent and deep.unpublished_rows == 1
        # ...and the row is invisible either way, which is the property that
        # actually protects a decision. The enumeration only affects REPORTING.
        assert loader.load_window(conn, start="2026-08-01",
                                  end="2026-08-31").sessions == []


class TestEveryReaderAgrees:
    """One corpus, one frontier. The defect class this closes is two components
    holding different views of the same fact and each being individually
    correct — the shape of the ownership-reader split."""

    def test_the_reported_frontier_is_the_READABLE_one(self, conn):
        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)
        put_bar(conn, "2026-08-10", run_id=a_run(conn), sid="P-AAA2")

        # The INGEST resume point is the physical frontier — filtering it would
        # re-fetch the unpublished window every evening forever.
        assert S.latest_session(conn) == "2026-08-10"
        # What a decision may read is the published one.
        assert S.latest_visible_session(conn) == "2026-08-09"

    def test_readiness_FAILS_on_an_incoherent_corpus(self, conn):
        from sentinel.feed import readiness

        run_a = a_run(conn)
        put_bar(conn, "2026-08-09", run_id=run_a)
        P.publish(conn, run_id=run_a)
        put_bar(conn, "2026-08-10", run_id=a_run(conn), sid="P-AAA2")

        state = readiness.check_readiness(conn, today="2026-08-10")
        failed = {c.name for c in state.failures}
        assert "corpus coherence" in failed
        assert not state.ready

    def test_a_hand_built_corpus_WARNS_rather_than_failing(self, conn):
        """Rows with no ingest id are readable and unversioned. Refusing them
        would make an upgrade indistinguishable from data loss — the same reason
        they stay visible."""
        from sentinel.feed import readiness

        put_bar(conn, "2026-08-10", run_id=None)
        state = readiness.check_readiness(conn, today="2026-08-10")
        version = [c for c in state.checks if c.name == "corpus version"][0]
        assert version.status == readiness.WARN
        assert "corpus coherence" not in {c.name for c in state.failures}


class TestMemory:
    def test_the_loader_STREAMS_rather_than_fetchall(self, conn):
        """#10. `fetchall()` materialised every row and then built a second
        complete graph of VendorBar objects, so both representations coexisted
        at peak — on the machine whose memory ceiling is the binding constraint
        for the whole deployment."""
        # THE CODE, not the prose — see tests/support/source.py. The first
        # version grepped raw source and went red on the docstring EXPLAINING
        # why fetchall() was removed, which is a guard that punishes its own
        # explanation.
        assert "fetchall" not in code_of(loader.load_window), (
            "iterate the cursor; the second full copy is free to avoid")
