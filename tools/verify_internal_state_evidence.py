#!/usr/bin/env python3
"""Require complete commit-, source-, runtime-, owner-, and campaign-bound evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATHS = ("sentinel/requirements.lock", "tests/requirements.lock")
EXPECTED_PYTHON = "3.12.13"
CATALOGUE_SCENARIOS = (
    "populated_lifecycle",
    "submit_process_death",
    "submit_response_loss",
    "partial_cancel_fill_race",
    "external_cash_isolation",
    "startup_failure_after_plan",
    "interrupted_publication",
    "backup_loss_after_plan",
    "wal_corruption_after_plan",
    "stale_populated_restore",
    "valid_json_state_corruption",
    "competing_execution_workers",
    "interrupted_multi_session_catchup",
    "stress_and_recovery",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def expected_locks() -> dict[str, str]:
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in LOCK_PATHS}


def expected_campaign_plan(seeds: int, seed_start: int = 0) -> list[str]:
    require(0 <= seeds <= 4096, "invalid authoritative campaign seed budget")
    require(0 <= seed_start < 2**32 and seed_start + seeds <= 2**32,
            "invalid authoritative campaign seed range")
    plan = [
        f"{scenario}-{profile}"
        for scenario in CATALOGUE_SCENARIOS
        for profile in ("paper", "live_cash")
    ]
    plan.extend(
        f"generated_{seed:08d}-{'paper' if seed % 2 == 0 else 'live_cash'}"
        for seed in range(seed_start, seed_start + seeds)
    )
    return plan


def event_campaign_budget() -> int | None:
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event in {"pull_request", "merge_group"}:
        return 16
    if event == "workflow_dispatch":
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        require(bool(event_path) and Path(event_path).is_file(),
                "workflow-dispatch payload is unavailable for campaign authority")
        payload = load(Path(event_path))
        raw = payload.get("inputs", {}).get("seeds", 128)
        try:
            seeds = int(raw)
        except (TypeError, ValueError) as exc:
            raise AssertionError("invalid workflow-dispatch campaign seed budget") from exc
        require(0 <= seeds <= 4096, "workflow-dispatch campaign seed budget is out of range")
        return seeds
    return None


def _require_owner_evidence(root: Path, owner: str) -> dict:
    matches = []
    for path in root.rglob("test-owner.json"):
        data = load(path)
        if data.get("owner") == owner:
            matches.append((path, data))
    require(len(matches) == 1, f"expected exactly one {owner} owner-verifier report")
    path, data = matches[0]
    require(data.get("schema") == "stocker.test-owner-execution/3",
            f"{owner} owner-verifier schema mismatch: {path}")
    require(data.get("verdict") == "PASS", f"{owner} owner verifier failed: {path}")
    require(data.get("complete_collection") is True,
            f"{owner} owner verifier did not prove complete collection: {path}")
    require(data.get("collected_nodes") == data.get("passing_nodes")
            and isinstance(data.get("collected_nodes"), int)
            and data.get("collected_nodes") > 0,
            f"{owner} owner-verifier execution counts differ: {path}")
    return data


def verify(root: Path, *, commit: str, tree: str, shards: int = 4,
           python_version: str = EXPECTED_PYTHON,
           campaign_seeds: int | None = None, seed_start: int = 0) -> dict:
    campaigns = sorted(root.rglob("campaign.json"))
    require(len(campaigns) == shards, "missing or extra lifecycle campaign manifests")
    indices = []
    runtime_identity = None
    locks = expected_locks()
    expected_plan = (expected_campaign_plan(campaign_seeds, seed_start)
                     if campaign_seeds is not None else None)
    planned_union = []
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
        shard = data.get("shard")
        indices.append(shard)
        if expected_plan is not None:
            require(data.get("seeds") == campaign_seeds,
                    f"campaign seed budget mismatch: {path}")
            require(data.get("seed_start") == seed_start,
                    f"campaign seed start mismatch: {path}")
            require(data.get("scenario_filter") == [],
                    f"campaign scenario filter is not authoritative: {path}")
            require(data.get("replay_mode") is False,
                    f"campaign replay mode cannot satisfy aggregate authority: {path}")
            require(isinstance(shard, int) and 0 <= shard < shards,
                    f"campaign shard index invalid: {path}")
            expected_shard = [case for index, case in enumerate(expected_plan)
                              if index % shards == shard]
            require(data.get("planned") == expected_shard,
                    f"campaign shard does not equal authoritative partition: {path}")
        planned_union.extend(data.get("planned", []))
    require(sorted(indices) == list(range(shards)), "duplicate or missing lifecycle shard")
    if expected_plan is not None:
        require(len(planned_union) == len(set(planned_union)),
                "lifecycle campaign partitions overlap")
        require(set(planned_union) == set(expected_plan),
                "lifecycle campaign union differs from authoritative campaign")

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

    contract_owner = _require_owner_evidence(root, "internal-state.contract")
    core_owner = _require_owner_evidence(root, "core.infrastructure")

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
        "schema": "stocker.internal-state-complete/3",
        "verdict": "PASS",
        "commit": commit,
        "tree": tree,
        "contract_tests": len(report["collected"]),
        "contract_owner_nodes": contract_owner["passing_nodes"],
        "campaign_shards": shards,
        "campaign_cases": sum(len(load(p)["planned"]) for p in campaigns),
        "campaign_seeds": campaign_seeds,
        "campaign_seed_start": seed_start if campaign_seeds is not None else None,
        "core_suites": core_report["suites"],
        "core_owner_nodes": core_owner["passing_nodes"],
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
    result = verify(
        args.root,
        commit=args.commit,
        tree=args.tree,
        shards=args.shards,
        python_version=args.python_version,
        campaign_seeds=event_campaign_budget(),
        seed_start=0,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
