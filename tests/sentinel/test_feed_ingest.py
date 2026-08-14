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

CANONICAL = REPO / "services" / "bt-data" / "app" / "sharadar_client.py"


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
        for t in ("sentinel_bars", "sentinel_spy_total_return",
                  "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sep_row(ticker, date, close=50.0, raw=100.0, open_=49.0):
    return {"ticker": ticker, "date": date, "close": close,
            "closeunadj": raw, "open": open_, "volume": 1_000_000}


def fetcher(sep_rows, action_rows=(), ticker_rows=None, sfp_rows=()):
    """An injected fetch that records which windows were requested.

    TICKERS defaults to one open-ended listing per symbol seen in `sep_rows`, so
    identity resolves 1:1 and these tests stay about ORCHESTRATION. Resolution
    itself is covered in test_feed_universe.py.
    """
    calls = []
    if ticker_rows is None:
        ticker_rows = [{"ticker": t, "permaticker": f"P-{t}"}
                       for t in sorted({r["ticker"] for r in sep_rows})]

    def fetch(table, params=None, **kw):
        calls.append((table, dict(params or {})))
        if table == sharadar.TICKERS:
            return list(ticker_rows)
        lo = (params or {}).get("date.gte", "0000-00-00")
        hi = (params or {}).get("date.lte", "9999-99-99")
        if table == sharadar.ACTIONS:
            return [r for r in action_rows if lo <= r["date"] <= hi]
        if table == sharadar.SFP:
            return [r for r in sfp_rows if lo <= r["date"] <= hi]
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
            r = S.run_status(watcher)[0]
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
                if boom["n"] == 2:
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
        ingest.seed(conn, date_from="2024-01-01", date_to="2024-01-31",
                    fetch=fetcher([sep_row("AAA", "2024-01-15", raw=100.0)]))
        f = fetcher([sep_row("AAA", "2024-01-15", raw=123.0),
                     sep_row("AAA", "2024-02-01", raw=130.0)])
        ingest.daily(conn, fetch=f, today="2024-02-01")

        requested_from = [c for c in f.calls
                          if c[0] == sharadar.SEP][0][1]["date.gte"]
        assert requested_from < "2024-01-15", "the daily window did not overlap"
        with conn.cursor() as cur:
            cur.execute("SELECT close_unadjusted FROM sentinel_bars"
                        " WHERE session='2024-01-15'")
            assert cur.fetchone()[0] == 123.0, "the restated bar was not repaired"

    def test_daily_on_an_EMPTY_corpus_refuses_with_the_remedy(self, conn):
        """A two-week window would leave Wealth Core far short of 126 sessions
        and surface as an eligibility failure rather than the missing seed."""
        with pytest.raises(RuntimeError, match="feed-seed"):
            ingest.daily(conn, fetch=fetcher([]))

    def test_a_mostly_empty_raw_domain_REFUSES_on_the_daily_path(self, conn):
        ingest.seed(conn, date_from="2024-01-01", date_to="2024-01-31",
                    fetch=fetcher([sep_row("AAA", "2024-01-15")]))
        blank = [dict(sep_row("BBB", "2024-02-01"), closeunadj=None)
                 for _ in range(20)]
        with pytest.raises(Exception, match="closeunadj"):
            ingest.daily(conn, fetch=fetcher(blank), today="2024-02-01",
                         resolve_identity=lambda t, s: t)

    def test_legacy_equities_with_empty_spy_are_repaired_from_bounded_sfp(
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
        sfp = [{"ticker": "SPY", "date": session,
                "closeadj": 400.0 + i}
               for i, session in enumerate(spy_sessions)]
        fetch = fetcher([], sfp_rows=sfp, ticker_rows=[
            {"ticker": "AAA", "permaticker": "P-AAA",
             "firstpricedate": "2000-01-03", "lastpricedate": None,
             "relatedtickers": "AAA",
             "category": "Domestic Common Stock"}])

        ingest.seed(conn, date_from=spy_sessions[0], date_to=frontier,
                    fetch=fetch)
        for _ in range(2):
            ingest.daily(conn, fetch=fetch, today=frontier)

        sfp_calls = [params for table, params in fetch.calls
                     if table == sharadar.SFP]
        assert sfp_calls and all(call["ticker"] == "SPY" for call in sfp_calls)
        assert all(call["date.gte"] == spy_sessions[0] for call in sfp_calls)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT session),"
                        " COUNT(DISTINCT last_written_run_id)"
                        " FROM sentinel_spy_total_return")
            assert cur.fetchone() == (41, 41, 1)
            cur.execute("SELECT COUNT(*) FROM sentinel_bars WHERE ticker='SPY'")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM sentinel_universe WHERE ticker='SPY'")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM sentinel_spy_total_return"
                        " WHERE last_written_run_id=%s",
                        (publication.current(conn).run_id,))
            assert cur.fetchone()[0] == 41
            cur.execute("SELECT kind, COUNT(*) FROM feed_ingest_runs"
                        " WHERE status='success' GROUP BY kind ORDER BY kind")
            assert cur.fetchall() == [("daily", 2), ("seed", 1)]

        result = readiness.check_readiness(conn, today=frontier)
        benchmark = next(c for c in result.checks
                         if c.name == "frontier benchmark")
        assert benchmark.status == readiness.PASS, benchmark.detail


