#!/usr/bin/env python3
"""Require complete commit-, source-, and runtime-bound internal-state evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATHS = ("sentinel/requirements.lock", "tests/requirements.lock")
EXPECTED_PYTHON = "3.12.13"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def expected_locks() -> dict[str, str]:
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in LOCK_PATHS}


def verify(root: Path, *, commit: str, tree: str, shards: int = 4,
           python_version: str = EXPECTED_PYTHON) -> dict:
    campaigns = sorted(root.rglob("campaign.json"))
    require(len(campaigns) == shards, "missing or extra lifecycle campaign manifests")
    indices = []
    runtime_identity = None
    locks = expected_locks()
    for path in campaigns:
        data = load(path)
        require(data.get("commit") == commit, f"campaign commit mismatch: {path}")
        require(data.get("tree") == tree, f"campaign tree mismatch: {path}")
        require(data.get("tracked_dirty") is False, f"campaign source tree was dirty: {path}")
        require(data.get("verdict") == "PASS", f"campaign failed: {path}")
        require(data.get("shards") == shards, f"campaign shard count mismatch: {path}")
        require(bool(data.get("planned")) and data.get("planned") == data.get("completed"),
                f"campaign incomplete: {path}")
        require(not data.get("failures"), f"campaign recorded failures: {path}")
        require(data.get("python") == python_version,
                f"campaign Python runtime mismatch: {path}")
        require(data.get("locks") == locks, f"campaign dependency-lock identity mismatch: {path}")
        dependencies = data.get("dependencies")
        require(isinstance(dependencies, dict) and dependencies,
                f"campaign dependency runtime identity missing: {path}")
        current_runtime = {
            "python": data.get("python"),
            "dependencies": dependencies,
            "locks": data.get("locks"),
        }
        if runtime_identity is None:
            runtime_identity = current_runtime
        require(current_runtime == runtime_identity,
                f"campaign runtime identity differs across shards: {path}")
        indices.append(data.get("shard"))
    require(sorted(indices) == list(range(shards)), "duplicate or missing lifecycle shard")

    suite_reports = [load(p) for p in root.rglob("suites/*.json")]
    contract = [r for r in suite_reports if r.get("collected") and
                all(str(node).startswith("tests/internal_state/") for node in r["collected"])]
    require(len(contract) == 1, "expected exactly one internal-state contract-suite report")
    report = contract[0]
    require(report.get("verdict") == "PASS", "internal-state contract suite failed")
    require(report.get("commit") == commit and report.get("tree") == tree,
            "internal-state contract evidence identity mismatch")
    require(not report.get("skipped") and not report.get("failures")
            and not report.get("expected_failures")
            and not report.get("unexpected_successes")
            and not report.get("deselected"),
            "internal-state contract evidence contains non-passes or deselection")

    core_candidates = []
    for path in root.rglob("evidence.json"):
        data = load(path)
        if data.get("schema") == "stocker.core-infrastructure/2":
            core_candidates.append(data)
    require(len(core_candidates) == 1, "expected exactly one core-infrastructure report")
    core_report = core_candidates[0]
    require(core_report.get("verdict") == "PASS", "core-infrastructure suite failed")
    require(core_report.get("commit") == commit and core_report.get("tree") == tree,
            "core-infrastructure evidence identity mismatch")

    return {
        "schema": "stocker.internal-state-complete/2",
        "verdict": "PASS",
        "commit": commit,
        "tree": tree,
        "contract_tests": len(report["collected"]),
        "campaign_shards": shards,
        "campaign_cases": sum(len(load(p)["planned"]) for p in campaigns),
        "core_suites": core_report["suites"],
        "runtime_identity": runtime_identity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--python-version", default=EXPECTED_PYTHON)
    args = parser.parse_args()
    result = verify(args.root, commit=args.commit, tree=args.tree, shards=args.shards,
                    python_version=args.python_version)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
