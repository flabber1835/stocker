import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import parse_historical_metadata_bulk_v2 as bulk


class ParseHistoricalMetadataBulkV2Tests(unittest.TestCase):
    def test_disk_backed_parser_is_deterministic_and_removes_work_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sec = root / "sec"
            sec.mkdir()
            archive = sec / "2006q1_form345.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("SUBMISSION.tsv",
                    "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
                    "a1\t15-JAN-2006\t4\t1\tABC\n")
                zf.writestr("NONDERIV_TRANS.tsv",
                    "ACCESSION_NUMBER\tSECURITY_TITLE\n"
                    "a1\tCommon Stock\n"
                    "a1\tCommon Stock\n")
                zf.writestr("NONDERIV_HOLDING.tsv", "ACCESSION_NUMBER\tSECURITY_TITLE\n")
            candidates = root / "candidates.csv.gz"
            base.write_gzip_csv(candidates, [
                "security_id", "ticker", "first_session", "last_session", "observations",
                "unknown_type_observations", "missing_sector_observations", "observed_ciks",
                "alias_symbol", "alias_safe",
            ], [{
                "security_id": "sid", "ticker": "ABC", "first_session": "2006-01-03",
                "last_session": "2006-12-31", "observations": 1,
                "unknown_type_observations": 1, "missing_sector_observations": 1,
                "observed_ciks": "0000000001", "alias_symbol": "", "alias_safe": "false",
            }])
            out = root / "out"
            with mock.patch.object(base, "expected_archive_names", return_value=[archive.name]):
                result = bulk.parse_bulk(sec, candidates, out)
            self.assertEqual(result["identity_sources"], 1)
            self.assertEqual(result["security_type_sources"], 1)
            self.assertEqual(result["security_title_sources"], 1)
            self.assertEqual(result["staging"], "sqlite_disk_backed_bounded_memory")
            self.assertFalse((out / ".bulk-work.sqlite").exists())
            base.verify_checksums(out)


if __name__ == "__main__":
    unittest.main()
