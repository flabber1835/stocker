"""Seed and daily ingest, driven end-to-end with an injected fetcher.

No network. The point is the ORCHESTRATION: that chunks publish committed
progress, that an interrupted seed resumes rather than duplicates, that the daily
path overlaps the frontier so a restated bar is repaired, and that the retry
constants — which encode an outage rather than a preference — have not drifted
from the ones bt-data arrived at.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from sentinel.feed import ingest, sharadar  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

CANONICAL = ROOT / "services" / "bt-data" / "app" / "sharadar_client.py"


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
        for t in ("sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sep_row(ticker, date, close=50.0, raw=100.0, open_=49.0):
    return {"ticker": ticker, "date": date, "close": close,
            "closeunadj": raw, "open": open_, "volume": 1_000_000}


def fetcher(sep_rows, action_rows=()):
    """An injected fetch that records which windows were requested."""
    calls = []

    def fetch(table, params=None, **kw):
        calls.append((table, dict(params or {})))
        lo = (params or {}).get("date.gte", "0000-00-00")
        hi = (params or {}).get("date.lte", "9999-99-99")
        if table == sharadar.ACTIONS:
            return [r for r in action_rows if lo <= r["date"] <= hi]
        return [r for r in sep_rows if lo <= r["date"] <= hi]

    fetch.calls = calls
    return fetch


class TestSeed:
    def test_it_chunks_by_YEAR_and_publishes_each(self, conn, pg):
        rows = [sep_row("AAA", "2020-06-01"), sep_row("AAA", "2021-06-01"),
                sep_row("BBB", "2022-06-01")]
        p = ingest.seed(conn, date_from="2020-01-01", date_to="2022-12-31",
                        fetch=fetcher(rows))
        assert p.chunks_total == 4          # actions + three years
        assert p.chunks_done == 4

        watcher = S.connect(pg.sync_dsn)
        try:
            r = S.run_status(watcher)[0]
            assert r["status"] == "success"
            assert r["chunks_done"] == 4
            assert r["rows_written"] == 3
        finally:
            watcher.close()

    def test_ACTIONS_is_fetched_BEFORE_the_prices(self, conn):
        """The authoritative corporate-action stream must be present from the
        first year, not the last, or the derived split ratio has nothing to be
        cross-checked against until the load is nearly over."""
        f = fetcher([sep_row("AAA", "2020-06-01")])
        ingest.seed(conn, date_from="2020-01-01", date_to="2020-12-31", fetch=f)
        assert f.calls[0][0] == sharadar.ACTIONS

    def test_an_interrupted_seed_RESUMES_without_duplicating(self, conn):
        rows = [sep_row("AAA", "2020-06-01"), sep_row("AAA", "2021-06-01")]
        boom = {"n": 0}

        def flaky(table, params=None, **kw):
            if table == sharadar.SEP:
                boom["n"] += 1
                if boom["n"] == 2:
                    raise RuntimeError("connection reset")
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

        requested_from = f.calls[0][1]["date.gte"]
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
            ingest.daily(conn, fetch=fetcher(blank), today="2024-02-01")


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
