"""#13 — increases are sized against proceeds that have not arrived.

THE FAILURE, written before the fix.

`order_of_operations` puts reductions before increases, and that ordering is
right as far as it goes: a purchase that fails must never consume the budget or
the time a required sale needed. But every delta in the pass is sized against
ONE observation, taken before anything was sent, and then all of them are
submitted back to back:

```text
observe            A: 50 held,  B: 0 held
size               SELL A 50,   BUY B 100
submit SELL A 50   ... still working
submit BUY  B 100  <- sized against a book that no longer exists, funded by
                      proceeds that have not settled
```

Two things go wrong, and they are different.

**The money.** The buy assumes the sale's proceeds. If the sale is partial, or
still working, or came back UNKNOWN, the purchase is funded by margin — which
the long-only unlevered envelope exists to exclude, and which the broker will
happily provide.

**The quantity.** Anything that changes the book between the two submissions is
invisible to the second one. A foreign fill, a working order the broker closed
`done_for_day`, an over-fill on the sale — each makes `desired - held -
committed` a stale arithmetic, and the exact-delta machinery that exists to make
convergence exact silently converges to the wrong number.

THE PROPERTY BEING BOUGHT: **an increase is sized against an observation taken
after the reductions have settled.** Not "reductions are submitted first" —
submitted is not settled, and the whole failure lives in that gap.

And when that fresh observation cannot be had — the reductions are still in
flight past the settle budget, or the read comes back incomplete — the increases
are DEFERRED rather than sized against the stale one. That is §13.1's asymmetry
applied where it belongs: buying late is opportunity cost, buying wrong is not.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import executor as E  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.commands import Command  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, Side,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import FaultKind, SimulatedBroker  # noqa: E402
from sentinel.execution.states import (  # noqa: E402
    CommandState as CS, RuntimeState,
)
from sentinel.feed import store as feed_store  # noqa: E402

D = Decimal
DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
TODAY = dt.date(2026, 8, 11)

AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA")
BBB = BrokerInstrument(security_id="SEC-BBB", symbol="BBB")
INSTRUMENTS = {"SEC-AAA": AAA, "SEC-BBB": BBB}


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
                  "sentinel_observations",
                  "sentinel_terminal_recovery_watermark"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    schema.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    yield c
    c.close()


def broker(**kw):
    return SimulatedBroker(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"),
                           **kw)


def fill_everything_resting(sim):
    """What a real settle looks like: the working orders complete."""
    for order in list(sim._orders.values()):
        if order.client_key and order.remaining > 0:
            sim.fill(order.client_key)


def settles_on_the_second_read(sim_hook=None):
    """A hook script: the FIRST observe is the pre-trade read, the SECOND is
    the settle poll, and the sale completes at the second one."""
    def during_settle(sim):
        fill_everything_resting(sim)
        if sim_hook is not None:
            sim_hook(sim)
    return [None, during_settle]


def a_plan(basket, pid="plan-1", *, unpriced=()):
    return ExecutionPlan(plan_id=pid, decision_session=TODAY,
                         effective_session=TODAY, target_exposure=D(1),
                         target_basket={k: D(v) for k, v in basket.items()},
                         data_version=1,
                         unpriced_securities=tuple(unpriced))


def seed_held(conn, b, instrument, qty, *, plan_id="plan-0"):
    """A holding Sentinel KNOWS it owns: broker position AND journal entry.

    Seeding only the broker side is a different scenario — an unexplained
    position is foreign activity, and the appliance correctly refuses to
    increase exposure while one exists. Getting this wrong makes a test look
    like it exercises ordering when it exercises the foreign-activity block.
    """
    b.seed_position(instrument, str(qty))
    journal.save_command(conn, Command(
        identity=CommandIdentity(deployment=DEPLOY, plan_id=plan_id,
                                 security_id=instrument.security_id),
        instrument=instrument, side=Side.BUY, quantity=D(qty),
        state=CS.FILLED, filled_quantity=D(qty)))


def run(conn, b, plan, **kw):
    E.adopt_plan(conn, plan)
    return asyncio.run(E.execute_session(
        broker=b, conn=conn, deployment=DEPLOY, plan=plan,
        instruments=INSTRUMENTS, today=TODAY, **kw))


def restart_run(pg, b, plan, **kw):
    """A second process: no Python state survives, only broker + Postgres."""
    restarted = feed_store.connect(pg.sync_dsn)
    try:
        return run(restarted, b, plan, **kw)
    finally:
        restarted.close()


def submits(b):
    """(security_id, quantity) per submission, in order."""
    out = []
    for key in [c.split(":", 1)[1] for c in b.calls if c.startswith("submit:")]:
        order = b._by_key(key)
        out.append((order.instrument.security_id, str(order.quantity)))
    return out


def phase_of(b, security_id: str) -> int:
    """How many POSITION reads preceded this security's submission.

    The defect is entirely about sequence — which observation each order was
    sized against — and a sequence claim can only be checked against a
    sequence. Counting reads would pass a fix that observed twice and still
    sized both phases from the first read.
    """
    seen = 0
    for call in b.calls:
        if call == "get_positions":
            seen += 1
        elif call.startswith("submit:"):
            if b._by_key(call.split(":", 1)[1]).instrument.security_id == security_id:
                return seen
    raise AssertionError(f"{security_id} was never submitted: {b.calls}")


class TestSimulatedCashReservations:
    def test_two_working_buys_cannot_spend_the_same_cash(self):
        b = broker(equity=D("100"), cash=D("100"), buying_power=D("100"))

        first = asyncio.run(b.submit(
            client_key="buy-a", instrument=AAA,
            side=Side.BUY, quantity=D(1)))
        blocked = asyncio.run(b.submit(
            client_key="buy-b", instrument=BBB,
            side=Side.BUY, quantity=D(1)))

        assert first.state is CS.ACKNOWLEDGED
        assert blocked.state is CS.REJECTED
        assert b._by_key("buy-b") is None

        # Terminal cancellation releases the first reservation.  Exactly one
        # replacement may then spend the $100, and filling it cannot drive the
        # simulated cash account negative.
        asyncio.run(b.cancel(first.broker_order_id))
        replacement = asyncio.run(b.submit(
            client_key="buy-b-retry", instrument=BBB,
            side=Side.BUY, quantity=D(1)))
        assert replacement.state is CS.ACKNOWLEDGED

        b.fill("buy-b-retry")
        assert b.cash == b.buying_power == D(0)


class TestTheFailure:
    def test_the_BUY_is_sized_after_the_SELL_has_SETTLED(self, conn):
        """The headline, stated as a sequence.

        Not "the sell was submitted first" — it always was. The buy must be
        sized against a read taken AFTER the sell stopped being outstanding.
        """
        b = broker(observe_hooks=settles_on_the_second_read())
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}))

        assert phase_of(b, "SEC-AAA") < phase_of(b, "SEC-BBB"), (
            f"the buy was sized against the same observation as the sell: "
            f"{b.calls}")
        assert len(result.submitted) == 2

    def test_filled_but_unsettled_cash_defers_the_buy(self, conn):
        """Position settlement is not cash buying-power settlement."""
        def withhold_proceeds(sim):
            sim.buying_power = sim.cash - D("5000")

        b = broker(
            buying_power=D("100000"),
            observe_hooks=settles_on_the_second_read(withhold_proceeds))
        seed_held(conn, b, AAA, 50)

        async def cash_authority(_observation):
            account = await b.account_snapshot()
            if account.buying_power != account.cash:
                raise RuntimeError("cash-only settlement is not observable")

        result = run(
            conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
            increase_authority=cash_authority)

        assert [sid for sid, _ in submits(b)] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        assert "cash-only settlement" in result.detail

    def test_a_FOREIGN_fill_BETWEEN_the_phases_is_seen(self, conn):
        """The quantity, concretely.

        The account is sold down; while that happens, 30 shares of B arrive
        from somewhere else — a transfer, a manual order, a stale intent that
        finally filled. Desired is 100.

            single phase   sized against the pre-sale read: BUY 100,
                           leaving 130 for a 100 target
            two phase      sized against the post-settle read: BUY 70
        """
        # The 30 shares land during the settle — between the two reads.
        b = broker(observe_hooks=settles_on_the_second_read(
            lambda sim: seed_held(conn, sim, BBB, 30, plan_id="plan-foreign")))
        seed_held(conn, b, AAA, 50)

        run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}))

        buys = [q for sid, q in submits(b) if sid == "SEC-BBB"]
        assert buys == ["70"], (
            f"bought {buys} on top of 30 already held, for a 100 target")

    def test_convergence_is_EXACT(self, conn):
        b = broker(observe_hooks=settles_on_the_second_read(
            lambda sim: seed_held(conn, sim, BBB, 30, plan_id="plan-foreign")))
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}))
        for command in result.submitted:
            b.fill(command.client_key)

        held = asyncio.run(b.observe()).positions_by_security()
        assert held.get("SEC-BBB") == D("100")
        assert held.get("SEC-AAA", D(0)) == D("0")


class TestTheAsymmetryWhenTheSETTLEFails:
    def test_an_UNSETTLED_reduction_defers_the_increase(self, conn):
        """Submitted is not settled. A sale still working past the settle
        budget means the proceeds are not there, and a purchase funded by them
        is funded by margin — which the long-only unlevered envelope exists to
        exclude and which the broker will happily provide."""
        b = broker()   # nothing fills; the sale stays working
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=2)

        assert [sid for sid, _ in submits(b)] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        assert "settle" in result.detail.lower()

    def test_the_REDUCTION_still_went_out(self, conn):
        """De-risking is never blocked by what blocks buying. That is the
        asymmetry, and inverting it is the expensive direction."""
        b = broker()   # nothing fills; the sale stays working
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=2)
        assert len(result.submitted) == 1
        assert result.submitted[0].security_id == "SEC-AAA"
        assert result.submitted[0].state is not CS.REJECTED

    def test_an_INCOMPLETE_settle_read_does_not_count_as_settled(self, conn):
        """The other half of the settle condition, and the half that is easy to
        leave out — it was, until a mutation of the implementation went green
        with the check removed.

        The sale DOES complete during this read, so a naive "is it still
        working?" test answers no and calls it settled. But the read that
        answered is INCONSISTENT — a fill landed between the orders read and
        the positions read, which is invariant 21's hazard — so it establishes
        nothing. An unreliable read cannot prove proceeds exist.
        """
        b = broker()
        seed_held(conn, b, AAA, 50)
        # One cycle only, and that cycle's read is made inconsistent by a fill
        # landing mid-read. With the COMPLETE guard: deferred. Without it: the
        # buy is sized against a read that authorises nothing.
        b.observe_hooks = [None, lambda sim: setattr(
            sim, "fill_between_reads", fill_everything_resting)]

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [sid for sid, _ in submits(b)] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred

    def test_a_pure_BUY_session_pays_for_no_extra_settle(self, conn):
        """The second read exists to see the proceeds. With nothing sold there
        are none, and an unconditional extra round trip is latency for
        nothing."""
        b = broker()
        result = run(conn, b, a_plan({"SEC-BBB": "100"}))

        assert len(result.submitted) == 1
        assert b.calls.count("get_positions") <= 2, b.calls


class TestOnlyReconciledFillsCanFundIncreases:
    @pytest.mark.parametrize(
        ("fault", "terminal_state"),
        [
            (FaultKind.REJECT, CS.REJECTED),
            (FaultKind.NEVER_RECEIVED, CS.CANCELLED),
        ],
        ids=["rejected", "unknown-never-landed"],
    )
    def test_a_reduction_without_a_fill_cannot_fund_a_buy(
            self, conn, fault, terminal_state):
        """Terminal does not mean FILLED. A rejected or never-landed sale is
        no longer working, but it produced no proceeds."""
        b = broker(submit_faults=[fault])
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [command.security_id for command in result.submitted] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        reduction = journal.load_commands(conn, DEPLOY, plan_id="plan-1")[0]
        assert reduction.state is terminal_state
        assert reduction.filled_quantity == D(0)

    def test_an_UNKNOWN_reduction_is_resolved_again_between_phases(self, conn):
        """The timeout may conceal a live sale. Reconciliation must resolve
        its exact key, then still wait for a full observed fill before buying."""
        b = broker(submit_faults=[FaultKind.ACCEPT_THEN_TIMEOUT])
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [command.security_id for command in result.submitted] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        reduction = journal.load_commands(conn, DEPLOY, plan_id="plan-1")[0]
        assert reduction.state is CS.ACKNOWLEDGED
        assert f"find:{reduction.client_key}" in b.calls

    def test_a_PARTIAL_reduction_cannot_fund_the_whole_buy(self, conn):
        def partly_fill_sale(sim):
            sale = next(o for o in sim._orders.values()
                        if o.instrument.security_id == "SEC-AAA")
            sim.fill(sale.client_key, "25")

        b = broker(observe_hooks=[None, partly_fill_sale])
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [command.security_id for command in result.submitted] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        reduction = journal.load_commands(conn, DEPLOY, plan_id="plan-1")[0]
        assert reduction.state is CS.PARTIALLY_FILLED
        assert reduction.filled_quantity == D(25)

    def test_a_CANCELLED_reduction_cannot_fund_a_buy(self, conn):
        def cancel_sale(sim):
            sale = next(o for o in sim._orders.values()
                        if o.instrument.security_id == "SEC-AAA")
            sale.state = CS.CANCELLED

        b = broker(observe_hooks=[None, cancel_sale])
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [sid for sid, _ in submits(b)] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        reduction = journal.load_commands(conn, DEPLOY, plan_id="plan-1")[0]
        assert reduction.state is CS.CANCELLED
        assert reduction.filled_quantity == D(0)

    def test_an_ABSENT_reduction_cannot_fund_a_buy(self, conn):
        """Ordinary acknowledged commands do not infer a terminal state from
        absence. Phase two must therefore keep the command UNKNOWN and reject
        the increase."""
        def lose_sale(sim):
            sim._orders.clear()

        b = broker(observe_hooks=[None, lose_sale])
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [command.security_id for command in result.submitted] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        reduction = journal.load_commands(conn, DEPLOY, plan_id="plan-1")[0]
        # Open-order silence cannot establish FILLED/CANCELLED/REJECTED.  The
        # exact lookup also found no positive terminal evidence, so the durable
        # command becomes UNKNOWN and continues to block every increase.
        assert reduction.state is CS.UNKNOWN


class TestTheReductionBarrierSurvivesRestart:
    @pytest.mark.parametrize(
        "submit_fault",
        [None, FaultKind.ACCEPT_THEN_TIMEOUT],
        ids=["ordinary-ack", "timeout-resolved-to-ack"],
    )
    def test_a_working_SELL_netted_to_zero_still_blocks_the_BUY(
            self, conn, pg, submit_fault):
        """On restart, held + committed SELL equals the zero target.

        The freshly computed AAA delta is therefore NONE.  The durable working
        reduction must nevertheless remain a global barrier for the unrelated
        BBB increase until a complete reconciliation observes the sale FILLED.
        """
        faults = [] if submit_fault is None else [submit_fault]
        b = broker(submit_faults=faults)
        seed_held(conn, b, AAA, 50)
        plan = a_plan({"SEC-AAA": "0", "SEC-BBB": "100"})

        first = run(conn, b, plan, settle_cycles=1)
        sale = first.submitted[0]
        assert sale.security_id == "SEC-AAA"
        assert "SEC-BBB" in first.deferred
        assert journal.load_commands(
            conn, DEPLOY, plan_id=plan.plan_id)[0].state is CS.ACKNOWLEDGED

        b.calls.clear()
        second = restart_run(pg, b, plan, settle_cycles=1)

        assert second.submitted == ()
        assert "SEC-BBB" in second.deferred
        assert not any(call.startswith("submit:") for call in b.calls)

        b.fill(sale.client_key)
        b.calls.clear()
        after_fill = restart_run(pg, b, plan, settle_cycles=1)

        assert [command.security_id for command in after_fill.submitted] == [
            "SEC-BBB"]
        assert [sid for sid, _ in submits(b)] == ["SEC-BBB"]

    def test_a_PARTIAL_SELL_netted_to_zero_survives_restart_as_a_barrier(
            self, conn, pg):
        b = broker()
        seed_held(conn, b, AAA, 50)
        plan = a_plan({"SEC-AAA": "0", "SEC-BBB": "100"})

        first = run(conn, b, plan, settle_cycles=1)
        sale = first.submitted[0]
        b.fill(sale.client_key, "25")

        b.calls.clear()
        second = restart_run(pg, b, plan, settle_cycles=1)

        assert second.submitted == ()
        assert "SEC-BBB" in second.deferred
        stored = journal.load_commands(
            conn, DEPLOY, plan_id=plan.plan_id)[0]
        assert stored.state is CS.PARTIALLY_FILLED
        assert stored.filled_quantity == D("25")
        assert not any(call.startswith("submit:") for call in b.calls)

        b.fill(sale.client_key)
        b.calls.clear()
        after_fill = restart_run(pg, b, plan, settle_cycles=1)

        assert [command.security_id for command in after_fill.submitted] == [
            "SEC-BBB"]

    def test_a_smaller_old_SELL_does_not_satisfy_a_blocked_new_SELL(
            self, conn, pg):
        """An existing sale can be both real and insufficient.

        Fifty AAA are held and this plan already has a working SELL 20, so its
        zero target still needs another SELL 30.  The overlap guard correctly
        refuses that second sale.  Even if the old 20 fills during the settle
        poll, it must not be mistaken for the missing 30; BBB remains deferred.
        """
        b = broker()
        seed_held(conn, b, AAA, 50)
        current = a_plan(
            {"SEC-AAA": "0", "SEC-BBB": "100"}, pid="current-plan")
        E.adopt_plan(conn, current)
        identity = CommandIdentity(
            deployment=DEPLOY, plan_id=current.plan_id,
            security_id=AAA.security_id)
        outcome = asyncio.run(b.submit(
            client_key=identity.client_key, instrument=AAA,
            side=Side.SELL, quantity=D("20")))
        journal.save_command(conn, Command(
            identity=identity, instrument=AAA, side=Side.SELL,
            quantity=D("20"), state=outcome.state,
            broker_order_id=outcome.broker_order_id))
        b.observe_hooks = [None, fill_everything_resting]
        b.calls.clear()
        result = restart_run(pg, b, current, settle_cycles=1)

        assert result.submitted == ()
        assert "SEC-AAA" in result.refused
        assert "SEC-BBB" in result.deferred
        assert not any(call.startswith("submit:") for call in b.calls)
        commands = journal.load_commands(conn, DEPLOY)
        assert [(command.identity.plan_id, command.security_id,
                 command.quantity, command.state)
                for command in commands if command.side is Side.SELL] == [
                    ("current-plan", "SEC-AAA", D("20"), CS.ACKNOWLEDGED)]


class TestUnavailablePriceAuthorityIsOneWay:
    def test_a_cancelled_preservation_BUY_does_not_become_a_fresh_BUY(self, conn):
        """The plan preserved a wanted, unpriced name while a BUY was working.

        If that order later cancels, `desired - held - committed` becomes a
        positive delta.  Preservation is not price authority for a replacement
        order, so the executor must refuse instead of blindly restoring it.
        """
        b = broker()
        priced = a_plan({"SEC-AAA": "100"}, pid="priced-plan")
        original = run(conn, b, priced)
        working_buy = original.submitted[0]
        resting = b._by_key(working_buy.client_key)
        assert resting is not None and resting.state is CS.ACKNOWLEDGED

        # This is the evidence the unpriced plan was prepared from: the wanted
        # quantity was preserved entirely by the still-working BUY.  It cancels
        # before execution's fresh observation, exposing a new BUY delta.
        unpriced = a_plan(
            {"SEC-AAA": "100"}, pid="unpriced-plan",
            unpriced=("SEC-AAA",))
        resting.state = CS.CANCELLED
        b.calls.clear()

        result = run(conn, b, unpriced)

        assert result.submitted == ()
        assert "SEC-AAA" in result.refused
        assert "unpriced" in result.refused["SEC-AAA"].lower()
        assert not any(call.startswith("submit:") for call in b.calls)

    def test_an_unpriced_name_may_still_be_reduced(self, conn):
        b = broker()
        seed_held(conn, b, AAA, 50)
        plan = a_plan(
            {"SEC-AAA": "0"}, unpriced=("SEC-AAA",))

        result = run(conn, b, plan)

        assert [(command.security_id, command.side, command.quantity)
                for command in result.submitted] == [
                    ("SEC-AAA", Side.SELL, D("50"))]
        assert "SEC-AAA" not in result.refused


class TestSamePlanCommandRevisionRecovery:
    @staticmethod
    def commands(conn, plan, security_id="SEC-BBB"):
        return sorted(
            (command for command in journal.load_commands(
                conn, DEPLOY, plan_id=plan.plan_id)
             if command.security_id == security_id),
            key=lambda command: command.identity.revision)

    def test_an_identical_PLANNED_crash_remnant_reuses_revision_zero(
            self, conn, pg):
        b = broker()
        plan = a_plan({"SEC-BBB": "100"})
        E.adopt_plan(conn, plan)
        planned = Command(
            identity=CommandIdentity(
                deployment=DEPLOY, plan_id=plan.plan_id,
                security_id=BBB.security_id),
            instrument=BBB, side=Side.BUY, quantity=D("100"))
        journal.save_command(conn, planned)

        result = restart_run(pg, b, plan)

        assert len(result.submitted) == 1
        assert result.submitted[0].client_key == planned.client_key
        assert result.submitted[0].identity.revision == 0
        assert len(self.commands(conn, plan)) == 1
        assert [event["to"] for event in journal.command_history(
            conn, planned.client_key)] == [
                "PLANNED", "SEND_PENDING", "ACKNOWLEDGED"]

    def test_a_changed_PLANNED_remnant_is_superseded_not_rewritten(
            self, conn, pg):
        b = broker()
        plan = a_plan({"SEC-BBB": "100"})
        E.adopt_plan(conn, plan)
        stale = Command(
            identity=CommandIdentity(
                deployment=DEPLOY, plan_id=plan.plan_id,
                security_id=BBB.security_id),
            instrument=BBB, side=Side.BUY, quantity=D("50"))
        journal.save_command(conn, stale)

        result = restart_run(pg, b, plan)

        replacement = result.submitted[0]
        assert replacement.identity.revision == 1
        assert replacement.quantity == D("100")
        assert replacement.client_key != stale.client_key
        old, new = self.commands(conn, plan)
        assert (old.identity.revision, old.state,
                old.quantity) == (0, CS.SUPERSEDED, D("50"))
        assert (new.identity.revision, new.state,
                new.quantity) == (1, CS.ACKNOWLEDGED, D("100"))

    def test_a_CANCELLED_command_is_not_resurrected_on_restart(self, conn, pg):
        b = broker()
        plan = a_plan({"SEC-BBB": "100"})
        first = run(conn, b, plan)
        original = first.submitted[0]
        b._by_key(original.client_key).state = CS.CANCELLED

        result = restart_run(pg, b, plan)

        replacement = result.submitted[0]
        assert replacement.identity.revision == 1
        assert replacement.client_key != original.client_key
        old, new = self.commands(conn, plan)
        assert (old.identity.revision, old.state) == (0, CS.CANCELLED)
        assert (new.identity.revision, new.state) == (1, CS.ACKNOWLEDGED)
        assert [event["to"] for event in journal.command_history(
            conn, original.client_key)] == [
                "PLANNED", "SEND_PENDING", "ACKNOWLEDGED", "CANCELLED"]

    def test_a_REJECTED_command_is_not_resurrected_on_restart(self, conn, pg):
        b = broker(submit_faults=[FaultKind.REJECT])
        plan = a_plan({"SEC-BBB": "100"})
        first = run(conn, b, plan)
        original = first.submitted[0]
        assert original.state is CS.REJECTED

        result = restart_run(pg, b, plan)

        replacement = result.submitted[0]
        assert replacement.identity.revision == 1
        assert replacement.client_key != original.client_key
        old, new = self.commands(conn, plan)
        assert (old.identity.revision, old.state) == (0, CS.REJECTED)
        assert (new.identity.revision, new.state) == (1, CS.ACKNOWLEDGED)
        assert [event["to"] for event in journal.command_history(
            conn, original.client_key)] == [
                "PLANNED", "SEND_PENDING", "REJECTED"]

    def test_a_PARTIAL_then_CANCELLED_command_restarts_at_remaining_revision(
            self, conn, pg):
        b = broker()
        plan = a_plan({"SEC-BBB": "100"})
        first = run(conn, b, plan)
        original = first.submitted[0]
        b.fill(original.client_key, "40")

        at_partial_boundary = restart_run(pg, b, plan)
        assert at_partial_boundary.submitted == ()
        partial, = self.commands(conn, plan)
        assert partial.state is CS.PARTIALLY_FILLED
        assert partial.filled_quantity == D("40")

        b._by_key(original.client_key).state = CS.CANCELLED
        result = restart_run(pg, b, plan)

        replacement = result.submitted[0]
        assert replacement.identity.revision == 1
        assert replacement.quantity == D("60")
        assert replacement.client_key != original.client_key
        old, new = self.commands(conn, plan)
        assert (old.identity.revision, old.state,
                old.filled_quantity) == (0, CS.CANCELLED, D("40"))
        assert (new.identity.revision, new.state,
                new.quantity) == (1, CS.ACKNOWLEDGED, D("60"))


class TestPhaseTwoReconcilesTheWorldAgain:
    def test_FOREIGN_activity_arriving_between_phases_blocks_the_buy(self, conn):
        def fill_then_add_foreign_position(sim):
            fill_everything_resting(sim)
            sim.seed_position(BBB, "30")

        b = broker(observe_hooks=[None, fill_then_add_foreign_position])
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                     settle_cycles=1)

        assert [sid for sid, _ in submits(b)] == ["SEC-AAA"]
        assert "SEC-BBB" in result.deferred
        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert result.reconciliation is not None
        assert not result.reconciliation.clean

    def test_account_identity_is_rechecked_between_phases(self, conn):
        b = broker(observe_hooks=settles_on_the_second_read())
        seed_held(conn, b, AAA, 50)

        # Initial reconcile, reduction authorisation and increase pre-flight
        # each identify the account. The fourth check is the fresh phase-two
        # reconciliation; make only that check see the switched account.
        original_identify = b.identify_account
        identify_calls = 0

        async def identify_account():
            nonlocal identify_calls
            identify_calls += 1
            if identify_calls == 4:
                b.account = BrokerAccountIdentity("sim", "OTHER-ACCOUNT")
            return await original_identify()

        b.identify_account = identify_account

        with pytest.raises(B.AccountMismatch):
            run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}),
                settle_cycles=1)

        submitted = journal.load_commands(conn, DEPLOY, plan_id="plan-1")
        assert [command.security_id for command in submitted] == ["SEC-AAA"]


class TestNothingIsSubmittedTwice:
    def test_a_security_that_only_REDUCES_is_not_revisited(self, conn):
        """The re-size must not re-open a delta phase one already satisfied.
        The fresh read shows the position gone, so a naive re-size computes
        NONE — but a fix that re-ran the whole delta set against the new read
        without excluding phase one's work would find the sale's own fill and
        act on it."""
        b = broker(observe_hooks=settles_on_the_second_read())
        seed_held(conn, b, AAA, 50)

        result = run(conn, b, a_plan({"SEC-AAA": "0"}))
        assert [sid for sid, _ in submits(b)] == ["SEC-AAA"]
        assert len(result.submitted) == 1

    def test_one_command_per_security_per_plan(self, conn):
        b = broker(observe_hooks=settles_on_the_second_read(
            lambda sim: seed_held(conn, sim, BBB, 30, plan_id="plan-foreign")))
        seed_held(conn, b, AAA, 50)
        run(conn, b, a_plan({"SEC-AAA": "0", "SEC-BBB": "100"}))

        with conn.cursor() as cur:
            cur.execute("SELECT security_id, COUNT(*) FROM sentinel_commands"
                        " WHERE plan_id = %s GROUP BY security_id", ("plan-1",))
            assert all(n == 1 for _, n in cur.fetchall())
