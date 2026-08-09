"""The data contract, checked clause by clause.

Every test is a corpus that a ROW COUNT would accept and the engine cannot plan
on. That is the whole argument of docs/sentinel-deployment.md §8: "126 rows" is
satisfied by 126 rows of anything, and each of these states produces a plan that
is wrong in a way nothing downstream reports.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from sentinel.feed import readiness as R  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from sentinel.feed.domains import NormalisedBar  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

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
        for t in ("sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sessions(n, end=TODAY):
    """`n` consecutive daily sessions ending at `end`. Weekends included — the
    check is about CONTINUITY of what the corpus holds, not a market calendar."""
    e = dt.date.fromisoformat(end)
    return [(e - dt.timedelta(days=i)).isoformat() for i in range(n)][::-1]


def load(conn, n_sessions=300, *, open_=99.0, volume=1e6, actions=True,
         universe=True, related="BBB", n_secs=2, signal_missing=False):
    for s in sessions(n_sessions):
        bars = [NormalisedBar(
                    close_signal=None if signal_missing else 50.0,
                    vendor=VendorBar(session=s, security_id=f"P{i}",
                                     ticker=f"T{i}", raw_close=100.0,
                                     raw_open=open_, volume=volume,
                                     split_ratio=1.0, dividend_per_share=0.0))
                for i in range(n_secs)]
        S.write_bars(conn, bars)
    with conn.cursor() as cur:
        if universe:
            for i in range(n_secs):
                cur.execute(
                    "INSERT INTO sentinel_universe (permaticker, ticker,"
                    " related_tickers, snapshot_date) VALUES (%s,%s,%s,%s)",
                    (f"P{i}", f"T{i}", related, TODAY))
        if actions:
            cur.execute(
                "INSERT INTO sentinel_actions (ticker, session, action)"
                " VALUES ('T0', %s, 'split')", (sessions(n_sessions)[-5],))
    conn.commit()


def by_name(result):
    return {c.name: c for c in result.checks}


class TestAHealthyCorpus:
    def test_it_is_READY(self, conn):
        load(conn)
        r = R.check_readiness(conn, today=TODAY)
        assert r.ready, [c.detail for c in r.failures]
        assert by_name(r)["continuity"].status == R.PASS


class TestWhatARowCountWouldMiss:
    def test_an_EMPTY_corpus_names_the_remedy(self, conn):
        r = R.check_readiness(conn, today=TODAY)
        assert not r.ready
        assert "feed-seed" in by_name(r)["sessions"].detail

    def test_TOO_FEW_sessions_fails_with_the_ENGINE_s_number(self, conn):
        """127 closes is the engine's requirement, not a number chosen here:
        momentum reads closes[-127]."""
        load(conn, n_sessions=50)
        r = R.check_readiness(conn, today=TODAY)
        c = by_name(r)["continuity"]
        assert c.status == R.FAIL
        assert str(R.REQUIRED_SESSIONS) in c.detail

    def test_between_required_and_preferred_WARNS_but_stays_ready(self, conn):
        """The one genuine judgement call: it runs, with no margin for a gap."""
        load(conn, n_sessions=150)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["continuity"].status == R.WARN
        assert r.ready, "a warning must not block a bootstrap"

    def test_a_STALE_frontier_fails_even_with_ample_history(self, conn):
        """The count is perfect and the data is old. Planning on it produces
        yesterday's book with today's confidence."""
        load(conn, n_sessions=300)
        r = R.check_readiness(conn, today="2025-03-01")
        assert by_name(r)["freshness"].status == R.FAIL
        assert not r.ready

    def test_a_MISSING_RAW_OPEN_fails_though_every_row_exists(self, conn):
        """Every bar is present; none can be filled."""
        load(conn, n_sessions=300, open_=None)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["raw open"].status == R.FAIL
        assert "every fill" in by_name(r)["raw open"].detail

    def test_MISSING_VOLUME_fails_because_eligibility_reads_it(self, conn):
        load(conn, n_sessions=300, volume=None)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["volume"].status == R.FAIL

    def test_NO_IDENTITY_fails_though_the_prices_are_perfect(self, conn):
        """Ticker reuse splices two unrelated companies into one security."""
        load(conn, n_sessions=300, universe=False)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["identity"].status == R.FAIL
        assert not r.ready

    def test_NO_RELATED_TICKERS_fails_because_GOOG_GOOGL_becomes_UNDETECTABLE(self, conn):
        """Without them every issuer key falls back to the permaticker, and the
        duplicate-issuer invariant has nothing to compare."""
        load(conn, n_sessions=300, related=None)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["issuer keys"].status == R.FAIL

    def test_NO_ACTIONS_over_a_long_window_is_a_missing_ingest(self, conn):
        """Splits and terminal events would both go unseen."""
        load(conn, n_sessions=300, actions=False)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["actions"].status == R.FAIL


class TestTheReportItself:
    def test_EVERY_check_is_reported_even_after_one_fails(self, conn):
        """Stopping at the first failure turns one diagnosis into several round
        trips."""
        load(conn, n_sessions=300, open_=None, volume=None, actions=False)
        r = R.check_readiness(conn, today=TODAY)
        assert len(r.failures) >= 3
        assert {"raw open", "volume", "actions"} <= set(by_name(r))

    def test_a_single_failure_makes_the_whole_thing_NOT_READY(self, conn):
        load(conn, n_sessions=300, actions=False)
        assert R.check_readiness(conn, today=TODAY).ready is False
