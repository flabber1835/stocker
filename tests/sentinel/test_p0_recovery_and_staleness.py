"""Two P0 defects from the multi-day-outage review, and their falsifiers.

P0-1  SEND_PENDING had no recovery path. The entire crash-safety design is
      "persist SEND_PENDING, then call the broker", so a SIGKILL in that window
      leaves exactly that state in the journal BY CONSTRUCTION — and recovery
      resolved only UNKNOWN. The one window the state exists to make
      recoverable was the one window nothing recovered.

P0-2  a stale plan could still de-risk, and nothing checked whether it was
      still WANTED. Monday says 0%, the broker is down; Wednesday the target is
      100% and the broker returns. Retry Monday's plan and the executor is
      authorised to liquidate the book — the exact inverse of convergence.

The shared lesson is that "late" and "obsolete" are different questions, and
only one of them may authorise a trade.
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

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import (  # noqa: E402
    executor, journal, reconcile as R, recovery)
from sentinel.execution.commands import Command  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import FaultKind as F, SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState as S  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")
MON, WED = date(2026, 8, 10), date(2026, 8, 12)

STATE_TABLES = ("sentinel_account_binding", "sentinel_ownership_events",
                "sentinel_commands", "sentinel_command_events",
                "sentinel_execution_plans", "sentinel_fills",
                "sentinel_observations",
                "sentinel_terminal_recovery_watermark")


def run(coro):
    return asyncio.run(coro)


def D(x):
    return Decimal(str(x))


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
        for t in STATE_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    schema.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    yield c
    c.close()


def broker():
    return SimulatedBroker(account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))


def plan(plan_id, basket, *, exposure="1", effective=WED):
    return ExecutionPlan(plan_id=plan_id, decision_session=effective,
                         effective_session=effective,
                         target_exposure=D(exposure), target_basket=basket,
                         data_version=1)


def go(b, conn, p, today=WED):
    executor.adopt_plan(conn, p)
    return run(executor.execute_session(
        broker=b, conn=conn, deployment=DEPLOY, plan=p,
        instruments={"SEC-AAA": AAA}, today=today))


# ===========================================================================
# P0-1 — SEND_PENDING is recoverable
# ===========================================================================

class TestP0SendPendingRecovery:
    def _killed_mid_send(self, conn, b, *, landed: bool):
        """A journal in the exact state a SIGKILL in the send window leaves.

        Written directly rather than by killing a process: the point under test
        is that RECOVERY handles the state, and the state is fully determined by
        the persist-before-send ordering.
        """
        identity = CommandIdentity(deployment=DEPLOY, plan_id="plan-1",
                                   security_id="SEC-AAA")
        cmd = Command(identity=identity, instrument=AAA, side=Side.BUY,
                      quantity=D(100))
        journal.save_command(conn, cmd)
        pending = cmd.transition(S.SEND_PENDING)
        journal.save_command(conn, pending, previous=S.PLANNED)
        if landed:
            # The broker accepted it; the response never came back.
            run(b.submit(client_key=cmd.client_key, instrument=AAA,
                         side=Side.BUY, quantity=D(100)))
        return pending

    def test_SEND_PENDING_is_in_the_INDETERMINATE_set(self):
        assert S.SEND_PENDING in recovery.INDETERMINATE
        assert S.UNKNOWN in recovery.INDETERMINATE

    def test_a_landed_order_is_ADOPTED_not_left_pending_forever(self, conn):
        """The broker owns 100 shares and the journal says SEND_PENDING. Before
        the fix there was no path from here."""
        b = broker()
        self._killed_mid_send(conn, b, landed=True)

        resolved = run(executor.resolve_outstanding(
            broker=b, conn=conn, deployment=DEPLOY))
        assert [c.state for c in resolved] == [S.ACKNOWLEDGED]
        assert journal.load_commands(conn, DEPLOY)[0].state is S.ACKNOWLEDGED

    def test_an_order_that_never_landed_resolves_to_cancelled(self, conn):
        b = broker()
        self._killed_mid_send(conn, b, landed=False)

        resolved = run(executor.resolve_outstanding(
            broker=b, conn=conn, deployment=DEPLOY))
        assert [c.state for c in resolved] == [S.CANCELLED]

    def test_reconciliation_resolves_it_too_not_only_the_boot_path(self, conn):
        b = broker()
        self._killed_mid_send(conn, b, landed=True)

        rec = run(R.reconcile(broker=b, conn=conn, binding=None,
                              deployment=DEPLOY))
        assert journal.load_commands(conn, DEPLOY)[0].state is S.ACKNOWLEDGED
        assert rec.unresolved == ()

    def test_the_history_says_HOW_it_was_resolved(self, conn):
        """A SEND_PENDING found at rest is promoted to UNKNOWN before being
        resolved, so the journal reads: pending, therefore undetermined,
        therefore asked. Collapsing that would lose why the appliance
        distrusted its own record."""
        b = broker()
        cmd = self._killed_mid_send(conn, b, landed=True)
        run(executor.resolve_outstanding(broker=b, conn=conn,
                                         deployment=DEPLOY))

        states = [h["to"] for h in journal.command_history(conn, cmd.client_key)]
        assert states == ["PLANNED", "SEND_PENDING", "UNKNOWN", "ACKNOWLEDGED"]

    def test_it_BLOCKS_an_overlapping_command_until_resolved(self, conn):
        """While pending it is in-flight, so nothing else may touch the
        security — the crash must not open a second position either."""
        b = broker()
        self._killed_mid_send(conn, b, landed=True)
        stored = journal.in_flight_commands(conn, DEPLOY)
        assert [c.state for c in stored] == [S.SEND_PENDING]
        assert recovery.blocked_securities(stored) == {"SEC-AAA"}

    def test_a_TRUNCATED_read_may_not_declare_it_never_landed(self, conn):
        b = broker()
        self._killed_mid_send(conn, b, landed=False)
        b.schedule_observe(F.TRUNCATED_ORDERS)

        resolved = run(executor.resolve_outstanding(
            broker=b, conn=conn, deployment=DEPLOY))
        assert resolved == (), "unresolved rather than wrongly cancelled"
        # It does NOT stay SEND_PENDING: the promotion to UNKNOWN is persisted
        # first, so the record now says the outcome is undetermined rather than
        # still claiming a send is in progress. Either way it keeps blocking,
        # and a COMPLETE read is still required before anything concludes.
        assert journal.load_commands(conn, DEPLOY)[0].state is S.UNKNOWN


# ===========================================================================
# P0-2 — only the current plan may execute
# ===========================================================================

class TestP0LatestPlanOnly:
    def test_MONDAY_ZERO_CANNOT_LIQUIDATE_ON_WEDNESDAY(self, conn):
        """The scenario in full, and the reason this is a P0.

        Monday wanted 0% and the broker was down. By Wednesday the controller
        wants 100%. Replaying Monday's plan would sell everything — while
        Wednesday's buys are deferred for being outside their window — producing
        the exact opposite of convergence.
        """
        b = broker()
        held = plan("plan-fri", {"SEC-AAA": D(100)}, effective=date(2026, 8, 7))
        go(b, conn, held, today=date(2026, 8, 7))
        b.fill(journal.load_commands(conn, DEPLOY)[0].client_key)

        monday_zero = plan("plan-mon", {}, exposure="0", effective=MON)
        executor.adopt_plan(conn, monday_zero)

        wednesday_full = plan("plan-wed", {"SEC-AAA": D(100)}, effective=WED)
        executor.adopt_plan(conn, wednesday_full)   # supersedes Monday's

        submits_before = len([c for c in b.calls if c.startswith("submit:")])
        with pytest.raises(executor.StalePlanRefused, match="superseded"):
            run(executor.execute_session(
                broker=b, conn=conn, deployment=DEPLOY, plan=monday_zero,
                instruments={"SEC-AAA": AAA}, today=WED))

        assert len([c for c in b.calls if c.startswith("submit:")]) \
            == submits_before, "not one order from the obsolete plan"

    def test_the_CURRENT_plan_still_executes_normally(self, conn):
        b = broker()
        result = go(b, conn, plan("plan-wed", {"SEC-AAA": D(100)}))
        assert len(result.submitted) == 1

    def test_adopting_a_plan_supersedes_every_other(self, conn):
        """Catch-up replaying five missed sessions produces five plans; only
        the last describes what is wanted now."""
        for i, day in enumerate([date(2026, 8, 8), date(2026, 8, 9), MON]):
            executor.adopt_plan(conn, plan(f"plan-{i}", {}, exposure="0",
                                           effective=day))
        latest = executor.adopt_plan(conn, plan("plan-now", {"SEC-AAA": D(10)}))

        assert journal.latest_plan(conn).plan_id == "plan-now"
        assert latest.superseded_by is None

        # A CHAIN, not a star: each plan is superseded by the one that replaced
        # it. That keeps the order of intent readable — "plan-0 was replaced by
        # plan-1" is a fact worth having, and collapsing every arrow onto the
        # final plan would erase the sequence. What matters for safety is that
        # none of them is the latest, and none may execute.
        assert journal.load_plan(conn, "plan-0").superseded_by == "plan-1"
        assert journal.load_plan(conn, "plan-1").superseded_by == "plan-2"
        assert journal.load_plan(conn, "plan-2").superseded_by == "plan-now"
        for i in range(3):
            assert journal.load_plan(conn, f"plan-{i}").is_superseded

    def test_an_UNPERSISTED_plan_is_refused(self, conn):
        """The executor runs the DURABLE current plan, not whatever it was
        handed — an in-memory plan cannot be shown to be the latest."""
        b = broker()
        with pytest.raises(executor.StalePlanRefused, match="not persisted"):
            run(executor.execute_session(
                broker=b, conn=conn, deployment=DEPLOY,
                plan=plan("ghost", {"SEC-AAA": D(10)}),
                instruments={"SEC-AAA": AAA}, today=WED))

    def test_a_plan_that_DIFFERS_from_its_stored_record_is_refused(self, conn):
        """Same id, different economics. The client keys derive from the id, so
        the wire and the journal would disagree about what is being attempted."""
        b = broker()
        stored = plan("plan-wed", {"SEC-AAA": D(100)})
        executor.adopt_plan(conn, stored)

        with pytest.raises(executor.StalePlanRefused, match="does not match"):
            run(executor.execute_session(
                broker=b, conn=conn, deployment=DEPLOY,
                plan=replace(stored, target_basket={"SEC-AAA": D(999)}),
                instruments={"SEC-AAA": AAA}, today=WED))

    def test_re_adopting_the_current_plan_is_idempotent(self, conn):
        """A restart mid-session re-derives the same plan; that must not count
        as a new intent."""
        p = plan("plan-wed", {"SEC-AAA": D(10)})
        executor.adopt_plan(conn, p)
        executor.adopt_plan(conn, p)
        assert journal.latest_plan(conn).plan_id == "plan-wed"
        assert journal.load_plan(conn, "plan-wed").superseded_by is None

    def test_the_refusal_happens_before_the_broker_is_touched(self, conn):
        b = broker()
        old = plan("plan-mon", {}, exposure="0", effective=MON)
        executor.adopt_plan(conn, old)
        executor.adopt_plan(conn, plan("plan-wed", {"SEC-AAA": D(10)}))

        with pytest.raises(executor.StalePlanRefused):
            run(executor.execute_session(
                broker=b, conn=conn, deployment=DEPLOY, plan=old,
                instruments={"SEC-AAA": AAA}, today=WED))
        assert b.calls == []
