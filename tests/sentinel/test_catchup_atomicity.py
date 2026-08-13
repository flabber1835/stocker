"""P1 — the pointer's atomicity was advertised, not structural.

THE FAILURE, written before the fix.

The contract says state advancement and `last_processed_session` commit
together. The signature does not make that true:

```python
advance_state(session, state) -> state
```

The returned `state` can be — and in every test was — a plain Python object.
`catch_up` then writes the pointer and commits PostgreSQL, so the only durable
half is the pointer:

```text
advance_state(Aug 10)   -> a new IN-MEMORY Wealth Core state
write pointer = Aug 10
COMMIT                  <- the pointer is now durable. The state is not
SIGKILL
restart
pointer says Aug 10 is done
durable Wealth Core state still says Aug 9
```

Aug 10 is skipped. Permanently, silently, and in the direction the module's own
docstring names as the worse one — a replayed session double-ages every episode
and is at least visible in the numbers, while a skipped session simply never
happened.

This is not an argument that the seam is wrong. It is that a seam which can be
satisfied by an in-memory object cannot carry a transactional guarantee, and
saying it does in a comment is how the guarantee gets lost the day Wealth Core
is actually wired.

THE PROPERTY BEING BOUGHT: **the pointer can never be ahead of the durable
state.** Enforced two ways, because either alone is escapable: `advance_state`
receives the transaction it must write through, and `catch_up` persists the
state it was handed in the same statement as the pointer.
"""
from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import catchup as CU  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

D = Decimal


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
        # A REAL durable strategy state, standing in for Wealth Core's book.
        # The whole point of this file is that an in-memory dict cannot
        # demonstrate the property, so the fake has to be a table.
        cur.execute("""CREATE TABLE strategy_state (
            security_id TEXT PRIMARY KEY,
            age         INTEGER NOT NULL,
            last_session DATE NOT NULL)""")
    c.commit()
    S.ensure_schema(c)
    from sentinel import schema as sentinel_schema
    sentinel_schema.ensure_schema(c)
    yield c
    c.close()


def a_plan(session="2026-08-13"):
    d = dt.date.fromisoformat(session)
    return ExecutionPlan(plan_id=f"plan-{session}", decision_session=d,
                         effective_session=d, target_exposure=D("1"),
                         target_basket={"P-AAA": D("100")}, data_version=1)


def durable_advance(explode_on=None):
    """Wealth Core's stand-in: PATH-DEPENDENT and written through `conn`.

    `age` increments per session, so replaying one is visible as a double
    increment and skipping one as a gap. That is what makes this a falsifier
    rather than a smoke test — both failure directions leave a mark.
    """
    def advance(conn, session, state):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO strategy_state (security_id, age, last_session)"
                " VALUES ('P-AAA', 1, %s) ON CONFLICT (security_id) DO UPDATE"
                " SET age = strategy_state.age + 1, last_session = EXCLUDED.last_session",
                (session,))
        if explode_on == session:
            raise RuntimeError("SIGKILL equivalent: the process died here")
        return {"last": session}
    return advance


def durable_state(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT age, last_session FROM strategy_state"
                    " WHERE security_id = 'P-AAA'")
        row = cur.fetchone()
    return (None, None) if row is None else (int(row[0]), row[1])


def run(conn, through, missed, advance, **kw):
    return CU.catch_up(conn, through=through, missed=missed,
                       advance_state=advance,
                       decide=lambda session, state: a_plan(session), **kw)


