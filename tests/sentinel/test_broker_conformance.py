"""The execution state machine, driven through every hostile path.

These run against the SIMULATOR, and that is the point: the simulator certifies
the CONTRACT, so this suite is broker-independent and runs ONCE. The per-adapter
suites (Alpaca, IBKR) are separate and prove only that a real transport MAPS onto
the same contract — they do not re-litigate the state machine.

If this file could only be satisfied by something that behaves like Alpaca, the
simulator has become an emulator and the contract is worth only as much as the
messiest adapter.

Every scenario below is a way Stocker lost money or nearly did, restated as a
convergence requirement.
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.execution import recovery  # noqa: E402
from sentinel.execution.commands import Command  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerInstrument, Completeness, IncompleteObservation, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity  # noqa: E402
from sentinel.execution.simulator import (  # noqa: E402
    BrokerUnavailable, FaultKind as F, SimulatedBroker)
from sentinel.execution.states import CommandState as S  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")


def run(coro):
    return asyncio.run(coro)


def command(qty="10", side=Side.BUY, revision=0, plan="plan-1"):
    return Command(
        identity=CommandIdentity(deployment=DEPLOY, plan_id=plan,
                                 security_id=AAA.security_id, revision=revision),
        instrument=AAA, side=side, quantity=Decimal(qty))


async def send(broker, cmd):
    """The two-step every caller must perform: persist SEND_PENDING, then call."""
    pending = recovery.prepare_send(cmd)
    return await recovery.dispatch(broker, pending)


class TestTheHappyPath:
    def test_a_submit_is_acknowledged_and_fills(self):
        b = SimulatedBroker()
        cmd = run(send(b, command()))
        assert cmd.state is S.ACKNOWLEDGED and cmd.broker_order_id

        b.fill(cmd.client_key)
        cmd = recovery.apply_observation(cmd, run(b.observe()))
        assert cmd.state is S.FILLED and cmd.filled_quantity == Decimal(10)

    def test_orders_are_read_before_positions_and_then_AGAIN(self):
        """Invariant 21, plus the consistency re-read.

        Orders-first stops a fill in the gap making an object vanish. The third
        read is what stops the same fill being counted twice — see
        `TestFillBetweenObservationReads`.
        """
        b = SimulatedBroker()
        assert run(b.observe()).is_complete
        assert b.calls == ["list_orders", "get_positions", "list_orders"]


class TestAcceptThenTimeout:
    """The order EXISTS and the caller was told nothing. Stocker called this
    FAILED, which licenced a retry that opened a second position."""

    def test_the_caller_lands_in_UNKNOWN_not_a_failure(self):
        b = SimulatedBroker().schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        cmd = run(send(b, command()))
        assert cmd.state is S.UNKNOWN

    def test_resolution_finds_the_live_order_by_key(self):
        b = SimulatedBroker().schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        cmd = run(send(b, command()))
        cmd = run(recovery.resolve_unknown(b, cmd, run(b.observe())))
        assert cmd.state is S.ACKNOWLEDGED and cmd.broker_order_id == "sim-1"

    def test_a_RETRY_under_the_same_key_does_not_create_a_second_order(self):
        """The whole reason identity is derived rather than generated."""
        b = SimulatedBroker().schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        cmd = command()
        run(send(b, cmd))
        run(send(b, cmd))                       # blind retry, same key
        assert len(b._orders) == 1

    def test_a_FRESH_identity_on_retry_WOULD_have_doubled_the_position(self):
        """The bug, reproduced, so the rule against it is not merely asserted."""
        b = SimulatedBroker().schedule_submit(F.ACCEPT_THEN_TIMEOUT)
        run(send(b, command()))
        run(send(b, command(revision=1)))       # what a uuid4 retry amounts to
        assert len(b._orders) == 2, "two live orders for one economic intent"


class TestNeverReceived:
    """Indistinguishable from accept-then-timeout at the call site. That is not
    a weakness of the simulator, it is the reason UNKNOWN exists."""

    def test_it_also_lands_in_UNKNOWN(self):
        b = SimulatedBroker().schedule_submit(F.NEVER_RECEIVED)
        assert run(send(b, command())).state is S.UNKNOWN

    def test_resolution_against_a_COMPLETE_observation_declares_never_landed(self):
        b = SimulatedBroker().schedule_submit(F.NEVER_RECEIVED)
        cmd = run(send(b, command()))
        cmd = run(recovery.resolve_unknown(b, cmd, run(b.observe())))
        assert cmd.state is S.CANCELLED and "never landed" in cmd.detail

    def test_a_TRUNCATED_observation_may_NOT_resolve_it(self):
        """A short read that happens not to contain our order is not evidence
        the order does not exist. Resolving on one marks a live order never-sent
        and then replaces it — the duplicate position by another road."""
        b = SimulatedBroker().schedule_submit(F.NEVER_RECEIVED)
        cmd = run(send(b, command()))
        b.schedule_observe(F.TRUNCATED_ORDERS)
        with pytest.raises(IncompleteObservation):
            run(recovery.resolve_unknown(b, cmd, run(b.observe())))

    def test_after_resolution_a_NEW_command_is_permitted(self):
        b = SimulatedBroker().schedule_submit(F.NEVER_RECEIVED)
        cmd = run(send(b, command()))
        assert recovery.blocked_securities([cmd]) == {"SEC-AAA"}
        cmd = run(recovery.resolve_unknown(b, cmd, run(b.observe())))
        assert recovery.blocked_securities([cmd]) == frozenset()


class TestOutage:
    def test_a_transport_exception_becomes_UNKNOWN_not_an_error(self):
        b = SimulatedBroker().schedule_submit(F.OUTAGE)
        cmd = run(send(b, command()))
        assert cmd.state is S.UNKNOWN and "BrokerUnavailable" in cmd.detail

    def test_an_observe_outage_propagates(self):
        """Reconciliation must not paper over a missing broker — the caller
        transitions to BROKER_DEGRADED, which permits nothing."""
        b = SimulatedBroker().schedule_observe(F.OUTAGE)
        with pytest.raises(BrokerUnavailable):
            run(b.observe())

    def test_recovery_after_an_outage_finds_the_order_that_did_land(self):
        b = SimulatedBroker().schedule_submit(F.ACCEPT_THEN_TIMEOUT, F.OUTAGE)
        cmd = run(send(b, command()))
        b.schedule_observe(F.OUTAGE)
        with pytest.raises(BrokerUnavailable):
            run(b.observe())
        cmd = run(recovery.resolve_unknown(b, cmd, run(b.observe())))
        assert cmd.state is S.ACKNOWLEDGED


class TestPartialFills:
    def test_a_partial_moves_the_remaining_delta_and_nothing_else(self):
        b = SimulatedBroker()
        cmd = run(send(b, command("10")))
        b.fill(cmd.client_key, "4")
        cmd = recovery.apply_observation(cmd, run(b.observe()))
        assert cmd.state is S.PARTIALLY_FILLED
        assert cmd.filled_quantity == Decimal(4) and cmd.remaining == Decimal(6)

    def test_successive_partials_accumulate(self):
        b = SimulatedBroker()
        cmd = run(send(b, command("10")))
        for chunk in ("3", "3", "4"):
            b.fill(cmd.client_key, chunk)
            cmd = recovery.apply_observation(cmd, run(b.observe()))
        assert cmd.state is S.FILLED and cmd.filled_quantity == Decimal(10)

    def test_a_partially_filled_command_still_BLOCKS_an_overlapping_one(self):
        b = SimulatedBroker()
        cmd = run(send(b, command("10")))
        b.fill(cmd.client_key, "4")
        cmd = recovery.apply_observation(cmd, run(b.observe()))
        assert recovery.blocked_securities([cmd]) == {"SEC-AAA"}


class TestCancellation:
    def test_a_cancel_the_broker_IGNORED_does_not_advance_the_state(self):
        """Reproduced against a real broker 2026-08-09: accepted, cancelled
        nothing. The acknowledgement is telemetry; only absence is proof."""
        b = SimulatedBroker()
        cmd = run(send(b, command()))
        cmd = cmd.transition(S.CANCEL_PENDING)
        b.schedule_cancel(F.CANCEL_ACCEPTED_BUT_IGNORED)
        run(b.cancel(cmd.broker_order_id))

        cmd = recovery.confirm_cancellation(cmd, run(b.observe()))
        assert cmd.state is S.CANCEL_PENDING, "still working, so still pending"

    def test_a_real_cancellation_is_confirmed_by_ABSENCE(self):
        b = SimulatedBroker()
        cmd = run(send(b, command()))
        cmd = cmd.transition(S.CANCEL_PENDING)
        run(b.cancel(cmd.broker_order_id))
        cmd = recovery.confirm_cancellation(cmd, run(b.observe()))
        assert cmd.state is S.CANCELLED

    def test_absence_from_a_TRUNCATED_read_confirms_nothing(self):
        b = SimulatedBroker()
        cmd = run(send(b, command()))
        cmd = cmd.transition(S.CANCEL_PENDING)
        run(b.cancel(cmd.broker_order_id))
        b.schedule_observe(F.TRUNCATED_ORDERS)
        with pytest.raises(IncompleteObservation):
            recovery.confirm_cancellation(cmd, run(b.observe()))

    def test_a_cancel_that_LOSES_the_race_adopts_the_fill(self):
        b = SimulatedBroker()
        cmd = run(send(b, command()))
        cmd = cmd.transition(S.CANCEL_PENDING)
        b.fill(cmd.client_key, "4")             # the fill wins
        cmd = recovery.confirm_cancellation(cmd, run(b.observe()))
        assert cmd.state is S.PARTIALLY_FILLED and cmd.filled_quantity == Decimal(4)


class TestFillBetweenObservationReads:
    """The invariant-21 hazard, and the one the fix for it creates.

    Ordering solves half the problem and the suite has to be honest about which
    half:

    ```text
    positions, then orders   the fill VANISHES from both reads   -> false flat
    orders, then positions   the fill is in BOTH reads           -> double count
    orders, positions, orders  the disagreement is DETECTED      -> observe again
    ```

    A false flat ends a migration irreversibly. A double count nets a working
    order against the position it just became and produces a delta that would
    SELL a holding correctly acquired seconds earlier. Neither is acceptable, so
    ordering is necessary and not sufficient.
    """

    def _mid_read_fill(self):
        b = SimulatedBroker()
        cmd = run(send(b, command("10")))
        key = cmd.client_key
        b.fill_between_reads = lambda sim: sim.fill(key)
        return b, key

    def test_the_position_is_never_lost(self):
        """The original hazard: under positions-first this would be empty."""
        b, _ = self._mid_read_fill()
        assert run(b.observe()).positions_by_security() == {"SEC-AAA": Decimal(10)}

    def test_the_observation_declares_itself_INCONSISTENT(self):
        b, _ = self._mid_read_fill()
        observation = run(b.observe())
        assert observation.completeness is Completeness.INCONSISTENT
        assert not observation.is_complete

    def test_the_DOUBLE_COUNT_is_real_if_the_two_halves_are_mixed(self):
        """Why the re-read is needed, shown with the two halves it compares.

        The PRE-fill order list says a BUY for 10 is still working; the POST-fill
        positions say 10 are held. Against a desired 10 that nets to −10 — a SELL
        of the holding just acquired. Neither half is wrong; they describe
        different instants.

        Built from the halves directly rather than from a broker call, because
        the whole purpose of the third read is that no single call returns this
        pairing any more.
        """
        from sentinel.execution import commands as C
        from sentinel.execution.contract import BrokerObservation
        b, key = self._mid_read_fill()

        pre_fill_orders = tuple(b._snapshot_orders())      # a BUY, still working
        b.fill(key)
        post_fill_positions = run(b.observe()).positions

        mixed = BrokerObservation(observed_at=b.now, orders=pre_fill_orders,
                                  positions=post_fill_positions,
                                  completeness=Completeness.COMPLETE)
        delta = C.compute_delta(security_id="SEC-AAA", desired=Decimal(10),
                                observation=mixed)
        assert delta.side is Side.SELL and delta.quantity == Decimal(10), (
            "this is the trade the re-read exists to prevent")

    def test_an_INCONSISTENT_observation_cannot_authorise_anything(self):
        """Whatever the arithmetic happens to produce, the observation is barred.

        Deliberately NOT asserting a particular delta: substituting the re-read
        order list resolves some interleavings by luck, and a suite that pinned
        that luck would be asserting the accident rather than the rule. The rule
        is that a snapshot which disagreed with itself does not authorise a
        trade.
        """
        b, _ = self._mid_read_fill()
        observation = run(b.observe())
        assert observation.completeness is Completeness.INCONSISTENT
        with pytest.raises(IncompleteObservation):
            observation.require_complete("acting on any delta")

    def test_the_NEXT_observation_is_coherent_and_says_nothing_to_do(self):
        """Convergence: looking again is a complete remedy, which is what makes
        'observe again, never trade' an acceptable rule."""
        from sentinel.execution import commands as C
        b, _ = self._mid_read_fill()
        run(b.observe())                       # the inconsistent one

        observation = run(b.observe())
        assert observation.is_complete
        delta = C.compute_delta(security_id="SEC-AAA", desired=Decimal(10),
                                observation=observation)
        assert delta.classification is C.DeltaClass.NONE


class TestForeignActivity:
    def test_an_order_with_no_key_of_ours_is_not_adopted(self):
        from sentinel.execution.identity import is_sentinel_key
        b = SimulatedBroker()
        b.seed_foreign_order(AAA, side=Side.BUY, qty="5")
        observation = run(b.observe())
        assert [o.client_key for o in observation.orders] == [None]
        assert not any(is_sentinel_key(o.client_key) for o in observation.orders)

    def test_a_corporate_action_changes_a_share_count_with_no_order(self):
        """The input to the rule that ACTIONS is applied BEFORE foreign-activity
        classification: without it, every split during an outage reads as
        somebody trading the account."""
        b = SimulatedBroker()
        b.seed_position(AAA, "10")
        b.apply_corporate_action("SEC-AAA", "2")
        assert run(b.observe()).positions_by_security() == {"SEC-AAA": Decimal(20)}
        assert not b._orders, "nobody traded"


class TestRejection:
    def test_a_real_rejection_is_terminal_and_frees_the_security(self):
        b = SimulatedBroker().schedule_submit(F.REJECT)
        cmd = run(send(b, command()))
        assert cmd.state is S.REJECTED
        assert recovery.blocked_securities([cmd]) == frozenset()


class TestTheSimulatorItselfIsDeterministic:
    def test_the_same_script_gives_the_same_calls_every_time(self):
        def episode():
            b = SimulatedBroker().schedule_submit(F.ACCEPT_THEN_TIMEOUT)
            cmd = run(send(b, command()))
            run(recovery.resolve_unknown(b, cmd, run(b.observe())))
            return tuple(b.calls)

        assert episode() == episode()

    def test_it_can_emit_a_state_no_real_broker_offers_on_demand(self):
        """If everything it can do is something Alpaca does, it is an emulator
        and the contract is only as strong as the messiest adapter."""
        b = SimulatedBroker().schedule_submit(F.NEVER_RECEIVED)
        cmd = run(send(b, command()))
        assert cmd.state is S.UNKNOWN and not b._orders, (
            "accepted-nothing-and-said-nothing is not a response any broker API "
            "documents, and it is exactly the case recovery must survive")
