#!/usr/bin/env python3
"""Prove that every module assigned to a test owner produced JUnit evidence."""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

from test_responsibility_lib import (
    junit_execution, load_authority, owned_test_modules,
    relative_posix, validate_contract_selectors,
)


def verify(owner_name: str, junit_paths: list[Path]) -> dict:
    authority = load_authority()
    expected = owned_test_modules(authority, owner_name)
    if not expected:
        raise AssertionError(f"{owner_name}: owner has no test modules")
    paths = [path.resolve() for path in junit_paths]
    if not paths or any(not path.is_file() for path in paths):
        raise AssertionError(f"{owner_name}: missing JUnit execution evidence")
    executed, logical_nodeids = junit_execution(paths, expected)
    expected_names = {relative_posix(path) for path in expected}
    missing = sorted(expected_names - executed)
    if missing:
        raise AssertionError(
            f"{owner_name}: owned test modules have no execution evidence: {missing}")

    delegated_contracts = {}
    owners = authority["owners"]
    for delegated_name, delegated in owners.items():
        execution = delegated.get("execution", {})
        if execution.get("kind") != "delegated" or execution.get("owner") != owner_name:
            continue
        contract_group = execution.get("required_contracts")
        if not contract_group:
            continue
        required = validate_contract_selectors(
            authority.get(contract_group, {}).get("required_contracts"))
        missing_contracts = {
            contract_id: selector for contract_id, selector in required.items()
            if selector not in logical_nodeids
        }
        if missing_contracts:
            raise AssertionError(
                f"{delegated_name}: required contracts lack execution evidence: "
                f"{missing_contracts}")
        delegated_contracts[delegated_name] = len(required)

    return {
        "schema": "stocker.test-owner-execution/1",
        "verdict": "PASS",
        "owner": owner_name,
        "expected_modules": sorted(expected_names),
        "executed_modules": sorted(executed),
        "junit": [str(path) for path in paths],
        "delegated_contracts": delegated_contracts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--junit", action="append", default=[])
    parser.add_argument("--junit-glob", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = [Path(value) for value in args.junit]
    for pattern in args.junit_glob:
        paths.extend(Path(value) for value in sorted(glob.glob(pattern, recursive=True)))
    result = verify(args.owner, paths)
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
