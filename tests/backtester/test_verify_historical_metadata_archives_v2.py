import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import verify_historical_metadata_archives_v2 as verify


class VerifyHistoricalMetadataArchivesV2Tests(unittest.TestCase):
    def test_exact_sha256_and_size_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sec = root / "sec"
            sec.mkdir()
            archive = sec / "2006q1_form345.zip"
            archive.write_bytes(b"archive")
            coverage = root / "coverage.json"
            coverage.write_text(json.dumps({
                "archive_count": 1,
                "archives": [{
                    "archive": archive.name,
                    "sha256": base.sha256_file(archive),
                    "size_bytes": archive.stat().st_size,
                }],
            }) + "\n")
            lock = root / "lock.json"
            lock.write_text(json.dumps({"sec_bulk": {
                "first_year": 2006, "through_year": 2006, "through_quarter": 1,
            }}) + "\n")
            with mock.patch.object(base, "expected_archive_names", return_value=[archive.name]):
                result = verify.verify_archives(sec, coverage, lock)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["archive_count"], 1)

            archive.write_bytes(b"tampered")
            with mock.patch.object(base, "expected_archive_names", return_value=[archive.name]):
                with self.assertRaises(base.ReconstructionError):
                    verify.verify_archives(sec, coverage, lock)

    def test_manifest_must_cover_exact_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sec = root / "sec"
            sec.mkdir()
            coverage = root / "coverage.json"
            coverage.write_text(json.dumps({"archive_count": 0, "archives": []}) + "\n")
            lock = root / "lock.json"
            lock.write_text(json.dumps({"sec_bulk": {
                "first_year": 2006, "through_year": 2006, "through_quarter": 1,
            }}) + "\n")
            with mock.patch.object(base, "expected_archive_names", return_value=["2006q1_form345.zip"]):
                with self.assertRaises(base.ReconstructionError):
                    verify.verify_archives(sec, coverage, lock)


if __name__ == "__main__":
    unittest.main()
