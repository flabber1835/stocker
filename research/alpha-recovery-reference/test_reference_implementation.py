from __future__ import annotations

import math
import unittest

from reference_implementation import (
    BranchStatus, ExecutionInterval, FastContext, FastDecision, HoldingHistory,
    Observation, PeerSnapshot, ReplayInput, State, build_peer_snapshot,
    evaluate_fast, run_replay, state_from_dict, state_to_dict, step,
    transition_factor,
)


def fast(warning: bool, confirmed: bool = False,
         status: BranchStatus = BranchStatus.CONTROLLABLE) -> FastDecision:
    return FastDecision(status, warning, confirmed, 2 if confirmed else 0, 3,
                        confirmed, True, "TEST_FAST")


def ob(day: int, *, signal: FastDecision | None = None, slow: bool = False,
       r20: float | None = .01, r40: float | None = .01,
       damaged: float | None = .40, green: float | None = .40,
       wr20: float | None = .01, wr40: float | None = .01,
       spy: float | None = .01, dd: float | None = -.05) -> Observation:
    return Observation(f"2026-01-{day:02d}", signal or fast(False), slow,
                       r20, r40, damaged, green, wr20, wr40, spy, dd)


class ControllerTests(unittest.TestCase):
    def test_one_session_warning_clears_without_recovery_episode(self):
        state, first = step(observation=ob(1, signal=fast(True)), state=State())
        self.assertEqual(first.allocation, .55)
        self.assertTrue(first.provisional_active)
        self.assertFalse(first.recovery_episode)
        state, second = step(observation=ob(2), state=state)
        self.assertEqual(second.allocation, 1.0)
        self.assertFalse(second.provisional_active)
        self.assertFalse(second.recovery_episode)
        self.assertIn("FAST_PROVISIONAL_CLEAR_IMMEDIATE", second.reason)

    def test_second_warning_confirms_zero(self):
        state, _ = step(observation=ob(1, signal=fast(True)), state=State())
        state, decision = step(observation=ob(2, signal=fast(True)), state=state)
        self.assertEqual(decision.allocation, 0.0)
        self.assertTrue(decision.fast_severe)
        self.assertTrue(decision.recovery_episode)
        self.assertIn("FAST_CONFIRMED_PERSISTENCE", decision.reason)

    def test_independent_confirmation_skips_provisional(self):
        state, decision = step(observation=ob(1, signal=fast(True, True)),
                               state=State())
        self.assertEqual(decision.allocation, 0.0)
        self.assertTrue(state.fast_severe)
        self.assertFalse(state.provisional_active)

    def test_confirmed_recovery_starts_real_55_percent_basket(self):
        state = State(fast_severe=True, fast_age=9, fast_healthy_streak=2,
                      recovery_episode=True, previous_allocation=0.0,
                      r40_history=(-.06, -.07, -.08, -.09, -.10, -.11),
                      last_session="2026-01-01")
        state, decision = step(observation=ob(2), state=state)
        self.assertFalse(decision.fast_severe)
        self.assertEqual(decision.allocation, .55)
        self.assertTrue(decision.ramp_active)
        self.assertIn("RECOVERY_FRAGILE_RAMP", decision.reason)

    def test_full_promotion_holds_65_until_witness(self):
        state = State(recovery_episode=True, ramp_active=True, ramp_index=1,
                      ramp_streak=9, previous_allocation=.65,
                      last_session="2026-01-01")
        state, decision = step(observation=ob(2, wr20=-.01, wr40=-.01),
                               state=state)
        self.assertEqual(decision.allocation, .65)
        self.assertTrue(decision.ramp_active)
        self.assertIn("RAMP_FULL_HELD_FOR_CONCORDANCE", decision.reason)

    def test_native_full_readiness_stays_latched_while_waiting(self):
        state = State(recovery_episode=True, ramp_active=True, ramp_index=1,
                      ramp_streak=10, witness_streak=6,
                      previous_allocation=.65, last_session="2026-01-01")
        state, decision = step(observation=ob(2, r20=-.01,
                                                    damaged=.70, green=.10),
                               state=state)
        self.assertEqual(decision.allocation, 1.0)
        self.assertFalse(decision.ramp_active)
        self.assertFalse(decision.recovery_episode)

    def test_divergence_trigger_is_preserved(self):
        state, decision = step(observation=ob(1, dd=-.10, wr20=-.08,
                                                    wr40=-.20, spy=0.0),
                               state=State())
        self.assertEqual(decision.allocation, .55)
        self.assertTrue(decision.divergence_latched)
        self.assertIn("LD_ENTER_DIVERGENCE", decision.reason)

    def test_state_round_trip(self):
        original = State(provisional_active=True, warning_streak=1,
                         previous_allocation=.55,
                         r40_history=(None, -.10, -.08),
                         last_session="2026-01-01")
        self.assertEqual(state_from_dict(state_to_dict(original)), original)


