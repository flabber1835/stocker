"""A priced-but-unnameable security survives INGEST as evidence.

THE DEFECT, found in certification review. S4 keys its relevance population on
the RAW VENDOR TICKER precisely so that a security the vendor priced but the
ingest could not NAME stays visible. But it read that population from
`sentinel_bars`, and `domains.normalise_sep_rows` DROPS an unresolvable row
before storage:

    SEP prices XYZ
      -> identity resolution fails
      -> normaliser drops the bar          (correct: keying on the ticker would
                                            re-introduce the reuse splice)
      -> no XYZ anywhere in sentinel_bars
      -> S4 sees a terminal action for XYZ
      -> "XYZ was never priced in this corpus"
      -> SECURITY_ABSENT_FROM_CORPUS

That is the exact hiding S4 was built to prevent, arriving one layer UPSTREAM of
where it was defended.

WHY THE EXISTING TEST COULD NOT CATCH IT. S4's unit test writes a bar into
`sentinel_bars` and then withholds its identity — a perfectly valid test of an
IMPOSSIBLE PRODUCTION STATE, because ordinary ingestion can never produce it.
So this suite drives `ingest.seed()` and `ingest.daily()` with a fake vendor and
asserts on what survives.

THE INVARIANT:

    if Sharadar SEP presented a priced ticker in the operational window and
    identity resolution failed, that fact SURVIVES ingestion, and readiness
    cannot classify its terminal action as SECURITY_ABSENT_FROM_CORPUS
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import terminal as T  # noqa: E402
from sentinel.feed import ingest, sharadar  # noqa: E402
from sentinel.feed import readiness as R  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

TODAY = "2024-12-31"


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
        for t in ("sentinel_processed_sessions",
                  "sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "sentinel_publication_validation_receipts",
                  "sentinel_publication_validation_policy",
                  "sentinel_corpus_publications",
                  "feed_ingest_runs", "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.require_feed_schema(c)
    yield c
    c.close()


def sess(n, end=TODAY):
    from sentinel.feed import calendar as C
    return C.previous_sessions(end, n)


def fake_vendor(*, sep_tickers, actions=(), tickers=()):
    """A stand-in for SHARADAR. `sep_tickers` prices every named symbol on every
    session in the retained fixture; `tickers` is the identity table, so a symbol
    priced and NOT listed is exactly the unnameable case.

    Like the real source contract, each bounded call exposes only rows inside its
    inclusive requested interval. Returning the full retained fixture for a
    yearly seed chunk would itself be an off-envelope provider defect.
    """
    days = sess(30)

    def fetch(table, params=None, **kw):
        params = dict(params or {})
        lo = params.get("date.gte", "0000-00-00")
        hi = params.get("date.lte", "9999-99-99")
        if table == sharadar.SEP:
            return [{"date": d, "ticker": t, "close": 100.0,
                     "closeunadj": 100.0, "open": 99.0, "volume": 1e6,
                     "lastupdated": d}
                    for d in days if lo <= d <= hi for t in sep_tickers]
        if table == sharadar.ACTIONS:
            rows = list(actions)
            if not rows and params.get("date.gte") == "1900-01-01":
                return [{"ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
                         "action": "listed", "value": None,
                         "contraticker": None}]
            return [row for row in rows if lo <= str(row.get("date") or "") <= hi]
        if table == sharadar.TICKERS:
            return list(tickers)
        return []
    return fetch


def listing(ticker, permaticker):
    return {"permaticker": permaticker, "ticker": ticker,
            "firstpricedate": "2000-01-03", "lastpricedate": None,
            "relatedtickers": "", "category": "Domestic Common Stock"}


# ── 1. the evidence survives a REAL ingest ───────────────────────────────────

class TestARealIngestPreservesTheRefusal:

    def test_an_unnameable_priced_ticker_is_RECORDED(self, conn):
        """`AAA` is listed, `XYZ` is priced and has no identity."""
        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY,
                    fetch=fake_vendor(sep_tickers=["AAA", "XYZ"],
                                      tickers=[listing("AAA", "P:AAA")]))

        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ticker FROM sentinel_bars")
            stored = {r[0] for r in cur.fetchall()}
        assert stored == {"AAA"}, "the unnameable bar was stored after all"

        rejected = S.rejected_tickers(conn, sess(30)[0], TODAY)
        assert "XYZ" in rejected, (
            "the ingest dropped a priced row and left no evidence it existed")

    def test_re_ingest_appends_history_but_active_projection_is_idempotent(self, conn):
        f = fake_vendor(sep_tickers=["AAA", "XYZ"],
                        tickers=[listing("AAA", "P:AAA")])
        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY, fetch=f)
        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY, fetch=f)
        expected = len(sess(30))
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT last_written_run_id)"
                        " FROM sentinel_ingest_rejections"
                        " WHERE ticker = 'XYZ'")
            raw_count, generations = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM sentinel_active_ingest_rejections"
                        " WHERE ticker = 'XYZ'")
            active_count = cur.fetchone()[0]
        assert raw_count == 2 * expected, (
            "re-ingest must retain one immutable rejection observation per run")
        assert generations == 2, "re-ingest collapsed distinct evidence generations"
        assert active_count == expected, (
            "the current rejection projection multiplied across equivalent re-ingests")

    def test_SEED_records_them_too(self, conn):
        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY,
                    fetch=fake_vendor(sep_tickers=["AAA", "XYZ"],
                                      tickers=[listing("AAA", "P:AAA")]))
        assert "XYZ" in S.rejected_tickers(conn, "2024-11-01", TODAY)


# ── 2. and defeats the misclassification ─────────────────────────────────────

class TestTheTerminalActionIsNotHIDDEN:

    def _ingest(self, conn):
        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY,
                    fetch=fake_vendor(
                        sep_tickers=["AAA", "XYZ"],
                        tickers=[listing("AAA", "P:AAA")],
                        actions=[{"ticker": "XYZ", "date": sess(30)[15],
                                  "action": "delisted", "value": None,
                                  "contraticker": None}]))

    def test_it_is_UNRESOLVED_not_ABSENT_FROM_CORPUS(self, conn):
        self._ingest(conn)
        acc = T.load_terminal_events(
            conn, start=sess(30)[0], end=TODAY,
            resolve_with_reason=__import__(
                "sentinel.feed.universe", fromlist=["load_resolver"]
            ).load_resolver(conn).resolve_with_reason)

        excluded = [x.reason for x in acc.excluded]
        assert T.EXCLUDED_ABSENT_FROM_CORPUS not in excluded, (
            "the terminal action was filed as 'never priced' because the "
            "ingest had already erased the evidence that it was")
        assert [x.ticker for x in acc.unresolved] == ["XYZ"]
        assert acc.unresolved[0].reason == "NO_PERMANENT_ID"
        assert acc.conservation_holds()

    def test_a_genuinely_UNPRICED_ticker_is_still_excluded(self, conn):
        """The control. The union must not turn every unknown symbol into an
        unresolved termination — a security the vendor never priced still
        cannot affect a book."""
        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY,
                    fetch=fake_vendor(
                        sep_tickers=["AAA"], tickers=[listing("AAA", "P:AAA")],
                        actions=[{"ticker": "GONE", "date": sess(30)[15],
                                  "action": "delisted", "value": None,
                                  "contraticker": None}]))
        acc = T.load_terminal_events(
            conn, start=sess(30)[0], end=TODAY,
            resolve_with_reason=__import__(
                "sentinel.feed.universe", fromlist=["load_resolver"]
            ).load_resolver(conn).resolve_with_reason)
        assert [x.reason for x in acc.excluded] == [T.EXCLUDED_ABSENT_FROM_CORPUS]
        assert acc.unresolved == []


# ── 3. readiness says so in its own right ────────────────────────────────────

class TestReadinessReportsTheRefusals:

    def test_dropped_rows_are_LOUD(self, conn):
        ingest.seed(conn, date_from="2023-06-01", date_to=TODAY,
                    fetch=fake_vendor(sep_tickers=["AAA", "XYZ"],
                                      tickers=[listing("AAA", "P:AAA")]))
        c = {x.name: x for x in R.check_readiness(conn, today=TODAY).checks}
        assert "ingest refusals" in c
        assert c["ingest refusals"].status == R.WARN
        assert "PRICE_ROW_DROPPED_NO_IDENTITY" in c["ingest refusals"].detail
        assert "XYZ" in c["ingest refusals"].detail

    def test_a_clean_ingest_reports_none(self, conn):
        ingest.seed(conn, date_from="2023-06-01", date_to=TODAY,
                    fetch=fake_vendor(sep_tickers=["AAA"],
                                      tickers=[listing("AAA", "P:AAA")]))
        c = {x.name: x for x in R.check_readiness(conn, today=TODAY).checks}
        assert c["ingest refusals"].status == R.PASS
