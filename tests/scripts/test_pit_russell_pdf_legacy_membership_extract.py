import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_pdf_legacy_membership_extract.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_pdf_legacy_membership_extract", MODULE_PATH)
legacy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = legacy
SPEC.loader.exec_module(legacy)


class RussellLegacyMembershipExtractTests(unittest.TestCase):
    def test_terminal_ticker_record(self):
        rows = legacy.parse_raw_records("ABRAXAS PETROLEUM CORP ABP\nIDERA PHARMACEUTICALS IDRA\n")
        self.assertEqual(
            [("ABP", "ABRAXAS PETROLEUM CORP"), ("IDRA", "IDERA PHARMACEUTICALS")],
            [(row.ticker, row.company) for row in rows],
        )

    def test_class_and_dot_tickers_are_preserved(self):
        rows = legacy.parse_raw_records("ACME HOLDINGS CLASS A ACM.A\nBERKSHIRE EXAMPLE BRK-B\n")
        self.assertEqual(["ACM.A", "BRK-B"], [row.ticker for row in rows])

    def test_headers_and_footer_are_rejected(self):
        text = (
            "Russell 3000 Index Membership List R3000\n"
            "Company Symbol\n"
            "EXAMPLE CORP EXM\n"
            "Copyright 2005 Russell Investment Group\n"
            "Page 1\n"
        )
        rows = legacy.parse_raw_records(text)
        self.assertEqual([("EXM", "EXAMPLE CORP")], [(row.ticker, row.company) for row in rows])

    def test_non_terminal_ticker_is_not_guessed(self):
        rows = legacy.parse_raw_records("EXM EXAMPLE CORP\n")
        self.assertEqual([], rows)

    def test_exact_duplicate_is_deduplicated(self):
        rows = legacy.parse_raw_records("EXAMPLE CORP EXM\nEXAMPLE CORP EXM\n")
        self.assertEqual(1, len(rows))

    def test_conflicting_company_labels_are_preserved_for_ambiguity_gate(self):
        rows = legacy.parse_raw_records("EXAMPLE CORP EXM\nEXAMPLE HOLDINGS EXM\n")
        self.assertEqual(2, len(rows))


if __name__ == "__main__":
    unittest.main()
