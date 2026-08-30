from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtester.canonical_pit_dataset import (
    METADATA_COLUMNS,
    SCHEMA,
    SESSION_HASH_COLUMNS,
    CanonicalPITDataset,
    _DeterministicGzipCsv,
    _dataset_hash,
    _member,
)
from backtester.canonical_pit_package import (
    POINTER_SCHEMA,
    load_pointer,
    verify_pointer_dataset,
    write_pointer,
)
from backtester.causal_split_overrides import _load_sidecar_records
from backtester.strict_pit_metadata import SecurityTypeAuthority


def _artifact(root: Path, *, status: str = "PASS") -> Path:
    root.mkdir()
    timeline = root / "metadata-timeline.csv.gz"
    with _DeterministicGzipCsv(timeline, METADATA_COLUMNS) as writer:
        writer.write({
            "effective_session": "2006-01-03",
            "security_id": "1",
            "ticker": "ABC",
            "issuer_id": "SEC_CIK:7",
            "issuer_source": "SEC_CIK_STRICT_PRIOR",
            "security_type": "common",
            "security_type_source": "SEC_POSITIVE_STRICT_PRIOR_CIK_MATCH",
            "security_type_eligible": "1",
            "sic": "3571",
            "ff12": "06 BusEq",
            "sector_source": "SEC_CIK_SIC_STRICT_PRIOR_FROZEN_FF12",
            "listing_first_session": "2005-01-03",
            "metadata_admitted": "1",
        })
    hashes = root / "session-hashes.csv"
    with hashes.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SESSION_HASH_COLUMNS)
        writer.writeheader()
        writer.writerow({
            "session": "2006-01-03", "observation_rows": "1",
            "action_rows": "0", "terminal_rows": "0", "input_sha256": "a" * 64,
        })
    members = {
        timeline.name: _member(timeline, root, 1),
        hashes.name: _member(hashes, root, 1),
    }
    manifest = {
        "schema": SCHEMA,
        "dataset_id": "strict-pit-test",
        "status": status,
        "dataset_hash": _dataset_hash(members),
        "reconstruction_code_sha": "b" * 40,
        "window": {
            "warmup_start": "2006-01-03",
            "measurement_start": "2006-01-03",
            "end": "2006-01-03",
        },
        "counts": {"unresolved_corporate_actions": 0},
        "blockers": {},
        "members": members,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return root


class CanonicalPITDatasetTests(unittest.TestCase):
    def test_security_type_provenance_distinguishes_cik_mismatch(self) -> None:
        class Model:
            cik_dates = {"ABC": ("2006-01-01",)}
            cik_values = {"ABC": ("8",)}

            @staticmethod
            def _strict_prior(dates, values, session):
                return values[0] if dates and dates[0] < session else None

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            positive = root / "positive.csv.gz"
            pd.DataFrame([{
                "ticker": "ABC", "filed": "2005-12-01", "cik": "7"
            }]).to_csv(positive, index=False, compression="gzip")
            authority = SecurityTypeAuthority(
                positive, root / "missing-manual.csv", Model()
            )
            self.assertEqual(
                authority.classify("ABC", "2006-02-01"),
                ("unknown", "SEC_POSITIVE_STRICT_PRIOR_CIK_MISMATCH"),
            )
            self.assertEqual(
                authority.classify("XYZ", "2006-02-01"),
                ("unknown", "NO_STRICT_PRIOR_POSITIVE_EVIDENCE"),
            )

    def test_loader_validates_hashes_and_asof_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dataset = CanonicalPITDataset(
                _artifact(Path(raw) / "pit"),
                expected_start="2006-01-03",
                expected_end="2006-01-03",
            )
            self.assertIsNone(dataset.metadata_for("1", "2006-01-02"))
            self.assertEqual(
                dataset.metadata_for("1", "2006-01-03")["issuer_id"], "SEC_CIK:7"
            )
            self.assertEqual(dataset.session_hash("2006-01-03"), "a" * 64)

    def test_loader_rejects_failed_or_mutated_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            failed = _artifact(root / "failed", status="FAIL")
            with self.assertRaisesRegex(RuntimeError, "not certified"):
                CanonicalPITDataset(failed)

            changed = _artifact(root / "changed")
            with (changed / "session-hashes.csv").open("a", encoding="utf-8") as handle:
                handle.write("changed\n")
            with self.assertRaisesRegex(RuntimeError, "member changed"):
                CanonicalPITDataset(changed)

    def test_diagnostic_split_adjudications_are_content_addressed(self) -> None:
        data = Path("backtester/data/causal-split-overrides-v1.json")
        records, witnesses = _load_sidecar_records(data)
        by_key = {
            (str(row["ticker"]), str(row["effective_session"])): row
            for row in records
        }
        self.assertEqual(by_key[("AAWW", "2006-04-03")]["multiplier"], 1.0)
        self.assertEqual(by_key[("MBCRQ", "2006-06-20")]["multiplier"], 3.0)
        self.assertEqual(by_key[("ETELY", "2007-09-04")]["multiplier"], 1.0)
        witness_names = {name for name, _digest in witnesses}
        self.assertTrue(any(name.startswith("AAWW_2006-04-03_") for name in witness_names))
        self.assertTrue(any(name.startswith("MBCRQ_2006-06-20_") for name in witness_names))
        self.assertTrue(any(name.startswith("ETELY_2007-09-04_") for name in witness_names))

    def test_strategy_entrypoints_have_no_builder_authority(self) -> None:
        for path in (
            Path("backtester/run_research_strict_pit_certification.py"),
            Path("backtester/run_production_strict_pit_certification.py"),
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("build_dataset", text)
            self.assertIn("CanonicalPITDataset", text)

    def test_research_progress_reports_research_and_spy(self) -> None:
        text = Path(
            "backtester/run_research_strict_pit_certification.py"
        ).read_text(encoding="utf-8")
        self.assertIn("role=research date={ds}", text)
        self.assertIn("role=spy date={ds}", text)
        self.assertIn("phase=WARMUP cagr=N/A", text)
        self.assertIn("_quarter_last", text)

    def test_package_pointer_pins_and_revalidates_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dataset = _artifact(root / "pit")
            pointer_path = root / "pointer.json"
            package = "ghcr.io/flabber1835/stocker-canonical-pit@sha256:" + "c" * 64
            written = write_pointer(
                dataset_path=dataset,
                output=pointer_path,
                package=package,
                source_run_id="123",
                source_run_url="https://github.com/flabber1835/stocker/actions/runs/123",
            )
            self.assertEqual(written["schema"], POINTER_SCHEMA)
            self.assertEqual(load_pointer(pointer_path)["package"], package)
            self.assertEqual(
                verify_pointer_dataset(pointer_path, dataset)["dataset_hash"],
                written["dataset_hash"],
            )

            changed = json.loads(pointer_path.read_text(encoding="utf-8"))
            changed["package"] = "ghcr.io/flabber1835/stocker-canonical-pit:latest"
            pointer_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "not pinned"):
                load_pointer(pointer_path)

    def test_dataset_build_and_replay_are_separate_workflows(self) -> None:
        build = Path(
            ".github/workflows/backtester-build-canonical-pit-attempt.yml"
        ).read_text(encoding="utf-8")
        orchestrator = Path(
            ".github/workflows/backtester-build-canonical-pit-20y.yml"
        ).read_text(encoding="utf-8")
        replay = Path(
            ".github/workflows/backtester-research-only-20y.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("canonical_pit_dataset.py build", build)
        self.assertNotIn("canonical_pit_dataset.py build", replay)
        self.assertNotIn("SHARADAR_SEP_", replay)
        self.assertIn("packages: write", orchestrator)
        self.assertIn("packages: read", replay)
        self.assertIn("canonical-pit-20y.json", replay)
        self.assertIn("docker pull", replay)
        self.assertEqual(orchestrator.count("uses: ./.github/workflows/backtester-build-canonical-pit-attempt.yml"), 3)


if __name__ == "__main__":
    unittest.main()
