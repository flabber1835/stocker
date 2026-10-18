"""Listing metadata publication preserves candidate isolation and null semantics."""
import pytest
from sentinel.feed import publication, store, universe
from tests.support.postgres import _EphemeralPostgres


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
    connection = store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    connection.commit()
    store.migrate_schema(connection)
    yield connection
    connection.close()


class TestListingWindowCorrections:
    @staticmethod
    def _publish_universe(conn, *, snapshot, first=None, last=None,
                          relatedtickers=None):
        run = store.IngestRun(conn, "daily")
        run_id = run.progress.run_id
        row = {"ticker": "ABC", "permaticker": "P1",
               "firstpricedate": first, "lastpricedate": last}
        if relatedtickers is not None:
            row["relatedtickers"] = relatedtickers
        universe.write_universe(conn, [row], snapshot, run_id=run_id)
        run.finish("success")
        publication.publish(conn, run_id=run_id)
        return run_id

    def test_later_authority_can_narrow_both_listing_bounds(self, conn):
        self._publish_universe(
            conn, snapshot="2026-08-01",
            first="2000-01-03", last="2026-08-01")
        current = universe.load_resolver(conn)
        assert current.resolve("ABC", "2005-01-03") == "P1"
        assert current.resolve("ABC", "2024-01-03") == "P1"

        candidate = store.IngestRun(conn, "daily")
        run_id = candidate.progress.run_id
        universe.write_universe(
            conn,
            [{"ticker": "ABC", "permaticker": "P1",
              "firstpricedate": "2010-01-04",
              "lastpricedate": "2020-12-31"}],
            "2026-08-02", run_id=run_id)

        # Publication isolation: existing readers keep the old interval, while
        # the candidate resolver validates bars against the interval it would
        # make authoritative if publication succeeds.
        assert universe.load_resolver(conn).resolve("ABC", "2005-01-03") == "P1"
        proposed = universe.load_resolver(conn, include_run_id=run_id)
        assert proposed.resolve("ABC", "2005-01-03") is None
        assert proposed.resolve("ABC", "2015-01-05") == "P1"
        assert proposed.resolve("ABC", "2024-01-03") is None

        candidate.finish("success")
        publication.publish(conn, run_id=run_id)
        published = universe.load_resolver(conn)
        assert published.resolve("ABC", "2005-01-03") is None
        assert published.resolve("ABC", "2015-01-05") == "P1"
        assert published.resolve("ABC", "2024-01-03") is None

    def test_authoritative_empty_related_tickers_clears_but_null_carries(self,
                                                                          conn):
        self._publish_universe(
            conn, snapshot="2026-08-01", relatedtickers="BBB CCC")
        with conn.cursor() as cur:
            cur.execute("SELECT related_tickers FROM feed_universe_current")
            assert cur.fetchone()[0] == "BBB CCC"

        # Blank is observed evidence: no issuer siblings now. It must be able to
        # clear the old relationship rather than collapsing to SQL NULL.
        run = store.IngestRun(conn, "daily")
        universe.write_universe(
            conn,
            [{"ticker": "ABC", "permaticker": "P1", "relatedtickers": ""}],
            "2026-08-02", run_id=run.progress.run_id)
        run.finish("success")
        publication.publish(conn, run_id=run.progress.run_id)
        with conn.cursor() as cur:
            cur.execute("SELECT related_tickers FROM feed_universe_current")
            assert cur.fetchone()[0] == ""

        # True sparse/null observation carries the last known authoritative
        # empty set forward; it does not resurrect the old relationship.
        run = store.IngestRun(conn, "daily")
        universe.write_universe(
            conn,
            [{"ticker": "ABC", "permaticker": "P1", "relatedtickers": None}],
            "2026-08-03", run_id=run.progress.run_id)
        run.finish("success")
        publication.publish(conn, run_id=run.progress.run_id)
        with conn.cursor() as cur:
            cur.execute("SELECT related_tickers FROM feed_universe_current")
            assert cur.fetchone()[0] == ""


@pytest.fixture(autouse=True)
def synthetic_producer_identity(monkeypatch):
    from sentinel import identity
    monkeypatch.setattr(identity, "require_feed_producer_identity", lambda: {
        "schema": "sentinel.feed-producer/1", "git_commit": "a" * 40,
        "runtime_image_digest": "sha256:" + "b" * 64, "image_source_revision": "a" * 40})
    monkeypatch.setenv("SENTINEL_PUBLICATION_RECEIPT_KEY", "test-only-receipt-key-" * 4)
