#!/usr/bin/env python3
"""Require complete commit-bound evidence for the deduplicated internal-state gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def verify(root: Path, *, commit: str, tree: str, shards: int = 4) -> dict:
    campaigns = sorted(root.rglob("campaign.json"))
    assert len(campaigns) == shards, "missing or extra lifecycle campaign manifests"
    indices = []
    for path in campaigns:
        data = load(path)
        assert data.get("commit") == commit, f"campaign commit mismatch: {path}"
        assert data.get("tree") == tree, f"campaign tree mismatch: {path}"
        assert data.get("verdict") == "PASS", f"campaign failed: {path}"
        assert data.get("shards") == shards, f"campaign shard count mismatch: {path}"
        assert data.get("planned") and data.get("planned") == data.get("completed"), \
            f"campaign incomplete: {path}"
        assert not data.get("failures"), f"campaign recorded failures: {path}"
        indices.append(data.get("shard"))
    assert sorted(indices) == list(range(shards)), "duplicate or missing lifecycle shard"

    suite_reports = [load(p) for p in root.rglob("suites/*.json")]
    contract = [r for r in suite_reports if r.get("collected") and
                all(str(node).startswith("tests/internal_state/") for node in r["collected"])]
    assert len(contract) == 1, "expected exactly one internal-state contract-suite report"
    report = contract[0]
    assert report.get("verdict") == "PASS", "internal-state contract suite failed"
    assert report.get("commit") == commit and report.get("tree") == tree, \
        "internal-state contract evidence identity mismatch"
    assert not report.get("skipped") and not report.get("failures"), \
        "internal-state contract evidence contains non-passes"

    core = [load(p) for p in root.rglob("evidence.json")
            if load(p).get("schema") == "stocker.core-infrastructure/1"]
    assert len(core) == 1, "expected exactly one core-infrastructure report"
    core_report = core[0]
    assert core_report.get("verdict") == "PASS", "core-infrastructure suite failed"
    assert core_report.get("commit") == commit and core_report.get("tree") == tree, \
        "core-infrastructure evidence identity mismatch"

    return {
        "schema": "stocker.internal-state-complete/1",
        "verdict": "PASS",
        "commit": commit,
        "tree": tree,
        "contract_tests": len(report["collected"]),
        "campaign_shards": shards,
        "campaign_cases": sum(len(load(p)["planned"]) for p in campaigns),
        "core_suites": core_report["suites"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()
    result = verify(args.root, commit=args.commit, tree=args.tree, shards=args.shards)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
