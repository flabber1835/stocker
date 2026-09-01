import tempfile
import unittest
from pathlib import Path

from backtester import bound_historical_metadata_web_plan_v2 as bounds
from backtester import historical_metadata_reconstruction_v2 as base


class BoundHistoricalMetadataWebPlanV2Tests(unittest.TestCase):
    def test_source_window_ends_at_first_unresolved_observation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base.write_gzip_csv(root / "web_plan.csv.gz", [
                "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type", "need_sic",
                "discovery_only_cik_hint", "first_session", "last_session", "first_need_session",
                "first_unknown_type_session", "first_missing_sector_session",
            ], [{
                "security_id": "sid", "ticker": "ABC", "alias_symbol": "", "cik": "0000000001",
                "need_identity": "true", "need_type": "true", "need_sic": "true",
                "discovery_only_cik_hint": "true", "first_session": "2006-01-03",
                "last_session": "2026-07-31", "first_need_session": "2015-04-06",
                "first_unknown_type_session": "2015-04-06", "first_missing_sector_session": "2015-04-06",
            }])
            (root / "web_plan_coverage.json").write_text("{}\n", encoding="utf-8")
            result = bounds.bound_plan(root)
            row = base.read_gzip_csv(root / "web_plan.csv.gz")[0]
            self.assertEqual(row["first_session"], "2015-04-06")
            self.assertEqual(row["last_session"], "2015-04-06")
            self.assertEqual(row["episode_first_session"], "2006-01-03")
            self.assertEqual(row["episode_last_session"], "2026-07-31")
            self.assertIn("three-year lookback", result["source_selection_rule"])

    def test_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base.write_gzip_csv(root / "web_plan.csv.gz", [
                "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type", "need_sic",
                "discovery_only_cik_hint", "first_session", "last_session", "first_need_session",
                "first_unknown_type_session", "first_missing_sector_session",
            ], [{
                "security_id": "sid", "ticker": "ABC1", "alias_symbol": "ABC", "cik": "0000000001",
                "need_identity": "true", "need_type": "true", "need_sic": "true",
                "discovery_only_cik_hint": "true", "first_session": "2006-01-03",
                "last_session": "2006-12-31", "first_need_session": "2006-01-03",
                "first_unknown_type_session": "2006-01-03", "first_missing_sector_session": "2006-01-03",
            }])
            (root / "web_plan_coverage.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(base.ReconstructionError):
                bounds.bound_plan(root)


if __name__ == "__main__":
    unittest.main()
