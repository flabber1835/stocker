import json
import tempfile
import unittest
from pathlib import Path

from backtester import derive_historical_metadata_timeline_guarded_v2 as guarded
from backtester import historical_metadata_reconstruction_v2 as base
from backtester import merge_historical_metadata_web_shards_v2 as merge_web
from backtester import sanitize_historical_metadata_candidates_v2 as sanitize_candidates
from backtester import shard_historical_metadata_web_plan_v2 as shard_plan


CANDIDATE_FIELDS = [
    "security_id", "ticker", "first_session", "last_session", "observations",
    "unknown_type_observations", "missing_sector_observations", "observed_ciks",
    "alias_symbol", "alias_safe",
]


class HistoricalMetadataV2DeploymentTests(unittest.TestCase):
    def test_workflow_uses_import_safe_module_entrypoints(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "backtester-historical-metadata-reconstruction-v2.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("python backtester/", workflow)
        modules = (
            "historical_metadata_reconstruction_v2",
            "verify_historical_metadata_archives_v2",
            "canonical_pit_package",
            "sanitize_historical_metadata_candidates_v2",
            "build_historical_metadata_episode_guard_v2",
            "parse_historical_metadata_bulk_v2",
            "enforce_historical_metadata_type_authority_v2",
            "derive_historical_metadata_timeline_guarded_v2",
            "bound_historical_metadata_web_plan_v2",
            "shard_historical_metadata_web_plan_v2",
            "run_historical_metadata_web_shard_v2",
            "merge_historical_metadata_web_shards_v2",
        )
        for module in modules:
            self.assertIn(f"python -m backtester.{module}", workflow)

    def test_candidate_sanitizer_removes_invalid_cik_and_disables_vendor_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base.write_gzip_csv(root / "candidate_episodes.csv.gz", CANDIDATE_FIELDS, [{
                "security_id": "247195603529201713", "ticker": "ABC1",
                "first_session": "2006-01-03", "last_session": "2006-12-29", "observations": 10,
                "unknown_type_observations": 10, "missing_sector_observations": 10,
                "observed_ciks": "247195603529201713;12345",
                "alias_symbol": "ABC", "alias_safe": "true",
            }])
            (root / "candidate_coverage.json").write_text("{}\n", encoding="utf-8")
            result = sanitize_candidates.sanitize(root)
            row = base.read_gzip_csv(root / "candidate_episodes.csv.gz")[0]
            self.assertEqual(row["observed_ciks"], "0000012345")
            self.assertEqual(row["alias_symbol"], "")
            self.assertEqual(row["alias_safe"], "false")
            self.assertEqual(result["candidate_aliases_admitted"], 0)
            self.assertEqual(result["security_id_in_cik_fields"], 0)

    def test_prestart_identity_seed_is_blocked_by_intervening_ticker_episode(self):
        candidate = base.CandidateEpisode(
            "new", "ABC", "2009-01-02", "2009-12-31", 10, 10, 10, ("0000000002",)
        )
        guard = {
            "ABC": [
                {"security_id": "old", "ticker": "ABC", "first_session": "2006-01-03", "last_session": "2008-03-31"},
                {"security_id": "new", "ticker": "ABC", "first_session": "2009-01-02", "last_session": "2009-12-31"},
            ]
        }
        self.assertFalse(guarded._prestart_allowed(candidate, "2007-06-01", guard))
        self.assertTrue(guarded._prestart_allowed(candidate, "2008-06-01", guard))
        self.assertFalse(guarded._prestart_allowed(candidate, "2005-12-31", guard))

    def test_guarded_identity_allocation_never_uses_alias(self):
        candidate = base.CandidateEpisode(
            "sid", "ABC1", "2006-01-03", "2006-12-29", 10, 10, 10, (), "ABC", True
        )
        with self.assertRaises(base.ReconstructionError):
            guarded.allocate_identity_events_guarded([candidate], [], {})

    def test_stable_cik_shards_keep_one_cik_in_one_partition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan"
            plan.mkdir()
            rows = [
                {"security_id": "a", "ticker": "AAA", "alias_symbol": "", "cik": "1", "first_session": "2006-01-03", "last_session": "2006-01-03"},
                {"security_id": "b", "ticker": "BBB", "alias_symbol": "", "cik": "1", "first_session": "2007-01-03", "last_session": "2007-01-03"},
                {"security_id": "c", "ticker": "CCC", "alias_symbol": "", "cik": "2", "first_session": "2006-01-03", "last_session": "2006-01-03"},
            ]
            base.write_gzip_csv(plan / "web_plan.csv.gz", shard_plan.FIELDS, rows)
            out = root / "shards"
            result = shard_plan.shard_plan(plan, out, shards=4)
            seen = {}
            for index in range(4):
                for row in base.read_gzip_csv(out / f"web_plan_shard_{index:02d}.csv.gz"):
                    seen.setdefault(row["cik"], set()).add(index)
            self.assertEqual(result["unique_valid_ciks"], 2)
            self.assertTrue(all(len(shards) == 1 for shards in seen.values()))

    def _write_empty_web_shard(self, root: Path, label: str):
        root.mkdir(parents=True)
        base.write_gzip_csv(root / "web_source_manifest.csv.gz", [
            "url", "status", "path", "sha256", "bytes", "attempts", "terminal_absence", "retrieved_at", "artifact_member"
        ], [])
        base.write_gzip_csv(root / "web_identity_sources.csv.gz", [
            "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind", "source_url", "source_sha256"
        ], [])
        base.write_gzip_csv(root / "web_security_type_sources.csv.gz", [
            "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
            "security_title_evidence", "authority", "source_url", "source_sha256"
        ], [])
        base.write_gzip_csv(root / "web_security_type_rejected.csv.gz", [
            "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification", "reason", "source_url", "source_sha256"
        ], [])
        base.write_gzip_csv(root / "web_sic_sources.csv.gz", [
            "filed", "cik", "sic", "source_kind", "accession", "source_url", "source_sha256"
        ], [])
        (root / "web_coverage.json").write_text(json.dumps({
            "status": "PASS", "complete": True, "planned_unique_ciks": 0,
            "completed_unique_ciks": 0, "transport": {}, "terminal_source_absences": 0,
        }) + "\n", encoding="utf-8")
        (root / "shard_runner_coverage.json").write_text(json.dumps({"status": "PASS", "shard": label}) + "\n", encoding="utf-8")
        base.write_checksums(root)

    def test_web_merge_requires_complete_shard_inventory_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shards = root / "inputs"
            self._write_empty_web_shard(shards / "artifact-00", "00")
            self._write_empty_web_shard(shards / "artifact-01", "01")
            out1 = root / "out1"
            out2 = root / "out2"
            first = merge_web.merge(shards, out1, expected_shards=2)
            second = merge_web.merge(shards, out2, expected_shards=2)
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(first["normalized_evidence_sha256"], second["normalized_evidence_sha256"])
            self.assertEqual(base.sha256_file(out1 / "SHA256SUMS.txt"), base.sha256_file(out2 / "SHA256SUMS.txt"))

            missing = root / "missing"
            self._write_empty_web_shard(missing / "artifact-00", "00")
            with self.assertRaises(base.ReconstructionError):
                merge_web.merge(missing, root / "bad", expected_shards=2)


if __name__ == "__main__":
    unittest.main()
