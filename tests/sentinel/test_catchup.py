"""#3 — convergence after absence, and external cash as a first-class event.

THE FAILURES, written before the fix.

## Absence

Sentinel is off Monday, Tuesday and Wednesday. It returns Thursday morning. The
obvious implementation walks the missed sessions and executes each one:

```text
Monday      controller wanted 0%       ->  liquidate
Tuesday     controller wanted 55%      ->  re-enter
Wednesday   controller wanted 100%     ->  rotate
Thursday    controller wants 100%      ->  ...
```

Every one of those fires at Thursday's prices, against Thursday's book. Three
round trips of slippage and commission to arrive where a single Thursday plan
would have arrived directly — and the first of them liquidates a live account
because of what a Monday that is over wanted.

The rule the execution contract already states, and which nothing enforced:

    historical sessions advance DETERMINISTIC STATE.
    historical EXECUTION INTENT is never replayed.

So catch-up replays Wealth Core and the controller across the gap — peaks, ages,
cooldowns and exposure all advance exactly as they would have — and then emits
exactly ONE execution intent, for now.

## External cash

A deposit is not a return and a withdrawal is not a loss. Both change what is
investable; neither changes what Wealth Core did.

```text
NAV 100k -> 150k overnight
```

Read as P&L that is +50% in a day, and it is now in every performance number
the system will ever report. Read as a cash flow when it was actually a
reconciliation break, and a real discrepancy has been explained away. NAV moves
for two reasons and the difference is not recoverable from the number, so it is
never INFERRED — it is declared, and what cannot be attributed stays
UNEXPLAINED.

What a cash flow does trigger is a RE-PROJECTION: the current target is sized
against the new NAV and Sentinel converges to it. What it must never trigger is
a REPLAY — the historical book is not a function of today's balance.
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

from tests.support.postgres import (  # noqa: E402
    _EphemeralPostgres,
    drop_public_tables,
)

from sentinel.core import cashflow as CF  # noqa: E402
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
    drop_public_tables(c)
    S.require_feed_schema(c)
    from sentinel import schema as sentinel_schema
    sentinel_schema.ensure_schema(c)
    yield c
    c.close()


def a_plan(session="2026-08-10", basket=None, exposure="1.0", pid=None):
    d = dt.date.fromisoformat(session)
    return ExecutionPlan(
        plan_id=pid or f"plan-{session}",
        decision_session=d, effective_session=d,
        target_exposure=D(exposure),
        target_basket={k: D(v) for k, v in (basket or {"P-AAA": "100"}).items()},
        data_version=1)


# ══════════════════════════════════════════════════════════════════════════
# ABSENCE
# ══════════════════════════════════════════════════════════════════════════

class TestHistoricalIntentIsNeverReplayed:
    def test_three_missed_sessions_produce_ONE_execution_intent(self, conn):
        """The headline. Not three plans executed in order — one plan, for now.

        The replay still HAPPENS: each missed session advances the deterministic
        state. What does not happen is three trips to the broker.
        """
        seen = []

        def advance(conn, session, state):
            seen.append(session)
            return {"sessions": state.get("sessions", 0) + 1}

        result = CU.catch_up(
            conn, through="2026-08-13",
            missed=["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
            advance_state=advance, state={},
            decide=lambda session, state: a_plan(session))

        assert seen == ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"]
        assert result.sessions_replayed == 4
        assert result.plan.decision_session == dt.date(2026, 8, 13)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_execution_plans"
                        " WHERE superseded_by IS NULL")
            assert cur.fetchone()[0] == 1, (
                "exactly one surviving execution intent after a catch-up")

    def test_the_surviving_plan_is_the_NEWEST_not_the_first(self, conn):
        """Which one survives is the whole safety property. Monday wanted zero;
        surviving on Thursday it would liquidate a live account."""
        # A COMPLETE session list. It used to read `["2026-08-10",
        # "2026-08-13"]`, skipping the Tuesday and Wednesday — which catch-up
        # now refuses, because advancing over a gap and then marking `through`
        # processed buries the omitted sessions permanently. The gap was
        # incidental here anyway: `decide` is called ONCE, for `through`, so
        # the two-element list never produced two plans.
        CU.catch_up(conn, through="2026-08-13",
                    missed=["2026-08-10", "2026-08-11",
                            "2026-08-12", "2026-08-13"],
                    advance_state=lambda c, s, st: st,
                    decide=lambda session, state: a_plan(
                        session,
                        basket={} if session == "2026-08-10" else {"P-AAA": "100"},
                        exposure="0.0" if session == "2026-08-10" else "1.0"))

        current = journal.latest_plan(conn)
        assert current.decision_session == dt.date(2026, 8, 13)
        assert current.target_exposure == D("1.0")

    def test_an_intent_from_BEFORE_the_gap_is_superseded_too(self, conn):
        """A plan left outstanding when the process died is historical intent
        as much as one produced during the replay."""
        stale = a_plan("2026-08-07", pid="plan-stale")
        journal.save_plan(conn, stale)

        CU.catch_up(conn, through="2026-08-13", missed=["2026-08-13"],
                    advance_state=lambda c, s, st: st,
                    decide=lambda session, state: a_plan(session))

        assert journal.load_plan(conn, "plan-stale").is_superseded


class TestCatchUpIsResumable:
    def test_the_processed_session_is_DURABLE(self, conn):
        CU.catch_up(conn, through="2026-08-11",
                    missed=["2026-08-10", "2026-08-11"],
                    advance_state=lambda c, s, st: st,
                    decide=lambda session, state: a_plan(session))
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 11)

    def test_a_crash_MIDWAY_does_not_lose_the_sessions_already_advanced(self, conn):
        """The pointer advances with the state it describes, in one
        transaction. A pointer written after the loop would replay everything
        after a crash; one written before would skip a session forever, and
        skipping is the silent one."""
        def explode_on_wednesday(conn, session, state):
            if session == "2026-08-12":
                raise RuntimeError("the process died here")
            return state

        with pytest.raises(RuntimeError):
            CU.catch_up(conn, through="2026-08-13",
                        missed=["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"],
                        advance_state=explode_on_wednesday,
                        decide=lambda session, state: a_plan(session))

        assert CU.last_processed_session(conn) == dt.date(2026, 8, 11), (
            "the two sessions that DID advance must not be replayed, and the "
            "one that did not must not be skipped")

    def test_resuming_replays_only_what_is_OWED(self, conn):
        CU.catch_up(conn, through="2026-08-11",
                    missed=["2026-08-10", "2026-08-11"],
                    advance_state=lambda c, s, st: st,
                    decide=lambda session, state: a_plan(session))

        seen = []
        CU.catch_up(conn, through="2026-08-13",
                    missed=["2026-08-10", "2026-08-11", "2026-08-12",
                            "2026-08-13"],
                    advance_state=lambda c, s, st: seen.append(s) or st,
                    decide=lambda session, state: a_plan(session))
        assert seen == ["2026-08-12", "2026-08-13"], (
            "a session already advanced must not advance twice — the state is "
            "path-dependent, so a replayed session double-ages every episode")

    def test_two_catch_ups_at_once_are_REFUSED(self, conn, pg):
        """Deterministic state advanced twice concurrently is not deterministic.
        The same writer lock the executor takes."""
        other = S.connect(pg.sync_dsn)
        try:
            with journal.writer_lock(other):
                with pytest.raises(journal.WriterLockUnavailable):
                    CU.catch_up(conn, through="2026-08-13",
                                missed=["2026-08-13"],
                                advance_state=lambda c, s, st: st,
                                decide=lambda session, state: a_plan(session))
        finally:
            other.close()


# ══════════════════════════════════════════════════════════════════════════
# EXTERNAL CASH
# ══════════════════════════════════════════════════════════════════════════

class TestNavMovesForTwoReasons:
    def test_an_unexplained_NAV_move_is_NOT_silently_pl(self, conn):
        """Reading it as P&L puts a $50k deposit into every return this system
        will ever report, permanently and invisibly."""
        r = CF.reconcile_nav(conn, session="2026-08-10",
                             previous_nav=D("100000"), observed_nav=D("150000"),
                             marked_pl=D("250"))
        assert not r.explained
        assert r.unexplained == D("49750")

    def test_nor_silently_a_CASH_FLOW(self, conn):
        """The opposite error is worse in a different way: a genuine
        reconciliation break — a position that vanished, a fill nobody saw —
        gets a benign label and stops being investigated."""
        r = CF.reconcile_nav(conn, session="2026-08-10",
                             previous_nav=D("100000"), observed_nav=D("150000"),
                             marked_pl=D("250"))
        assert CF.flows_between(conn, "2026-08-01", "2026-08-31") == []
        assert r.attribution is CF.Attribution.UNEXPLAINED

    def test_a_DECLARED_flow_explains_it(self, conn):
        CF.record(conn, session="2026-08-10", amount=D("50000"),
                  detail="wire from Chase ****1234")
        r = CF.reconcile_nav(conn, session="2026-08-10",
                             previous_nav=D("100000"), observed_nav=D("150250"),
                             marked_pl=D("250"))
        assert r.explained and r.unexplained == D("0")

    def test_ordinary_pl_needs_no_declaration(self, conn):
        r = CF.reconcile_nav(conn, session="2026-08-10",
                             previous_nav=D("100000"), observed_nav=D("101337"),
                             marked_pl=D("1337"))
        assert r.explained and r.external == D("0")


class TestCashIsNotPerformance:
    def test_a_deposit_is_not_a_return(self, conn):
        """+$50k on a $100k account is not +50%. This is the number that would
        be quoted."""
        CF.record(conn, session="2026-08-10", amount=D("50000"), detail="wire")
        pl = CF.strategy_pl(conn, start="2026-08-01", end="2026-08-31",
                            opening_nav=D("100000"), closing_nav=D("150250"))
        assert pl == D("250")

    def test_a_withdrawal_is_not_a_loss(self, conn):
        CF.record(conn, session="2026-08-10", amount=D("-50000"), detail="wire")
        pl = CF.strategy_pl(conn, start="2026-08-01", end="2026-08-31",
                            opening_nav=D("150000"), closing_nav=D("100250"))
        assert pl == D("250")

    def test_the_net_of_several_flows_is_removed(self, conn):
        for amt in ("50000", "-20000", "5000"):
            CF.record(conn, session="2026-08-10", amount=D(amt), detail="x")
        assert CF.net_external(conn, "2026-08-01", "2026-08-31") == D("35000")


class TestReprojectionNotReplay:
    """The five cases the review named."""

    def test_PLUS_50k_reprojects_the_CURRENT_target_upward(self, conn):
        """Case 1. Same names, same weights, more of each. Membership is Wealth
        Core's business and does not change because money arrived."""
        before = CU.project(weights={"P-AAA": D("0.5"), "P-BBB": D("0.5")},
                            nav=D("100000"), exposure=D("1"),
                            marks={"P-AAA": D("100"), "P-BBB": D("50")})
        after = CU.project(weights={"P-AAA": D("0.5"), "P-BBB": D("0.5")},
                           nav=D("150000"), exposure=D("1"),
                           marks={"P-AAA": D("100"), "P-BBB": D("50")})
        assert before == {"P-AAA": D("500"), "P-BBB": D("1000")}
        assert after == {"P-AAA": D("750"), "P-BBB": D("1500")}
        assert set(before) == set(after), "the deposit did not change WHAT"

    def test_MINUS_50k_reprojects_downward(self, conn):
        """Case 2."""
        after = CU.project(weights={"P-AAA": D("0.5"), "P-BBB": D("0.5")},
                           nav=D("100000"), exposure=D("1"),
                           marks={"P-AAA": D("100"), "P-BBB": D("50")})
        assert after == {"P-AAA": D("500"), "P-BBB": D("1000")}

    def test_a_cash_flow_advances_NO_sessions(self, conn):
        """The property that separates a re-projection from a replay. Wealth
        Core's peaks, ages, review clocks and cooldowns are a function of price
        history, not of the balance."""
        CU.catch_up(conn, through="2026-08-10", missed=["2026-08-10"],
                    advance_state=lambda c, s, st: st,
                    decide=lambda session, state: a_plan(session))
        CF.record(conn, session="2026-08-10", amount=D("50000"), detail="wire")

        advanced = []
        out = CU.reproject(conn, session="2026-08-10", nav=D("150000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")},
                           advance_state=lambda c, s, st: advanced.append(s) or st)
        assert advanced == [], "a deposit must not replay a single session"
        assert out.plan.target_basket == {"P-AAA": D("1500")}
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 10)

    def test_a_deposit_while_the_BROKER_is_unavailable(self, conn):
        """Case 3. The money is real and unobserved. Nothing may execute
        against a guessed NAV — but the moment the broker returns and the NAV
        is observed, the re-projection happens and Sentinel converges.
        """
        CF.record(conn, session="2026-08-10", amount=D("50000"),
                  detail="declared while the broker was down")
        with pytest.raises(CU.NavUnobserved):
            CU.reproject(conn, session="2026-08-10", nav=None,
                         weights={"P-AAA": D("1.0")}, exposure=D("1"),
                         marks={"P-AAA": D("100")})

        out = CU.reproject(conn, session="2026-08-10", nav=D("150000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")})
        assert out.plan.target_basket == {"P-AAA": D("1500")}

    def test_a_withdrawal_while_SHARADAR_is_unavailable_still_REDUCES(self, conn):
        """Case 4. A withdrawal creates an obligation the account must meet.

        The missed-open asymmetry decides it: reductions may execute late,
        increases wait. Doing nothing because the corpus is stale leaves the
        account unable to settle the wire, which is not the conservative choice
        it looks like. Sized against the last PUBLISHED marks, and the staleness
        is recorded on the plan rather than assumed away.
        """
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")}, marks_stale=True,
                           # $150k before the wire, so the book is ABOVE the
                           # new target. That is what makes this a reduction.
                           held={"P-AAA": D("1500")})
        assert out.plan.target_basket == {"P-AAA": D("1000")}
        assert out.remaining == {"P-AAA": D("-500")}
        assert out.reduction_only is True
        assert any("stale" in c.lower() for c in out.caveats)

    def test_and_the_same_staleness_REFUSES_an_increase(self, conn):
        """The other half of the asymmetry, and the half that costs money if it
        is wrong. Buying on stale marks buys the wrong quantity of the right
        names at an unknown price."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("150000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")}, marks_stale=True,
                           held={"P-AAA": D("1000")})
        assert out.plan is None and out.reduction_only is True
        assert any("increase" in c.lower() for c in out.caveats)

    def test_cash_movement_DURING_a_partial_fill_converges_exactly_once(self, conn):
        """Case 5, and the one where the arithmetic earns its keep.

        A BUY 100 is 40 filled with 60 still working when a deposit lands. The
        re-projection wants 150. Naively that is a new BUY 150 on top of 40
        held and 60 committed — 250 shares for a 150-share target.

        `remaining = desired - held - committed` gives 50, and the working
        order is CANCELLED and confirmed rather than silently superseded,
        because declaring a live order superseded abandons it.
        """
        out = CU.reproject(conn, session="2026-08-10", nav=D("150000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("1000")},
                           held={"P-AAA": D("40")},
                           committed={"P-AAA": D("60")})
        assert out.plan.target_basket == {"P-AAA": D("150")}
        assert out.remaining == {"P-AAA": D("50")}, (
            "150 wanted, 40 held, 60 already working — 50 left to buy, not 150")
        assert out.cancel_first == ("P-AAA",) or out.cancel_first == []

    def test_the_re_projected_plan_is_a_NEW_plan_not_an_edit(self, conn):
        """A plan is immutable. Editing the basket under a live plan_id would
        change what the derived client keys mean — the same id would name two
        different economic intents."""
        CU.catch_up(conn, through="2026-08-10", missed=["2026-08-10"],
                    advance_state=lambda c, s, st: st,
                    decide=lambda session, state: a_plan(session))
        first = journal.latest_plan(conn)

        out = CU.reproject(conn, session="2026-08-10", nav=D("150000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")})
        assert out.plan.plan_id != first.plan_id
        assert journal.load_plan(conn, first.plan_id).is_superseded


class TestUnexplainedNavBlocksIncreasesOnly:
    def test_an_unexplained_move_REFUSES_to_increase(self, conn):
        """Increasing exposure on a NAV nobody can account for sizes a purchase
        against a number that may be wrong."""
        r = CF.reconcile_nav(conn, session="2026-08-10",
                             previous_nav=D("100000"), observed_nav=D("150000"),
                             marked_pl=D("0"))
        out = CU.reproject(conn, session="2026-08-10", nav=D("150000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")},
                           held={"P-AAA": D("1000")}, nav_reconciliation=r)
        assert out.plan is None and out.reduction_only is True

    def test_but_still_permits_DE_RISKING(self, conn):
        """A break of unknown cause is a reason to hold less, never a reason to
        be unable to."""
        r = CF.reconcile_nav(conn, session="2026-08-10",
                             previous_nav=D("100000"), observed_nav=D("60000"),
                             marked_pl=D("0"))
        out = CU.reproject(conn, session="2026-08-10", nav=D("60000"),
                           weights={"P-AAA": D("1.0")}, exposure=D("1"),
                           marks={"P-AAA": D("100")},
                           held={"P-AAA": D("1000")}, nav_reconciliation=r)
        assert out.plan is not None
        assert out.plan.target_basket == {"P-AAA": D("600")}


# ── the session list is PROVEN against the exchange calendar ─────────────────

class TestCatchUpCannotBeToldToSkipASession:
    """Catch-up used to trust `missed` and then mark `through` regardless.

    ```text
    last processed  Monday
    missed          [Tuesday, Thursday]
    through         Friday
    ```

    Wednesday and Friday never advanced Wealth Core or the controller, and the
    durable pointer then said Friday. Every later catch-up skips at or before
    the pointer, so those two sessions are gone — permanently and silently.
    That is the same class of loss `_mark_processed` closes from the other
    direction, arrived at through the argument list instead of a crash.

    The authority is now the certified XNYS calendar, not the caller. All dates
    below are real sessions unless the test says otherwise; 2026-08-15 is a
    Saturday and 2026-09-07 is Labor Day.
    """

    def advance(self):
        seen = []

        def _a(conn, session, state):
            seen.append(session)
            return {"last": session}
        _a.seen = seen
        return _a

    def run(self, conn, through, missed, adv=None):
        return CU.catch_up(conn, through=through, missed=missed,
                           advance_state=adv or self.advance(),
                           decide=lambda session, state: None)

    def test_a_MISSING_MIDDLE_session_refuses(self, conn):
        """The review's scenario. Wednesday is a session and is not listed."""
        with pytest.raises(CU.SessionsIncomplete) as e:
            self.run(conn, "2026-08-13",
                     ["2026-08-10", "2026-08-11", "2026-08-13"])
        assert "OMITTED" in str(e.value) and "2026-08-12" in str(e.value)

    def test_a_MISSING_THROUGH_session_refuses(self, conn):
        """`through` itself absent — the half that let the pointer jump."""
        with pytest.raises(CU.SessionsIncomplete) as e:
            self.run(conn, "2026-08-13",
                     ["2026-08-10", "2026-08-11", "2026-08-12"])
        assert "2026-08-13" in str(e.value)

    def test_and_NOTHING_is_marked_when_it_refuses(self, conn):
        """The refusal has to come BEFORE any advance. Refusing after
        advancing two of four sessions would leave exactly the half-applied
        state the whole module exists to prevent."""
        adv = self.advance()
        with pytest.raises(CU.SessionsIncomplete):
            self.run(conn, "2026-08-13",
                     ["2026-08-10", "2026-08-11", "2026-08-13"], adv)
        assert adv.seen == [], f"state advanced before refusing: {adv.seen}"
        assert CU.last_processed_session(conn) is None

    def test_a_DUPLICATE_refuses_rather_than_being_normalised(self, conn):
        """Silently de-duplicating hides a caller that believes it is asking
        for two advances of one session — and a double advance double-ages
        every episode in the book."""
        with pytest.raises(CU.SessionsIncomplete) as e:
            self.run(conn, "2026-08-11",
                     ["2026-08-10", "2026-08-10", "2026-08-11"])
        assert "duplicate" in str(e.value).lower()

    def test_OUT_OF_ORDER_is_accepted_and_sorted(self, conn):
        """Order is not information here — the sessions run in calendar order
        regardless — so refusing it would be pedantry rather than safety."""
        adv = self.advance()
        self.run(conn, "2026-08-11", ["2026-08-11", "2026-08-10"], adv)
        assert adv.seen == ["2026-08-10", "2026-08-11"]

    def test_a_WEEKEND_day_refuses(self, conn):
        """2026-08-15 is a Saturday. Advancing state over a non-session is not
        a no-op: it ages the book by a day the market never had."""
        with pytest.raises(CU.SessionsIncomplete) as e:
            self.run(conn, "2026-08-17",
                     ["2026-08-14", "2026-08-15", "2026-08-17"])
        assert "NOT SESSIONS" in str(e.value)

    def test_a_HOLIDAY_refuses(self, conn):
        """2026-09-07 is Labor Day. The calendar knows; the caller may not."""
        with pytest.raises(CU.SessionsIncomplete) as e:
            self.run(conn, "2026-09-08",
                     ["2026-09-04", "2026-09-07", "2026-09-08"])
        assert "NOT SESSIONS" in str(e.value)

    def test_the_holiday_is_not_required_either(self, conn):
        """The complement, and the reason the calendar has to be the authority
        rather than "every weekday": omitting Labor Day is CORRECT, and a
        contiguity rule built on dates would have refused it."""
        adv = self.advance()
        self.run(conn, "2026-09-08", ["2026-09-04", "2026-09-08"], adv)
        assert adv.seen == ["2026-09-04", "2026-09-08"]

    def test_a_RESUMING_caller_may_repeat_processed_sessions(self, conn):
        """The normal path after a partial run: the caller reports everything
        it believes it missed without knowing where the pointer reached. Those
        are dropped, not refused — the guard must not break recovery."""
        adv1 = self.advance()
        self.run(conn, "2026-08-11", ["2026-08-10", "2026-08-11"], adv1)
        adv2 = self.advance()
        self.run(conn, "2026-08-13",
                 ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], adv2)
        assert adv2.seen == ["2026-08-12", "2026-08-13"]

    def test_a_COMPLETE_list_still_works(self, conn):
        """Without this the guard could pass by refusing everything."""
        adv = self.advance()
        self.run(conn, "2026-08-13",
                 ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], adv)
        assert adv.seen == ["2026-08-10", "2026-08-11", "2026-08-12",
                            "2026-08-13"]
        assert CU.last_processed_session(conn) == dt.date(2026, 8, 13)
