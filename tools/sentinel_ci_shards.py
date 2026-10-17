#!/usr/bin/env python3
"""Deterministic, complete module partitions for the Sentinel CI test lens."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

SHARDS = 4
AUTOMATION = frozenset({
    "test_activation_startup_contention.py",
    "test_automation_clock_sampling.py",
    "test_automation_generation.py",
    "test_automation_composition.py",
    "test_automation_worker_source_recovery.py",
    "test_automation_service.py",
    "test_issue_201_automation_financial_grade.py",
    "test_automation_p1_continuity.py",
    "test_automation_safety_seams.py",
    "test_automation_process_contracts.py",
    "test_automation_service_fault_paths.py",
})
SPECIAL = AUTOMATION | frozenset({
    "test_source_seed_warmup.py", "test_runtime_contention.py",
    "test_status_memory.py",
})
DURATIONS = Path(__file__).with_name("sentinel_ci_durations.json")


def load_durations(path: Path = DURATIONS) -> tuple[dict[str, int], int]:
    """Scheduling evidence only; inventory authority remains the exact checkout."""
    def unique_pairs(items):
        if len(items) != len({key for key, _ in items}):
            raise ValueError("duplicate duration manifest key")
        return dict(items)

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    if (not isinstance(value, dict) or set(value) != {
            "schema", "source_commit", "junit_sha256", "default_milliseconds", "modules"}
            or value["schema"] != "sentinel.ci-module-durations/1"
            or not isinstance(value["source_commit"], str)
            or re.fullmatch(r"[0-9a-f]{40}", value["source_commit"]) is None
            or not isinstance(value["junit_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["junit_sha256"]) is None):
        raise ValueError("invalid source-bound duration manifest")
    default, weights = value["default_milliseconds"], value["modules"]
    if type(default) is not int or default <= 0 or not isinstance(weights, dict) or not weights:
        raise ValueError("invalid positive duration estimates")
    if any(MODULE.fullmatch(name) is None or type(cost) is not int or cost <= 0
           for name, cost in weights.items()):
        raise ValueError("invalid module duration estimate")
    return weights, default


MODULE = re.compile(r"tests/sentinel/test_[a-zA-Z0-9_]+\.py\Z")


def tracked_modules(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/sentinel/test_*.py"],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    modules = [name.decode("utf-8") for name in result.stdout.split(b"\0") if name]
    if not modules or len(modules) != len(set(modules)):
        raise ValueError("Sentinel test module inventory is empty or duplicated")
    for name in modules:
        path = root / name
        if MODULE.fullmatch(name) is None or path.is_symlink() or not path.is_file():
            raise ValueError("invalid tracked Sentinel test module: " + name)
    return sorted(modules)


def plan(modules: list[str]) -> dict[str, tuple[str, ...]]:
    if SHARDS != 4:
        raise ValueError("incomplete reviewed four-shard inventory")
    if not modules or len(modules) != len(set(modules)):
        raise ValueError("Sentinel test module inventory is empty or duplicated")
    if any(MODULE.fullmatch(name) is None for name in modules):
        raise ValueError("invalid Sentinel test module path")
    general = [name for name in modules if Path(name).name not in SPECIAL
               and not Path(name).name.startswith("test_rolling_")]
    rolling = [name for name in modules if Path(name).name.startswith("test_rolling_")]
    if len(general) < SHARDS or len(rolling) < SHARDS:
        raise ValueError("too few Sentinel modules for four complete shards")

    groups: dict[str, list[str]] = {f"sentinel-general-{i}": [] for i in range(SHARDS)}
    groups.update({f"sentinel-rolling-{i}": [] for i in range(SHARDS)})
    estimates, default = load_durations()
    for family, selected_modules in (("general", general), ("rolling", rolling)):
        totals = [0] * SHARDS
        for name in sorted(selected_modules, key=lambda item: (-estimates.get(item, default), item)):
            index = min(range(SHARDS), key=lambda item: (totals[item], item))
            groups[f"sentinel-{family}-{index}"].append(name)
            totals[index] += estimates.get(name, default)

    selected = [name for files in groups.values() for name in files]
    if (any(not files for files in groups.values()) or len(selected) != len(set(selected))
            or set(selected) != set(general) | set(rolling)):
        raise ValueError("Sentinel shard plan is incomplete or overlapping")
    return {lane: tuple(files) for lane, files in groups.items()}


def automation_modules(modules: list[str]) -> tuple[str, ...]:
    """Select the coverage owner from the same registry as shard exclusion."""
    plan(modules)  # Refuse malformed or incomplete inventories before selection.
    selected = tuple(sorted(name for name in modules if Path(name).name in AUTOMATION))
    if {Path(name).name for name in selected} != AUTOMATION:
        raise ValueError("missing registered automation test module")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--lane", required=True)
    args = parser.parse_args()
    modules = tracked_modules(args.root)
    selected = (automation_modules(modules) if args.lane == "sentinel-automation"
                else plan(modules).get(args.lane))
    if selected is None:
        parser.error("unknown Sentinel shard lane")
    print("\n".join(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