class PeerSignalTests(unittest.TestCase):
    @staticmethod
    def histories() -> tuple[list[HoldingHistory], list[float]]:
        n = 300
        market = [.004*math.sin(i/7) for i in range(n)]
        common = [.012 if i % 5 in (0, 1) else -.008 for i in range(n)]
        distress = [i % 11 in (0, 1, 2) for i in range(n)]
        rows = [HoldingHistory(
            "RED", tuple(1.2*m+r for m, r in zip(market, common)),
            tuple(distress), True, False, True)]
        for k in range(8):
            noise = [.001*math.sin((i+k)/3) for i in range(n)]
            rows.append(HoldingHistory(
                f"V{k}", tuple(.8*m+.85*r+e for m, r, e in
                                zip(market, common, noise)),
                tuple(value if i % 17 else False
                      for i, value in enumerate(distress)),
                False, False, False))
        rows.append(HoldingHistory(
            "GREEN", tuple(.5*m+.01*math.sin(i/2.7)
                           for i, m in enumerate(market)),
            tuple(i % 29 == 0 for i in range(n)), False, True, False))
        return rows, market

    def test_dynamic_signal_confirms_controllable_branch(self):
        holdings, market = self.histories()
        peers = build_peer_snapshot(holdings=holdings, market_returns=market,
                                    exact_minimum=.10, exact_maximum=.90)
        decision = evaluate_fast(
            context=FastContext(-.12, .10, -.06, -.10, .50, .08, -.02),
            peers=peers)
        self.assertEqual(decision.status, BranchStatus.CONTROLLABLE)
        self.assertTrue(decision.warning)
        self.assertTrue(decision.confirmed)
        self.assertGreaterEqual(decision.residual_votes, 2)

    def test_impossible_branch_does_not_warn(self):
        peers = PeerSnapshot(.20, .70,
                             ((.145, .70), (.15, .70), (.155, .70)),
                             .70, 20, 20, 20)
        decision = evaluate_fast(
            context=FastContext(-.12, .10, -.06, -.10, .50, .08, -.02),
            peers=peers)
        self.assertEqual(decision.status, BranchStatus.IMPOSSIBLE)
        self.assertFalse(decision.warning)

    def test_missing_short_loss_is_unavailable_not_negative(self):
        peers = PeerSnapshot(.20, .90,
                             ((.145, .90), (.15, .90), (.155, .90)),
                             .90, 20, 20, 20)
        decision = evaluate_fast(
            context=FastContext(-.12, .10, None, None, .50, .08, -.02),
            peers=peers)
        self.assertEqual(decision.status, BranchStatus.UNAVAILABLE)
        self.assertFalse(decision.warning)


class ExecutionTests(unittest.TestCase):
    def test_old_overnight_new_intraday(self):
        interval = ExecutionInterval(-.10, .04, .01, .002)
        factor = transition_factor(old_allocation=1.0,
                                   new_allocation=.55,
                                   interval=interval)
        expected = (.9)*(1-.001*.45)*(1+.55*.04+.45*.002)
        self.assertAlmostEqual(factor, expected, places=14)

    def test_replay_applies_close_decision_at_following_open(self):
        interval = ExecutionInterval(-.10, .04, .01, .002)
        result = run_replay([
            ReplayInput(ob(2, signal=fast(True))),
            ReplayInput(ob(5), interval),
        ])
        expected = transition_factor(old_allocation=1.0,
                                     new_allocation=.55,
                                     interval=interval)
        self.assertEqual(result.rows[0].effective_allocation, 1.0)
        self.assertEqual(result.rows[0].pending_allocation, .55)
        self.assertEqual(result.rows[1].effective_allocation, .55)
        self.assertEqual(result.rows[1].pending_allocation, 1.0)
        self.assertAlmostEqual(result.rows[1].nav, expected, places=14)
        self.assertEqual(result.metrics.transitions, 1)


if __name__ == "__main__":
    unittest.main()
