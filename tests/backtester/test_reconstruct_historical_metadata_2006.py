import unittest

from backtester.reconstruct_historical_metadata_2006 import (
    ISSUER_SYMBOL_RE,
    SIC_RE,
    SECURITY_TITLE_RE,
    classify_titles,
    norm_cik,
    norm_ticker,
)


class HistoricalMetadata2006EvidenceTests(unittest.TestCase):
    def test_ownership_xml_proves_symbol_and_common_title(self):
        text = """
        <issuer><issuerCik>0000123456</issuerCik><issuerTradingSymbol>ABC</issuerTradingSymbol></issuer>
        <securityTitle><value>Common Stock, $0.01 par value</value></securityTitle>
        """
        self.assertEqual({norm_ticker(x) for x in ISSUER_SYMBOL_RE.findall(text)}, {"ABC"})
        titles = SECURITY_TITLE_RE.findall(text)
        self.assertEqual(classify_titles(titles)[0], "common")

    def test_non_common_title_does_not_become_common(self):
        self.assertEqual(classify_titles(["Series A Preferred Stock"])[0], "non_common")
        self.assertEqual(classify_titles(["Warrants to Purchase Common Stock"])[0], "unknown")

    def test_conflicting_titles_fail_closed(self):
        classification, _ = classify_titles(["Common Stock", "Series A Preferred Stock"])
        self.assertEqual(classification, "unknown")

    def test_sic_is_read_from_historical_sec_header(self):
        text = "STANDARD INDUSTRIAL CLASSIFICATION: ELECTRONIC COMPUTERS [3571]"
        self.assertEqual(SIC_RE.search(text).group(1), "3571")

    def test_normalization(self):
        self.assertEqual(norm_ticker(" abc "), "ABC")
        self.assertEqual(norm_cik("12345"), "0000012345")


if __name__ == "__main__":
    unittest.main()
