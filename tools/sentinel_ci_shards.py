#!/usr/bin/env python3
"""Deterministic, complete module partitions for the Sentinel CI test lens."""
from __future__ import annotations

import argparse
import hashlib
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
# Rounded CI wall-time estimates, including the first test's fixture setup.
# Retained activation is conservatively estimated from a cancelled partial run.
# These affect balance only; the complete inventory comes from the checkout.
ROLLING_WEIGHTS = {
    "test_rolling_retained_runtime_activation.py": 40,
    "test_rolling_runtime.py": 27,
    "test_rolling_daily.py": 23,
    "test_rolling_paper_inputs.py": 19,
    "test_rolling_initialization.py": 14,
    "test_rolling_restore_integrity.py": 14,
    "test_rolling_recovery.py": 10,
    "test_rolling_admission_readers.py": 4,
    "test_rolling_audit_acceptance.py": 3,
    "test_rolling_recovery_report_inputs.py": 3,
    "test_rolling_go_inputs.py": 2,
    "test_rolling_history_retention.py": 2,
    "test_rolling_report_consumers.py": 2,
    "test_rolling_retention_runtime.py": 2,
}
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
    for name in sorted(general):
        index = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:4], "big") % SHARDS
        groups[f"sentinel-general-{index}"].append(name)

    weights = [0] * SHARDS
    for name in sorted(rolling, key=lambda item: (-ROLLING_WEIGHTS.get(Path(item).name, 1), item)):
        index = min(range(SHARDS), key=lambda item: (weights[item], item))
        groups[f"sentinel-rolling-{index}"].append(name)
        weights[index] += ROLLING_WEIGHTS.get(Path(name).name, 1)

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
