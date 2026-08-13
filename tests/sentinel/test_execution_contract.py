"""The command contract: identity, UNKNOWN, sizing, and the permission kernel.

These are the rules every later stage depends on, so they are tested as rules
rather than through a scenario. Each class below corresponds to an invariant in
docs/sentinel-execution-contract.md §17, and each names the failure it prevents —
most of them observed in Stocker's execution lineage rather than imagined.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.execution import commands as C  # noqa: E402
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerCapabilities, BrokerInstrument,
    BrokerObservation, BrokerOrder, BrokerPosition, CapabilityNotCertified,
    CommandOutcome, Completeness, IncompleteObservation, Side)
from sentinel.execution.identity import (  # noqa: E402
    CommandIdentity, DeploymentIdentity, IdentityFieldInvalid, is_sentinel_key)
from sentinel.execution.states import (  # noqa: E402
    Action, ActionNotPermitted, CommandState as S, IllegalTransition,
    RuntimeState as R, assert_transition, blocks_overlapping, can_transition,
    is_terminal, permits)

NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)

DEPLOY = DeploymentIdentity(deployment_id="nas-1", broker="alpaca",
                            broker_account_id="ACC-123", takeover_epoch=1)
INSTR = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-1")


def ident(plan="plan-1", security="SEC-AAA", revision=0, deployment=DEPLOY):
    return CommandIdentity(deployment=deployment, plan_id=plan,
                           security_id=security, revision=revision)


def obs(*, orders=(), positions=(), completeness=Completeness.COMPLETE):
    return BrokerObservation(observed_at=NOW, orders=tuple(orders),
                             positions=tuple(positions),
                             completeness=completeness)


def order(oid="b-1", *, side=Side.BUY, qty="10", filled="0",
          state=S.ACKNOWLEDGED, key=None, instrument=INSTR):
    return BrokerOrder(broker_order_id=oid, client_key=key, instrument=instrument,
                       side=side, state=state, quantity=Decimal(qty),
                       filled_quantity=Decimal(filled),
                       filled_average_price=(Decimal("100")
                                             if Decimal(filled) else None))


def pos(qty="10", instrument=INSTR):
    return BrokerPosition(instrument=instrument, quantity=Decimal(qty))


class TestIdentityIsDerived:
    def test_the_same_inputs_always_give_the_same_key(self):
        assert ident().client_key == ident().client_key

    def test_it_is_recomputable_from_DURABLE_FIELDS_ALONE(self):
        """The design test. Rebuilt from a dict, as a journal row would be."""
        row = {"deployment_id": "nas-1", "broker": "alpaca",
               "broker_account_id": "ACC-123", "takeover_epoch": 1,
               "plan_id": "plan-1", "security_id": "SEC-AAA", "revision": 0}
        rebuilt = CommandIdentity(
            deployment=DeploymentIdentity(
                deployment_id=row["deployment_id"], broker=row["broker"],
                broker_account_id=row["broker_account_id"],
                takeover_epoch=row["takeover_epoch"]),
            plan_id=row["plan_id"], security_id=row["security_id"],
            revision=row["revision"])
        assert rebuilt.client_key == ident().client_key

    @pytest.mark.parametrize("change", [
        {"plan": "plan-2"}, {"security": "SEC-BBB"}, {"revision": 1},
        {"deployment": DeploymentIdentity("nas-2", "alpaca", "ACC-123", 1)},
        {"deployment": DeploymentIdentity("nas-1", "alpaca", "ACC-999", 1)},
        {"deployment": DeploymentIdentity("nas-1", "alpaca", "ACC-123", 2)},
    ])
    def test_every_component_CHANGES_the_key(self, change):
        """A component that does not affect the key is not really in it, and
        two commands would collide along that axis."""
        assert ident(**change).client_key != ident().client_key

    def test_a_takeover_epoch_bump_disjoins_the_whole_namespace(self):
        """Fencing: a restored appliance's keys can never be confused with its
        predecessor's. It does NOT stop both trading — that needs credential
        revocation — but it bounds and attributes the damage."""
        before = ident().client_key
        after = ident(deployment=DeploymentIdentity(
            "nas-1", "alpaca", "ACC-123", 2)).client_key
        assert before != after

    def test_the_key_is_short_enough_for_every_broker(self):
        key = ident().client_key
        assert len(key) <= 48, "must fit the shortest client-id limit in use"
        assert is_sentinel_key(key)

    def test_an_empty_component_RAISES_rather_than_hashing(self):
        with pytest.raises(IdentityFieldInvalid):
            ident(security="")
        with pytest.raises(IdentityFieldInvalid):
            CommandIdentity(deployment=DEPLOY, plan_id="  ", security_id="S")

    def test_superseding_gives_a_DIFFERENT_key_and_only_via_that_route(self):
        base = ident()
        nxt = base.superseding()
        assert nxt.revision == 1 and nxt.client_key != base.client_key

    def test_a_foreign_order_is_not_mistaken_for_ours(self):
        assert not is_sentinel_key("some-other-system-42")
        assert not is_sentinel_key(None)

    def test_an_order_from_a_PREVIOUS_epoch_is_still_recognised_as_ours(self):
        """Recovery must adopt it, not classify it as foreign — even though the
        current epoch cannot regenerate its key."""
        old = ident(deployment=DeploymentIdentity(
            "nas-1", "alpaca", "ACC-123", 0)).client_key
        assert is_sentinel_key(old)


class TestUnknownIsAState:
    def test_a_submit_outcome_cannot_be_FAILED(self):
        """Stocker recorded an uncertain POST as FAILED, which licenced a retry
        that opened a second position. The type makes that unsayable."""
        for ok in (S.ACKNOWLEDGED, S.REJECTED, S.UNKNOWN):
            CommandOutcome(state=ok)
        with pytest.raises(ValueError, match="no FAILED"):
            CommandOutcome(state=S.PLANNED)

    def test_UNKNOWN_resolves_to_anything_the_broker_turns_out_to_hold(self):
        for landed in (S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.FILLED,
                       S.CANCELLED, S.REJECTED):
            assert can_transition(S.UNKNOWN, landed)

    def test_UNKNOWN_may_NOT_be_superseded(self):
        with pytest.raises(IllegalTransition, match="UNDETERMINED"):
            assert_transition(S.UNKNOWN, S.SUPERSEDED)

    def test_UNKNOWN_blocks_an_overlapping_command(self):
        assert blocks_overlapping(S.UNKNOWN)

    def test_only_a_PLANNED_command_may_be_superseded(self):
        assert can_transition(S.PLANNED, S.SUPERSEDED)
        for sent in (S.SEND_PENDING, S.ACKNOWLEDGED, S.PARTIALLY_FILLED,
                     S.CANCEL_PENDING):
            with pytest.raises(IllegalTransition):
                assert_transition(sent, S.SUPERSEDED)

    def test_terminal_states_are_terminal(self):
        for t in (S.FILLED, S.CANCELLED, S.REJECTED, S.SUPERSEDED):
            assert is_terminal(t) and not blocks_overlapping(t)
            for anywhere in S:
                assert not can_transition(t, anywhere)

    def test_a_cancel_can_LOSE_the_race_to_a_fill(self):
        assert can_transition(S.CANCEL_PENDING, S.FILLED)

    def test_a_partial_fill_can_be_followed_by_another(self):
        assert can_transition(S.PARTIALLY_FILLED, S.PARTIALLY_FILLED)


class TestObservationCompleteness:
    @pytest.mark.parametrize(
        ("qty", "filled", "average", "match"),
        [
            ("10", "11", "100", "between zero and quantity"),
            ("10", "1", None, "requires filled_average_price"),
            ("10", "10", "100", "full quantity"),
        ])
    def test_malformed_recovery_economics_are_not_observations(
            self, qty, filled, average, match):
        state = S.FILLED if filled == qty and qty == "10" else S.ACKNOWLEDGED
        if match == "full quantity":
            filled = "9"
            state = S.FILLED
        with pytest.raises(ValueError, match=match):
            BrokerOrder(
                broker_order_id="malformed", client_key="sntl-malformed",
                instrument=INSTR, side=Side.BUY, state=state,
                quantity=Decimal(qty), filled_quantity=Decimal(filled),
                filled_average_price=(Decimal(average) if average else None),
                submitted_at=NOW)

    def test_one_client_key_cannot_name_two_broker_orders(self):
        first = order(oid="broker-a", key="sntl-one-key")
        second = order(oid="broker-b", key="sntl-one-key")
        with pytest.raises(ValueError, match="multiple broker ids"):
            obs(orders=(first, second))

    def test_a_truncated_read_cannot_support_an_irreversible_conclusion(self):
        with pytest.raises(IncompleteObservation):
            obs(completeness=Completeness.TRUNCATED).require_complete("resolving")

    def test_a_complete_read_can(self):
        obs().require_complete("resolving")

    def test_a_zero_quantity_position_is_not_a_position(self):
        """Alpaca can report a closed position transiently; treating it as held
        keeps the machine liquidating something that no longer exists."""
        assert obs(positions=[pos("0")]).positions_by_security() == {}


class TestRemainingDelta:
    def test_a_full_exit_sizes_to_the_observed_quantity(self):
        d = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                            observation=obs(positions=[pos("37")]))
        assert d.side is Side.SELL and d.quantity == Decimal(37)
        assert d.classification is C.DeltaClass.ACTIONABLE

    def test_a_working_order_is_COMMITTED_and_not_re_ordered(self):
        """The double-submit this prevents: 10 desired, 0 held, 10 already
        working — the remaining delta is zero, not ten."""
        d = C.compute_delta(
            security_id="SEC-AAA", desired=Decimal(10),
            observation=obs(orders=[order(side=Side.BUY, qty="10")]))
        assert d.remaining == 0 and d.classification is C.DeltaClass.NONE

    def test_only_the_UNFILLED_part_of_a_working_order_counts(self):
        """The filled part is already in the observed position; counting it
        again would double it."""
        d = C.compute_delta(
            security_id="SEC-AAA", desired=Decimal(10),
            observation=obs(positions=[pos("4")],
                            orders=[order(side=Side.BUY, qty="10", filled="4")]))
        assert d.held == Decimal(4) and d.committed == Decimal(6)
        assert d.remaining == Decimal(0)

    def test_a_TERMINAL_order_claims_nothing(self):
        d = C.compute_delta(
            security_id="SEC-AAA", desired=Decimal(10),
            observation=obs(orders=[order(side=Side.BUY, qty="10",
                                          state=S.CANCELLED)]))
        assert d.remaining == Decimal(10)

    def test_an_opposing_working_order_is_reported_as_a_CONFLICT(self):
        d = C.compute_delta(
            security_id="SEC-AAA", desired=Decimal(10),
            observation=obs(orders=[order("b-9", side=Side.SELL, qty="5")]))
        assert d.conflicting_orders and d.side is Side.BUY

    def test_a_sub_increment_remainder_is_DUST(self):
        d = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                            observation=obs(positions=[pos("0.4")]),
                            min_increment=Decimal(1))
        assert d.classification is C.DeltaClass.DUST

    def test_quantities_are_DECIMAL_and_a_float_is_refused(self):
        """A float that works in every round-numbered test and fails on the
        first reverse-split residual is the worst kind of passing test."""
        with pytest.raises(TypeError):
            C.compute_delta(security_id="SEC-AAA", desired=0.0,
                            observation=obs())
        with pytest.raises(TypeError):
            BrokerPosition(instrument=INSTR, quantity=1.5)

    def test_a_fractional_residual_is_represented_EXACTLY(self):
        d = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                            observation=obs(positions=[pos("0.1")]),
                            min_increment=Decimal("0.001"))
        assert d.quantity == Decimal("0.1")


class TestRuntimePermissions:
    def test_reducing_exposure_survives_states_that_forbid_increasing_it(self):
        for degraded in (R.DATA_DEGRADED, R.FOREIGN_ACTIVITY):
            assert permits(degraded, Action.REDUCE_EXPOSURE)
            assert not permits(degraded, Action.INCREASE_EXPOSURE)

    def test_BROKER_DEGRADED_permits_no_broker_contact_at_all(self):
        assert not permits(R.BROKER_DEGRADED, Action.RECONCILE)
        assert permits(R.BROKER_DEGRADED, Action.ADVANCE_STRATEGY)

    def test_the_shadow_keeps_advancing_in_every_state_but_INTEGRITY_HALTED(self):
        """Being unable to ACT is not a reason to stop KNOWING — a controller
        that skipped sessions would lose its event memory."""
        for state in R:
            expected = state is not R.INTEGRITY_HALTED
            assert permits(state, Action.ADVANCE_STRATEGY) is expected

    def test_INTEGRITY_HALTED_permits_nothing(self):
        for action in Action:
            assert not permits(R.INTEGRITY_HALTED, action)

    def test_RECONCILING_submits_nothing(self):
        assert not permits(R.RECONCILING, Action.REDUCE_EXPOSURE)
        assert not permits(R.RECONCILING, Action.INCREASE_EXPOSURE)


class TestAuthorize:
    def _args(self, **over):
        base = dict(
            delta=C.compute_delta(security_id="SEC-AAA", desired=Decimal(10),
                                  observation=obs()),
            runtime=R.RUNNING, binding=DEPLOY,
            observed_account=BrokerAccountIdentity("alpaca", "ACC-123"),
            observation=obs(), open_commands=(), capabilities=None)
        base.update(over)
        return base

    def test_the_happy_path_returns_the_permission_it_granted(self):
        assert C.authorize(**self._args()) is Action.INCREASE_EXPOSURE

    def test_the_WRONG_ACCOUNT_is_refused_before_anything_else(self):
        with pytest.raises(C.CommandRefused, match="account binding"):
            C.authorize(**self._args(
                observed_account=BrokerAccountIdentity("alpaca", "SOMEONE-ELSE")))

    def test_an_unreadable_account_is_refused_too(self):
        """None is not 'probably fine'."""
        with pytest.raises(C.CommandRefused, match="account binding"):
            C.authorize(**self._args(observed_account=None))

    def test_an_INCREASE_needs_a_COMPLETE_observation(self):
        short = obs(completeness=Completeness.TRUNCATED)
        with pytest.raises(IncompleteObservation):
            C.authorize(**self._args(observation=short))

    def test_a_REDUCE_does_not(self):
        """The asymmetry, exercised: a short read is enough to get OUT."""
        short = obs(positions=[pos("10")], completeness=Completeness.TRUNCATED)
        delta = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                                observation=short)
        assert C.authorize(**self._args(delta=delta, observation=short)) \
            is Action.REDUCE_EXPOSURE

    def test_an_UNKNOWN_command_blocks_a_new_one_for_that_security(self):
        stuck = C.Command(identity=ident(), instrument=INSTR, side=Side.BUY,
                          quantity=Decimal(10), state=S.UNKNOWN)
        with pytest.raises(C.CommandRefused, match="UNDETERMINED"):
            C.authorize(**self._args(open_commands=[stuck]))

    def test_an_in_flight_command_for_ANOTHER_security_does_not_block(self):
        other = C.Command(
            identity=ident(security="SEC-BBB"),
            instrument=BrokerInstrument(security_id="SEC-BBB", symbol="BBB"),
            side=Side.BUY, quantity=Decimal(10), state=S.UNKNOWN)
        assert C.authorize(**self._args(open_commands=[other]))

    def test_a_terminal_command_does_not_block(self):
        done = C.Command(identity=ident(), instrument=INSTR, side=Side.BUY,
                         quantity=Decimal(10), state=S.FILLED)
        assert C.authorize(**self._args(open_commands=[done]))

    def test_an_opposing_working_order_is_refused_until_cancelled(self):
        o = obs(orders=[order("b-9", side=Side.SELL, qty="5")])
        delta = C.compute_delta(security_id="SEC-AAA", desired=Decimal(10),
                                observation=o)
        with pytest.raises(C.CommandRefused, match="oppose"):
            C.authorize(**self._args(delta=delta, observation=o))

    def test_DUST_is_refused_as_an_operator_matter(self):
        d = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                            observation=obs(positions=[pos("0.4")]))
        with pytest.raises(C.CommandRefused, match="DUST_RESIDUAL"):
            C.authorize(**self._args(delta=d))

    def test_a_degraded_runtime_refuses_the_INCREASE(self):
        with pytest.raises(ActionNotPermitted):
            C.authorize(**self._args(runtime=R.FOREIGN_ACTIVITY))

    def test_capabilities_FAIL_CLOSED(self):
        with pytest.raises(CapabilityNotCertified, match="stable_client_key"):
            C.authorize(**self._args(capabilities=BrokerCapabilities()))

    def test_a_fractional_command_needs_the_fractional_capability(self):
        integer_only = BrokerCapabilities(stable_client_key=True,
                                          single_order_cancel=True)
        o = obs(positions=[pos("10.5")])
        d = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                            observation=o, min_increment=Decimal("0.0001"))
        with pytest.raises(CapabilityNotCertified, match="fractional"):
            C.authorize(**self._args(delta=d, observation=o,
                                     capabilities=integer_only))


class TestCommandConstruction:
    def test_direction_lives_in_side_not_in_a_signed_quantity(self):
        with pytest.raises(ValueError, match="positive"):
            C.Command(identity=ident(), instrument=INSTR, side=Side.SELL,
                      quantity=Decimal(-5))

    def test_build_produces_a_PLANNED_command_carrying_the_key(self):
        d = C.compute_delta(security_id="SEC-AAA", desired=Decimal(0),
                            observation=obs(positions=[pos("37")]))
        cmd = C.build(delta=d, identity=ident(), instrument=INSTR, created_at=NOW)
        assert cmd.state is S.PLANNED and cmd.side is Side.SELL
        assert cmd.quantity == Decimal(37)
        assert cmd.client_key == ident().client_key

    def test_a_command_is_replaced_not_edited(self):
        cmd = C.Command(identity=ident(), instrument=INSTR, side=Side.BUY,
                        quantity=Decimal(10))
        sent = cmd.transition(S.SEND_PENDING)
        assert cmd.state is S.PLANNED and sent.state is S.SEND_PENDING

    def test_an_illegal_transition_raises_from_the_command_too(self):
        cmd = C.Command(identity=ident(), instrument=INSTR, side=Side.BUY,
                        quantity=Decimal(10), state=S.UNKNOWN)
        with pytest.raises(IllegalTransition):
            cmd.transition(S.SUPERSEDED)
