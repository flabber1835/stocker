import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_preserved_full_membership_validate.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_preserved_full_membership_validate", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


class PreservedRussellMembershipValidateTests(unittest.TestCase):
    def test_ltd_is_accepted_as_a_real_preserved_source_ticker(self):
        payload = b"Company,Ticker\nLIMITED BRANDS INC,LTD\n"
        tickers, companies = validator.csv_membership(payload)
        self.assertEqual({"LTD"}, tickers)
        self.assertEqual("LIMITED BRANDS INC", companies["LTD"])

    def test_generic_document_token_is_still_rejected(self):
        payload = b"Company,Ticker\nEXAMPLE COMPANY,INDEX\n"
        with self.assertRaises(RuntimeError):
            validator.csv_membership(payload)


if __name__ == "__main__":
    unittest.main()
