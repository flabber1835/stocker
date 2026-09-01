import json
import tempfile
import unittest
from pathlib import Path

from backtester import enforce_historical_metadata_type_authority_v2 as authority
from backtester import historical_metadata_reconstruction_v2 as base


class TypeAuthorityCheckpointV2Tests(unittest.TestCase):
    def test_filter_rebinds_checkpoint_to_filtered_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base.write_gzip_csv(root / "web_identity_sources.csv.gz", ["security_id_hint", "filed", "cik"], [])
            base.write_gzip_csv(root / "web_sic_sources.csv.gz", ["filed", "cik", "sic"], [])
            base.write_gzip_csv(root / "web_security_type_sources.csv.gz", [
                "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
                "security_title_evidence", "authority", "source_url", "source_sha256",
            ], [{
                "security_id_hint": "sid", "accession": "f4", "filed": "2006-01-03",
                "cik": "0000000001", "sec_symbol": "ABC", "document_type": "4",
                "classification": "common", "security_title_evidence": "Common Stock",
                "authority": "raw", "source_url": "u", "source_sha256": "h",
            }])
            before = base.normalized_web_evidence_hash([], base.read_gzip_csv(root / "web_security_type_sources.csv.gz"), [])
            (root / "checkpoint.json").write_text(json.dumps({"normalized_evidence_sha256": before}) + "\n")
            (root / "web_coverage.json").write_text(json.dumps({"status": "PASS", "complete": True}) + "\n")
            authority.filter_web(root)
            checkpoint = json.loads((root / "checkpoint.json").read_text())
            kept = base.read_gzip_csv(root / "web_security_type_sources.csv.gz")
            expected = base.normalized_web_evidence_hash([], kept, [])
            self.assertEqual(kept, [])
            self.assertEqual(checkpoint["normalized_evidence_sha256"], expected)
            self.assertTrue(checkpoint["post_fetch_security_type_authority_filter"])


if __name__ == "__main__":
    unittest.main()
