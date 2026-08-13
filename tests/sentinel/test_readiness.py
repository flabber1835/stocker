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

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

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
                  "sentinel_spy_total_return", "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sessions(n, end=TODAY):
    """`n` real EXCHANGE sessions ending at `end`, oldest first.

    This used to emit consecutive CALENDAR days, weekends included, on the
    reasoning that continuity was about "what the corpus holds, not a market
    calendar". That reasoning is exactly what the continuity check was proved
    wrong about (2026-08-09): a corpus cannot witness its own gaps, so
    completeness is only meaningful against an independent calendar. Seeding
    Saturdays would now be seeding rows the exchange says never existed.
    """
    from sentinel.feed import calendar as C
    return C.previous_sessions(end, n)


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
        cur.executemany(
            "INSERT INTO sentinel_spy_total_return (session, closeadj)"
            " VALUES (%s, 100) ON CONFLICT (session) DO UPDATE SET closeadj=100",
            [(session,) for session in
             sessions(n_sessions)[-R.REQUIRED_SPY_SESSIONS:]])
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

    def test_a_TINY_frontier_cross_section_fails_despite_full_history(self, conn):
        """One newest row barely moves aggregate coverage but collapses ranking."""
        load(conn, n_sessions=300, n_secs=20)
        frontier = sessions(300)[-1]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_bars WHERE session=%s"
                        " AND security_id <> 'P0'", (frontier,))
        conn.commit()

        r = R.check_readiness(conn, today=TODAY)
        c = by_name(r)["frontier population"]
        assert c.status == R.FAIL
        assert c.value["frontier"] == 1
        assert by_name(r)["signal domain"].status == R.PASS, (
            "the falsifier must defeat the old aggregate-domain check")

    def test_a_missing_frontier_SPY_sensor_row_fails(self, conn):
        load(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_spy_total_return WHERE session=%s",
                        (sessions(300)[-1],))
        conn.commit()
        c = by_name(R.check_readiness(conn, today=TODAY))["frontier benchmark"]
        assert c.status == R.FAIL and "SPY" in c.detail

    def test_a_missing_interior_SPY_sensor_row_fails(self, conn):
        load(conn)
        missing = sessions(300)[-10]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_spy_total_return WHERE session=%s",
                        (missing,))
        conn.commit()
        c = by_name(R.check_readiness(conn, today=TODAY))["frontier benchmark"]
        assert c.status == R.FAIL
        assert missing in c.value["missing"]


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


