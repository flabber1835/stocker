"""The execution projection, and the loop that drives an account toward it.

Two orderings are the substance of this suite, and both encode the same
asymmetry: selling late is dangerous, buying late is opportunity cost.

    reductions are emitted before increases, and a failed purchase never
        prevents a sale;
    a plan whose execution window has passed may still de-risk, but may not buy.

The missed-open rule is the one that stops a three-day outage turning into a
replay of orders that could never have been placed.

Contract: docs/sentinel-execution-contract.md §13, invariants 25-26.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import (  # noqa: E402
    commands as C, executor, journal, projection as PJ)
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, Side)
from sentinel.execution.identity import DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import FaultKind as F, SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState as S, RuntimeState  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")
BBB = BrokerInstrument(security_id="SEC-BBB", symbol="BBB", broker_id="b-BBB")
BIL = BrokerInstrument(security_id="SEC-BIL", symbol="BIL", broker_id="b-BIL")
INSTRUMENTS = {i.security_id: i for i in (AAA, BBB, BIL)}


def run(coro):
    return asyncio.run(coro)


def D(x):
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# Projection — pure
# ---------------------------------------------------------------------------

class TestProjection:
    def test_full_exposure_buys_whole_shares(self):
        p = PJ.project(shadow_weights={"SEC-AAA": D("0.5"), "SEC-BBB": D("0.5")},
                       exposure=D(1), nav=D(10_000),
                       marks={"SEC-AAA": D(100), "SEC-BBB": D(200)})
        assert p.quantities == {"SEC-AAA": D(50), "SEC-BBB": D(25)}

    def test_half_exposure_halves_every_holding(self):
        """Sentinel scales HOW MUCH, never WHAT. Invariant 9."""
        p = PJ.project(shadow_weights={"SEC-AAA": D("0.5"), "SEC-BBB": D("0.5")},
                       exposure=D("0.5"), nav=D(10_000),
                       marks={"SEC-AAA": D(100), "SEC-BBB": D(200)})
        assert p.quantities == {"SEC-AAA": D(25), "SEC-BBB": D(12)}
        assert set(p.quantities) == {"SEC-AAA", "SEC-BBB"}, "membership unchanged"

    def test_zero_exposure_holds_nothing_of_the_core(self):
        p = PJ.project(shadow_weights={"SEC-AAA": D(1)}, exposure=D(0),
                       nav=D(10_000), marks={"SEC-AAA": D(100)})
        assert p.quantities == {}

    def test_rounding_is_DOWN_never_nearest(self):
        """Rounding to nearest can OVERSHOOT the exposure the controller asked
        for, and overshoot is the wrong direction in exactly the state where the
        controller is cutting."""
        p = PJ.project(shadow_weights={"SEC-AAA": D(1)}, exposure=D(1),
                       nav=D(199), marks={"SEC-AAA": D(100)})
        assert p.quantities == {"SEC-AAA": D(1)}

    def test_realised_exposure_is_reported_SEPARATELY_from_the_target(self):
        """Conflating them is how a book that rounded to 96% gets recorded as
        having been ASKED for 96%, after which nobody can tell an execution
        shortfall from a decision."""
        p = PJ.project(shadow_weights={"SEC-AAA": D(1)}, exposure=D(1),
                       nav=D(1050), marks={"SEC-AAA": D(100)})
        assert p.target_exposure == D(1)
        assert p.realised_exposure < D(1)

    def test_an_unpriced_security_is_NAMED_not_guessed_and_not_renormalised(self):
        """Renormalising would silently redistribute its weight, making the
        realised exposure look right while the book was concentrated somewhere
        nobody chose."""
        p = PJ.project(shadow_weights={"SEC-AAA": D("0.5"), "SEC-BBB": D("0.5")},
                       exposure=D(1), nav=D(10_000),
                       marks={"SEC-AAA": D(100)})
        assert p.unpriced == ("SEC-BBB",)
        assert p.quantities == {"SEC-AAA": D(50)}, "AAA is NOT scaled up"

    def test_the_defensive_sleeve_absorbs_what_the_core_did_not_take(self):
        """A 0.55 exposure is not '45% idle cash', it is '45% in the sleeve' —
        that IS the mechanism."""
        p = PJ.project(shadow_weights={"SEC-AAA": D(1)}, exposure=D("0.5"),
                       nav=D(10_000), marks={"SEC-AAA": D(100), "SEC-BIL": D(100)},
                       defensive_security="SEC-BIL")
        assert p.quantities == {"SEC-AAA": D(50)}
        assert p.defensive_quantity == D(50)
        assert p.cash_residual == D(0)

    def test_leverage_is_refused_rather_than_clamped(self):
        with pytest.raises(PJ.ProjectionRefused, match=r"\[0, 1\]"):
            PJ.project(shadow_weights={"SEC-AAA": D(1)}, exposure=D("1.5"),
                       nav=D(10_000), marks={"SEC-AAA": D(100)})

    def test_floats_are_refused(self):
        with pytest.raises(TypeError):
            PJ.project(shadow_weights={"SEC-AAA": 1.0}, exposure=D(1),
                       nav=D(10_000), marks={"SEC-AAA": D(100)})

    def test_desired_basket_includes_the_sleeve(self):
        p = PJ.project(shadow_weights={"SEC-AAA": D(1)}, exposure=D("0.5"),
                       nav=D(10_000), marks={"SEC-AAA": D(100), "SEC-BIL": D(100)},
                       defensive_security="SEC-BIL")
        assert PJ.desired_basket(p) == {"SEC-AAA": D(50), "SEC-BIL": D(50)}


class TestOrderOfOperations:
    def _delta(self, security_id, remaining):
        return C.Delta(security_id=security_id, desired=D(0), held=D(0),
                       committed=D(0), remaining=D(remaining),
                       classification=C.DeltaClass.ACTIONABLE)

    def test_reductions_come_before_increases(self):
        ordered = executor.order_of_operations([
            self._delta("SEC-BUY", 10), self._delta("SEC-SELL", -10)])
        assert [d.security_id for d in ordered] == ["SEC-SELL", "SEC-BUY"]

    def test_it_is_deterministic_within_each_group(self):
        ordered = executor.order_of_operations([
            self._delta("SEC-B", -1), self._delta("SEC-A", -1),
            self._delta("SEC-D", 1), self._delta("SEC-C", 1)])
        assert [d.security_id for d in ordered] == ["SEC-A", "SEC-B",
                                                    "SEC-C", "SEC-D"]


# ---------------------------------------------------------------------------
# Executor — against the simulator and a real database
# ---------------------------------------------------------------------------

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
    c = feed_store.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for t in ("sentinel_account_binding", "sentinel_ownership_events",
                  "sentinel_commands", "sentinel_command_events",
                  "sentinel_execution_plans", "sentinel_fills",
                  "sentinel_observations"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    schema.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    yield c
    c.close()


TODAY = date(2026, 8, 11)


def plan(effective=TODAY, plan_id="plan-1"):
    return ExecutionPlan(plan_id=plan_id, decision_session=date(2026, 8, 10),
                         effective_session=effective,
                         target_exposure=D(1), data_version=1)


def broker():
    return SimulatedBroker(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))


def go(b, conn, desired, *, p=None, today=TODAY):
    """`desired` is folded INTO the plan — the executor has no other
    source of economics, which is the point of R3."""
    base = p or plan()
    return run(executor.execute_session(
        broker=b, conn=conn, deployment=DEPLOY,
        plan=replace(base, target_basket=desired),
        instruments=INSTRUMENTS, today=today))


def seed_held(conn, b, instrument, qty, *, plan_id="plan-0"):
    """A holding Sentinel KNOWS it owns: broker position AND journal entry.

    Seeding only the broker side is a different scenario entirely — an
    unexplained position is foreign activity, and the appliance correctly
    refuses to increase exposure while one exists. Getting this wrong in a
    fixture makes a test look like it is exercising ordering when it is really
    exercising the foreign-activity block.
    """
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity

    b.seed_position(instrument, str(qty))
    journal.save_command(conn, Command(
        identity=CommandIdentity(deployment=DEPLOY, plan_id=plan_id,
                                 security_id=instrument.security_id),
        instrument=instrument, side=Side.BUY, quantity=D(qty),
        state=S.FILLED, filled_quantity=D(qty)))


class TestExecuteSession:
    def test_it_submits_a_buy_and_journals_every_transition(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})

        assert len(result.submitted) == 1
        key = result.submitted[0].client_key
        assert [h["to"] for h in journal.command_history(conn, key)] == \
            ["PLANNED", "SEND_PENDING", "ACKNOWLEDGED"]

    def test_SEND_PENDING_is_written_BEFORE_the_broker_call(self, conn):
        """The crash-safety property. A crash after this write and before the
        outcome leaves a row with a DERIVED key — exactly enough for the next
        reconciliation to ask the broker what happened."""
        b = broker()
        order_of_writes = []
        real = journal.save_command

        def spy(c, command, previous=None):
            order_of_writes.append(("save", command.state.value))
            return real(c, command, previous=previous)

        real_submit = b.submit

        async def watched_submit(**kw):
            order_of_writes.append(("submit", None))
            return await real_submit(**kw)

        journal.save_command = spy
        b.submit = watched_submit
        try:
            go(b, conn, {"SEC-AAA": D(10)})
        finally:
            journal.save_command = real

        assert order_of_writes[:3] == [("save", "PLANNED"),
                                       ("save", "SEND_PENDING"),
                                       ("submit", None)]

    def test_an_UNKNOWN_outcome_is_journalled_and_blocks_the_security(self, conn):
        from sentinel.execution.recovery import blocked_securities
        b = broker()
        b.schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        result = go(b, conn, {"SEC-AAA": D(10)})

        assert result.submitted[0].state is S.UNKNOWN
        stored = journal.in_flight_commands(conn, DEPLOY)
        assert [c.state for c in stored] == [S.UNKNOWN]
        assert blocked_securities(stored) == {"SEC-AAA"}

    def test_the_NEXT_session_resolves_it_rather_than_double_submitting(self, conn):
        """The safety property that matters more than the block itself.

        `execute_session` reconciles first, so the UNKNOWN is resolved against
        the broker before any sizing happens — and the now-visible working order
        counts as committed, leaving nothing to do. A second submit here would
        be the doubled position.
        """
        b = broker()
        b.schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        go(b, conn, {"SEC-AAA": D(10)})

        again = go(b, conn, {"SEC-AAA": D(10)}, p=plan(plan_id="plan-2"))
        assert again.submitted == ()
        assert len([c for c in b.calls if c.startswith("submit:")]) == 1
        assert journal.load_commands(conn, DEPLOY)[0].state is S.ACKNOWLEDGED

    def test_an_UNRESOLVABLE_UNKNOWN_stops_the_session_entirely(self, conn):
        """When the evidence cannot resolve it, the appliance does not proceed
        to size anything — it stays RECONCILING."""
        b = broker()
        b.schedule_submit(F.NEVER_RECEIVED)
        go(b, conn, {"SEC-AAA": D(10)})

        b.schedule_observe(F.TRUNCATED_ORDERS)
        again = go(b, conn, {"SEC-AAA": D(10)}, p=plan(plan_id="plan-2"))
        assert again.runtime_state is RuntimeState.RECONCILING
        assert again.submitted == ()

    def test_nothing_is_submitted_while_the_broker_is_down(self, conn):
        b = broker()
        b.schedule_observe(F.OUTAGE)
        result = go(b, conn, {"SEC-AAA": D(10)})
        assert result.runtime_state is RuntimeState.BROKER_DEGRADED
        assert result.submitted == ()

    def test_reductions_are_sent_before_increases(self, conn):
        b = broker()
        seed_held(conn, b, BBB, 20)
        go(b, conn, {"SEC-AAA": D(10), "SEC-BBB": D(0)})

        submits = [c for c in b.calls if c.startswith("submit:")]
        assert len(submits) == 2
        first = b._by_key(submits[0].split(":", 1)[1])
        assert first.side is Side.SELL, "the sale goes first"

    def test_a_refused_purchase_does_not_prevent_a_sale(self, conn):
        """The asymmetry, exercised end to end: the sale is attempted first and
        the purchase's fate cannot reach back and stop it."""
        b = broker()
        seed_held(conn, b, BBB, 20)
        b.schedule_submit(F.REJECT)          # hits the FIRST submit = the sale
        result = go(b, conn, {"SEC-AAA": D(10), "SEC-BBB": D(0)})

        assert len(result.submitted) == 2, "both attempted regardless"
        by_side = {c.side: c.state for c in result.submitted}
        assert by_side[Side.SELL] is S.REJECTED
        assert by_side[Side.BUY] is S.ACKNOWLEDGED

    def test_FOREIGN_ACTIVITY_blocks_buying_but_not_selling(self, conn):
        b = broker()
        b.seed_foreign_order(BIL, side=Side.BUY, qty="1")
        seed_held(conn, b, BBB, 20)
        result = go(b, conn, {"SEC-AAA": D(10), "SEC-BBB": D(0)})

        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        sides = {c.side for c in result.submitted}
        assert sides == {Side.SELL}, "the sale went; the purchase did not"
        assert "SEC-AAA" in result.refused

    def test_an_UNEXPLAINED_broker_position_is_itself_foreign_activity(self, conn):
        """Seeding the broker WITHOUT the journal is a different scenario, and
        it is worth pinning: the appliance refuses to add exposure while it
        holds something it cannot account for."""
        b = broker()
        b.seed_position(BBB, "20")          # no journal entry: unexplained
        result = go(b, conn, {"SEC-AAA": D(10)})
        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert "SEC-AAA" in result.refused


