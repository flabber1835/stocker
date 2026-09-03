import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


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

    def test_fetch_seed_captures_uses_archive_request_seam(self):
        payload = json.dumps(
            [
                list(nav.archive.CDX_FIELDS),
                [
                    "20060703120000",
                    "http://www.russell.com/US/Indexes/US/reconstitution/schedule.asp",
                    "200",
                    "text/html",
                    "ABC",
                    "123",
                ],
            ]
        ).encode()
        with mock.patch.object(
            nav.archive,
            "_request",
            return_value=(payload, 200, "application/json", "https://web.archive.org/cdx/search/cdx"),
        ) as request:
            rows = nav.fetch_seed_captures(
                "http://www.russell.com/us/indexes/us/reconstitution/schedule.asp",
                2005,
                2008,
                20,
                3,
            )
        self.assertEqual(1, len(rows))
        self.assertEqual("ABC", rows[0].digest)
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