class TestNeitherCanExistWithoutTheOther:
    def test_the_pointer_is_NEVER_ahead_of_the_durable_state(self, conn):
        run(conn, "2026-08-13",
            ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
            durable_advance())

        age, last = durable_state(conn)
        assert age == 4
        assert last == CU.last_processed_session(conn) == dt.date(2026, 8, 13)

    def test_a_CRASH_rolls_back_the_state_AND_the_pointer_together(self, conn):
        """The headline. The state write for Aug 12 lands in the transaction,
        then the process dies before the commit. Both halves must be gone.

        A pointer that survived here would skip Aug 12 forever; a state that
        survived would replay it and double-age the episode.
        """
        with pytest.raises(RuntimeError):
            run(conn, "2026-08-13",
                ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
                durable_advance(explode_on="2026-08-12"))

        age, last = durable_state(conn)
        assert age == 2, "Aug 12's uncommitted state write survived"
        assert last == dt.date(2026, 8, 11)
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 11)

    def test_a_crash_BETWEEN_the_seam_and_the_pointer_loses_both(self, conn,
                                                                 monkeypatch):
        """The window the other crash test cannot reach.

        Raising inside `advance_state` never exercises the gap AFTER it returns
        — the mutation sweep proved that by inserting a commit there and
        staying green. This kills the process in the one place where the state
        write exists and the pointer write has not happened yet, which is
        precisely where a state-ahead-of-pointer divergence would be born.
        """
        real = CU._mark_processed
        calls = {"n": 0}

        def die_on_the_third(conn_, session, state=None):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("died between the state and the pointer")
            return real(conn_, session, state)

        monkeypatch.setattr(CU, "_mark_processed", die_on_the_third)

        with pytest.raises(RuntimeError):
            run(conn, "2026-08-13",
                ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], durable_advance())

        age, last = durable_state(conn)
        assert (age, last) == (2, dt.date(2026, 8, 11)), (
            f"the third session's state survived without its pointer: {age}")
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 11)

    def test_and_the_RESUME_replays_exactly_the_missing_session(self, conn):
        """Convergence. Neither skipped nor doubled."""
        with pytest.raises(RuntimeError):
            run(conn, "2026-08-13",
                ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
                durable_advance(explode_on="2026-08-12"))

        run(conn, "2026-08-13",
            ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
            durable_advance())

        age, last = durable_state(conn)
        assert age == 4, f"aged {age} times across four sessions"
        assert last == dt.date(2026, 8, 13)
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 13)

    def test_final_state_plan_and_supersession_roll_back_together(
            self, conn, monkeypatch):
        """A crash in final plan adoption cannot expose final state alone."""
        run(conn, "2026-08-11", ["2026-08-10", "2026-08-11"],
            durable_advance())
        prior = CU.last_processed_session(conn)
        prior_state = CU.resume_state(conn)
        prior_plan = journal.latest_plan(conn)

        real_supersede = CU.journal.supersede_all_but

        def die_after_plan_insert(c, plan_id, *, commit=True):
            real_supersede(c, plan_id, commit=False)
            raise RuntimeError("died before final state/plan commit")

        monkeypatch.setattr(CU.journal, "supersede_all_but", die_after_plan_insert)
        with pytest.raises(RuntimeError, match="final state/plan commit"):
            run(conn, "2026-08-12", ["2026-08-12"], durable_advance())

        assert CU.last_processed_session(conn) == prior
        assert CU.resume_state(conn) == prior_state
        latest = journal.latest_plan(conn)
        assert latest.plan_id == prior_plan.plan_id
        assert journal.load_plan(conn, "plan-2026-08-12") is None


class TestTheSeamCannotBeSatisfiedInMemory:
    def test_advance_state_RECEIVES_the_transaction(self, conn):
        """A seam that is handed the connection can write through it. One that
        is not cannot, no matter what the docstring claims — and the day Wealth
        Core is wired, whoever writes the adapter will reach for whatever the
        signature offers."""
        import inspect

        sig = inspect.signature(CU.catch_up)
        assert "advance_state" in sig.parameters

        seen = {}

        def advance(c, session, state):
            seen["conn"] = c
            return state

        run(conn, "2026-08-10", ["2026-08-10"], advance)
        assert seen["conn"] is conn

    def test_catch_up_PERSISTS_the_state_it_was_handed(self, conn):
        """The second enforcement, and the one that does not depend on the
        seam's cooperation. Whatever `advance_state` returns is encoded into
        the same row as the pointer, in the same statement — so even a seam
        that keeps its own state purely in memory leaves catch-up's copy
        durable and consistent with the cursor.
        """
        run(conn, "2026-08-11", ["2026-08-10", "2026-08-11"],
            lambda c, s, st: {"last": s})

        assert CU.resume_state(conn) == {"last": "2026-08-11"}

    def test_a_RESTART_recovers_the_state_without_being_handed_one(self, conn):
        """What a real restart does: no in-memory state, read what is durable
        and carry on. Without this the resumed run starts from `None` and the
        seam has no history to advance."""
        run(conn, "2026-08-11", ["2026-08-10", "2026-08-11"],
            lambda c, s, st: {"seen": (st or {}).get("seen", []) + [s]})

        carried = []

        def advance(c, session, state):
            carried.append(list((state or {}).get("seen", [])))
            return {"seen": (state or {}).get("seen", []) + [session]}

        run(conn, "2026-08-12", ["2026-08-11", "2026-08-12"], advance)
        assert carried == [["2026-08-10", "2026-08-11"]], (
            "the resumed run did not see the state the first one left")

    def test_an_UNENCODABLE_state_is_refused_at_the_first_session(self, conn):
        """Fail loudly and immediately, not after four hours of replay.

        A state catch-up cannot encode is one it cannot make atomic with the
        pointer, which is the whole guarantee. Refusing at session one costs a
        clear error; discovering it at the end costs the run.
        """
        class Opaque:
            pass

        with pytest.raises(CU.StateNotDurable, match="encode"):
            run(conn, "2026-08-11", ["2026-08-10", "2026-08-11"],
                lambda c, s, st: Opaque())

        assert CU.last_processed_session(conn) is None, (
            "nothing may advance when the state cannot be made durable")


