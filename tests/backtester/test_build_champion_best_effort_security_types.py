import csv
import gzip
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from backtester.build_champion_best_effort_security_types import LABEL, build


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ChampionBestEffortSecurityTypeTests(unittest.TestCase):
    def test_accepts_unambiguous_categories_and_rejects_conflicts(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            work = root / "work.csv"
            rows = []
            for sid, ticker in (("1", "COM"), ("2", "PREF"), ("3", "FUND"), ("4", "CONFLICT")):
                rows.append({
                    "security_id": sid, "ticker": ticker,
                    "potential_displacer": "True", "unknown_type_base_sessions": "1",
                    "known_common_base_sessions": "0",
                    "known_non_common_base_sessions": "1" if sid == "4" else "0",
                })
            _write_csv(work, rows)

            sessions = root / "sessions.jsonl.gz"
            with gzip.open(sessions, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "session": "2020-01-02",
                    "base_candidate_unknown": ["1", "2", "3", "4"],
                }) + "\n")

            priority = root / "priority.csv"
            _write_csv(priority, [{
                "security_id": sid, "allocation_status": "UNRESOLVED",
                "v4_common_sessions": "0", "v4_non_common_sessions": "0",
            } for sid in ("1", "2", "3", "4")])

            metadata_csv = root / "tickers.csv"
            metadata = []
            categories = {
                "COM": "Domestic Common Stock",
                "PREF": "Domestic Preferred Stock",
                "FUND": "Domestic Closed End Fund",
                "CONFLICT": "Domestic Common Stock",
            }
            for ticker, category in categories.items():
                metadata.append({
                    "table": "SEP", "ticker": ticker, "category": category,
                    "firstpricedate": "2019-01-01", "lastpricedate": "2021-01-01",
                    "permaticker": ticker, "figi": ticker, "cusips": ticker,
                })
            _write_csv(metadata_csv, metadata)
            tickers = root / "tickers.zip"
            with zipfile.ZipFile(tickers, "w") as archive:
                archive.write(metadata_csv, arcname="tickers.csv")

            result = build(
                worklist=work, session_ledger=sessions, stage1_priority=priority,
                tickers=tickers, output=root / "out", enforce_frozen_inputs=False,
            )
            self.assertFalse(result["certification_eligible"])
            self.assertEqual(result["label"], LABEL)
            self.assertEqual(result["counts"]["classification"], {
                "common": 1, "non_common": 1, "unknown": 2,
            })
            with (root / "out/security-type-best-effort.csv").open() as handle:
                ledger = {row["ticker"]: row for row in csv.DictReader(handle)}
            self.assertEqual(ledger["COM"]["disposition"], "INFERRED_COMMON")
            self.assertEqual(ledger["PREF"]["disposition"], "INFERRED_NON_COMMON")
            self.assertEqual(ledger["FUND"]["disposition"], "REJECTED_AMBIGUOUS_CATEGORY")
            self.assertEqual(ledger["CONFLICT"]["disposition"], "REJECTED_KNOWN_PATH_CONFLICT")

    def test_rejects_metadata_outside_unknown_session_interval(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            work = root / "work.csv"
            _write_csv(work, [{
                "security_id": "1", "ticker": "LATE", "potential_displacer": "True",
                "unknown_type_base_sessions": "1", "known_common_base_sessions": "0",
                "known_non_common_base_sessions": "0",
            }])
            sessions = root / "sessions.jsonl.gz"
            with gzip.open(sessions, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"session": "2020-01-02", "base_candidate_unknown": ["1"]}) + "\n")
            priority = root / "priority.csv"
            _write_csv(priority, [{
                "security_id": "1", "allocation_status": "UNRESOLVED",
                "v4_common_sessions": "0", "v4_non_common_sessions": "0",
            }])
            metadata_csv = root / "tickers.csv"
            _write_csv(metadata_csv, [{
                "table": "SEP", "ticker": "LATE", "category": "Domestic Common Stock",
                "firstpricedate": "2020-02-01", "lastpricedate": "2021-01-01",
                "permaticker": "1", "figi": "1", "cusips": "1",
            }])
            tickers = root / "tickers.zip"
            with zipfile.ZipFile(tickers, "w") as archive:
                archive.write(metadata_csv, arcname="tickers.csv")
            result = build(
                worklist=work, session_ledger=sessions, stage1_priority=priority,
                tickers=tickers, output=root / "out", enforce_frozen_inputs=False,
            )
            self.assertEqual(result["counts"]["disposition"], {"REJECTED_PRICE_INTERVAL": 1})


if __name__ == "__main__":
    unittest.main()
