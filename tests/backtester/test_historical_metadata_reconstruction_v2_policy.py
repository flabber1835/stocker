import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import historical_metadata_reconstruction_v2_policy as policy


def write_candidates(root: Path, rows):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "candidate_episodes.csv.gz"
    base.write_gzip_csv(path, [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks",
        "alias_symbol", "alias_safe",
    ], rows)
    (root / "candidate_coverage.json").write_text("{}\n", encoding="utf-8")
    return path


def write_timeline(root: Path, identities=(), types=(), sics=()):
    root.mkdir(parents=True, exist_ok=True)
    base.write_gzip_csv(root / "identity_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession"
    ], identities)
    base.write_gzip_csv(root / "security_type_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "classification", "accession"
    ], types)
    base.write_gzip_csv(root / "sic_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sic", "accession"
    ], sics)


class HistoricalMetadataV2PolicyTests(unittest.TestCase):
    def test_harden_candidates_records_first_gaps_and_disables_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates_dir = root / "candidates"
            write_candidates(candidates_dir, [{
                "security_id": "sid1", "ticker": "ABC1", "first_session": "2006-01-03",
                "last_session": "2006-01-04", "observations": 2,
                "unknown_type_observations": 1, "missing_sector_observations": 1,
                "observed_ciks": "0000000001", "alias_symbol": "ABC", "alias_safe": "true",
            }])
            dataset = root / "canonical"
            dataset.mkdir()
            base.write_gzip_csv(dataset / "obs.csv.gz", [
                "session", "security_id", "ticker", "issuer_id", "security_type", "sic", "ff12"
            ], [
                {"session": "2006-01-03", "security_id": "sid1", "ticker": "ABC1",
                 "issuer_id": "SEC_CIK:1", "security_type": "unknown", "sic": "", "ff12": ""},
                {"session": "2006-01-04", "security_id": "sid1", "ticker": "ABC1",
                 "issuer_id": "SEC_CIK:1", "security_type": "common", "sic": "3571", "ff12": "BusEq"},
            ])
            result = policy.harden_candidates(dataset, candidates_dir)
            rows = base.read_gzip_csv(candidates_dir / "candidate_episodes.csv.gz")
            self.assertEqual(rows[0]["first_unknown_type_session"], "2006-01-03")
            self.assertEqual(rows[0]["first_missing_sector_session"], "2006-01-03")
            self.assertEqual(rows[0]["alias_symbol"], "")
            self.assertEqual(rows[0]["alias_safe"], "false")
            self.assertEqual(rows[0]["alias_policy"], policy.ALIAS_POLICY)
            self.assertEqual(result["security_id_in_cik_fields"], 0)

    def test_harden_candidates_rejects_cik_set_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates_dir = root / "candidates"
            write_candidates(candidates_dir, [{
                "security_id": "sid1", "ticker": "ABC", "first_session": "2006-01-03",
                "last_session": "2006-01-03", "observations": 1,
                "unknown_type_observations": 1, "missing_sector_observations": 0,
                "observed_ciks": "0000000002", "alias_symbol": "", "alias_safe": "false",
            }])
            dataset = root / "canonical"
            dataset.mkdir()
            base.write_gzip_csv(dataset / "obs.csv.gz", [
                "session", "security_id", "ticker", "issuer_id", "security_type", "sic", "ff12"
            ], [{"session": "2006-01-03", "security_id": "sid1", "ticker": "ABC",
                 "issuer_id": "SEC_CIK:1", "security_type": "unknown", "sic": "3571", "ff12": "BusEq"}])
            with self.assertRaises(base.ReconstructionError):
                policy.harden_candidates(dataset, candidates_dir)

    def test_strict_web_plan_treats_late_evidence_as_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates = root / "candidates.csv.gz"
            base.write_gzip_csv(candidates, [
                "security_id", "ticker", "first_session", "last_session", "observations",
                "unknown_type_observations", "missing_sector_observations", "observed_ciks",
                "first_unknown_type_session", "last_unknown_type_session",
                "first_missing_sector_session", "last_missing_sector_session",
                "alias_symbol", "alias_safe", "alias_policy",
            ], [{
                "security_id": "sid1", "ticker": "ABC", "first_session": "2006-01-03",
                "last_session": "2006-12-31", "observations": 250,
                "unknown_type_observations": 10, "missing_sector_observations": 10,
                "observed_ciks": "0000000001", "first_unknown_type_session": "2006-01-03",
                "last_unknown_type_session": "2006-01-20", "first_missing_sector_session": "2006-01-03",
                "last_missing_sector_session": "2006-01-20", "alias_symbol": "", "alias_safe": "false",
                "alias_policy": policy.ALIAS_POLICY,
            }])
            timeline = root / "timeline"
            late = "2006-02-01"
            write_timeline(timeline,
                identities=[{"security_id": "sid1", "ticker": "ABC", "filed": late, "usable_after": late,
                             "cik": "0000000001", "sec_symbol": "ABC", "accession": "i"}],
                types=[{"security_id": "sid1", "ticker": "ABC", "filed": late, "usable_after": late,
                        "cik": "0000000001", "classification": "common", "accession": "t"}],
                sics=[{"security_id": "sid1", "ticker": "ABC", "filed": late, "usable_after": late,
                       "cik": "0000000001", "sic": "3571", "accession": "s"}],
            )
            out = root / "plan"
            result = policy.build_strict_web_plan(candidates, timeline, out)
            rows = base.read_gzip_csv(out / "web_plan.csv.gz")
            self.assertEqual(result["unique_ciks"], 1)
            self.assertEqual(rows[0]["need_identity"], "true")
            self.assertEqual(rows[0]["need_type"], "true")
            self.assertEqual(rows[0]["need_sic"], "true")
            self.assertEqual(rows[0]["discovery_only_cik_hint"], "true")

    def test_strict_web_plan_skips_when_all_evidence_is_strict_prior(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidates = root / "candidates.csv.gz"
            base.write_gzip_csv(candidates, [
                "security_id", "ticker", "first_session", "last_session", "observations",
                "unknown_type_observations", "missing_sector_observations", "observed_ciks",
                "first_unknown_type_session", "last_unknown_type_session",
                "first_missing_sector_session", "last_missing_sector_session",
                "alias_symbol", "alias_safe", "alias_policy",
            ], [{
                "security_id": "sid1", "ticker": "ABC", "first_session": "2006-01-03",
                "last_session": "2006-12-31", "observations": 250,
                "unknown_type_observations": 10, "missing_sector_observations": 10,
                "observed_ciks": "0000000001", "first_unknown_type_session": "2006-01-03",
                "last_unknown_type_session": "2006-01-20", "first_missing_sector_session": "2006-01-03",
                "last_missing_sector_session": "2006-01-20", "alias_symbol": "", "alias_safe": "false",
                "alias_policy": policy.ALIAS_POLICY,
            }])
            timeline = root / "timeline"
            prior = "2005-12-30"
            write_timeline(timeline,
                identities=[{"security_id": "sid1", "ticker": "ABC", "filed": prior, "usable_after": prior,
                             "cik": "0000000001", "sec_symbol": "ABC", "accession": "i"}],
                types=[{"security_id": "sid1", "ticker": "ABC", "filed": prior, "usable_after": prior,
                        "cik": "0000000001", "classification": "common", "accession": "t"}],
                sics=[{"security_id": "sid1", "ticker": "ABC", "filed": prior, "usable_after": prior,
                       "cik": "0000000001", "sic": "3571", "accession": "s"}],
            )
            out = root / "plan"
            result = policy.build_strict_web_plan(candidates, timeline, out)
            self.assertEqual(result["episode_cik_rows"], 0)

    def test_fetch_policy_allows_terminal_source_absence_but_not_network_failure(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(base, "fetch_web_fallback", return_value={
                "status": "PARTIAL", "complete": True, "failures": [],
                "transport": {"terminal_absences": 2},
            }):
                result = policy.fetch_web_policy(
                    plan_path=out / "plan", output=out, source_sha="s", canonical_hash="c",
                    candidates_sha="x", parser_sha="p"
                )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["source_absences"], 2)

    def test_admission_ready_requires_all_strict_prior_observations_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "manifest.json"
            coverage = root / "coverage.json"
            timeline = root / "timeline.json"
            manifest.write_text(json.dumps({"status": "PASS", "web": {"status": "PASS", "complete": True}}))
            coverage.write_text(json.dumps({"resolution_rates": {"security_type": 1.0, "sector": 1.0}}))
            timeline.write_text(json.dumps({
                "status": "PASS", "ambiguous_identity_events": 0,
                "security_type_conflicts": 0, "unresolved_episode_records": 0,
            }))
            result = policy.apply_admission_status(manifest, coverage, timeline)
            self.assertEqual(result["admission_status"], "READY")
            self.assertEqual(result["status"], "PASS")

            coverage.write_text(json.dumps({"resolution_rates": {"security_type": 0.99, "sector": 1.0}}))
            manifest.write_text(json.dumps({"status": "PASS", "web": {"status": "PASS", "complete": True}}))
            result = policy.apply_admission_status(manifest, coverage, timeline)
            self.assertEqual(result["admission_status"], "REVIEW_REQUIRED")
            self.assertEqual(result["status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
