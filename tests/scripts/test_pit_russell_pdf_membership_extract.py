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

    def test_bbox_parser_uses_two_explicit_company_symbol_columns(self):
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <doc><page width="400" height="600"><flow><block>
          <line xMin="10" yMin="10"><word xMin="10" yMin="10">Company</word><word xMin="100" yMin="10">Symbol</word></line>
          <line xMin="210" yMin="10.2"><word xMin="210" yMin="10.2">Company</word><word xMin="300" yMin="10.2">Symbol</word></line>
          <line xMin="10" yMin="30"><word xMin="10" yMin="30">ABRAXAS</word><word xMin="35" yMin="30">PETE</word><word xMin="55" yMin="30">CORP</word><word xMin="100" yMin="30">ABP</word></line>
          <line xMin="210" yMin="30.3"><word xMin="210" yMin="30.3">IDERA</word><word xMin="238" yMin="30.3">PHARMACEUTICALS</word><word xMin="300" yMin="30.3">IDRA</word></line>
        </block></flow></page></doc>'''
        rows = extractor.parse_bbox_xml(xml)
        self.assertEqual(
            [("ABP", "ABRAXAS PETE CORP"), ("IDRA", "IDERA PHARMACEUTICALS")],
            [(row.ticker, row.company) for row in rows],
        )

    def test_bbox_header_positions_require_company_then_symbol(self):
        words = [
            extractor.PositionedWord(10, 10, "Symbol"),
            extractor.PositionedWord(100, 10, "Company"),
        ]
        self.assertIsNone(extractor._header_positions(words))

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
