from __future__ import annotations
import unittest

from fast_confirmation import (
    Config, Evidence, State, compose_after_ldrc, state_from_dict,
    state_to_dict, step,
)


class FastConfirmationTests(unittest.TestCase):
    def test_first_warning_is_external_provisional_only(self):
        state, decision = step(
            evidence=Evidence("2025-04-07", True, False), state=State())
        self.assertFalse(decision.parent_fast_signal)
        self.assertEqual(decision.provisional_ceiling, 0.55)
        self.assertEqual(state.warning_streak, 1)

    def test_one_session_warning_clears_immediately(self):
        state, _ = step(evidence=Evidence("2025-04-07", True, False), state=State())
        state, decision = step(
            evidence=Evidence("2025-04-08", False, False), state=state)
        self.assertFalse(decision.parent_fast_signal)
        self.assertIsNone(decision.provisional_ceiling)
        self.assertEqual(state.warning_streak, 0)

    def test_second_warning_confirms_parent_fast(self):
        state, _ = step(evidence=Evidence("2020-02-27", True, False), state=State())
        _, decision = step(evidence=Evidence("2020-02-28", True, False), state=state)
        self.assertTrue(decision.parent_fast_signal)
        self.assertIsNone(decision.provisional_ceiling)

    def test_causal_confirmation_skips_provisional(self):
        _, decision = step(
            evidence=Evidence("2022-04-26", True, True), state=State())
        self.assertTrue(decision.parent_fast_signal)
        self.assertIsNone(decision.provisional_ceiling)

    def test_confirmation_without_warning_is_rejected(self):
        with self.assertRaises(ValueError):
            step(evidence=Evidence("2022-04-26", False, True), state=State())

    def test_provisional_composition_never_increases_ldrc(self):
        self.assertEqual(compose_after_ldrc(authoritative_allocation=1.0, provisional_ceiling=0.55), 0.55)
        self.assertEqual(compose_after_ldrc(authoritative_allocation=0.0, provisional_ceiling=0.55), 0.0)
        self.assertEqual(compose_after_ldrc(authoritative_allocation=0.55, provisional_ceiling=None), 0.55)

    def test_state_round_trip(self):
        state = State(warning_streak=1, last_session="2025-04-07")
        self.assertEqual(state_from_dict(state_to_dict(state)), state)

    def test_sessions_must_advance(self):
        state = State(last_session="2025-04-07")
        with self.assertRaises(ValueError):
            step(evidence=Evidence("2025-04-07", False, False), state=state)

    def test_invalid_persistence_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            step(
                evidence=Evidence("2025-04-07", True, False),
                state=State(), cfg=Config(persistence_sessions=1),
            )


if __name__ == "__main__":
    unittest.main()
