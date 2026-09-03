import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_wayback_nav_probe.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_wayback_nav_probe", MODULE_PATH)
nav = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = nav
SPEC.loader.exec_module(nav)


class RussellNavigationProbeTests(unittest.TestCase):
    def capture(self):
        return nav.archive.Capture(
            query_url="http://www.russell.com/us/indexes/us/reconstitution/schedule.asp",
            timestamp="20060703120000",
            original="http://www.russell.com/US/Indexes/US/reconstitution/schedule.asp",
            statuscode="200",
            mimetype="text/html",
            digest="ABC",
            reported_length="123",
        )

    def test_extracts_only_relevant_links_and_resolves_relative_targets(self):
        payload = b'''<html><body>
        <a href="membership/r3000final.xls">Final Russell 3000 membership</a>
        <a href="about.asp">About Russell</a>
        <a href="deletions.asp">Deletions</a>
        </body></html>'''
        rows = nav.extract_relevant_links("seed", self.capture(), payload)
        self.assertEqual(2, len(rows))
        self.assertTrue(rows[0].resolved_url.endswith("/reconstitution/membership/r3000final.xls"))
        self.assertIn("3000", rows[0].matched_keywords)
        self.assertIn("membership", rows[0].matched_keywords)
        self.assertTrue(rows[1].resolved_url.endswith("/reconstitution/deletions.asp"))

    def test_irrelevant_link_is_ignored(self):
        self.assertIsNone(nav.relevant_link("http://example.test/a/", "about.asp", "About"))


if __name__ == "__main__":
    unittest.main()
