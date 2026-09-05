import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backtester.plan_champion_terminal_integration import plan


class TerminalIntegrationPlanTest(unittest.TestCase):
    def test_maps_cash_and_blocks_election(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            dataset.mkdir()
            observations = dataset / "observations-2020.csv.gz"
            fields = ["session", "security_id", "ticker", "issuer_id", "raw_close"]
            with gzip.open(observations, "wt", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"session": "2020-01-03", "security_id": "CASH", "ticker": "AAA", "issuer_id": "I1", "raw_close": "9"})
                writer.writerow({"session": "2020-01-03", "security_id": "ELECT", "ticker": "BBB", "issuer_id": "I2", "raw_close": "10"})
            digest = hashlib.sha256(observations.read_bytes()).hexdigest()
            (dataset / "manifest.json").write_text(json.dumps({
                "schema": "backtester.canonical-pit-dataset/2", "dataset_hash": "D",
                "members": {observations.name: {"sha256": digest}}
            }))
            base = {"effective_date": "2020-01-06", "last_executable_session": "2020-01-03", "cash_per_share": 5,
                    "share_conversion_ratio": 0, "successor_ticker": None, "terms_known_date": "2019-12-01",
                    "terms_source": "https://www.sec.gov/Archives/edgar/data/a", "completion_source": "https://www.sec.gov/Archives/edgar/data/b"}
            evidence = root / "evidence.json"
            evidence.write_text(json.dumps({
                "schema": "backtester.research-champion-terminal-authority-package/1",
                "events": [{**base, "security_id": "CASH", "ticker": "AAA", "event_type": "cash_merger"},
                           {**base, "security_id": "ELECT", "ticker": "BBB", "event_type": "election_merger"}]
            }))
            value = plan(evidence, dataset, root / "out")
            self.assertEqual(value["integration_ready"], 1)
            self.assertEqual(value["blocked"], 1)
            self.assertEqual(value["records"][0]["kind"], "CASH_MERGER")


if __name__ == "__main__":
    unittest.main()
