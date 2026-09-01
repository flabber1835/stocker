import json
import tempfile
import unittest
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import verify_historical_metadata_resume_v2 as verify


class VerifyHistoricalMetadataResumeV2Tests(unittest.TestCase):
    def _setup(self, root: Path):
        plan = root / "plan.csv.gz"
        base.write_gzip_csv(plan, ["cik"], [{"cik": "0000000001"}])
        web = root / "web"
        (web / ".http-cache").mkdir(parents=True)
        for name, fields in (
            ("web_identity_sources.csv.gz", ["security_id_hint", "filed", "cik"]),
            ("web_security_type_sources.csv.gz", ["security_id_hint", "filed", "cik", "classification"]),
            ("web_sic_sources.csv.gz", ["filed", "cik", "sic"]),
        ):
            base.write_gzip_csv(web / name, fields, [])
        identity = base.checkpoint_identity("src", "canon", "cand", base.sha256_file(plan), "parser")
        evidence = base.normalized_web_evidence_hash([], [], [])
        checkpoint = {
            "identity": identity,
            "completed_ciks": ["0000000001"],
            "cache_manifest_sha256": base.directory_content_hash(web / ".http-cache"),
            "normalized_evidence_sha256": evidence,
        }
        (web / "checkpoint.json").write_text(json.dumps(checkpoint) + "\n", encoding="utf-8")
        return plan, web

    def test_clean_resume_state_passes(self):
        with tempfile.TemporaryDirectory() as td:
            plan, web = self._setup(Path(td))
            result = verify.verify_resume(plan, web, "src", "canon", "cand", "parser")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["completed_ciks"], 1)

    def test_tampered_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            plan, web = self._setup(Path(td))
            base.write_gzip_csv(web / "web_identity_sources.csv.gz", ["security_id_hint", "filed", "cik"], [{
                "security_id_hint": "sid", "filed": "2006-01-01", "cik": "0000000001"
            }])
            with self.assertRaises(base.ReconstructionError):
                verify.verify_resume(plan, web, "src", "canon", "cand", "parser")

    def test_completed_cik_must_belong_to_plan(self):
        with tempfile.TemporaryDirectory() as td:
            plan, web = self._setup(Path(td))
            checkpoint = json.loads((web / "checkpoint.json").read_text())
            checkpoint["completed_ciks"] = ["0000000002"]
            (web / "checkpoint.json").write_text(json.dumps(checkpoint) + "\n")
            with self.assertRaises(base.ReconstructionError):
                verify.verify_resume(plan, web, "src", "canon", "cand", "parser")


if __name__ == "__main__":
    unittest.main()
