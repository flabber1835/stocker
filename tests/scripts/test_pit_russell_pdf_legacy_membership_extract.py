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


def bbox(lines: list[list[tuple[float, float, str]]], width: float = 612.0) -> str:
    rendered = []
    for words in lines:
        body = "".join(
            f'<word xMin="{x}" yMin="{y}">{text}</word>' for x, y, text in words
        )
        rendered.append(f"<line>{body}</line>")
    return f'<doc><page width="{width}" height="792">{"".join(rendered)}</page></doc>'


class RussellLegacyMembershipExtractTests(unittest.TestCase):
    def test_two_side_by_side_ticker_company_groups(self):
        xml = bbox([[
            (90.0, 100.0, "ABP"), (135.0, 100.0, "ABRAXAS"), (171.0, 100.0, "PETROLEUM"), (220.0, 100.0, "CORP"),
            (330.0, 100.0, "IDRA"), (375.0, 100.0, "IDERA"), (405.0, 100.0, "PHARMACEUTICALS"),
        ]])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], issues)
        self.assertEqual(
            [("ABP", "ABRAXAS PETROLEUM CORP"), ("IDRA", "IDERA PHARMACEUTICALS")],
            [(row.ticker, row.company) for row in rows],
        )

    def test_company_start_may_move_left_of_nominal_tab(self):
        xml = bbox([[
            (330.0, 110.0, "JH"), (345.0, 110.0, "HARLAND"), (390.0, 110.0, "JOHN"), (420.0, 110.0, "H"), (430.0, 110.0, "CO"),
        ]])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], issues)
        self.assertEqual([("JH", "HARLAND JOHN H CO")], [(r.ticker, r.company) for r in rows])

    def test_fragments_at_same_y_are_reconstructed_as_one_visual_row(self):
        xml = bbox([
            [(90.0, 120.0, "ACMR"), (135.0, 120.0, "A"), (145.0, 120.0, "C"), (155.0, 120.0, "MOORE")],
            [(180.0, 120.4, "ARTS"), (205.0, 120.4, "&amp;"), (218.0, 120.4, "CRAFTS")],
        ])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], issues)
        self.assertEqual([("ACMR", "A C MOORE ARTS & CRAFTS")], [(r.ticker, r.company) for r in rows])

    def test_header_at_ticker_anchor_is_ignored(self):
        xml = bbox([[(90.0, 80.0, "Ticker"), (135.0, 80.0, "Company")]])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], rows)
        self.assertEqual([], issues)

    def test_non_ticker_document_furniture_at_anchor_is_ignored(self):
        xml = bbox([[(90.0, 140.0, "Copyright"), (135.0, 140.0, "Frank"), (170.0, 140.0, "Russell")]])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], rows)
        self.assertEqual([], issues)

    def test_anchored_valid_ticker_without_company_is_unexplained(self):
        xml = bbox([[(90.0, 140.0, "ABP")]])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], rows)
        self.assertEqual(1, len(issues))
        self.assertEqual("missing_company", issues[0].reason)

    def test_class_dash_and_suffix_word_tickers_are_preserved(self):
        xml = bbox([
            [(90.0, 150.0, "ACM.A"), (135.0, 150.0, "ACME"), (170.0, 150.0, "HOLDINGS")],
            [(90.0, 160.0, "BRK-B"), (135.0, 160.0, "BERKSHIRE"), (190.0, 160.0, "EXAMPLE")],
            [(90.0, 170.0, "LTD"), (135.0, 170.0, "LIMITED"), (175.0, 170.0, "BRANDS"), (210.0, 170.0, "INC")],
        ])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], issues)
        self.assertEqual(["ACM.A", "BRK-B", "LTD"], [row.ticker for row in rows])

    def test_exact_duplicate_pair_is_deduplicated(self):
        xml = bbox([
            [(90.0, 180.0, "EXM"), (135.0, 180.0, "EXAMPLE"), (175.0, 180.0, "CORP")],
            [(90.0, 190.0, "EXM"), (135.0, 190.0, "EXAMPLE"), (175.0, 190.0, "CORP")],
        ])
        rows, issues = legacy.parse_bbox_records(xml)
        self.assertEqual([], issues)
        self.assertEqual(1, len(rows))

    def test_unexpected_page_width_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected page width"):
            legacy.parse_bbox_records(bbox([[(90.0, 100.0, "EXM"), (135.0, 100.0, "EXAMPLE")]], width=600.0))

    def test_row_hash_is_stable(self):
        xml = bbox([[(90.0, 200.0, "EXM"), (135.0, 200.0, "EXAMPLE"), (175.0, 200.0, "CORP")]])
        first, _ = legacy.parse_bbox_records(xml)
        second, _ = legacy.parse_bbox_records(xml)
        self.assertEqual(first, second)
        self.assertEqual(legacy.rows_sha256(first), legacy.rows_sha256(second))


if __name__ == "__main__":
    unittest.main()
