from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import unittest

from backtester.production_year_checkpoint_overlay import hash_value, write_checkpoint
from backtester import write_production_year_certificate as certificate


ROOT = Path(__file__).resolve().parents[2]
SHA40 = "1" * 40
MAIN_SHA = "2" * 40
SHA64 = "a" * 64
DATASET_SHA = "b" * 64
OVERLAY_SHA = "c" * 64


def _metric_block(start: str, end: str) -> dict:
    return {
        "start": start,
        "end": end,
        "sessions": 2,
        "elapsed_years": 0.5,
        "cagr": 0.21,
        "sharpe": 1.1,
        "max_drawdown": -0.04,
        "ending_multiple": 1.1,
    }


def _make_certificate(
    year: int,
    *,
    checkpoint_sha: str = SHA64,
    payload_sha: str = "d" * 64,
    previous: dict | None = None,
    run_id: str = "7001",
    run_attempt: int = 1,
    artifact_name: str | None = None,
) -> dict:
    end = "2006-12-29" if year == 2006 else f"{year}-12-31"
    predecessor = None
    if previous is not None:
        predecessor = {
            "year": previous["year"],
            "run_id": previous["current_run"]["id"],
            "run_attempt": previous["current_run"]["attempt"],
            "artifact_name": previous["current_run"]["artifact_name"],
            "certificate_hash": previous["certificate_hash"],
            "chain_hash": previous["chain_hash"],
            "checkpoint_sha256": previous["checkpoint"]["file_sha256"],
        }
    body = {
        "schema": certificate.SCHEMA,
        "chain_generation": certificate.CHAIN_GENERATION,
        "status": "PASS",
        "year": year,
        "segment_end": end,
        "identities": {
            "source_sha": SHA40,
            "workflow_sha": SHA40,
            "chain_ref": "refs/heads/research/backtester",
            "production_main_sha": MAIN_SHA,
            "production_overlay_sha256": OVERLAY_SHA,
            "dataset_hash": DATASET_SHA,
            "checkpoint_schema": "backtester.production-year-checkpoint/3",
            "checkpoint_format_generation": 3,
        },
        "current_run": {
            "id": run_id,
            "attempt": run_attempt,
            "artifact_name": artifact_name or f"production-year-{year}-run-{run_id}-attempt-{run_attempt}",
        },
        "predecessor": predecessor,
        "checkpoint": {
            "file_sha256": checkpoint_sha,
            "payload_sha256": payload_sha,
            "session_hash": "e" * 64,
            "canonical_prefix_sha256": "f" * 64,
            "daily_prefix_sha256": "0" * 64,
            "expected_pointer": 252,
            "production_state_hash": "3" * 64,
            "next_session": f"{year + 1}-01-03",
            "next_session_hash": "4" * 64,
        },
        "metrics": {
            "measurement_start": certificate.MEASUREMENT_START,
            "end": end,
            "Production": _metric_block(certificate.MEASUREMENT_START, end),
            "SPY": _metric_block(certificate.MEASUREMENT_START, end),
        },
        "evidence_sha256": {"production_output/summary.json": "5" * 64},
        "complete_20_year_certificate": False,
    }
    content_hash = certificate._json_hash(body)
    previous_chain = None if previous is None else previous["chain_hash"]
    chain_hash = hashlib.sha256(
        ((previous_chain or "GENESIS") + "\n" + content_hash).encode()
    ).hexdigest()
    return {**body, "certificate_hash": content_hash, "chain_hash": chain_hash}


