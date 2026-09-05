import csv
import json
import tempfile
import unittest
from pathlib import Path

from backtester.validate_champion_terminal_evidence import validate


class TerminalEvidenceTest(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path]:
        evidence = root / "evidence.json"
        evidence.write_text(json.dumps({
            "schema": "backtester.research-champion-terminal-authority/1",
            "status": "ACCEPTED",
            "source_champion_run_id": 1,
            "source_priority_run_id": 2,
            "events": [{
                "security_id": "SID1", "ticker": "ABC", "effective_date": "2020-01-06",
                "last_executable_session": "2020-01-03", "event_type": "cash_merger",
                "cash_per_share": 10.0, "successor_ticker": None, "share_conversion_ratio": 0.0,
                "terms_known_date": "2019-12-01", "completion_filed_date": "2020-01-06",
                "terms_source": "https://www.sec.gov/Archives/edgar/data/1/a.htm",
                "completion_source": "https://www.sec.gov/Archives/edgar/data/1/b.htm",
                "authority": "SEC_8_K", "acceptance_status": "ACCEPTED"
            }]
        }))
        priority = root / "priority.csv"
        with priority.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["security_id", "ticker", "priority", "incomplete_terminal_sessions", "held_sessions"])
            writer.writeheader()
            writer.writerow({"security_id": "SID1", "ticker": "ABC", "priority": "1_HELD_POSITION", "incomplete_terminal_sessions": 1, "held_sessions": 4})
        return evidence, priority

    def test_accepts_complete_causal_cash_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, priority = self.fixture(root)
            result = validate(evidence, priority, root / "out")
            self.assertEqual(result["accepted_events"], 1)
            self.assertEqual(result["cash_events"], 1)

    def test_rejects_future_completion_filing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, priority = self.fixture(root)
            value = json.loads(evidence.read_text())
            value["events"][0]["completion_filed_date"] = "2020-01-07"
            evidence.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "non-causal event chronology"):
                validate(evidence, priority, root / "out")


if __name__ == "__main__":
    unittest.main()
