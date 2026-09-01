"""Seed and daily ingest, driven end-to-end with an injected fetcher.

No network. The point is the ORCHESTRATION: that chunks publish committed
progress, that an interrupted seed resumes rather than duplicates, that the daily
path overlaps the frontier so a restated bar is repaired, and that the retry
constants — which encode an outage rather than a preference — have not drifted
from the ones bt-data arrived at.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
#: The REPOSITORY under inspection. Inside the certified image ROOT is /work
#: (tests, an importable backtester copy, tools) while the repo SOURCES live at
#: /work/repo — so a repo file read through ROOT resolves in a checkout and
#: raises FileNotFoundError in the image.
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import ingest, sharadar  # noqa: E402
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
        for t in ("sentinel_processed_sessions",
                  "sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_bars", "sentinel_spy_total_return",
                  "sentinel_defensive_bars",
                  "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.require_feed_schema(c)
    yield c
    c.close()


def sep_row(ticker, date, close=50.0, raw=100.0, open_=49.0):
    return {"ticker": ticker, "date": date, "close": close,
            "closeunadj": raw, "open": open_, "volume": 1_000_000,
            "lastupdated": date}


CONTROL_ACTION = {
    "ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
    "action": "listed", "value": None, "contraticker": None,
}


def fetcher(sep_rows, action_rows=None, ticker_rows=None, sfp_rows=()):
    """An injected fetch that records which windows were requested.

    TICKERS defaults to one open-ended listing per symbol seen in `sep_rows`, so
    identity resolves 1:1 and these tests stay about ORCHESTRATION. Resolution
    itself is covered in test_feed_universe.py.

    The real complete Sharadar ACTIONS table is globally non-empty. Most tests
    here have no action relevant to their securities, so an unrelated historical
    control row keeps the synthetic *source* realistic without changing the
    economic assertions under test.
    """
    calls = []
    if action_rows is None:
        action_rows = (CONTROL_ACTION,)
    if ticker_rows is None:
        ticker_rows = [{"ticker": t, "permaticker": f"P-{t}"}
                       for t in sorted({r["ticker"] for r in sep_rows})]

    def fetch(table, params=None, **kw):
        params = dict(params or {})
        calls.append((table, params))
        if table == sharadar.TICKERS:
            return list(ticker_rows)
        lo = params.get("date.gte", "0000-00-00")
        hi = params.get("date.lte", "9999-99-99")
        if table == sharadar.ACTIONS:
            return [r for r in action_rows if lo <= r["date"] <= hi]
        if table == sharadar.SFP:
            return [r for r in sfp_rows if lo <= r["date"] <= hi]
        if "lastupdated.gte" in params or "lastupdated.lte" in params:
            update_lo = params.get("lastupdated.gte", "0000-00-00")
            update_hi = params.get("lastupdated.lte", "9999-99-99")
            return [r for r in sep_rows
                    if update_lo <= r.get("lastupdated", "") <= update_hi]
        return [r for r in sep_rows if lo <= r["date"] <= hi]

    fetch.calls = calls
    return fetch


class TestSeed:
    def test_a_reversed_range_refuses_before_a_run_row_exists(self, conn):
        called = []

        def fetch(*args, **kwargs):
            called.append((args, kwargs))
            return []

        with pytest.raises(ValueError, match="reversed date range"):
            ingest.seed(conn, date_from="2024-02-01", date_to="2024-01-01",
                        fetch=fetch)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM feed_ingest_runs")
            assert cur.fetchone()[0] == 0
        assert called == []

    def test_it_chunks_by_YEAR_and_publishes_each(self, conn, pg):
        rows = [sep_row("AAA", "2020-06-01"), sep_row("AAA", "2021-06-01"),
                sep_row("BBB", "2022-06-01")]
        p = ingest.seed(conn, date_from="2020-01-01", date_to="2022-12-31",
                        fetch=fetcher(rows))
        assert p.chunks_total == 6     # tickers + actions + SPY + three years
        assert p.chunks_done == 6

        watcher = S.connect(pg.sync_dsn)
        try:
            r = next(row for row in S.run_status(watcher)
                     if str(row["run_id"]) == str(p.run_id))
            assert r["status"] == "success"
            assert r["chunks_done"] == 6
            assert r["rows_written"] == 3 + 2   # bars + two TICKERS listings
        finally:
            watcher.close()

    def test_IDENTITY_then_ACTIONS_then_prices(self, conn):
        """Order is load-bearing twice over. TICKERS must precede the prices or
        every bar is dropped as unresolvable; ACTIONS must precede them so the
        derived split ratio has something to be cross-checked against from the
        first year rather than the last."""
        f = fetcher([sep_row("AAA", "2020-06-01")])
        ingest.seed(conn, date_from="2020-01-01", date_to="2020-12-31", fetch=f)
        assert [c[0] for c in f.calls[:4]] == [
            sharadar.TICKERS, sharadar.ACTIONS, sharadar.SFP, sharadar.SEP]

    def test_an_interrupted_seed_RESUMES_without_duplicating(self, conn):
        rows = [sep_row("AAA", "2020-06-01"), sep_row("AAA", "2021-06-01")]
        boom = {"n": 0}

        def flaky(table, params=None, **kw):
            if table == sharadar.TICKERS:
                return [{"ticker": "AAA", "permaticker": "P-AAA"}]
            if table == sharadar.SEP:
                boom["n"] += 1
                # Each chunk now needs two complete observations before it can
                # publish. Fail on the next chunk so the first remains committed.
                if boom["n"] == 3:
                    raise RuntimeError("connection reset")
            if table == sharadar.SFP:
                return []
            lo = (params or {}).get("date.gte", "")
            hi = (params or {}).get("date.lte", "z")
            return [] if table == sharadar.ACTIONS else \
                [r for r in rows if lo <= r["date"] <= hi]

        with pytest.raises(RuntimeError):
            ingest.seed(conn, date_from="2020-01-01", date_to="2021-12-31",
                        fetch=flaky)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_bars")
            partial = cur.fetchone()[0]
        assert partial == 1, "the first year should have committed"

        ingest.seed(conn, date_from="2020-01-01", date_to="2021-12-31",
                    fetch=fetcher(rows))
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_bars")
            assert cur.fetchone()[0] == 2, "the resume duplicated rows"

    def test_a_failed_seed_is_RECORDED_as_failed(self, conn, pg):
        def boom(table, params=None, **kw):
            raise RuntimeError("vendor 500")
        with pytest.raises(RuntimeError):
            ingest.seed(conn, date_from="2020-01-01", date_to="2020-12-31",
                        fetch=boom)
        watcher = S.connect(pg.sync_dsn)
        try:
            assert S.run_status(watcher)[0]["status"] == "failed"
        finally:
            watcher.close()


class TestDaily:
    def test_it_OVERLAPS_the_frontier_so_restatements_are_repaired(self, conn):
        """Resuming strictly after the last stored session never revisits a bar,
        and Sharadar restates. A stale close would live forever — and the
        trailing stop reads exactly those closes."""
        # 2024-01-15 was the Martin Luther King Jr. market holiday. Use the next
        # real XNYS session so this orchestration test does not model an invalid
        # provider row.
        prior_session = "2024-01-16"
        ingest.seed(conn, date_from="2024-01-01", date_to="2024-01-31",
                    fetch=fetcher([sep_row("AAA", prior_session, raw=100.0)]))
        f = fetcher([sep_row("AAA", prior_session, raw=123.0),
                     sep_row("AAA", "2024-02-01", raw=130.0)])
        ingest.daily(conn, fetch=f, today="2024-02-01")

        requested_from = [c for c in f.calls
                          if c[0] == sharadar.SEP and "date.gte" in c[1]][0][1]["date.gte"]
        assert requested_from < prior_session, "the daily window did not overlap"
        with conn.cursor() as cur:
            cur.execute("SELECT close_unadjusted FROM sentinel_bars"
                        " WHERE session=%s", (prior_session,))
            assert cur.fetchone()[0] == 123.0, "the restated bar was not repaired"

    def test_daily_on_an_EMPTY_corpus_refuses_with_the_remedy(self, conn):
        """A two-week window would leave Wealth Core far short of 126 sessions
        and surface as an eligibility failure rather than the missing seed."""
        with pytest.raises(RuntimeError, match="feed-seed"):
            ingest.daily(conn, fetch=fetcher([]))

    def test_a_mostly_empty_raw_domain_REFUSES_on_the_daily_path(self, conn):
        prior = sep_row("AAA", "2024-01-16")
        ingest.seed(conn, date_from="2024-01-01", date_to="2024-01-31",
                    fetch=fetcher([prior]))
        # Use distinct canonical source keys. Repeating BBB/2024-02-01 twenty
        # times is itself invalid Sharadar evidence under the duplicate-key
        # authority gate and would correctly refuse before exercising the raw
        # price-domain coverage failure this test is intended to probe.
        blank = [dict(sep_row(f"BBB{i:02d}", "2024-02-01"), closeunadj=None)
                 for i in range(20)]
        # The injected vendor is a complete source, not merely the fresh delta:
        # reconciliation must still be able to prove the already-published AAA
        # row before the daily path rejects the deliberately broken BBB domain.
        with pytest.raises(Exception, match="closeunadj"):
            ingest.daily(conn, fetch=fetcher([prior, *blank]), today="2024-02-01",
                         resolve_identity=lambda t, s: t)

    def test_legacy_equities_get_bounded_spy_and_bil_reference_evidence(
            self, conn):
        from sentinel.feed import calendar, publication, readiness

        frontier = "2024-12-31"
        equity_sessions = calendar.previous_sessions(frontier, 50)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO sentinel_bars"
                " (security_id,session,ticker,close_signal,close_unadjusted,"
                "  open_unadjusted,volume,split_ratio,dividend_per_share)"
                " VALUES ('P-AAA',%s,'AAA',100,100,99,1000000,1,0)",
                [(session,) for session in equity_sessions])
        conn.commit()

        spy_sessions = calendar.previous_sessions(
            frontier, readiness.REQUIRED_SPY_SESSIONS)
        sfp = [row for i, session in enumerate(spy_sessions) for row in (
            {"ticker": "SPY", "date": session, "close": 400.0 + i,
             "open": 399.0 + i, "closeadj": 400.0 + i,
             "closeunadj": 400.0 + i},
            {"ticker": "BIL", "date": session, "open": 90.9,
             "close": 91.0, "closeadj": 91.1, "closeunadj": 91.0},
        )]
        equity_rows = [
            sep_row("AAA", session, close=100.0, raw=100.0, open_=99.0)
            for session in equity_sessions
        ]
        fetch = fetcher(
            equity_rows,
            sfp_rows=sfp, ticker_rows=[
                {"ticker": "AAA", "permaticker": "P-AAA",
                 "firstpricedate": "2000-01-03", "lastpricedate": None,
                 "relatedtickers": "AAA",
                 "category": "Domestic Common Stock"}])

        ingest.seed(conn, date_from=spy_sessions[0], date_to=frontier,
                    fetch=fetch)
        for _ in range(2):
            ingest.daily(conn, fetch=fetch, today=frontier)
