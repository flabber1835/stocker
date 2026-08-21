from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


loader = Path("sentinel/core/loader.py")
text = loader.read_text(encoding="utf-8")
start = text.index("def load_meta(conn) -> dict[str, SecurityMeta]:")
end = text.index("\n\ndef load_terminal_events", start)
new = r'''def _current_metadata_is_causal(conn, as_of: str) -> bool:
    """Whether the bounded current projection contains no observation after D."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(snapshot_date) FROM feed_universe_current")
        row = cur.fetchone()
    newest = row[0] if row else None
    return newest is not None and str(newest) <= str(as_of)


def _historical_metadata_rows(conn, *, as_of: str):
    """One session-effective metadata row per permanent security.

    Raw ``sentinel_universe`` is the immutable dated TICKERS evidence. Sparse
    fields carry forward only from observations that existed by ``as_of``;
    future snapshots are structurally absent from the CTE. Each ticker pairing
    resolves its own latest non-null value before the outer security aggregate,
    matching ``feed_universe_current`` without importing a later observation.
    """
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        cur.execute(
            "WITH pairing AS ("
            " SELECT permaticker,ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY snapshot_date DESC),NULL))[1] category,"
            "  MAX(snapshot_date) FILTER (WHERE category IS NOT NULL) category_date,"
            "  (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY snapshot_date DESC),NULL))[1] related_tickers,"
            "  MAX(snapshot_date) FILTER (WHERE related_tickers IS NOT NULL) related_date,"
            "  (ARRAY_REMOVE(ARRAY_AGG(first_price_date ORDER BY snapshot_date DESC),NULL))[1] first_price_date,"
            "  MAX(snapshot_date) snapshot_date"
            " FROM sentinel_universe u"
            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"
            "   AND snapshot_date<=%s AND " + visible_predicate("u") +
            " GROUP BY permaticker,ticker)"
            " SELECT permaticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(ticker ORDER BY snapshot_date DESC),NULL))[1] ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY category_date DESC NULLS LAST),NULL))[1] category,"
            "  (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY related_date DESC NULLS LAST),NULL))[1] related_tickers,"
            "  MIN(first_price_date) first_session"
            " FROM pairing GROUP BY permaticker",
            (as_of,))
        return cur.fetchall()


def load_meta(conn, *, as_of: str | None = None) -> dict[str, SecurityMeta]:
    """Per-security strategy metadata, optionally bounded to decision session D.

    Normal live planning uses the bounded ``feed_universe_current`` projection
    when that projection contains no observation after D. Outage catch-up must
    not do that: a recovery-day TICKERS snapshot is future information for a
    missed decision. In that case this reads the immutable dated snapshots and
    permits only observations with ``snapshot_date <= D``.
    """
    if as_of is not None and not _current_metadata_is_causal(conn, as_of):
        rows = _historical_metadata_rows(conn, as_of=as_of)
        if not rows:
            raise RuntimeError(
                f"no causally available TICKERS metadata exists on or before {as_of}")
    else:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,"
                " (ARRAY_REMOVE(ARRAY_AGG(ticker ORDER BY snapshot_date DESC),"
                "  NULL))[1] AS ticker,"
                " (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY"
                "  category_snapshot_date DESC NULLS LAST), NULL))[1] AS category,"
                " (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY"
                "  related_tickers_snapshot_date DESC NULLS LAST), NULL))[1]"
                "  AS related_tickers,"
                " MIN(first_price_date) AS first_session"
                " FROM feed_universe_current WHERE permaticker IS NOT NULL"
                " GROUP BY permaticker")
            rows = cur.fetchall()

    out: dict[str, SecurityMeta] = {}
    for permaticker, ticker, category, related, first_session in rows:
        out[str(permaticker)] = SecurityMeta(
            security_id=str(permaticker),
            ticker=str(ticker or permaticker),
            category=category,
            permaticker=str(permaticker),
            related_tickers=parse_related_tickers(related),
            first_session=None if first_session is None else str(first_session))
    return out


def load_sectors(conn, *, as_of: str | None = None) -> dict[str, str | None]:
    """Native-Sentinel sector labels with the same session-effective boundary."""
    if as_of is None or _current_metadata_is_causal(conn, as_of):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,"
                " (ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY"
                "  sector_snapshot_date DESC NULLS LAST),NULL))[1]"
                " FROM feed_universe_current WHERE permaticker IS NOT NULL"
                " GROUP BY permaticker")
            return {str(sid): sector for sid, sector in cur.fetchall()}

    from sentinel.feed.publication import visible_predicate
    with conn.cursor() as cur:
        cur.execute(
            "WITH pairing AS ("
            " SELECT permaticker,ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY snapshot_date DESC),NULL))[1] sector,"
            "  MAX(snapshot_date) FILTER (WHERE sector IS NOT NULL) sector_date"
            " FROM sentinel_universe u"
            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"
            "   AND snapshot_date<=%s AND " + visible_predicate("u") +
            " GROUP BY permaticker,ticker)"
            " SELECT permaticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY sector_date DESC NULLS LAST),NULL))[1]"
            " FROM pairing GROUP BY permaticker",
            (as_of,))
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError(
            f"no causally available TICKERS sector metadata exists on or before {as_of}")
    return {str(sid): sector for sid, sector in rows}
'''
loader.write_text(text[:start] + new + text[end:], encoding="utf-8")

replace_once(
    "sentinel/core/production.py",
    '''    from sentinel.core.loader import load_meta, load_terminal_events''',
    '''    from sentinel.core.loader import load_meta, load_sectors, load_terminal_events''')
replace_once(
    "sentinel/core/production.py",
    '''    meta = load_meta(conn)''',
    '''    meta = load_meta(conn, as_of=session)''')
replace_once(
    "sentinel/core/production.py",
    '''        cur.execute(
            "SELECT permaticker,(ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY"
            " snapshot_date DESC),NULL))[1] FROM sentinel_universe u"
            " WHERE permaticker IS NOT NULL"
            f" AND {visible_predicate('u')} GROUP BY permaticker")
        sectors = {str(sid): sector for sid, sector in cur.fetchall()}''',
    '''        sectors = load_sectors(conn, as_of=session)''')

Path("tests/sentinel/test_issue209_session_effective_metadata.py").write_text(r'''import datetime as dt

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
''', encoding="utf-8")
