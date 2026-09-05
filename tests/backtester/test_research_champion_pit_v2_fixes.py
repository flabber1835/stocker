from __future__ import annotations

import csv
import gzip
import importlib.util
from pathlib import Path
import tempfile
import unittest

from backtester import certify_backtest_result_v2 as certv2
from backtester import research_champion_terminal_leadership_overlay as leadership


def write_gzip(path: Path, fieldnames, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class ChampionPitV2FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_pytest_package_identity_is_unambiguous(self):
        self.assertTrue(Path("tests/__init__.py").is_file())
        spec = importlib.util.find_spec("tests.backtester.conftest")
        self.assertIsNotNone(spec)
        self.assertEqual(Path(spec.origin).resolve(), Path("tests/backtester/conftest.py").resolve())

    def test_same_session_terminal_is_removed_from_next_leadership_witness(self):
        source = "            " + leadership._OLD + "\n"
        out = leadership.install_terminal_leadership_filter(source)
        self.assertNotIn(leadership._OLD, out)
        self.assertIn("_leadership_terminal_tids.update(_exact_terminal_by_session.get(ds,{}))", out)
        self.assertIn("int(t) not in _leadership_terminal_tids", out)

    def test_explicit_schema_v2_unknown_is_resolved_fail_closed_ineligible(self):
        row = {
            "session": "2006-01-03", "security_id": "1", "ticker": "AAA",
            "listing_active": "1", "security_type": "",
            "security_type_eligible": "0", "metadata_admitted": "0",
        }
        write_gzip(self.root / "observations-2006.csv.gz", list(row), [row])
        manifest = {
            "members": {"observations-2006.csv.gz": {}},
            "counts": {"unknown_security_type_observations": 1, "incomplete_terminal_terms": 0},
            "identity_audit": {"blocking_identity_conflicts": 0},
        }
        out = certv2.audit_universe_resolution_v2(self.root, manifest)
        self.assertEqual(out["unresolved"], 0)
        self.assertEqual(out["unknown_security_type"], 1)
        self.assertEqual(out["unknown_security_type_explicit_fail_closed"], 1)
        self.assertEqual(out["resolved_pit_ineligible"], 1)

    def test_unknown_without_explicit_fail_closed_fields_remains_unresolved(self):
        row = {
            "session": "2006-01-03", "security_id": "1", "ticker": "AAA",
            "listing_active": "1", "security_type": "",
        }
        write_gzip(self.root / "observations-2006.csv.gz", list(row), [row])
        manifest = {
            "members": {"observations-2006.csv.gz": {}},
            "counts": {"unknown_security_type_observations": 1, "incomplete_terminal_terms": 0},
            "identity_audit": {"blocking_identity_conflicts": 0},
        }
        out = certv2.audit_universe_resolution_v2(self.root, manifest)
        self.assertEqual(out["unresolved"], 1)

    def test_explicit_incomplete_terminal_ledger_closes_dataset_accounting(self):
        row = {
            "effective_session": "2007-01-03", "security_id": "9", "ticker": "ZZZ",
            "kind": "CASH_MERGER", "disposition": "PIT_ACTION_INCOMPLETE:MISSING_CASH_PER_SHARE",
            "cash_per_share": "", "delivered_security_id": "", "delivered_ticker": "",
            "delivered_issuer_id": "", "exchange_ratio": "",
            "cash_in_lieu_price_per_delivered_share": "", "reference": "actions/delisted",
            "authority": "PIT_ACTIONS", "evidence_hash": "",
        }
        write_gzip(self.root / "terminal-events.csv.gz", list(row), [row])
        manifest = {"counts": {"incomplete_terminal_terms": 1}}
        out = certv2.audit_terminal_accounting_v2(self.root, manifest)
        self.assertTrue(out["complete"])
        self.assertEqual(out["represented_fail_closed_terminal_terms"], 1)

    def test_declared_incomplete_terminal_without_ledger_row_fails(self):
        fields = [
            "effective_session", "security_id", "ticker", "kind", "disposition",
            "cash_per_share", "delivered_security_id", "delivered_ticker",
            "delivered_issuer_id", "exchange_ratio",
            "cash_in_lieu_price_per_delivered_share", "reference", "authority", "evidence_hash",
        ]
        write_gzip(self.root / "terminal-events.csv.gz", fields, [])
        out = certv2.audit_terminal_accounting_v2(
            self.root, {"counts": {"incomplete_terminal_terms": 1}}
        )
        self.assertFalse(out["complete"])


if __name__ == "__main__":
    unittest.main()
