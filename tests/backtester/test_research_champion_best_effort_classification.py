import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backtester import research_champion_best_effort_classification as best


FIELDS = [
    "security_id", "ticker", "classification", "disposition", "label", "category",
    "unknown_first_session", "unknown_last_session", "unknown_sessions", "inferred_observations",
    "metadata_firstpricedate", "metadata_lastpricedate", "vendor_permaticker", "figi", "cusips",
    "stage1_status", "known_path_class", "v4_class", "reason",
]


class EstimateTests(unittest.TestCase):
    def make_ledger(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "ledger.csv"
        rows = []
        for i in range(1751):
            value = "common" if i == 0 else "non_common"
            disposition = "INFERRED_COMMON" if value == "common" else "INFERRED_NON_COMMON"
            if i == 1:
                value, disposition = "unknown", "REJECTED_V4_CONFLICT"
            rows.append({key: "" for key in FIELDS} | {
                "security_id": str(i), "ticker": f"T{i}", "classification": value,
                "disposition": disposition, "label": best.LABEL,
                "unknown_first_session": "2006-01-03", "unknown_last_session": "2026-07-31",
            })
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def estimate(self, scenario):
        path = self.make_ledger()
        with patch.object(best, "LEDGER_SHA256", best._sha256(path)):
            return best.SecurityTypeEstimate(path, scenario)

    def test_accepted_classes_and_interval(self):
        value = self.estimate("conflicts_excluded")
        self.assertEqual(value.classify("0", "2012-06-01"), "common")
        self.assertEqual(value.classify("2", "2012-06-01"), "non_common")
        with self.assertRaisesRegex(RuntimeError, "outside admitted interval"):
            value.classify("0", "2005-12-30")

    def test_conflict_is_explicit_sensitivity(self):
        self.assertEqual(self.estimate("conflicts_excluded").classify("1", "2012-06-01"), "unknown")
        self.assertEqual(self.estimate("conflicts_common").classify("1", "2012-06-01"), "common")

    def test_missing_security_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "absent"):
            self.estimate("conflicts_excluded").classify("missing", "2012-06-01")

    def test_reviewed_18_closes_exact_conflict_set(self):
        value = best.SecurityTypeEstimate(best.DEFAULT_LEDGER, "reviewed_18")
        self.assertEqual(value.classify("804009952146469650", "2010-01-04"), "common")
        self.assertEqual(value.classify("1148177820383038150", "2010-01-04"), "non_common")
        self.assertEqual(len(value.reviewed), 18)

    def test_reviewed_frontier_records_economic_contact(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            fields = [
                "security_id", "ticker", "base_candidate_sessions", "eligible_sessions",
                "momentum_pool_sessions", "durable_ranked_sessions", "recent_leadership_sessions",
                "pending_sessions", "held_sessions", "terminal_sessions",
                "incomplete_terminal_sessions", "best_durable_rank",
            ]
            with (output / "strategy-path-worklist.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({key: "" for key in fields} | {
                    "security_id": "804009952146469650", "ticker": "PCG",
                    "base_candidate_sessions": "10", "eligible_sessions": "8",
                    "durable_ranked_sessions": "2", "held_sessions": "1",
                })
            best._write_reviewed_frontier(output)
            result = json.loads((output / "reviewed-security-decision-frontier.json").read_text())
            self.assertEqual(result["counts"]["ECONOMIC_PATH_CONTACT"], 1)
            self.assertEqual(len(result["rows"]), 18)


if __name__ == "__main__":
    unittest.main()