class ProductionAnnualCertificateTests(unittest.TestCase):
    def test_genesis_and_contiguous_chain_are_strictly_validated(self):
        first = _make_certificate(2006)
        second = _make_certificate(2007, previous=first, run_id="7002")
        certificate.validate_certificate(first)
        certificate.validate_certificate(second)
        chain = {
            "schema": certificate.CHAIN_SCHEMA,
            "chain_generation": certificate.CHAIN_GENERATION,
            "certificates": [first, second],
            "chain_hash": second["chain_hash"],
        }
        self.assertEqual(certificate.validate_chain(chain), [first, second])

    def test_schema_and_hash_tampering_fail_closed(self):
        value = _make_certificate(2006)
        extra = copy.deepcopy(value)
        extra["legacy_result"] = 1.0
        with self.assertRaisesRegex(RuntimeError, "fields differ"):
            certificate.validate_certificate(extra)

        tampered = copy.deepcopy(value)
        tampered["metrics"]["Production"]["cagr"] += 0.01
        with self.assertRaisesRegex(RuntimeError, "content hash mismatch"):
            certificate.validate_certificate(tampered)

        wrong_chain = copy.deepcopy(value)
        wrong_chain["chain_hash"] = "9" * 64
        with self.assertRaisesRegex(RuntimeError, "chain hash mismatch"):
            certificate.validate_certificate(wrong_chain)

    def test_cagr_uses_calendar_time_and_measurement_anchor(self):
        rows = [
            {"date": "2006-01-03", "Production_nav": 9.0},
            {"date": "2006-07-31", "Production_nav": 2.0},
            {"date": "2006-10-31", "Production_nav": 2.1},
            {"date": "2006-12-29", "Production_nav": 2.2},
        ]
        block = certificate.metric_block(
            rows, "Production_nav", end="2006-12-29"
        )
        elapsed = 151 / 365.2425
        self.assertEqual(block["start"], "2006-07-31")
        self.assertEqual(block["sessions"], 3)
        self.assertAlmostEqual(block["ending_multiple"], 1.1)
        self.assertAlmostEqual(block["cagr"], 1.1 ** (1 / elapsed) - 1)

    def test_step_summary_exposes_only_production_and_spy_metrics(self):
        value = _make_certificate(2006)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "summary.md"
            certificate._append_step_summary(value, path)
            rendered = path.read_text()
        self.assertIn("| Production |", rendered)
        self.assertIn("| SPY |", rendered)
        self.assertNotRegex(rendered, r"\| [ABD] \|")

    def test_handoff_binds_run_artifact_source_and_checkpoint(self):
        payload = {
            "identities": {
                "backtester_sha": SHA40,
                "production_main_sha": MAIN_SHA,
                "production_overlay_sha256": OVERLAY_SHA,
            },
            "canonical": {"dataset_hash": DATASET_SHA},
            "chain": {
                "segment_year": 2006,
                "session_hash": "e" * 64,
                "canonical_prefix_sha256": "f" * 64,
                "expected_pointer": 252,
                "next_session": "2007-01-03",
                "next_session_hash": "4" * 64,
            },
            "daily": {"prefix_sha256": "0" * 64},
            "states": {"production": {"state_hash": "3" * 64}},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint_path = root / "production-checkpoint.json"
            checkpoint_sha = write_checkpoint(checkpoint_path, payload)
            envelope = json.loads(checkpoint_path.read_text())
            first = _make_certificate(
                2006,
                checkpoint_sha=checkpoint_sha,
                payload_sha=envelope["payload_sha256"],
            )
            cert_path = root / "certificate.json"
            cert_path.write_text(json.dumps(first))
            chain_path = root / "chain.json"
            chain_path.write_text(json.dumps({
                "schema": certificate.CHAIN_SCHEMA,
                "chain_generation": certificate.CHAIN_GENERATION,
                "certificates": [first],
                "chain_hash": first["chain_hash"],
            }))
            certificate.validate_handoff(
                certificate_path=cert_path,
                chain_path=chain_path,
                checkpoint_path=checkpoint_path,
                expected_year=2006,
                source_sha=SHA40,
                workflow_sha=SHA40,
                chain_ref="refs/heads/research/backtester",
                dataset_hash=DATASET_SHA,
                production_main_sha=MAIN_SHA,
                overlay_sha256=OVERLAY_SHA,
                run_id="7001",
                run_attempt=1,
                artifact_name="production-year-2006-run-7001-attempt-1",
                certificate_hash=first["certificate_hash"],
                chain_hash=first["chain_hash"],
            )
            with self.assertRaisesRegex(RuntimeError, "run/artifact"):
                certificate.validate_handoff(
                    certificate_path=cert_path,
                    chain_path=chain_path,
                    checkpoint_path=checkpoint_path,
                    expected_year=2006,
                    source_sha=SHA40,
                    workflow_sha=SHA40,
                    chain_ref="refs/heads/research/backtester",
                    dataset_hash=DATASET_SHA,
                    production_main_sha=MAIN_SHA,
                    overlay_sha256=OVERLAY_SHA,
                    run_id="7001",
                    run_attempt=1,
                    artifact_name="wrong-artifact",
                    certificate_hash=first["certificate_hash"],
                    chain_hash=first["chain_hash"],
                )


class ProductionAnnualWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caller_path = ROOT / ".github/workflows/backtester-production-strict-pit-20y.yml"
        cls.worker_path = ROOT / ".github/workflows/backtester-production-strict-pit-year-worker.yml"
        cls.caller = cls.caller_path.read_text()
        cls.worker = cls.worker_path.read_text()

    def test_exactly_21_dependency_chained_year_jobs(self):
        years = [
            int(value)
            for value in re.findall(r"^  year_(\d{4}):$", self.caller, re.MULTILINE)
        ]
        self.assertEqual(years, list(range(2006, 2027)))
        for year in range(2007, 2027):
            block = re.search(
                rf"^  year_{year}:\n(?P<body>.*?)(?=^  year_|\Z)",
                self.caller,
                re.MULTILINE | re.DOTALL,
            ).group("body")
            self.assertIn(f"needs: year_{year - 1}", block)
            self.assertIn(
                "uses: ./.github/workflows/backtester-production-strict-pit-year-worker.yml",
                block,
            )

    def test_each_job_has_an_independent_timeout_clock(self):
        self.assertIn("timeout-minutes: 350", self.worker)
        self.assertGreaterEqual(self.worker.count("timeout-minutes: 300"), 2)
        self.assertNotIn("timeout-minutes: 360", self.worker)

    def test_worker_runs_only_the_checkpointed_production_entrypoint(self):
        self.assertIn("run_production_strict_pit_20y_checkpointed.py", self.worker)
        self.assertNotIn("run_certification_parallel", self.worker)
        self.assertNotIn("run_research_strict_pit", self.worker)
        self.assertNotIn("workflow_dispatch", self.worker)
        self.assertNotIn("actions: write", self.worker)
        self.assertNotIn("apply_production_cooldown_age_zero.py", self.worker)
        self.assertIn("Verify pristine current-main production source", self.worker)
        self.assertIn("c851386fa4dddcf2e2533af3a1d313c38220b7f2", self.worker)

    def test_artifact_is_attempt_aware_excludes_canonical_package_and_stops_chain(self):
        self.assertIn(
            "production-year-${CHAIN_YEAR}-run-${GITHUB_RUN_ID}-attempt-${GITHUB_RUN_ATTEMPT}",
            self.worker,
        )
        upload = re.search(
            r"- name: Upload attempt-aware annual handoff and diagnostics(?P<body>.*?)"
            r"- name: Publish failed-attempt context",
            self.worker,
            re.DOTALL,
        ).group("body")
        self.assertIn("if: always()", upload)
        self.assertNotIn("backtester-results/canonical-pit-20y", upload)
        self.assertLess(
            self.worker.index("Issue content-addressed Production annual certificate"),
            self.worker.index("Upload attempt-aware annual handoff and diagnostics"),
        )
        self.assertIn("needs: year_2006", self.caller)

    def test_source_identity_failure_context_and_genesis_equivalence_are_enforced(self):
        self.assertIn('test "${WORKFLOW_SHA}" = "${SOURCE_SHA}"', self.worker)
        self.assertIn("BACKTESTER_BRANCH_SHA=${SOURCE_SHA}", self.worker)
        self.assertIn("PRODUCTION_OVERLAY_SHA256=", self.worker)
        self.assertIn("CANONICAL_PIT_EXPECTED_END: '2026-07-31'", self.worker)
        self.assertIn("PRODUCTION_FAILURE_CONTEXT_PATH=", self.worker)
        self.assertIn("PRODUCTION_EQUIVALENCE_UNINTERRUPTED=1", self.worker)
        self.assertIn("compare-resume", self.worker)

    def test_generation_descriptor_matches_workflow_limits(self):
        generation = json.loads(
            (ROOT / "backtester/data/production-chain-generation.json").read_text()
        )
        self.assertEqual(generation["generation"], 2)
        self.assertEqual(generation["supersedes_generation"], 1)
        historical = json.loads((ROOT / generation["historical_descriptor"]).read_text())
        self.assertEqual(historical["generation"], 1)
        self.assertEqual(historical["production_main_sha"], "887f479b15ad861313da666ad698034d3847121c")
        self.assertEqual(generation["production_main_sha"], "c851386fa4dddcf2e2533af3a1d313c38220b7f2")
        self.assertEqual(
            generation["production_checkpoint_schema"],
            "backtester.production-year-checkpoint/3",
        )
        self.assertEqual(
            generation["terminal_correction_sha256"],
            "cfd65c78317abd1671632b2a730507634cf036e798b0ade89be68194fda430dc",
        )
        self.assertEqual(generation["execution"]["job_timeout_minutes"], 350)
        self.assertEqual(generation["execution"]["replay_step_timeout_minutes"], 300)
        self.assertFalse(generation["execution"]["canonical_package_uploaded"])


if __name__ == "__main__":
    unittest.main()
