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
from sentinel.execution.simulator import SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState as CS  # noqa: E402
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
                  "sentinel_observations"):
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


def a_plan(basket, pid="plan-1"):
    return ExecutionPlan(plan_id=pid, decision_session=TODAY,
                         effective_session=TODAY, target_exposure=D(1),
                         target_basket={k: D(v) for k, v in basket.items()},
                         data_version=1)


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
