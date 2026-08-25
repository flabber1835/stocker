from __future__ import annotations

from dataclasses import replace
import unittest

from sentinel_fastgate_reference import (
    Config,
    Decision,
    FastEvidence,
    FastSnapshot,
    FastgateEvidenceUnavailable,
    State,
    compose_after_authoritative_ldrc,
    evaluate_fast_snapshot,
    state_from_dict,
    state_to_dict,
    step,
    strategy_identity,
)


def snapshot(**changes) -> FastSnapshot:
    values = {
        "session": "2026-08-24",
        "history_end_session": "2026-08-23",
        "shadow_drawdown": -0.12,
        "green_breadth": 0.10,
        "shadow_r5": -0.06,
        "shadow_r10": -0.09,
        "damaged_5_sessions_ago": 0.50,
        "spy_vol5_over_vol20_minus_1": 0.05,
        "spy_r20": -0.02,
        "minimum_damaged": 0.70,
        "maximum_damaged": 0.90,
        "residual_breadths": ((0.145, 0.86), (0.150, 0.86), (0.155, 0.86)),
        "codistress_breadth": 0.70,
        "holdings": 30,
        "residual_coverage": 28,
        "codistress_coverage": 26,
    }
    values.update(changes)
    return FastSnapshot(**values)


def evidence(session: str, warning: bool, confirmed: bool = False, status: str | None = None) -> FastEvidence:
    return FastEvidence(
        session=session,
        status=status or ("controllable" if warning else "impossible"),
        warning=warning,
        causal_confirmed=confirmed,
        residual_votes=2 if confirmed else 0,
        codistress_confirmed=confirmed,
        symbolic_floor_confirmed=confirmed,
        reason="TEST",
    )


class SignalTests(unittest.TestCase):
    def test_controllable_dynamic_peer_signal_confirms(self):
        result = evaluate_fast_snapshot(snapshot())
        self.assertEqual(result.status, "controllable")
        self.assertTrue(result.warning)
        self.assertTrue(result.causal_confirmed)
        self.assertEqual(result.residual_votes, 3)

    def test_non_peer_failure_is_impossible(self):
        result = evaluate_fast_snapshot(snapshot(shadow_drawdown=-0.05))
        self.assertEqual(result.status, "impossible")
        self.assertFalse(result.warning)

    def test_missing_required_evidence_is_unavailable(self):
        result = evaluate_fast_snapshot(snapshot(shadow_drawdown=None))
        self.assertEqual(result.status, "unavailable")

    def test_history_must_end_before_decision(self):
        with self.assertRaisesRegex(ValueError, "before the decision"):
            evaluate_fast_snapshot(snapshot(history_end_session="2026-08-24"))


class GateTests(unittest.TestCase):
    def test_first_warning_is_external_55_percent_ceiling(self):
        state, result = step(evidence=evidence("2026-08-24", True), state=State())
        self.assertEqual(state.warning_streak, 1)
        self.assertFalse(result.parent_fast_signal)
        self.assertEqual(result.provisional_ceiling, 0.55)

    def test_second_warning_confirms(self):
        state, _ = step(evidence=evidence("2026-08-23", True), state=State())
        _, result = step(evidence=evidence("2026-08-24", True), state=state)
        self.assertTrue(result.parent_fast_signal)
        self.assertEqual(result.reason, "FASTGATE_CONFIRMED_PERSISTENCE")

    def test_causal_confirmation_is_immediate(self):
        _, result = step(evidence=evidence("2026-08-24", True, True), state=State())
        self.assertTrue(result.parent_fast_signal)
        self.assertIsNone(result.provisional_ceiling)

    def test_one_session_warning_clears_immediately(self):
        state, _ = step(evidence=evidence("2026-08-23", True), state=State())
        state, result = step(evidence=evidence("2026-08-24", False), state=state)
        self.assertEqual(state.warning_streak, 0)
        self.assertEqual(result.reason, "FASTGATE_PROVISIONAL_CLEAR_IMMEDIATE")

    def test_unavailable_evidence_withholds_without_mutation(self):
        state = State(warning_streak=1, last_session="2026-08-23")
        with self.assertRaises(FastgateEvidenceUnavailable):
            step(evidence=evidence("2026-08-24", False, status="unavailable"), state=state)
        self.assertEqual(state.warning_streak, 1)


class CompositionTests(unittest.TestCase):
    def provisional(self) -> Decision:
        return Decision("2026-08-24", 1, False, 0.55, "FASTGATE_PROVISIONAL_FIRST_WARNING", "TEST")

    def test_provisional_ceiling_is_applied_after_ldrc(self):
        result = compose_after_authoritative_ldrc(
            authoritative_desired_allocation=1.0,
            authoritative_native_allocation=1.0,
            authoritative_fast_active=False,
            authoritative_slow_active=False,
            decision=self.provisional(),
        )
        self.assertTrue(result.provisional_applied)
        self.assertEqual(result.allocation, 0.55)

    def test_provisional_never_overrides_severe_or_increases_exposure(self):
        severe = compose_after_authoritative_ldrc(
            authoritative_desired_allocation=0.0,
            authoritative_native_allocation=0.0,
            authoritative_fast_active=True,
            authoritative_slow_active=False,
            decision=self.provisional(),
        )
        partial = compose_after_authoritative_ldrc(
            authoritative_desired_allocation=0.40,
            authoritative_native_allocation=0.40,
            authoritative_fast_active=False,
            authoritative_slow_active=False,
            decision=self.provisional(),
        )
        self.assertEqual(severe.allocation, 0.0)
        self.assertEqual(partial.allocation, 0.40)


class IdentityTests(unittest.TestCase):
    def test_identity_and_state_round_trip_are_deterministic(self):
        self.assertEqual(strategy_identity(), strategy_identity())
        state = State(1, 1, "2026-08-24")
        self.assertEqual(state_from_dict(state_to_dict(state)), state)

    def test_invalid_persistence_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            step(
                evidence=evidence("2026-08-24", False),
                state=State(),
                cfg=replace(Config(), persistence_sessions=1),
            )


if __name__ == "__main__":
    unittest.main()
