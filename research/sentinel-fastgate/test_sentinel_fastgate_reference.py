from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from sentinel_fastgate_reference import (
    AUTHORITATIVE_DEPENDENCY_GIT_BLOBS,
    Config,
    Decision,
    FastContext,
    FastEvidence,
    FastSnapshot,
    FastgateEvidenceUnavailable,
    HoldingHistory,
    MarketHistory,
    SentinelFastgate,
    State,
    build_fast_snapshot,
    compose_after_authoritative_ldrc,
    evaluate_fast_from_histories,
    evaluate_fast_snapshot,
    state_from_dict,
    state_to_dict,
    step,
    strategy_identity,
    verify_authoritative_dependencies,
)


def direct_snapshot(**changes) -> FastSnapshot:
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
        "residual_breadths": (
            (0.145, 0.86),
            (0.150, 0.86),
            (0.155, 0.86),
        ),
        "codistress_breadth": 0.86,
        "holdings": 30,
        "residual_coverage": 28,
        "codistress_coverage": 26,
    }
    values.update(changes)
    return FastSnapshot(**values)


def evidence(
    session: str,
    warning: bool,
    confirmed: bool = False,
    status: str | None = None,
) -> FastEvidence:
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


def synthetic_histories() -> tuple[FastContext, MarketHistory, tuple[HoldingHistory, ...]]:
    start = date(2026, 1, 1)
    sessions = tuple(
        (start + timedelta(days=index)).isoformat()
        for index in range(130)
    )
    market = tuple(
        0.004 * (1 if index % 2 == 0 else -1)
        + 0.00002 * index
        for index in range(130)
    )
    shared = tuple(
        0.003 * (1 if index % 7 < 3 else -1)
        + 0.0001 * ((index % 5) - 2)
        for index in range(130)
    )

    # Two RED/core-amber anchors plus seven vulnerable names with the same
    # market-neutral residual and one GREEN name.
    holdings: list[HoldingHistory] = []
    for index in range(10):
        if index < 9:
            returns = tuple(
                0.8 * market_value + shared_value + index * 1e-7
                for market_value, shared_value in zip(market, shared)
            )
        else:
            returns = tuple(
                0.3 * market_value
                + 0.004 * (1 if sample % 11 < 4 else -1)
                for sample, market_value in enumerate(market)
            )

        if index < 2:
            distress = tuple(sample % 10 < 4 for sample in range(130))
            red = True
            core_amber = True
            green = False
        elif index < 9:
            # Similar but not identical historical co-distress.
            distress = tuple((sample + index) % 10 < 4 for sample in range(130))
            red = False
            core_amber = False
            green = False
        else:
            distress = tuple(sample % 13 == 0 for sample in range(130))
            red = False
            core_amber = False
            green = True

        holdings.append(
            HoldingHistory(
                security_id=f"S{index:02d}",
                returns=returns,
                distress=distress,
                red=red,
                green=green,
                core_amber=core_amber,
            )
        )

    context = FastContext(
        session=(start + timedelta(days=130)).isoformat(),
        shadow_drawdown=-0.12,
        green_breadth=0.10,
        shadow_r5=-0.06,
        shadow_r10=-0.09,
        damaged_5_sessions_ago=0.50,
        spy_vol5_over_vol20_minus_1=0.05,
        spy_r20=-0.02,
        minimum_damaged=0.70,
        maximum_damaged=0.90,
    )
    return context, MarketHistory(sessions, market), tuple(holdings)


class EndToEndSignalTests(unittest.TestCase):
    def test_raw_prior_histories_build_and_confirm_dynamic_peer_signal(self):
        context, market_history, holdings = synthetic_histories()
        snapshot, result = evaluate_fast_from_histories(
            context=context,
            market_history=market_history,
            holdings=holdings,
        )
        self.assertEqual(snapshot.history_end_session, market_history.sessions[-1])
        self.assertEqual(snapshot.holdings, 10)
        self.assertGreaterEqual(snapshot.residual_coverage, 8)
        self.assertTrue(all(breadth >= 0.85 for _, breadth in snapshot.residual_breadths))
        self.assertEqual(result.status, "controllable")
        self.assertTrue(result.warning)
        self.assertTrue(result.causal_confirmed)
        self.assertEqual(result.residual_votes, 3)

    def test_builder_rejects_history_reaching_decision_session(self):
        context, market_history, holdings = synthetic_histories()
        bad_context = replace(
            context,
            session=market_history.sessions[-1],
        )
        with self.assertRaisesRegex(ValueError, "before the decision"):
            build_fast_snapshot(
                context=bad_context,
                market_history=market_history,
                holdings=holdings,
            )

    def test_builder_rejects_misaligned_holding_history(self):
        context, market_history, holdings = synthetic_histories()
        bad = replace(holdings[0], returns=holdings[0].returns[:-1])
        with self.assertRaisesRegex(ValueError, "align"):
            build_fast_snapshot(
                context=context,
                market_history=market_history,
                holdings=(bad, *holdings[1:]),
            )

    def test_exact_symbolic_bounds_are_required(self):
        context, market_history, holdings = synthetic_histories()
        bad_context = replace(context, minimum_damaged=float("nan"))
        with self.assertRaisesRegex(ValueError, "exact symbolic"):
            build_fast_snapshot(
                context=bad_context,
                market_history=market_history,
                holdings=holdings,
            )


