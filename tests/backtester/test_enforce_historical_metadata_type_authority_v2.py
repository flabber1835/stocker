import json
import tempfile
import unittest
from pathlib import Path

from backtester import enforce_historical_metadata_type_authority_v2 as authority
from backtester import historical_metadata_reconstruction_v2 as base


class HistoricalMetadataTypeAuthorityV2Tests(unittest.TestCase):
    def test_form345_titles_are_supplementary_not_listed_class_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base.write_gzip_csv(root / "bulk_security_type_sources.csv.gz", [
                "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
                "security_title_evidence", "authority", "archive", "archive_sha256",
            ], [{
                "accession": "a", "filed": "2006-01-03", "cik": "0000000001",
                "sec_symbol": "ABC", "document_type": "4", "classification": "common",
                "security_title_evidence": "Common Stock", "authority": "raw",
                "archive": "2006q1_form345.zip", "archive_sha256": "x",
            }])
            (root / "bulk_coverage.json").write_text("{}\n", encoding="utf-8")
            result = authority.demote_bulk(root)
            row = base.read_gzip_csv(root / "bulk_security_type_sources.csv.gz")[0]
            self.assertEqual(row["classification"], "unknown")
            self.assertEqual(row["observed_classification"], "common")
            self.assertEqual(result["form345_type_role"], "supplementary_only_not_admitted")

    def test_web_type_authority_keeps_periodic_cover_and_rejects_ownership_form(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fields = [
                "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
                "security_title_evidence", "authority", "source_url", "source_sha256",
            ]
            base.write_gzip_csv(root / "web_security_type_sources.csv.gz", fields, [
                {"security_id_hint": "sid", "accession": "k", "filed": "2006-02-01",
                 "cik": "0000000001", "sec_symbol": "ABC", "document_type": "10-K",
                 "classification": "common", "security_title_evidence": "Common Stock Trading Symbol ABC",
                 "authority": "raw", "source_url": "u1", "source_sha256": "h1"},
                {"security_id_hint": "sid", "accession": "f4", "filed": "2006-03-01",
                 "cik": "0000000001", "sec_symbol": "ABC", "document_type": "4",
                 "classification": "common", "security_title_evidence": "Common Stock",
                 "authority": "raw", "source_url": "u2", "source_sha256": "h2"},
            ])
            (root / "web_coverage.json").write_text(json.dumps({"status": "PASS", "complete": True}) + "\n")
            result = authority.filter_web(root)
            kept = base.read_gzip_csv(root / "web_security_type_sources.csv.gz")
            rejected = base.read_gzip_csv(root / "web_security_type_rejected.csv.gz")
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["document_type"], "10-K")
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0]["document_type"], "4")
            self.assertEqual(result["admitted_security_type_sources"], 1)


if __name__ == "__main__":
    unittest.main()
