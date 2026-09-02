from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import yaml

from backtester.canonical_pit_dataset import (
    METADATA_COLUMNS,
    OBSERVATION_COLUMNS,
    SCHEMA,
    SESSION_HASH_COLUMNS,
    CanonicalPITDataset,
    _DeterministicGzipCsv,
    _canonical_csv_line,
    _dataset_hash,
    _member,
    _write_session_hashes,
)
from backtester.canonical_pit_package import (
    POINTER_SCHEMA,
    load_pointer,
    verify_pointer_dataset,
    write_pointer,
)
from backtester.causal_split_overrides import _load_sidecar_records
from backtester.strict_pit_metadata import SecurityTypeAuthority
from backtester.strict_pit_metadata import IDENTITY_AUTHORITY


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
    def test_manifest_identity_authority_matches_corrected_builder(self) -> None:
        self.assertIn("terminal/relisting corroboration", IDENTITY_AUTHORITY)
        self.assertIn("cannot create a security episode", IDENTITY_AUTHORITY)
        builder = Path("backtester/canonical_pit_dataset.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"identity": IDENTITY_AUTHORITY', builder)
        self.assertNotIn(
            '"identity": "historical SEP plus strict-prior SEC CIK-change episode boundary"',
            builder,
        )

    def test_streaming_session_hashes_match_v1_sorted_parts_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            observations = root / "observations-2006.csv.gz"
            rows = [
                {"session": "2006-01-03", "security_id": "2", "ticker": "XYZ"},
                {"session": "2006-01-03", "security_id": "1", "ticker": "ABC"},
                {"session": "2006-01-04", "security_id": "1", "ticker": "ABC"},
            ]
            with _DeterministicGzipCsv(observations, OBSERVATION_COLUMNS) as writer:
                for row in rows:
                    writer.write(row)

            non_observation = {
                "2006-01-03": ["C\0cash-1", "A\0action-1"],
                "2006-01-04": ["B\0benchmark-2"],
            }
            output = root / "session-hashes.csv"
            _write_session_hashes(
                path=output,
                sessions=("2006-01-03", "2006-01-04"),
                observation_paths=(observations,),
                non_observation_parts=non_observation,
                observation_rows={"2006-01-03": 2, "2006-01-04": 1},
                action_rows={"2006-01-03": 1},
                terminal_rows={},
            )

            expected = {}
            for session in ("2006-01-03", "2006-01-04"):
                parts = list(non_observation.get(session, ()))
                parts.extend(
                    "O\0" + _canonical_csv_line(row, OBSERVATION_COLUMNS)
                    for row in rows if row["session"] == session
                )
                import hashlib
                digest = hashlib.sha256()
                for part in sorted(parts):
                    digest.update(part.encode("utf-8"))
                    digest.update(b"\n")
                expected[session] = digest.hexdigest()
            actual = pd.read_csv(output, dtype=str)
            self.assertEqual(
                dict(zip(actual.session, actual.input_sha256)), expected
            )

    def test_loader_rejects_hash_valid_but_truncated_gzip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dataset = _artifact(Path(raw) / "pit")
            timeline = dataset / "metadata-timeline.csv.gz"
            timeline.write_bytes(timeline.read_bytes()[:-8])
            manifest_path = dataset / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["members"][timeline.name] = _member(timeline, dataset, 1)
            manifest["dataset_hash"] = _dataset_hash(manifest["members"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "compressed member invalid"):
                CanonicalPITDataset(dataset)

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

    def test_certified_split_adjudications_are_content_addressed(self) -> None:
        data = Path("backtester/data/causal-split-overrides-v1.json")
        records, witnesses = _load_sidecar_records(data)
        by_key = {
            (str(row["ticker"]), str(row["effective_session"])): row
            for row in records
        }
        self.assertEqual(by_key[("AAWW", "2006-04-03")]["multiplier"], 1.0)
        self.assertEqual(by_key[("MBCRQ", "2006-06-20")]["multiplier"], 3.0)
        self.assertEqual(by_key[("ETELY", "2007-09-04")]["multiplier"], 1.0)
        self.assertEqual(by_key[("STB", "2013-05-20")]["multiplier"], 1.0)
        self.assertEqual(by_key[("MHGVY", "2014-05-01")]["multiplier"], 1.0)
        self.assertEqual(
            by_key[("PRPO", "2017-06-06")]["multiplier"], 1.0 / 30.0
        )
        self.assertEqual(by_key[("GHI", "2022-12-29")]["multiplier"], 1.0105)
        witness_names = {name for name, _digest in witnesses}
        self.assertTrue(any(name.startswith("AAWW_2006-04-03_") for name in witness_names))
        self.assertTrue(any(name.startswith("MBCRQ_2006-06-20_") for name in witness_names))
        self.assertTrue(any(name.startswith("ETELY_2007-09-04_") for name in witness_names))
        self.assertTrue(any(name.startswith("STB_2013-05-20_") for name in witness_names))
        self.assertTrue(any(name.startswith("MHGVY_2014-05-01_") for name in witness_names))
        self.assertTrue(any(name.startswith("PRPO_2017-06-06_") for name in witness_names))
        self.assertTrue(any(name.startswith("GHI_2022-12-29_") for name in witness_names))

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
        diagnostic_publish = Path(
            ".github/workflows/backtester-publish-canonical-pit-diagnostic.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("canonical_pit_dataset.py build", build)
        self.assertNotIn("canonical_pit_dataset.py build", replay)
        self.assertNotIn("SHARADAR_SEP_", replay)
        self.assertIn("packages: write", orchestrator)
        self.assertIn("canonical-pit-20y-build-request.json", orchestrator)
        self.assertIn("packages: read", replay)
        self.assertIn("canonical-pit-20y.json", replay)
        self.assertIn("docker pull", replay)
        self.assertIn("canonical_pit_dataset.py build", diagnostic_publish)
        self.assertIn("canonical-pit-2006-2007.json", diagnostic_publish)
        self.assertIn("docker push", diagnostic_publish)
        self.assertIn("git rebase origin/research/backtester", diagnostic_publish)
        self.assertEqual(orchestrator.count("uses: ./.github/workflows/backtester-build-canonical-pit-attempt.yml"), 3)
        for fixture in (
            "/.github/workflows/backtester-build-canonical-pit-attempt.yml",
            "/.github/workflows/backtester-build-canonical-pit-20y.yml",
            "/.github/workflows/backtester-publish-canonical-pit-diagnostic.yml",
            "/.github/workflows/backtester-research-only-20y.yml",
            "/.github/workflows/backtester-strict-pit-20y.yml",
            "/backtester/run_research_strict_pit_certification.py",
            "/backtester/run_production_strict_pit_certification.py",
        ):
            self.assertIn(fixture, build)

        builder = Path("backtester/canonical_pit_dataset.py").read_text(encoding="utf-8")
        self.assertNotIn('session_parts[session].append("O\\0"', builder)
        self.assertIn("_write_session_hashes(", builder)

    def test_retired_generation_one_is_fail_closed_and_descriptor_bound(self) -> None:
        retired = yaml.load(
            Path(
                ".github/workflows/backtester-strict-pit-20y.yml"
            ).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(
            retired["name"],
            "RETIRED - generation 1 combined causal certification",
        )
        self.assertEqual(retired["on"], {"workflow_dispatch": ""})
        self.assertEqual(retired["permissions"], {"contents": "read"})
        self.assertEqual(set(retired["jobs"]), {"retired"})

        job = retired["jobs"]["retired"]
        self.assertEqual(
            set(job),
            {"name", "runs-on", "steps"},
        )
        self.assertEqual(job["name"], "Generation 1 is historical evidence only")
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertEqual(len(job["steps"]), 1)

        step = job["steps"][0]
        self.assertEqual(set(step), {"name", "shell", "run"})
        self.assertEqual(step["name"], "Refuse legacy certification execution")
        self.assertEqual(step["shell"], "bash")
        script = [
            line.strip()
            for line in step["run"].splitlines()
            if line.strip()
        ]
        self.assertEqual(len(script), 3)
        self.assertIn("HISTORICAL_EVIDENCE_ONLY", script[0])
        self.assertIn("backtester-production-strict-pit-20y.yml", script[1])
        self.assertEqual(script[2], "exit 1")

        active_path = Path("backtester/data/production-chain-generation.json")
        active = json.loads(active_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(active["generation"], 2)
        self.assertEqual(active["supersedes_generation"], active["generation"] - 1)
        self.assertEqual(
            active["production_main_sha"],
            "bb7747fe329a1a89de555e2a44cb2f04a7eaa285",
        )

        cursor = active
        seen = {active["generation"]}
        while cursor["generation"] > 1:
            historical_path = Path(cursor["historical_descriptor"])
            historical = json.loads(historical_path.read_text(encoding="utf-8"))
            self.assertEqual(historical["generation"], cursor["generation"] - 1)
            self.assertNotIn(historical["generation"], seen)
            seen.add(historical["generation"])
            if historical["generation"] == 1:
                self.assertEqual(historical["status"], "HISTORICAL_EVIDENCE_ONLY")
                self.assertEqual(
                    historical["production_main_sha"],
                    "887f479b15ad861313da666ad698034d3847121c",
                )
                self.assertEqual(
                    historical["canonical_dataset_hash"],
                    active["canonical_dataset_hash"],
                )
                self.assertEqual(historical["years"], active["years"])
                break
            self.assertEqual(
                historical["supersedes_generation"], historical["generation"] - 1
            )
            cursor = historical
        self.assertIn(1, seen)


if __name__ == "__main__":
    unittest.main()