class TestASeamThatCOMMITSCannotBeStopped_butIsBounded:
    """The limit of what any design can promise here, stated as a test.

    Handing `advance_state` the transaction lets it be atomic. It cannot FORCE
    it: a seam that calls `conn.commit()` itself has made its own state durable
    ahead of the pointer, and no arrangement of this module prevents that. The
    mutation sweep found this — committing inside the seam is the one change
    that left the suite green.

    What IS guaranteed is that catch-up's own copy never disagrees with its own
    pointer, so a restart resumes from a coherent pair and the divergence is
    detectable rather than silent.
    """

    def test_catch_ups_own_state_and_pointer_agree_even_then(self, conn):
        def commits_early(c, session, state):
            with c.cursor() as cur:
                cur.execute(
                    "INSERT INTO strategy_state (security_id, age, last_session)"
                    " VALUES ('P-AAA', 1, %s) ON CONFLICT (security_id)"
                    " DO UPDATE SET age = strategy_state.age + 1,"
                    " last_session = EXCLUDED.last_session", (session,))
            c.commit()                        # the mistake this bounds
            if session == "2026-08-12":
                raise RuntimeError("died after the seam committed")
            return {"last": session}

        with pytest.raises(RuntimeError):
            run(conn, "2026-08-13",
                ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], commits_early)

        assert CU.last_processed_session(conn) == dt.date(2026, 8, 11)
        assert CU.resume_state(conn) == {"last": "2026-08-11"}, (
            "catch-up's own state must match its own pointer regardless")

    def test_and_the_seams_over_advance_is_DETECTABLE(self, conn):
        """Not silent. The seam's durable state is one session ahead of the
        cursor, and an operator (or a startup check) comparing the two can see
        it — which is the difference between a bug that is found and one that
        quietly double-ages a book."""
        def commits_early(c, session, state):
            with c.cursor() as cur:
                cur.execute(
                    "INSERT INTO strategy_state (security_id, age, last_session)"
                    " VALUES ('P-AAA', 1, %s) ON CONFLICT (security_id)"
                    " DO UPDATE SET age = strategy_state.age + 1,"
                    " last_session = EXCLUDED.last_session", (session,))
            c.commit()
            if session == "2026-08-12":
                raise RuntimeError("died after the seam committed")
            return {"last": session}

        with pytest.raises(RuntimeError):
            run(conn, "2026-08-13",
                ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], commits_early)

        _, seam_session = durable_state(conn)
        assert seam_session > CU.last_processed_session(conn), (
            "the disagreement exists and is visible — that is the whole "
            "claim, since preventing it is not in this module's power")


class TestReprojectionDoesNotDisturbAnyOfIt:
    def test_a_cash_flow_moves_neither_the_pointer_nor_the_state(self, conn):
        run(conn, "2026-08-11", ["2026-08-10", "2026-08-11"],
            durable_advance())
        before = durable_state(conn)

        CU.reproject(conn, session="2026-08-11", nav=D("150000"),
                     weights={"P-AAA": D("1.0")}, exposure=D("1"),
                     marks={"P-AAA": D("100")})

        assert durable_state(conn) == before
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 11)
