from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from backtester.run_certification_parallel import _verify_spy_path_equivalence
from backtester.run_certification_parallel_20y import _first_strategy_divergence


class CertificationParallelTests(unittest.TestCase):
    def test_strategy_boundary_evidence_uses_comparable_semantics(self) -> None:
        production = Path(
            "backtester/run_production_strict_pit_certification.py"
        ).read_text(encoding="utf-8")
        replay = Path(
            "backtester/experiments/2026-08-27-sector-abc/run.py"
        ).read_text(encoding="utf-8")
        self.assertIn("if row.in_top_decile", production)
        self.assertIn("rank_ids = [str(row.security_id) for row in ranked]", production)
        self.assertIn('"ranking_count": len(rank_ids)', production)
        for key in ("episode", "latched", "prev_desired", "prev_native", "streak"):
            self.assertIn(f'"{key}"', replay)

    def test_spy_path_accepts_different_level_anchors(self) -> None:
        dates = pd.to_datetime(["2006-07-31", "2006-08-01", "2006-08-02"])
        production = pd.DataFrame({"date": dates, "spy": [1.02, 1.01, 1.04]})
        research = pd.DataFrame({
            "date": dates,
            "spy": [1.0, 1.01 / 1.02, 1.04 / 1.02],
        })
        evidence = _verify_spy_path_equivalence(production, research)
        self.assertEqual(evidence["normalization_session"], "2006-07-31")
        self.assertEqual(evidence["sessions_compared"], 3)
        self.assertLessEqual(evidence["max_normalized_absolute_delta"], 1e-15)

    def test_spy_path_rejects_economic_divergence(self) -> None:
        dates = pd.to_datetime(["2006-07-31", "2006-08-01"])
        production = pd.DataFrame({"date": dates, "spy": [1.0, 1.01]})
        research = pd.DataFrame({"date": dates, "spy": [1.0, 1.02]})
        with self.assertRaisesRegex(RuntimeError, "after measurement normalization"):
            _verify_spy_path_equivalence(production, research)

    def test_spy_path_rejects_session_axis_difference(self) -> None:
        production = pd.DataFrame({
            "date": pd.to_datetime(["2006-07-31", "2006-08-01"]),
            "spy": [1.0, 1.01],
        })
        research = pd.DataFrame({
            "date": pd.to_datetime(["2006-07-31"]),
            "spy": [1.0],
        })
        with self.assertRaisesRegex(RuntimeError, "session axes diverged"):
            _verify_spy_path_equivalence(production, research)

    def test_first_strategy_divergence_is_chronological_across_fields(self) -> None:
        merged = pd.DataFrame({
            "date": pd.to_datetime(["2006-08-16", "2007-03-30"]),
            "p_universe": [900, 899],
            "r_universe": [900, 900],
            "p_nav": [0.9603, 1.1],
            "r_nav": [0.9609, 1.1],
        })
        found = _first_strategy_divergence(
            merged,
            {
                "eligible_universe": ("p_universe", "r_universe"),
                "nav": ("p_nav", "r_nav"),
            },
            {},
            ("eligible_universe", "nav"),
            1e-10,
        )
        self.assertEqual(found["date"], "2006-08-16")
        self.assertEqual(found["field"], "nav")


if __name__ == "__main__":
    unittest.main()
