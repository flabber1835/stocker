import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_coverage_discovery.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_coverage_discovery", MODULE_PATH)
coverage = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = coverage
SPEC.loader.exec_module(coverage)


class RussellCoverageDiscoveryTests(unittest.TestCase):
    def capture(self, timestamp, original):
        return coverage.archive.Capture(
            query_url=original,
            timestamp=timestamp,
            original=original,
            statuscode="200",
            mimetype="application/pdf",
            digest="ABC",
            reported_length="123",
        )

    def test_embedded_document_date(self):
        url = (
            "https://content.ftserussell.com/sites/default/files/"
            "ru3000_membershiplist_20210628.pdf"
        )
        self.assertEqual("20210628", coverage.embedded_document_date(url))

    def test_stable_url_pre_reconstitution_capture_belongs_to_prior_year(self):
        row = self.capture(
            "20100331045830",
            "http://www.russell.com/indexes/documents/Membership/"
            "Russell3000_Membership_List.pdf",
        )
        year, doc_date, inference = coverage.infer_document_year(row)
        self.assertEqual(2009, year)
        self.assertIsNone(doc_date)
        self.assertEqual("stable-url-pre-reconstitution-carry", inference)

    def test_stable_url_post_reconstitution_capture_belongs_to_same_year(self):
        row = self.capture(
            "20100704211111",
            "http://www.russell.com/indexes/documents/Membership/"
            "Russell3000_Membership_List.pdf",
        )
        year, _, inference = coverage.infer_document_year(row)
        self.assertEqual(2010, year)
        self.assertEqual("stable-url-post-reconstitution-capture", inference)

    def test_dated_official_content_is_preferred(self):
        stable = coverage.candidate_from_capture(
            self.capture(
                "20210701000000",
                "http://www.russell.com/indexes/documents/Membership/"
                "Russell3000_Membership_List.pdf",
            )
        )
        dated = coverage.candidate_from_capture(
            self.capture(
                "20210702000000",
                "https://content.ftserussell.com/sites/default/files/"
                "ru3000_membershiplist_20210628.pdf",
            )
        )
        chosen = coverage.choose_year_candidate([stable, dated], 2021)
        self.assertIsNotNone(chosen)
        self.assertEqual("ftse-russell-dated-content", chosen.source_family)

    def test_invalid_filename_date_is_ignored(self):
        self.assertIsNone(
            coverage.embedded_document_date(
                "https://content.ftserussell.com/sites/default/files/"
                "ru3000_membershiplist_20211340.pdf"
            )
        )


if __name__ == "__main__":
    unittest.main()
