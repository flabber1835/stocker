from __future__ import annotations

import unittest

from backtester import reconstruct_historical_metadata_year as yearly


class HistoricalMetadataYearTests(unittest.TestCase):
    def test_choose_filings_carries_opening_evidence_and_target_year(self) -> None:
        rows = [
            {"accessionNumber": "a", "filingDate": "2008-06-01", "form": "4", "primaryDocument": "a.xml"},
            {"accessionNumber": "b", "filingDate": "2009-11-01", "form": "4", "primaryDocument": "b.xml"},
            {"accessionNumber": "c", "filingDate": "2010-02-01", "form": "4", "primaryDocument": "c.xml"},
            {"accessionNumber": "d", "filingDate": "2010-10-01", "form": "4", "primaryDocument": "d.xml"},
            {"accessionNumber": "e", "filingDate": "2009-03-01", "form": "10-K", "primaryDocument": "e.htm"},
            {"accessionNumber": "f", "filingDate": "2010-03-01", "form": "10-K", "primaryDocument": "f.htm"},
        ]
        selected = yearly.choose_filings(rows, 2010, "2007-01-01", "2010-12-31")
        self.assertEqual({r["accessionNumber"] for r in selected}, {"b", "c", "d", "e", "f"})

    def test_choose_filings_excludes_future_year(self) -> None:
        rows = [
            {"accessionNumber": "a", "filingDate": "2011-01-02", "form": "4", "primaryDocument": "a.xml"},
            {"accessionNumber": "b", "filingDate": "2010-12-30", "form": "4", "primaryDocument": "b.xml"},
        ]
        selected = yearly.choose_filings(rows, 2010, "2007-01-01", "2010-12-31")
        self.assertEqual([r["accessionNumber"] for r in selected], ["b"])

    def test_source_window_is_strictly_historical(self) -> None:
        year = 2020
        self.assertEqual(f"{year - 3}-01-01", "2017-01-01")
        self.assertEqual(f"{year}-12-31", "2020-12-31")


if __name__ == "__main__":
    unittest.main()
