#!/usr/bin/env python3
"""Build exact-SHA, machine-readable evidence from Sentinel's JUnit record."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


LAYERS = {
    "contract": ("test_execution_contract", "test_pit_clock_contract"),
    "end_to_end": (
        "test_full_production_trading_day", "test_system_simulation",
        "test_production_decision",
    ),
    "fault_recovery": (
        "test_process_death_recovery", "test_adversarial_scenario",
        "test_production_outage_recovery", "test_reboot_outage_recovery",
    ),
    "generated_invariants": ("test_generated_economic_sequences",),
    "point_in_time": (
        "test_production_state", "test_corpus_snapshot_stability",
        "test_corpus_visibility", "test_feed_universe",
    ),
    "differential_golden": (
        "test_controller_certification", "test_breadth_classifier",
        "test_forward_chain_certification",
    ),
    "historical_replay": ("test_historical_stress_checkpoints",),
    "performance_load": ("test_ingest_memory", "test_resource_envelope"),
    "deployment_recovery": (
        "test_image_layout", "test_automation_deployment",
        "test_backup_contract", "test_adapter_and_recovery_drill",
    ),
    "shadow": ("test_shadow_observation", "test_shadow_service"),
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True).strip()


def _digest_files(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _case_record(case: ET.Element) -> dict[str, object]:
    status = "passed"
    detail = ""
    for candidate in ("failure", "error", "skipped"):
        child = case.find(candidate)
        if child is not None:
            status = candidate
            detail = (child.get("message") or child.text or "")[-4000:]
            break
    node = ".".join(filter(None, (
        case.get("classname", ""), case.get("name", ""))))
    return {
        "node": node,
        "status": status,
        "seconds": float(case.get("time", "0")),
        "detail_tail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--tested-sha", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    junit = Path(args.junit)
    cases: list[dict[str, object]] = []
    harness_error = ""
    try:
        root = ET.parse(junit).getroot()
        cases = [_case_record(case) for case in root.iter("testcase")]
    except Exception as exc:  # noqa: BLE001
        harness_error = f"{type(exc).__name__}: {exc}"

    layers = {}
    for layer, patterns in LAYERS.items():
        selected = [
            case for case in cases
            if any(pattern in str(case["node"]) for pattern in patterns)
        ]
        layers[layer] = {
            "tests": len(selected),
            "passed": sum(case["status"] == "passed" for case in selected),
            "nonpasses": [
                case["node"] for case in selected
                if case["status"] != "passed"
            ],
        }

    test_files = [repo / path for path in _git(
        repo, "ls-files", "tests").splitlines() if path]
    locks = [repo / "sentinel/requirements.lock", repo / "tests/requirements.lock"]
    nonpasses = [case for case in cases if case["status"] != "passed"]
    required_layers_present = all(
        layers[name]["tests"] > 0
        for name in ("contract", "end_to_end", "fault_recovery",
                     "generated_invariants", "point_in_time",
                     "differential_golden", "historical_replay",
                     "performance_load", "deployment_recovery", "shadow")
    )
    passed = bool(cases) and not harness_error and not nonpasses \
        and required_layers_present

    evidence = {
        "schema": "sentinel.system-adversarial-certification/1",
        "certification_scope": "offline_ci_software",
        "tested_sha": args.tested_sha,
        "head_sha": _git(repo, "rev-parse", "HEAD"),
        "tree_sha": _git(repo, "rev-parse", "HEAD^{tree}"),
        "dependency_lock_sha256": _digest_files(locks, repo),
        "test_manifest_sha256": _digest_files(test_files, repo),
        "junit_sha256": (
            hashlib.sha256(junit.read_bytes()).hexdigest()
            if junit.is_file() else None
        ),
        "total_tests": len(cases),
        "passed_tests": sum(case["status"] == "passed" for case in cases),
        "nonpasses": nonpasses,
        "layers": layers,
        "required_layers_present": required_layers_present,
        "generated_seeds": list(range(8)),
        "external_evidence": {
            "authoritative_sharadar_full_history": "NAS_REQUIRED_NOT_RUN",
            "historical_metadata_causality": "NOT_CLAIMED",
            "nas_resource_envelope": "NAS_REQUIRED_NOT_RUN",
            "alpaca_expected_observed_shadow": "PAPER_ACCOUNT_REQUIRED_NOT_RUN",
        },
        "harness_error": harness_error or None,
        "certification_passed": passed,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "certification_passed": passed,
        "total_tests": len(cases),
        "nonpasses": len(nonpasses),
        "required_layers_present": required_layers_present,
    }, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