class TestRetryConstantsHaveNotDrifted:
    """These encode an outage, not a preference: without 429-aware backoff a
    throttle killed multi-hour loads about a minute in."""

    def _canonical(self):
        src = CANONICAL.read_text()
        start = src.index("def _retry_delay")
        end = src.index("async def _get_with_retry", start)
        ns = {"RATE_LIMIT_BACKOFF_CAP": sharadar.RATE_LIMIT_BACKOFF_CAP,
              "FETCH_BACKOFF_BASE": sharadar.FETCH_BACKOFF_BASE}
        exec(compile(src[start:end], str(CANONICAL), "exec"), ns)
        return ns["_retry_delay"]

    @pytest.mark.parametrize("attempt,status,retry_after", [
        (0, 429, None), (1, 429, None), (0, 429, "300"), (0, 429, "Wed, 21 Oct"),
        (0, 500, None), (2, 503, None), (5, None, None), (14, 429, None),
    ])
    def test_it_matches_bt_data(self, attempt, status, retry_after):
        assert sharadar.retry_delay(attempt, status, retry_after) == \
            self._canonical()(attempt, status, retry_after)

    def test_a_429_waits_MINUTES_not_seconds(self):
        assert sharadar.retry_delay(0, 429, None) >= 60.0
        assert sharadar.retry_delay(0, 500, None) < 10.0

    def test_the_429_wait_is_CAPPED(self):
        assert sharadar.retry_delay(99, 429, None) == sharadar.RATE_LIMIT_BACKOFF_CAP

    def test_a_missing_api_key_REFUSES_rather_than_loading_nothing(self, monkeypatch):
        """An unauthenticated fetch returns an EMPTY table, which is
        indistinguishable from a quiet market unless someone checks row counts."""
        monkeypatch.delenv("SHARADAR_API_KEY", raising=False)
        with pytest.raises(sharadar.MissingApiKey, match="empty table"):
            list(sharadar.fetch_table(sharadar.SEP))


class TestYearChunks:
    def test_it_splits_on_calendar_years_and_clips_the_ends(self):
        assert sharadar.year_chunks("2020-06-01", "2022-03-15") == [
            ("2020-06-01", "2020-12-31"),
            ("2021-01-01", "2021-12-31"),
            ("2022-01-01", "2022-03-15")]

    def test_a_single_day_is_one_chunk(self):
        assert sharadar.year_chunks("2024-05-05", "2024-05-05") == \
            [("2024-05-05", "2024-05-05")]


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Http:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass

    def __init__(self, payloads):
        self.payloads = list(payloads)
        outer = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def get(self, *_args, **_kwargs):
                return _Response(outer.payloads.pop(0))

        self.Client = Client


def _page(next_cursor):
    return {"datatable": {"columns": [{"name": "ticker"}], "data": [["AAA"]]},
            "meta": {"next_cursor_id": next_cursor}}


class TestPaginationMustProgress:
    def test_a_repeated_cursor_refuses_instead_of_looping(self, monkeypatch):
        monkeypatch.setenv("SHARADAR_API_KEY", "test-only")
        http = _Http([_page("same"), _page("same")])
        with pytest.raises(sharadar.PaginationError, match="repeated cursor"):
            list(sharadar.fetch_table(sharadar.SEP, http=http, sleep=lambda _: None))

    def test_the_page_cap_is_a_hard_completeness_bound(self, monkeypatch):
        monkeypatch.setenv("SHARADAR_API_KEY", "test-only")
        monkeypatch.setattr(sharadar, "FETCH_MAX_PAGES", 1)
        with pytest.raises(sharadar.PaginationError, match="bounded cap"):
            list(sharadar.fetch_table(
                sharadar.SEP, http=_Http([_page("more")]), sleep=lambda _: None))
