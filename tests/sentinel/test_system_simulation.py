"""Step 3b — the pieces COMPOSED, which no research artefact can answer.

The frozen artefacts certify the controller's arithmetic. They say nothing about
what happens when that controller is driven by the catch-up orchestrator, its
state persisted in the same transaction as a session pointer, its exposure
projected into shares against an observed NAV, and the result pushed through the
two-phase executor. Every one of those seams was built and certified separately;
this is the first time they run as one chain.

```text
observations -> Controller -> exposure -> project() -> ExecutionPlan -> executor
                    ^                                        |
                    +-- catchup.advance_state, state durable +
```

Wealth Core itself is still NOT wired — it is NO-GO, and `decide` stays a seam.
What is exercised here is everything between the controller and the broker,
which is the half that was untested as an assembly.

The scenarios are the ones a research tape structurally cannot produce: an
outage, a restart mid-ramp, a deposit landing at 55% exposure, a corpus that
stops advancing, and the same recovery run twice.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import (  # noqa: E402
    _EphemeralPostgres,
    drop_public_tables,
)

from sentinel.controller import frozen_rule  # noqa: E402
from sentinel.controller.machine import Controller, Observation  # noqa: E402
from sentinel.core import catchup as CU  # noqa: E402
from sentinel.core import cashflow as CF  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from tests.sentinel.test_controller_certification import observations  # noqa: E402

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
    drop_public_tables(c)
    S.ensure_schema(c)
    from sentinel import schema as sentinel_schema
    sentinel_schema.ensure_schema(c)
    yield c
    c.close()


# ── the seam: the controller AS `advance_state` ─────────────────────────────

CFG = frozen_rule.load()


def tape_window(n=400, offset=1200):
    """A slice of the frozen tape, as (session, Observation, parent_alloc).

    Offset into the middle so the window contains real severe episodes and at
    least one fragile recovery — a quiet stretch would compose just as happily
    and prove much less.
    """
    rows, obs = observations()
    sl = slice(offset, offset + n)
    parents = [float(r["canonical_alloc"]) for r in rows[sl]]
    return [r["date"] for r in rows[sl]], list(obs[sl]), parents


def controller_seam(by_session):
    """`advance_state(conn, session, state)` driving the real controller.

    The signature is the one `catch_up` enforces: it receives the transaction,
    and whatever it returns is persisted in the same statement as the session
    pointer. The controller's state is a plain dict precisely so it survives
    that trip.
    """
    ctl = Controller(CFG)

    def advance(conn, session, state):
        st = state or {"ctl": ctl.initial_state(), "path": []}
        ob, parent, prior = by_session[session]
        ctl_state, decision = ctl.step_with_parent(
            observation=ob, state=st["ctl"], parent_alloc=parent,
            prior_parent_alloc=prior)
        return {"ctl": ctl_state,
                "path": st["path"] + [[session, decision.target_core_exposure]]}
    return advance


def indexed(dates, obs, parents):
    return {d: (o, p, parents[i - 1] if i else 1.0)
            for i, (d, o, p) in enumerate(zip(dates, obs, parents))}


def straight_run(dates, obs, parents):
    """The controller alone, no database. The reference every composed run is
    compared against."""
    ctl = Controller(CFG)
    st = ctl.initial_state()
    path = []
    for i, (d, o) in enumerate(zip(dates, obs)):
        st, dec = ctl.step_with_parent(
            observation=o, state=st, parent_alloc=parents[i],
            prior_parent_alloc=parents[i - 1] if i else 1.0)
        path.append([d, dec.target_core_exposure])
    return st, path


def a_plan(session, exposure, basket=None):
    d = dt.date.fromisoformat(session)
    return ExecutionPlan(plan_id=f"plan-{session}", decision_session=d,
                         effective_session=d, target_exposure=D(str(exposure)),
                         target_basket={k: D(v) for k, v in
                                        (basket or {"P-AAA": "100"}).items()},
                         data_version=1)


class TestTheChainComposes:
    def test_the_controller_driven_through_CATCH_UP_matches_a_straight_run(
            self, conn):
        """The composition claim. Four hundred sessions of the frozen tape,
        replayed through the orchestrator with every session's state committed
        to PostgreSQL, must produce the exposure path the controller produces
        on its own.

        If the seam loses anything — a healthy streak, a ramp index, a stress
        clock — the paths diverge, and they diverge silently: both are smooth,
        both are plausible.
        """
        dates, obs, parents = tape_window()
        want_state, want_path = straight_run(dates, obs, parents)

        result = CU.catch_up(
            conn, through=dates[-1], missed=dates,
            advance_state=controller_seam(indexed(dates, obs, parents)),
            decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        assert result.sessions_replayed == len(dates)
        got = CU.resume_state(conn)
        assert got["path"] == want_path
        assert got["ctl"] == want_state

    def test_the_controllers_state_SURVIVES_the_transaction(self, conn):
        """`catch_up` refuses a state it cannot encode without a `default=`
        fallback. A controller whose state needed one could not be driven by it
        at all — so this is the constraint that made the state a plain dict."""
        dates, obs, parents = tape_window(n=60)
        CU.catch_up(conn, through=dates[-1], missed=dates,
                    advance_state=controller_seam(indexed(dates, obs, parents)),
                    decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        raw = CU.resume_state(conn)
        assert json.loads(json.dumps(raw, sort_keys=True)) == raw

    def test_the_exposure_reaches_the_PLAN(self, conn):
        """The controller decides HOW MUCH; the plan is where that becomes an
        instruction. A chain that computes the right exposure and emits a plan
        carrying a different one is worse than one that fails."""
        dates, obs, parents = tape_window()
        _, want_path = straight_run(dates, obs, parents)

        CU.catch_up(conn, through=dates[-1], missed=dates,
                    advance_state=controller_seam(indexed(dates, obs, parents)),
                    decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        plan = journal.latest_plan(conn)
        assert plan.target_exposure == D(str(want_path[-1][1]))


class TestOutageAndRestart:
    def test_an_OUTAGE_advances_every_session_and_emits_ONE_plan(self, conn):
        """Offline for the whole window, back on the last session. The
        deterministic state must advance through all of it — the ramp's clocks
        are path-dependent — while the broker sees a single intent."""
        dates, obs, parents = tape_window(n=120)
        _, want_path = straight_run(dates, obs, parents)

        result = CU.catch_up(
            conn, through=dates[-1], missed=dates,
            advance_state=controller_seam(indexed(dates, obs, parents)),
            decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        assert result.sessions_replayed == 120
        assert CU.resume_state(conn)["path"] == want_path
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_execution_plans"
                        " WHERE superseded_by IS NULL")
            assert cur.fetchone()[0] == 1

    def test_RESTARTING_every_thirty_sessions_changes_nothing(self, conn):
        """The process dies and comes back repeatedly. Each resume reads the
        durable state rather than a fresh one, so the ramp continues mid-flight
        — a silently reset healthy streak would delay a promotion by ten
        sessions while looking entirely healthy."""
        dates, obs, parents = tape_window()
        _, want_path = straight_run(dates, obs, parents)
        idx = indexed(dates, obs, parents)

        for chunk in range(0, len(dates), 30):
            window = dates[:chunk + 30]
            if not window:
                continue
            CU.catch_up(conn, through=window[-1], missed=window,
                        advance_state=controller_seam(idx),
                        decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        assert CU.resume_state(conn)["path"] == want_path

    def test_RECOVERING_TWICE_takes_no_further_economic_action(self, conn):
        """The rule the review named: a second recovery pass over the same
        window must advance nothing and change no intent.

        `last_processed_session` makes the sessions no-ops; the plan is
        re-derived and must be economically identical. Its fingerprint excludes
        `plan_id` and `superseded_by` precisely so 'the same intent, expressed
        again' is recognisable as such.
        """
        dates, obs, parents = tape_window(n=90)
        idx = indexed(dates, obs, parents)
        seam = controller_seam(idx)

        first = CU.catch_up(conn, through=dates[-1], missed=dates,
                            advance_state=seam,
                            decide=lambda s, st: a_plan(s, st["path"][-1][1]))
        state_after_first = CU.resume_state(conn)

        second = CU.catch_up(conn, through=dates[-1], missed=dates,
                             advance_state=seam,
                             decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        assert second.sessions_replayed == 0, "sessions were advanced twice"
        assert CU.resume_state(conn) == state_after_first
        assert second.plan.fingerprint() == first.plan.fingerprint()

    def test_and_the_second_pass_does_not_double_age_the_ramp(self, conn):
        """The specific damage a replayed session does. Wealth Core's state and
        the ramp's streaks are path-dependent, so advancing a session twice
        ages every clock twice — invisible in the exposure until a promotion
        arrives ten sessions early."""
        dates, obs, parents = tape_window(n=90)
        idx = indexed(dates, obs, parents)
        seam = controller_seam(idx)
        _, want_path = straight_run(dates, obs, parents)

        for _ in range(3):
            CU.catch_up(conn, through=dates[-1], missed=dates,
                        advance_state=seam,
                        decide=lambda s, st: a_plan(s, st["path"][-1][1]))

        assert CU.resume_state(conn)["path"] == want_path


class TestDegradedInputs:
    def test_a_STALLED_CORPUS_does_not_drift_exposure_upward(self, conn):
        """The corpus stops advancing: every observation arrives unavailable.

        The dangerous direction is UP. A controller that read missing breadth
        as comfortable would clear the healthy triple, promote through the
        ramp, and arrive at 100% on no evidence at all — the exact fail-open
        shape Stocker's crash brake had.
        """
        ctl = Controller(CFG)
        st = ctl.initial_state()
        # Enter a fragile ramp on a flat r40 window, then go blind.
        seq = [(1.0, True)] * 3 + [(0.0, False)] * 2 + [(1.0, True)]
        prior = 1.0
        for i, (parent, healthy) in enumerate(seq):
            ob = Observation(session=f"2030-02-{i + 1:02d}", shadow_nav=1.0,
                             damaged_breadth=0.1 if healthy else 0.9,
                             green_breadth=0.9 if healthy else 0.05,
                             shadow_r20=0.05 if healthy else -0.05,
                             shadow_r40=0.0)
            st, d = ctl.step_with_parent(observation=ob, state=st,
                                         parent_alloc=parent,
                                         prior_parent_alloc=prior)
            prior = parent
        assert d.target_core_exposure == 0.55, "should be mid-ramp"

        blind = st
        for i in range(30):
            ob = Observation(session=f"2030-03-{i + 1:02d}")   # everything None
            blind, d = ctl.step_with_parent(observation=ob, state=blind,
                                            parent_alloc=1.0,
                                            prior_parent_alloc=1.0)
        assert d.target_core_exposure == 0.55, (
            f"thirty blind sessions promoted the ramp to "
            f"{d.target_core_exposure} on no evidence")

    def test_an_unavailable_HEALTHY_breaks_the_streak(self, conn):
        """Nine confirmations, one blind session, one more healthy — must not
        promote. The rule asks for consecutive healthy CLOSES, and a close
        nobody could classify is not one of them."""
        ctl = Controller(CFG)
        st = ctl.initial_state()
        prior = 1.0
        seq = ([(1.0, True)] * 2 + [(0.0, False)] * 2
               + [(1.0, True)] * 9 + [(1.0, None)] + [(1.0, True)])
        for i, (parent, healthy) in enumerate(seq):
            ob = Observation(
                session=f"2030-04-{i + 1:02d}", shadow_nav=1.0,
                damaged_breadth=None if healthy is None else (0.1 if healthy else 0.9),
                green_breadth=None if healthy is None else (0.9 if healthy else 0.05),
                shadow_r20=None if healthy is None else (0.05 if healthy else -0.05),
                shadow_r40=0.0)
            st, d = ctl.step_with_parent(observation=ob, state=st,
                                         parent_alloc=parent,
                                         prior_parent_alloc=prior)
            prior = parent
        assert d.target_core_exposure == 0.55, (
            f"promoted to {d.target_core_exposure} across an unclassifiable "
            f"session")


class TestExternalCashAtAPartialExposure:
    """§7a made 0.55 and 0.65 real baskets rather than corner cases. A deposit
    landing mid-ramp is where that stops being a formality."""

    def test_a_deposit_at_55_percent_projects_against_55_percent(self, conn):
        CF.record(conn, session="2030-05-01", amount=D("50000"), detail="wire")
        out = CU.reproject(conn, session="2030-05-01", nav=D("150000"),
                           weights={"P-AAA": D("0.5"), "P-BBB": D("0.5")},
                           exposure=D("0.55"),
                           marks={"P-AAA": D("100"), "P-BBB": D("50")})
        # 150,000 x 0.5 x 0.55 = 41,250 -> 412 shares at 100, 825 at 50
        assert out.plan.target_basket == {"P-AAA": D("412"), "P-BBB": D("825")}

    def test_the_deposit_does_not_move_the_CONTROLLER(self, conn):
        """Exposure is the controller's; NAV is execution's. A deposit changes
        what 55% is worth and must not change that it is 55% — the membrane
        runs one way."""
        dates, obs, parents = tape_window(n=60)
        idx = indexed(dates, obs, parents)
        CU.catch_up(conn, through=dates[-1], missed=dates,
                    advance_state=controller_seam(idx),
                    decide=lambda s, st: a_plan(s, st["path"][-1][1]))
        before = CU.resume_state(conn)

        CF.record(conn, session=dates[-1], amount=D("50000"), detail="wire")
        CU.reproject(conn, session=dates[-1], nav=D("150000"),
                     weights={"P-AAA": D("1.0")}, exposure=D("1"),
                     marks={"P-AAA": D("100")})

        assert CU.resume_state(conn) == before
        assert CU.last_processed_session(conn) == dt.date.fromisoformat(dates[-1])

    def test_strategy_pl_excludes_it_even_mid_ramp(self, conn):
        CF.record(conn, session="2030-05-01", amount=D("50000"), detail="wire")
        assert CF.strategy_pl(conn, start="2030-05-01", end="2030-05-31",
                              opening_nav=D("100000"),
                              closing_nav=D("150250")) == D("250")


class TestASingleNameFailure:
    def test_a_holding_that_cannot_be_priced_is_not_liquidated(self, conn):
        """A catastrophic single-name event — halted, delisted mid-process, a
        vendor row with no close. The position is carried, not sold, and the
        rest of the book still converges."""
        out = CU.reproject(conn, session="2030-06-01", nav=D("100000"),
                           weights={"P-AAA": D("0.5"), "P-BBB": D("0.5")},
                           exposure=D("1"),
                           marks={"P-BBB": D("50")},          # AAA unpriceable
                           held={"P-AAA": D("100")})
        assert out.plan.target_basket["P-AAA"] == D("100")
        assert out.plan.target_basket["P-BBB"] == D("1000")
        assert any("P-AAA" in c for c in out.caveats)

    def test_but_a_name_the_STRATEGY_dropped_is_sold_even_unpriced(self, conn):
        out = CU.reproject(conn, session="2030-06-01", nav=D("100000"),
                           weights={"P-BBB": D("1.0")}, exposure=D("1"),
                           marks={"P-BBB": D("50")},
                           held={"P-ZZZ": D("40")})
        assert out.plan.target_basket["P-ZZZ"] == D("0")
        assert out.remaining["P-ZZZ"] == D("-40")


class TestAnUnevaluableFragilityGate:
    """A defect this file found, and the frozen tape structurally could not.

    The gate needs a five-session r40 window at the prior close. On a COLD
    START — or after a restore, or on the first recovery of a short history —
    that window does not exist, and `is_fragile` correctly returns None.

    The controller then took `if fragile:` and fell through to the not-fragile
    branch: **straight to 100%**. Exposure-increasing action on absent
    evidence, which architecture invariant 26 forbids in terms:

    > Exposure-increasing action requires strictly stronger evidence than
    > exposure-reducing action.

    The tape never exercises it — its first recovery is roughly 290 sessions
    in, and every window from there is full. Composing the controller with
    catch-up, where a cold start is the normal first day, is what surfaced it.
    """

    def _first_recovery(self, sessions_before: int):
        """Exposure on the first recovery, with `sessions_before` of history."""
        ctl = Controller(CFG)
        st = ctl.initial_state()
        prior = 1.0
        seq = ([(1.0, True)] * sessions_before + [(0.0, False)] * 2
               + [(1.0, True)])
        for i, (parent, healthy) in enumerate(seq):
            ob = Observation(session=f"2031-01-{i + 1:02d}", shadow_nav=1.0,
                             damaged_breadth=0.1 if healthy else 0.9,
                             green_breadth=0.9 if healthy else 0.05,
                             shadow_r20=0.05 if healthy else -0.05,
                             shadow_r40=0.0)
            st, d = ctl.step_with_parent(observation=ob, state=st,
                                         parent_alloc=parent,
                                         prior_parent_alloc=prior)
            prior = parent
        return d

    def test_a_COLD_START_recovery_ramps_rather_than_going_to_full(self):
        d = self._first_recovery(sessions_before=2)     # window too short
        assert d.target_core_exposure == 0.55, (
            f"went to {d.target_core_exposure} on a gate that could not be "
            f"evaluated — exposure-increasing action on absent evidence")
        assert d.reason == "RECOVERY_GATE_UNAVAILABLE_RAMP"

    def test_and_it_SAYS_the_gate_was_unavailable(self):
        """Distinguishable from a genuine fragile verdict. Both ramp, and an
        operator asking why needs to know which — one is the strategy working,
        the other is a data window that has not filled yet."""
        unavailable = self._first_recovery(sessions_before=2)
        evaluable = self._first_recovery(sessions_before=12)
        assert unavailable.reason == "RECOVERY_GATE_UNAVAILABLE_RAMP"
        assert evaluable.reason == "RECOVERY_FRAGILE_RAMP"
        assert unavailable.target_core_exposure == evaluable.target_core_exposure

    def test_a_ROBUST_recovery_with_a_full_window_still_goes_to_full(self):
        """The fix must not make every recovery cautious. A rising r40 window
        is genuinely not fragile and still takes the direct route."""
        ctl = Controller(CFG)
        st = ctl.initial_state()
        prior = 1.0
        # r40 climbing, so delta_r40_5 > 0 at the recovery -> not fragile.
        seq = [(1.0, True)] * 12 + [(0.0, False)] * 2 + [(1.0, True)]
        for i, (parent, healthy) in enumerate(seq):
            ob = Observation(session=f"2031-02-{i + 1:02d}", shadow_nav=1.0,
                             damaged_breadth=0.1, green_breadth=0.9,
                             shadow_r20=0.05, shadow_r40=0.01 * i)
            st, d = ctl.step_with_parent(observation=ob, state=st,
                                         parent_alloc=parent,
                                         prior_parent_alloc=prior)
            prior = parent
        assert d.target_core_exposure == 1.0
        assert d.reason == "RECOVERY_FULL"
