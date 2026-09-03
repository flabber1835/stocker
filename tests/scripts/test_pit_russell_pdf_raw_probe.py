import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_pdf_raw_probe.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_pdf_raw_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class RussellPdfRawProbeTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual("ticker", probe.classify_line("ABP"))
        self.assertEqual("text", probe.classify_line("ABRAXAS PETE CORP"))
        self.assertEqual("header", probe.classify_line("Company Symbol"))
        self.assertEqual("numeric", probe.classify_line("12/31/2005"))

    def test_structure_counts_preceding_company_pattern(self):
        text = "Company\nSymbol\nABRAXAS PETE CORP\nABP\nIDERA PHARMACEUTICALS\nIDRA\n"
        result = probe.raw_structure(text)
        self.assertEqual(2, result["preceding_company_candidates"])
        self.assertEqual(2, result["preceding_unique_tickers"])
        # The first ticker is followed by the next company's text, so the diagnostic
        # correctly records one competing following-text candidate as well.
        self.assertEqual(1, result["following_company_candidates"])

    def test_structure_counts_following_company_pattern(self):
        text = "ABP\nABRAXAS PETE CORP\nIDRA\nIDERA PHARMACEUTICALS\n"
        result = probe.raw_structure(text)
        self.assertEqual(2, result["following_company_candidates"])
        self.assertEqual(2, result["following_unique_tickers"])

    def test_diagnostic_prefix_does_not_persist_text(self):
        result = probe.raw_structure("SECRET COMPANY NAME\nSEC\n")
        self.assertNotIn("SECRET", str(result["structure_prefix"]))


if __name__ == "__main__":
    unittest.main()
