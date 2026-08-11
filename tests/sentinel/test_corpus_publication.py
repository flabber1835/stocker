"""`data_version` — an EXISTING invariant, finally implemented.

Architecture invariant #3 already reads *"every snapshot and decision records
data_version"*. It was adopted and unimplemented: there was no version to record,
and `sentinel_bars` is a destructive upsert, so a Sharadar restatement rewrote
the evidence underneath a decision that had already been made.

DETECTION TIER ONLY, and the tests say so. This answers "a decision read v47, the
corpus is now v52, so a replay may not reproduce it". It does not answer "show me
v47" — that needs revision history and is deferred. A test suite that blurred the
two would let the weaker guarantee be cited as the stronger one.

Contract: docs/sentinel-execution-contract.md §8.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import ingest, publication as P, sharadar  # noqa: E402
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


def sep(ticker, date, close=50.0, raw=50.0):
    return {"ticker": ticker, "date": date, "close": close, "closeunadj": raw,
            "open": 49.0, "volume": 1_000_000}


def fetcher(sep_rows, action_rows=()):
    tickers = [{"ticker": t, "permaticker": f"P-{t}"}
               for t in sorted({r["ticker"] for r in sep_rows})]

    def fetch(table, params=None, **kw):
        if table == sharadar.TICKERS:
            return list(tickers)
        lo = (params or {}).get("date.gte", "0000-00-00")
        hi = (params or {}).get("date.lte", "9999-99-99")
        if table == sharadar.ACTIONS:
            return [r for r in action_rows if lo <= r["date"] <= hi]
        return [r for r in sep_rows if lo <= r["date"] <= hi]
    return fetch


class TestARunIsNotAVersion:
    def test_an_unpublished_corpus_REFUSES_to_supply_a_version(self, conn):
        """Treating 'no version' as version 0 would let a decision record
        provenance that does not exist — the silent approximation this module
        exists to remove."""
        assert P.current(conn) is None
        with pytest.raises(P.NoPublishedVersion):
            P.require_current(conn)

    def test_a_successful_ingest_publishes_one(self, conn):
        ingest.seed(conn, date_from="2021-01-01", date_to="2021-12-31",
                    fetch=fetcher([sep("AAA", "2021-06-01")]))
        published = P.require_current(conn)
        assert published.version == 1 and published.previous_version is None
        assert published.evidence["kind"] == "seed"

    def test_a_FAILED_ingest_publishes_NOTHING(self, conn):
        """A run that dies halfway has a run_id. It must never be citable."""
        def exploding(table, params=None, **kw):
            if table == sharadar.SEP:
                raise RuntimeError("vendor exploded")
            return fetcher([sep("AAA", "2021-06-01")])(table, params, **kw)

        with pytest.raises(RuntimeError):
            ingest.seed(conn, date_from="2021-01-01", date_to="2021-12-31",
                        fetch=exploding)
        assert P.current(conn) is None

    def test_versions_CHAIN_so_a_gap_is_detectable(self, conn):
        for year in ("2021", "2022"):
            ingest.seed(conn, date_from=f"{year}-01-01", date_to=f"{year}-12-31",
                        fetch=fetcher([sep("AAA", f"{year}-06-01")]))
        assert P.require_current(conn).version == 2
        assert P.require_current(conn).previous_version == 1
        assert P.chain_gaps(conn) == []

    def test_a_broken_chain_is_REPORTED(self, conn):
        """Rows written by a run that never published leave a gap. Cheap to
        detect precisely because the link is explicit rather than implied by
        ordering."""
        P.publish(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sentinel_corpus_publications"
                        " (previous_version) VALUES (NULL)")
        conn.commit()
        assert P.chain_gaps(conn), "a second row claiming no predecessor"


class TestPinning:
    def test_a_pinned_session_is_told_which_version_it_read(self, conn):
        P.publish(conn, window_start="2021-01-01", window_end="2021-12-31")
        with P.pinned(conn) as version:
            assert version.version == 1

    def test_a_PUBLISH_is_REFUSED_while_a_session_holds_the_pin(self, conn, pg):
        """Without this, `data_version` on a decision is only APPROXIMATELY
        true — the corpus could move between the read and the write — and
        approximately-true provenance is worse than none because it is
        believed."""
        P.publish(conn)
        writer = S.connect(pg.sync_dsn)
        try:
            with P.pinned(conn):
                with pytest.raises(P.CorpusBusy):
                    P.publish(writer)
        finally:
            writer.close()

    def test_the_pin_is_released_and_publishing_resumes(self, conn, pg):
        P.publish(conn)
        with P.pinned(conn):
            pass
        writer = S.connect(pg.sync_dsn)
        try:
            assert P.publish(writer).version == 2
        finally:
            writer.close()

    def test_an_ingest_that_cannot_publish_still_KEEPS_ITS_DATA(self, conn, pg):
        """A corpus that loaded correctly but could not be published is still a
        correct corpus; failing the ingest would discard hours over a
        bookkeeping row. The absence is visible as a stale data_version."""
        P.publish(conn)
        reader = S.connect(pg.sync_dsn)
        try:
            with P.pinned(reader):
                ingest.seed(conn, date_from="2021-01-01", date_to="2021-12-31",
                            fetch=fetcher([sep("AAA", "2021-06-01")]))
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM sentinel_bars")
                assert cur.fetchone()[0] == 1, "the bar was written"
            assert P.require_current(conn).version == 1, "but not published"
        finally:
            reader.close()


class TestProvenanceOnRows:
    def test_a_bar_records_which_ingest_last_wrote_it(self, conn):
        ingest.seed(conn, date_from="2021-01-01", date_to="2021-12-31",
                    fetch=fetcher([sep("AAA", "2021-06-01")]))
        with conn.cursor() as cur:
            cur.execute("SELECT last_written_run_id FROM sentinel_bars")
            assert cur.fetchone()[0] is not None

    def test_the_run_id_matches_the_publication(self, conn):
        ingest.seed(conn, date_from="2021-01-01", date_to="2021-12-31",
                    fetch=fetcher([sep("AAA", "2021-06-01")]))
        published = P.require_current(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT last_written_run_id FROM sentinel_bars")
            assert str(cur.fetchone()[0]) == published.run_id


class TestBoundedWrites:
    def test_bars_are_flushed_in_BATCHES_not_one_list(self, conn):
        """Peak memory O(batch), not O(chunk). The generator used to be drained
        into a single list, so a seed year was resident twice on a NAS whose
        memory ceiling is the binding constraint for the whole deployment."""
        from stock_strategy_shared.wealth_core.feed import VendorBar

        seen = {"max_batch": 0}
        real = conn.cursor

        class CountingCursor:
            def __init__(self, inner): self.inner = inner
            def __enter__(self): return self
            def __exit__(self, *a): return self.inner.__exit__(*a)
            def executemany(self, sql, rows):
                seen["max_batch"] = max(seen["max_batch"], len(rows))
                return self.inner.__enter__().executemany(sql, rows)
            def __getattr__(self, name): return getattr(self.inner, name)

        def counting():
            return CountingCursor(real())

        bars = (VendorBar(session="2021-06-01", security_id=f"S-{i}",
                          ticker=f"T{i}", raw_close=10.0, raw_open=9.0,
                          volume=1000.0, split_ratio=1.0,
                          dividend_per_share=0.0, tradeable=True)
                for i in range(25))
        conn.cursor = counting
        try:
            written = S.write_bars(conn, bars, batch_size=10)
        finally:
            conn.cursor = real

        assert written == 25
        assert seen["max_batch"] == 10, "never more than one batch in memory"

    def test_an_empty_stream_writes_nothing_and_does_not_error(self, conn):
        assert S.write_bars(conn, iter(())) == 0
