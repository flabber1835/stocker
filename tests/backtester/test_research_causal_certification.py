"""Tests for retained-research causal-timing certification."""
from __future__ import annotations

import unittest

import pandas as pd

from backtester.research_causal_instrumentation import static_leakage_audit
from backtester.research_causal_runtime import (
    assert_allocation_timing,
    assert_fill_timing,
    assert_med_age119,
    assert_position_age,
    guarded_session_map,
    poison_observation_frame_for_test,
    reject_future,
    reset_causal_clock_for_test,
    activate_session,
)


class CausalRuntimeTest(unittest.TestCase):
    def tearDown(self) -> None:
        reset_causal_clock_for_test()

    def test_direct_future_request_fails_closed(self) -> None:
        activate_session("2006-08-15", 0)
        self.assertEqual(reject_future("2006-08-15", "test"), "2006-08-15")
        with self.assertRaisesRegex(RuntimeError, "requested future session"):
            reject_future("2006-08-16", "test")

    def test_guarded_cached_action_map_rejects_future_key(self) -> None:
        actions = guarded_session_map(
            {
                pd.Timestamp("2006-08-15"): {"MED": []},
                pd.Timestamp("2006-08-16"): {"CSX": []},
            },
            "actions",
        )
        activate_session("2006-08-15", 0)
        self.assertEqual(actions.get(pd.Timestamp("2006-08-15")), {"MED": []})
        with self.assertRaisesRegex(RuntimeError, "actions requested future"):
            actions.get(pd.Timestamp("2006-08-16"))

    def test_close_generated_orders_cannot_fill_same_session(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "filled on signal session"):
            assert_fill_timing(
                kind="buy",
                signal_index=10,
                fill_index=10,
                signal_session="2006-08-15",
                fill_session="2006-08-15",
                close_generated=True,
            )
        assert_fill_timing(
            kind="buy",
            signal_index=10,
            fill_index=11,
            signal_session="2006-08-15",
            fill_session="2006-08-16",
            close_generated=True,
        )

    def test_terminal_open_signal_may_fill_at_same_open(self) -> None:
        assert_fill_timing(
            kind="sell",
            signal_index=10,
            fill_index=10,
            signal_session="2006-08-15",
            fill_session="2006-08-15",
            close_generated=False,
        )

    def test_position_age_is_chronological_session_difference(self) -> None:
        assert_position_age(
            session_index=155,
            entry_index=36,
            observed_age=119,
            security_id="MED-SID",
        )
        with self.assertRaisesRegex(RuntimeError, "position age mismatch"):
            assert_position_age(
                session_index=155,
                entry_index=36,
                observed_age=118,
                security_id="MED-SID",
            )

    def test_allocation_uses_prior_close_pending_target(self) -> None:
        assert_allocation_timing(
            session="2006-08-16",
            prior_pending_native=0.55,
            effective_native=0.55,
            prior_pending={"control": 0.55, "A": 1.0},
            effective={"control": 0.55, "A": 1.0},
        )
        with self.assertRaisesRegex(RuntimeError, "prior-close target"):
            assert_allocation_timing(
                session="2006-08-16",
                prior_pending_native=0.55,
                effective_native=1.0,
                prior_pending={"control": 0.55},
                effective={"control": 1.0},
            )

    def test_med_age119_contract(self) -> None:
        activate_session("2006-08-15", 0)
        assert_med_age119(
            session="2006-08-15",
            entry_session="2006-02-24",
            age=119,
            entry_basis=6.8,
            current_close=12.23,
        )
        with self.assertRaisesRegex(RuntimeError, "entry session changed"):
            assert_med_age119(
                session="2006-08-15",
                entry_session="2006-02-23",
                age=119,
                entry_basis=6.8,
                current_close=12.23,
            )

    def test_future_poison_preserves_prefix_and_structure(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "session": "2006-08-15",
                    "security_id": "1",
                    "ticker": "MED",
                    "issuer_id": "SEC_CIK:910329",
                    "issuer_source": "SEC",
                    "security_type": "common",
                    "security_type_source": "SEC",
                    "security_type_eligible": 1,
                    "sic": "3845",
                    "ff12": "HEALTH",
                    "sector_source": "SEC",
                    "listing_active": 1,
                    "raw_open": 13.15,
                    "raw_close": 12.23,
                    "signal_close": 12.23,
                    "reported_volume": 1000.0,
                    "raw_compatible_volume": 1000.0,
                    "split_ratio": 1.0,
                    "dividend_per_share": 0.0,
                    "tradeable": 1,
                    "metadata_admitted": 1,
                },
                {
                    "session": "2006-08-16",
                    "security_id": "1",
                    "ticker": "MED",
                    "issuer_id": "SEC_CIK:910329",
                    "issuer_source": "SEC",
                    "security_type": "common",
                    "security_type_source": "SEC",
                    "security_type_eligible": 1,
                    "sic": "3845",
                    "ff12": "HEALTH",
                    "sector_source": "SEC",
                    "listing_active": 1,
                    "raw_open": 12.25,
                    "raw_close": 11.99,
                    "signal_close": 11.99,
                    "reported_volume": 1200.0,
                    "raw_compatible_volume": 1200.0,
                    "split_ratio": 1.0,
                    "dividend_per_share": 0.0,
                    "tradeable": 1,
                    "metadata_admitted": 1,
                },
            ]
        )
        poisoned = poison_observation_frame_for_test(frame, "2006-08-15")
        pd.testing.assert_series_equal(poisoned.iloc[0], frame.iloc[0])
        self.assertNotEqual(poisoned.iloc[1].raw_close, frame.iloc[1].raw_close)
        self.assertGreater(float(poisoned.iloc[1].raw_open), 0.0)
        self.assertGreater(float(poisoned.iloc[1].raw_close), 0.0)
        self.assertGreater(float(poisoned.iloc[1].reported_volume), 0.0)
        self.assertIn(poisoned.iloc[1].security_type, {"common", "non_common", "unknown"})


class StaticLeakageAuditTest(unittest.TestCase):
    def test_forbidden_constructs_fail(self) -> None:
        cases = (
            "x.shift(-1)",
            "x.rolling(20, center=True).mean()",
            "x.bfill()",
            "pd.merge_asof(a, b, direction='forward')",
        )
        for index, source in enumerate(cases):
            with self.subTest(source=source):
                report = static_leakage_audit(source, source_name=f"case-{index}.py")
                self.assertEqual(report["status"], "FAIL")
                self.assertTrue(report["blockers"])

    def test_safe_right_aligned_prefix_code_passes(self) -> None:
        source = """
def f(x, gday):
    a = x.rolling(20).mean()
    b = x[(gday-21) % 130]
    return a, b
"""
        report = static_leakage_audit(source, source_name="safe.py")
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["blockers"])


if __name__ == "__main__":
    unittest.main()