class TestMissedOpen:
    def test_a_STALE_plan_may_still_de_risk(self, conn):
        b = broker()
        b.seed_position(AAA, "10")
        stale = plan(effective=date(2026, 8, 8))
        result = go(b, conn, {"SEC-AAA": D(0)}, p=stale, today=TODAY)
        assert len(result.submitted) == 1
        assert result.submitted[0].side is Side.SELL

    def test_a_STALE_plan_may_NOT_buy(self, conn):
        """If the appliance was down through 100 -> 0 -> 55 -> 100 it does not
        replay orders it could never have placed."""
        b = broker()
        stale = plan(effective=date(2026, 8, 8))
        result = go(b, conn, {"SEC-AAA": D(10)}, p=stale, today=TODAY)
        assert result.submitted == ()
        assert result.deferred == ("SEC-AAA",)
        assert "DEFERRED" in result.detail

    def test_a_CURRENT_plan_buys_normally(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)}, p=plan(effective=TODAY))
        assert len(result.submitted) == 1

    def test_the_window_predicate_is_inclusive_of_its_own_session(self):
        assert executor.is_execution_window_open(plan(effective=TODAY), TODAY)
        assert not executor.is_execution_window_open(
            plan(effective=date(2026, 8, 10)), TODAY)


class TestRestartConvergence:
    def test_a_crash_after_SEND_PENDING_is_resolved_by_asking_the_broker(self, conn):
        """The whole design in one test.

        The command was accepted and the response never arrived. On restart the
        journal holds a derived key and nothing else — which is enough.
        """
        b = broker()
        b.schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        go(b, conn, {"SEC-AAA": D(10)})
        assert journal.load_commands(conn, DEPLOY)[0].state is S.UNKNOWN

        resolved = run(executor.resolve_outstanding(
            broker=b, conn=conn, deployment=DEPLOY))
        assert [c.state for c in resolved] == [S.ACKNOWLEDGED]
        assert journal.load_commands(conn, DEPLOY)[0].state is S.ACKNOWLEDGED

    def test_a_command_that_NEVER_LANDED_resolves_to_cancelled(self, conn):
        b = broker()
        b.schedule_submit(F.NEVER_RECEIVED)
        go(b, conn, {"SEC-AAA": D(10)})

        resolved = run(executor.resolve_outstanding(
            broker=b, conn=conn, deployment=DEPLOY))
        assert [c.state for c in resolved] == [S.CANCELLED]
        assert journal.in_flight_commands(conn, DEPLOY) == ()

    def test_after_resolution_the_session_retries_and_converges(self, conn):
        b = broker()
        b.schedule_submit(F.NEVER_RECEIVED)
        go(b, conn, {"SEC-AAA": D(10)})
        run(executor.resolve_outstanding(broker=b, conn=conn, deployment=DEPLOY))

        result = go(b, conn, {"SEC-AAA": D(10)}, p=plan(plan_id="plan-2"))
        assert len(result.submitted) == 1
        assert result.submitted[0].state is S.ACKNOWLEDGED

    def test_a_completed_book_asks_for_nothing_further(self, conn):
        b = broker()
        result = go(b, conn, {"SEC-AAA": D(10)})
        b.fill(result.submitted[0].client_key)

        again = go(b, conn, {"SEC-AAA": D(10)}, p=plan(plan_id="plan-2"))
        assert again.submitted == () and not again.refused
