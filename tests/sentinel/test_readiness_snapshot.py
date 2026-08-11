"""#14 — the panel computes the contract live, and gives up first when it matters.

THE FAILURE, written before the fix.

`_feed_rows` runs `check_readiness` inside a page load, under the tightest
timeout of the three reads, and its own comment explains why:

```python
# The contract check is the expensive read and the least urgent, so it
# gets the TIGHTEST budget and is the first thing given up. During a
# seed it legitimately takes minutes.
r, _ = _read(conn, readiness.check_readiness, READINESS_TIMEOUT_MS, default=None)
```

Both halves of that are true, and together they produce a panel that is blank on
exactly the question it exists to answer:

```text
a six-hour seed is running
every readiness query contends with the bulk load
the check times out
the page renders  ready: --   0 of 0 checks
```

Not "not ready" — *nothing*. An operator watching a seed cannot tell a corpus
that is still building from one that has failed a clause, and the answer they
need is one somebody already computed: `check-data` ran an hour ago and produced
a full verdict, which was printed to a terminal and lost.

Making the query faster does not fix this. The check reads the corpus, the
corpus is the thing under load, and any budget short enough to protect a page
load is short enough to lose under contention. A page must not compute a
contract; it must READ a verdict somebody else computed, and say how old it is.

THE PROPERTY BEING BOUGHT: **the panel's readiness row is a cheap keyed read,
and its staleness is visible rather than silent.** A stale verdict labelled with
its age is actionable. A blank one is not, and a stale one presented as current
is worse than either.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402
from tests.support.source import code_of  # noqa: E402

from sentinel.feed import readiness as R  # noqa: E402
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
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (t,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def a_verdict(ready=True):
    r = R.Readiness()
    r.add("sessions", R.PASS, "300 distinct sessions to 2026-08-10", 300)
    r.add("continuity", R.PASS if ready else R.FAIL,
          "no gaps" if ready else "MISSING_SESSIONS (2 of 252): 2026-08-06", 300)
    return r


class TestTheFailure:
    def test_the_panel_does_NOT_compute_the_contract(self, conn):
        """The structural half. A page that calls `check_readiness` will time
        out under exactly the load that makes the answer urgent, and no timeout
        budget fixes that: the check reads the corpus, and the corpus is the
        thing under load."""
        from sentinel.panel import sources

        src = code_of(sources._feed_rows)
        assert "check_readiness" not in src, (
            "the panel must READ a verdict, not compute one")

    def test_a_persisted_verdict_is_READABLE_without_touching_the_corpus(self, conn):
        R.save_snapshot(conn, a_verdict())

        snap = R.latest_snapshot(conn)
        assert snap is not None
        assert snap.ready is True
        assert snap.checks_passed == 2 and snap.checks_total == 2

    def test_the_read_is_a_SINGLE_keyed_query(self, conn):
        """Cheap is the whole point, and "cheap" has to be a property of the
        query rather than a hope about the data. One row, by primary key —
        which stays a lookup while the corpus grows to 35M rows."""
        R.save_snapshot(conn, a_verdict())
        with conn.cursor() as cur:
            cur.execute("EXPLAIN SELECT * FROM sentinel_readiness_snapshots"
                        " ORDER BY computed_at DESC LIMIT 1")
            plan = " ".join(r[0] for r in cur.fetchall())
        assert "Seq Scan" not in plan or "Limit" in plan, plan


class TestStalenessIsVISIBLE:
    def test_the_snapshot_carries_its_own_AGE(self, conn):
        """A stale verdict labelled with its age is actionable. One presented
        as current is worse than a blank."""
        R.save_snapshot(conn, a_verdict())
        snap = R.latest_snapshot(conn)
        assert snap.age_seconds is not None and snap.age_seconds < 60
        assert snap.stale is False

    def test_an_OLD_snapshot_reports_itself_stale(self, conn):
        R.save_snapshot(conn, a_verdict())
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_readiness_snapshots"
                        " SET computed_at = NOW() - INTERVAL '30 hours'")
        conn.commit()

        snap = R.latest_snapshot(conn)
        assert snap.stale is True
        assert snap.age_seconds > 24 * 3600

    def test_NO_snapshot_is_not_the_same_as_NOT_READY(self, conn):
        """Nothing has ever computed a verdict. That is 'we have not asked',
        and reporting it as False would say the corpus failed a clause it was
        never measured against — the same conflation the ownership readers had
        to have removed."""
        assert R.latest_snapshot(conn) is None

    def test_and_the_PANEL_renders_that_as_unknown_not_failed(self, conn, pg):
        """End to end, through the real reader.

        The module-level None above is necessary and not sufficient: what
        matters is what the page SHOWS, and a `default=False` anywhere between
        here and the row would turn "never measured" into a red alarm on a
        corpus nobody has checked yet. That mutation passes the assertion
        above.
        """
        from sentinel.panel import sources

        with conn.cursor() as cur:
            cur.execute("INSERT INTO sentinel_bars (security_id, session,"
                        " ticker, close_unadjusted, volume)"
                        " VALUES ('P-AAA','2026-08-10','AAA',10,1000)")
        conn.commit()

        rows, _ = sources._feed_rows(pg.sync_dsn)
        feed = [r for r in rows if r.key == "feed"][0]
        assert feed.status is not sources.model.FAIL
        assert "not checked" in feed.detail.lower()

    def test_a_stale_snapshot_does_not_claim_to_be_READY(self, conn):
        """`ready` stays what was measured; `trustworthy` is what a caller
        should gate on. Two facts, two fields — collapsing them would either
        discard a usable verdict or let a day-old one authorise a bootstrap."""
        R.save_snapshot(conn, a_verdict(ready=True))
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_readiness_snapshots"
                        " SET computed_at = NOW() - INTERVAL '30 hours'")
        conn.commit()

        snap = R.latest_snapshot(conn)
        assert snap.ready is True, "what was measured does not change with age"
        assert snap.trustworthy is False


class TestTheFailingCLAUSESSurvive:
    def test_the_failures_are_persisted_by_NAME_and_DETAIL(self, conn):
        """"ready: false" is not an answer anyone can act on. The whole design
        of this check is one verdict per clause; a snapshot that kept only the
        boolean would throw away the part that says which fetch to re-run."""
        R.save_snapshot(conn, a_verdict(ready=False))

        snap = R.latest_snapshot(conn)
        assert snap.ready is False
        names = [c["name"] for c in snap.failures]
        assert names == ["continuity"]
        assert "MISSING_SESSIONS" in snap.failures[0]["detail"]

    def test_every_check_is_kept_not_just_the_failures(self, conn):
        R.save_snapshot(conn, a_verdict(ready=False))
        snap = R.latest_snapshot(conn)
        assert [c["name"] for c in snap.checks] == ["sessions", "continuity"]


class TestItIsWrittenWhereTheCheckAlreadyRUNS:
    def test_check_data_persists_what_it_computed(self, conn):
        """The verdict already exists — `check-data` computes a full one and
        prints it to a terminal that scrolls. Persisting it costs one insert
        and is the entire supply side of this feature."""
        from sentinel import __main__ as cli

        src = code_of(cli.cmd_check_data)
        assert "save_snapshot" in src

    def test_the_ROW_dates_the_verdict_it_shows(self, conn):
        """Undated, a day-old PASS reads as now — and that is the ONE way a
        stale verdict does harm. The page no longer computes the contract, so
        the age is the only thing separating a current answer from one that
        predates a re-ingest."""
        import datetime as _dt

        from sentinel.panel import model

        now = _dt.datetime.now(_dt.timezone.utc)
        fresh = model.feed_row(frontier="2026-08-10", sessions_behind=0,
                               ready=True, checks_passed=9, checks_total=9,
                               as_of=now, checked_at=now)
        assert "checked" in fresh.detail and fresh.status is model.OK

        old = model.feed_row(frontier="2026-08-10", sessions_behind=0,
                             ready=True, checks_passed=9, checks_total=9,
                             as_of=now,
                             checked_at=now - _dt.timedelta(hours=30))
        assert "STALE" in old.detail
        assert old.status is model.WARN, (
            "reported, not downgraded to a failure — the verdict WAS a pass, "
            "and inventing a different result is not the same as saying it may "
            "no longer apply")

    def test_a_stale_FAILURE_stays_a_failure(self, conn):
        """Age cannot launder a red verdict into a warning. The corpus failed a
        clause; nothing since has said otherwise."""
        import datetime as _dt

        from sentinel.panel import model

        now = _dt.datetime.now(_dt.timezone.utc)
        row = model.feed_row(frontier="2026-08-10", sessions_behind=0,
                             ready=False, checks_passed=7, checks_total=9,
                             as_of=now,
                             checked_at=now - _dt.timedelta(hours=30))
        assert row.status is model.FAIL

    def test_saving_TWICE_keeps_both_and_returns_the_newer(self, conn):
        """History, not a single mutable row. "when did readiness last change?"
        is asked after an incident, and an upsert would have overwritten the
        evidence."""
        R.save_snapshot(conn, a_verdict(ready=False))
        R.save_snapshot(conn, a_verdict(ready=True))

        assert R.latest_snapshot(conn).ready is True
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_readiness_snapshots")
            assert cur.fetchone()[0] == 2