class SnapshotSignalTests(unittest.TestCase):
    def test_controllable_dynamic_peer_snapshot_confirms(self):
        result = evaluate_fast_snapshot(direct_snapshot())
        self.assertEqual(result.status, "controllable")
        self.assertTrue(result.warning)
        self.assertTrue(result.causal_confirmed)
        self.assertEqual(result.residual_votes, 3)

    def test_non_peer_failure_is_impossible(self):
        result = evaluate_fast_snapshot(
            direct_snapshot(shadow_drawdown=-0.05)
        )
        self.assertEqual(result.status, "impossible")
        self.assertFalse(result.warning)

    def test_missing_required_evidence_is_unavailable(self):
        result = evaluate_fast_snapshot(
            direct_snapshot(shadow_drawdown=None)
        )
        self.assertEqual(result.status, "unavailable")

    def test_history_must_end_before_decision(self):
        with self.assertRaisesRegex(ValueError, "before the decision"):
            evaluate_fast_snapshot(
                direct_snapshot(history_end_session="2026-08-24")
            )


class GateTests(unittest.TestCase):
    def test_first_warning_is_external_55_percent_ceiling(self):
        state, result = step(
            evidence=evidence("2026-08-24", True),
            state=State(),
        )
        self.assertEqual(state.warning_streak, 1)
        self.assertFalse(result.parent_fast_signal)
        self.assertEqual(result.provisional_ceiling, 0.55)

    def test_second_warning_confirms(self):
        state, _ = step(
            evidence=evidence("2026-08-23", True),
            state=State(),
        )
        _, result = step(
            evidence=evidence("2026-08-24", True),
            state=state,
        )
        self.assertTrue(result.parent_fast_signal)
        self.assertEqual(result.reason, "FASTGATE_CONFIRMED_PERSISTENCE")

    def test_causal_confirmation_is_immediate(self):
        _, result = step(
            evidence=evidence("2026-08-24", True, True),
            state=State(),
        )
        self.assertTrue(result.parent_fast_signal)
        self.assertIsNone(result.provisional_ceiling)

    def test_one_session_warning_clears_immediately(self):
        state, _ = step(
            evidence=evidence("2026-08-23", True),
            state=State(),
        )
        state, result = step(
            evidence=evidence("2026-08-24", False),
            state=state,
        )
        self.assertEqual(state.warning_streak, 0)
        self.assertEqual(
            result.reason,
            "FASTGATE_PROVISIONAL_CLEAR_IMMEDIATE",
        )

    def test_unavailable_evidence_withholds_without_mutation(self):
        state = State(
            warning_streak=1,
            last_session="2026-08-23",
        )
        with self.assertRaises(FastgateEvidenceUnavailable):
            step(
                evidence=evidence(
                    "2026-08-24",
                    False,
                    status="unavailable",
                ),
                state=state,
            )
        self.assertEqual(state.warning_streak, 1)

    def test_inconsistent_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot warn"):
            step(
                evidence=evidence(
                    "2026-08-24",
                    True,
                    status="impossible",
                ),
                state=State(),
            )


class CompositionTests(unittest.TestCase):
    @staticmethod
    def provisional() -> Decision:
        return Decision(
            "2026-08-24",
            1,
            False,
            0.55,
            "FASTGATE_PROVISIONAL_FIRST_WARNING",
            "TEST",
        )

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

    def test_dependency_verification_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = next(iter(AUTHORITATIVE_DEPENDENCY_GIT_BLOBS))
            path = root / first
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not the authoritative dependency", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "dependency mismatch"):
                verify_authoritative_dependencies(root)

    def test_stateful_facade_evaluates_and_decides(self):
        context, market_history, holdings = synthetic_histories()
        fastgate = SentinelFastgate()
        _, signal, decision = fastgate.evaluate_and_decide(
            context=context,
            market_history=market_history,
            holdings=holdings,
        )
        self.assertTrue(signal.causal_confirmed)
        self.assertTrue(decision.parent_fast_signal)


if __name__ == "__main__":
    unittest.main()