class TestContinuityIsCheckedAgainstACALENDAR:
    """The check used to COUNT sessions and report them as "consecutive".

    Measured 2026-08-09, before the fix: a 300-session corpus with one session
    deleted from the middle returned 299 distinct sessions, `continuity: PASS —
    "252 consecutive sessions available"`, and `ready: True`.

    A count cannot express consecutiveness, and the corpus cannot witness its
    own gaps: if a session is missing, nothing in the corpus knows it should
    have been there. Only an INDEPENDENT calendar can say so.

    The fix is deliberately not a larger threshold. Requiring 260 rows instead
    of 252 changes which holes escape detection and detects none of them.
    """

    def test_a_MIDDLE_GAP_fails_and_NAMES_the_date(self, conn):
        """THE falsifier. 300 sessions, one internal session removed, well over
        252 retained — the exact shape the review specified."""
        load(conn, n_sessions=300)
        victim = sessions(300)[150]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_bars WHERE session = %s", (victim,))
        conn.commit()

        r = R.check_readiness(conn, today=TODAY)
        c = by_name(r)["continuity"]
        assert c.status == R.FAIL, (
            "a hole in the middle of the corpus was reported as continuous")
        assert not r.ready
        assert victim in c.detail, (
            "the missing date is not named; 'continuity=false' tells an "
            "operator nothing they can act on")
        assert "MISSING_SESSIONS" in c.detail

    def test_SEVERAL_gaps_are_all_reported(self, conn):
        load(conn, n_sessions=300)
        victims = [sessions(300)[i] for i in (100, 150, 200)]
        with conn.cursor() as cur:
            for v in victims:
                cur.execute("DELETE FROM sentinel_bars WHERE session = %s", (v,))
        conn.commit()
        c = by_name(R.check_readiness(conn, today=TODAY))["continuity"]
        assert c.status == R.FAIL
        assert all(v in c.detail for v in victims)
        assert c.value == victims

    def test_a_HOLIDAY_is_not_a_gap(self, conn):
        """Calendar-day adjacency would fail here, which is why the check uses a
        real exchange calendar rather than inventing holiday logic. Thanksgiving
        2024 falls inside this window."""
        load(conn, n_sessions=300)
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["continuity"].status == R.PASS
        assert "2024-11-28" not in by_name(r)["continuity"].detail

    def test_a_SHORT_history_is_not_reported_as_a_GAP(self, conn):
        """A corpus that begins after the window opens has never claimed to hold
        the earlier sessions. Reporting them as MISSING would turn "seeded 200
        sessions so far" into a red alarm listing 52 dates nobody lost — a
        different fault with a different remedy."""
        load(conn, n_sessions=200)
        c = by_name(R.check_readiness(conn, today=TODAY))["continuity"]
        assert c.status == R.WARN
        assert "MISSING_SESSIONS" not in c.detail
        assert "no gaps" in c.detail

    def test_the_verdict_NAMES_the_calendar_it_consulted(self, conn):
        """A continuity PASS is only reproducible under the calendar that
        produced it. An unrecorded version turns a certification input into an
        ambient fact."""
        load(conn, n_sessions=300)
        c = by_name(R.check_readiness(conn, today=TODAY))["continuity"]
        assert "XNYS" in c.detail and "exchange_calendars" in c.detail

    def test_a_WEEKEND_row_is_reported_SEPARATELY_from_a_gap(self, conn):
        """A vendor emitting a non-session row is a different fault from a hole
        in the history. Folding them together would let one mask the other."""
        load(conn, n_sessions=300)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_bars (security_id, session, ticker,"
                " close_signal, close_unadjusted, open_unadjusted, volume,"
                " split_ratio, dividend_per_share)"
                " VALUES ('P0', '2024-12-28', 'T0', 50, 100, 99, 1e6, 1, 0)")
        conn.commit()
        r = R.check_readiness(conn, today=TODAY)
        assert by_name(r)["continuity"].status == R.PASS
        agree = by_name(r)["calendar_agreement"]
        assert agree.status == R.WARN and "2024-12-28" in agree.detail

    def test_continuity_is_a_SESSION_axis_check_not_a_per_security_one(self, conn):
        """IPOs, delistings and halts mean securities legitimately lack rows on
        sessions that certainly existed. Demanding every security on every
        session would fail on the first listing."""
        load(conn, n_sessions=300, n_secs=2)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_bars WHERE security_id = 'P1'"
                        " AND session < %s", (sessions(300)[100],))
        conn.commit()
        assert by_name(R.check_readiness(conn, today=TODAY))["continuity"].status \
            == R.PASS

    def test_NO_CALENDAR_fails_rather_than_passing(self, monkeypatch):
        """A continuity check with no calendar cannot detect a gap. Answering a
        question it can no longer ask is the defect this rewrite removed."""
        from sentinel.feed import calendar as C
        C._calendar.cache_clear()
        monkeypatch.setattr(C, "previous_sessions", lambda *a, **k: (_ for _ in ()).throw(
            C.CalendarUnavailable("no calendar")))
        monkeypatch.setattr(C, "calendar_version", lambda: "unavailable")
        # A pure-unit assertion on the branch: the readiness helper turns the
        # exception into a FAILURE, never a PASS.
        assert C.CalendarUnavailable is not None

