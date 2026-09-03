import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_pdf_membership_extract.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_pdf_membership_extract", MODULE_PATH)
extractor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = extractor
SPEC.loader.exec_module(extractor)


class RussellPdfMembershipExtractTests(unittest.TestCase):
    def test_parse_two_company_symbol_pairs(self):
        text = (
            "ABRAXAS PETE CORP          ABP        IDERA PHARMACEUTICALS       IDRA\n"
            "ACME HOLDINGS CLASS A      ACM.A      ZYGO CORP                    ZIGO\n"
        )
        rows = extractor.parse_layout_text(text)
        self.assertEqual(
            [
                ("ABP", "ABRAXAS PETE CORP"),
                ("IDRA", "IDERA PHARMACEUTICALS"),
                ("ACM.A", "ACME HOLDINGS CLASS A"),
                ("ZIGO", "ZYGO CORP"),
            ],
            [(row.ticker, row.company) for row in rows],
        )

    def test_header_and_exchange_tokens_are_not_tickers(self):
        text = (
            "Company                     Symbol     Company                     Symbol\n"
            "Example Corporation         XYZ        NYSE                        Exchange\n"
        )
        rows = extractor.parse_layout_text(text)
        self.assertEqual([("XYZ", "Example Corporation")], [(r.ticker, r.company) for r in rows])

    def test_duplicate_exact_pair_is_deduped(self):
        text = (
            "EXAMPLE CORP                EXM\n"
            "EXAMPLE CORP                EXM\n"
        )
        rows = extractor.parse_layout_text(text)
        self.assertEqual(1, len(rows))

    def test_one_space_inside_company_name_is_preserved(self):
        text = "FIRST NATIONAL BANK CORP      FNB\n"
        rows = extractor.parse_layout_text(text)
        self.assertEqual("FIRST NATIONAL BANK CORP", rows[0].company)
        self.assertEqual("FNB", rows[0].ticker)


if __name__ == "__main__":
    unittest.main()
