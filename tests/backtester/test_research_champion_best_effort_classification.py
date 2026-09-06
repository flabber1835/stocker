import csv
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


if __name__ == "__main__":
    unittest.main()
