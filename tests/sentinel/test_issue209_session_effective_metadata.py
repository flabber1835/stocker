import datetime as dt

import pytest

from sentinel.core.loader import load_meta, load_sectors
from sentinel.feed import store as feed_store
from sentinel.feed import universe_projection
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    drop_public_tables(connection)
    feed_store.ensure_schema(connection)
    yield connection
    connection.close()


def _snapshot(conn, date, *, category, related, sector):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_universe "
            "(permaticker,ticker,category,sector,related_tickers,first_price_date,"
            " snapshot_date,last_written_run_id) "
            "VALUES ('SEC-A','AAA',%s,%s,%s,'2020-01-01',%s,NULL)",
            (category, sector, related, date))
    universe_projection.project_legacy_snapshot(conn, snapshot_date=date)
    conn.commit()


def test_future_tickers_snapshot_cannot_change_missed_session(conn):
    _snapshot(
        conn, "2026-08-20", category="Domestic Common Stock",
        related="AAA,OLD", sector="Technology")
    before_meta = load_meta(conn, as_of="2026-08-20")["SEC-A"]
    before_sector = load_sectors(conn, as_of="2026-08-20")["SEC-A"]

    _snapshot(
        conn, "2026-08-24", category="ADR Common Stock",
        related="AAA,NEW", sector="Financial Services")

    # Catch-up for Thursday is causally frozen even though the current
    # projection now contains Monday's later metadata.
    replay_meta = load_meta(conn, as_of="2026-08-20")["SEC-A"]
    replay_sector = load_sectors(conn, as_of="2026-08-20")["SEC-A"]
    assert replay_meta.category == before_meta.category == "Domestic Common Stock"
    assert replay_meta.related_tickers == before_meta.related_tickers
    assert "OLD" in replay_meta.related_tickers and "NEW" not in replay_meta.related_tickers
    assert replay_sector == before_sector == "Technology"

    # The later decision may consume the later observation.
    current_meta = load_meta(conn, as_of="2026-08-24")["SEC-A"]
    assert current_meta.category == "ADR Common Stock"
    assert "NEW" in current_meta.related_tickers
    assert load_sectors(conn, as_of="2026-08-24")["SEC-A"] == "Financial Services"


def test_as_of_before_first_retained_snapshot_refuses(conn):
    _snapshot(
        conn, "2026-08-20", category="Domestic Common Stock",
        related="AAA", sector="Technology")
    with pytest.raises(RuntimeError, match="no causally available TICKERS"):
        load_meta(conn, as_of="2026-08-19")
    with pytest.raises(RuntimeError, match="sector metadata"):
        load_sectors(conn, as_of="2026-08-19")
