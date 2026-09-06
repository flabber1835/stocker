import unittest

from backtester.research_champion_wayback_security_types import matches, visible_text


class WaybackEvidenceTests(unittest.TestCase):
    def test_limited_partner_units_are_non_common(self):
        implication, context = matches("The partnership's common units represent limited partner interests.")
        self.assertEqual(implication, "non_common")
        self.assertIn("common units", context)

    def test_shares_of_common_stock_are_common(self):
        self.assertEqual(matches("Holders of shares of common stock may vote.")[0], "common")

    def test_mixed_language_stays_conflicted(self):
        text = "Our common shares were exchanged for common units representing limited partner interests."
        self.assertEqual(matches(text)[0], "conflict")

    def test_html_is_reduced_to_visible_text(self):
        text = visible_text(b"<style>common units</style><p>shares of common stock</p>")
        self.assertEqual(matches(text)[0], "common")


if __name__ == "__main__":
    unittest.main()
