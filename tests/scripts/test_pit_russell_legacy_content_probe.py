import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_legacy_content_probe.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_legacy_content_probe", MODULE_PATH)
legacy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = legacy
SPEC.loader.exec_module(legacy)


class RussellLegacyContentProbeTests(unittest.TestCase):
    def capture(self, original="http://www.russell.com/indexes/membership/Reconstitution/Recon_3000_Additions.asp"):
        return legacy.archive.Capture(
            query_url=original,
            timestamp="20080628165955",
            original=original,
            statuscode="200",
            mimetype="text/html",
            digest="ABC",
            reported_length="123",
        )

    def test_endpoint_kind(self):
        self.assertEqual("membership", legacy.endpoint_kind("http://x/membership.asp"))
        self.assertEqual("additions", legacy.endpoint_kind("http://x/recon_additions.asp"))
        self.assertEqual("deletions", legacy.endpoint_kind("http://x/recon_deletions.asp"))

    def test_extracts_artifact_links_and_ticker_rows(self):
        payload = b'''<html><body>
        <a href="files/Russell3000_final_2008.xls">Final Russell 3000 membership</a>
        <a href="about.asp">About</a>
        <table>
          <tr><th>Company</th><th>Ticker</th></tr>
          <tr><td>Example Holdings Inc.</td><td>EXM</td></tr>
          <tr><td>Acme Class A</td><td>ACM.A</td></tr>
        </table>
        </body></html>'''
        links, rows = legacy.extract_evidence(self.capture(), payload)
        self.assertEqual(1, len(links))
        self.assertTrue(links[0].resolved_url.endswith("/Reconstitution/files/Russell3000_final_2008.xls"))
        self.assertEqual(["ACM.A", "EXM"], sorted(row.ticker for row in rows))
        self.assertTrue(all(row.endpoint_kind == "additions" for row in rows))

    def test_extracts_both_company_ticker_pairs_from_one_russell_row(self):
        payload = b'''<table>
          <tr><td>ABRAXAS PETE CORP</td><td>ABP</td><td>IDERA PHARMACEUTICALS</td><td>IDRA</td></tr>
        </table>'''
        _, rows = legacy.extract_evidence(self.capture(), payload)
        self.assertEqual(
            [("ABP", "ABRAXAS PETE CORP"), ("IDRA", "IDERA PHARMACEUTICALS")],
            [(row.ticker, row.label) for row in rows],
        )

    def test_rejects_navigation_header_as_candidate(self):
        rows = legacy.candidates_from_cells(
            ["Company", "Ticker"], "20080628165955", "http://x/membership.asp", "membership"
        )
        self.assertEqual([], rows)

    def test_candidate_keeps_company_label_and_ignores_exchange_cell(self):
        rows = legacy.candidates_from_cells(
            ["Example Corporation", "XYZ", "NYSE"],
            "20080628165955",
            "http://x/recon_deletions.asp",
            "deletions",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("XYZ", rows[0].ticker)
        self.assertEqual("Example Corporation", rows[0].label)


if __name__ == "__main__":
    unittest.main()
