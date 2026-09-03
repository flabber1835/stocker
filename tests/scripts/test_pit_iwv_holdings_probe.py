import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "pit_iwv_holdings_probe.py"
SPEC = importlib.util.spec_from_file_location("pit_iwv_holdings_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class IwvHoldingsProbeTests(unittest.TestCase):
    def sample(self, ticker_column="Ticker"):
        return (
            "iShares Russell 3000 ETF\n"
            'Fund Holdings as of,"Jun 30, 2008"\n'
            "Inception Date,May 22 2000\n"
            "\n"
            f"{ticker_column},Name,Sector,Asset Class,Market Value,CUSIP\n"
            "AAA,ALPHA,Industrials,Equity,100,000000001\n"
            "BBB,BETA,Technology,Equity,200,000000002\n"
            "USD,USD CASH,Cash and/or Derivatives,Cash,50,-\n"
            "\n"
            "The values shown are for research fixture purposes only.\n"
        )

    def test_url_contains_requested_as_of_date(self):
        url = probe.holdings_url("20080630")
        self.assertIn("asOfDate=20080630", url)
        self.assertIn("fileType=csv", url)
        self.assertIn("IWV_holdings", url)

    def test_parser_finds_metadata_schema_and_counts(self):
        parsed = probe.parse_holdings_csv(self.sample().encode())
        self.assertEqual("Jun 30, 2008", parsed["metadata_as_of"])
        self.assertEqual("Ticker", parsed["ticker_column"])
        self.assertTrue(parsed["required_columns_present"])
        self.assertEqual(6, parsed["column_count"])
        self.assertEqual(3, parsed["data_rows"])
        self.assertEqual(2, parsed["equity_rows"])
        self.assertEqual(3, parsed["nonempty_tickers"])
        self.assertEqual(3, parsed["nonempty_cusips"])

    def test_parser_accepts_issuer_ticker_schema(self):
        parsed = probe.parse_holdings_csv(self.sample("Issuer Ticker").encode())
        self.assertEqual("Issuer Ticker", parsed["ticker_column"])
        self.assertEqual(2, parsed["equity_rows"])

    def test_parser_accepts_utf16_export(self):
        parsed = probe.parse_holdings_csv(self.sample("Issuer Ticker").encode("utf-16"))
        self.assertTrue(parsed["source_encoding"].startswith("utf-16"))
        self.assertEqual("Jun 30, 2008", parsed["metadata_as_of"])
        self.assertEqual(3, parsed["data_rows"])

    def test_metadata_match_is_exact(self):
        self.assertTrue(probe._metadata_matches_requested("Jun 30, 2008", "20080630"))
        self.assertFalse(probe._metadata_matches_requested("Jun 29, 2008", "20080630"))

    def test_parser_rejects_non_holdings_payload(self):
        with self.assertRaisesRegex(ValueError, "header not found"):
            probe.parse_holdings_csv(b"<html>not a holdings csv</html>")


if __name__ == "__main__":
    unittest.main()
