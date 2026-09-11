#!/usr/bin/env python3
"""Validate permanent test ownership and bind each owner to executable evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from test_responsibility_lib import (
    ROOT, SCHEMA, contains, incident_named, load_authority, owner_paths,
    owned_test_modules, relative_posix, validate_contract_selectors,
)

REQUIRED_OWNERS = {
    "sentinel.complete",
    "production-champion.regressions",
    "wealth-core.prospective",
    "scripts.operator",
    "host-python38.compatibility",
    "backup.reliability",
    "internal-state.contract",
    "internal-state.campaign",
    "core.infrastructure",
    "sharadar.daily-replay",
    "alpaca.contracts",
    "alpaca.mutations",
}
REQUIRED_SCOPES = {"exact-head", "synthetic-merge"}
EXECUTION_KINDS = {"pytest-junit", "unittest-discovery", "command", "delegated"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _require_ci_job(owner_name: str, value: object) -> tuple[str, str, str]:
    assert isinstance(value, str) and value.count("#") == 1, \
        f"{owner_name}: ci_job must be workflow.yml#job-id"
    workflow, job = value.split("#", 1)
    assert workflow.startswith(".github/workflows/") and workflow.endswith((".yml", ".yaml")), \
        f"{owner_name}: invalid workflow path in ci_job"
    assert job, f"{owner_name}: empty job id in ci_job"
    path = ROOT / workflow
    assert path.is_file(), f"{owner_name}: ci_job workflow does not exist: {workflow}"
    text = path.read_text()
    assert f"\n  {job}:\n" in text, f"{owner_name}: ci_job id not found in {workflow}: {job}"
    return workflow, job, text


def _require_execution_binding(name: str, owner: dict, workflow_text: str,
                               owners: dict) -> dict:
    execution = owner.get("execution")
    assert isinstance(execution, dict), f"{name}: missing execution binding"
    kind = execution.get("kind")
    assert kind in EXECUTION_KINDS, f"{name}: invalid execution kind: {kind}"
    if kind == "pytest-junit":
        marker = f"python tools/verify_test_owner_execution.py --owner {name}"
        assert marker in workflow_text, (
            f"{name}: declared CI workflow does not verify owned-module execution")
    elif kind == "unittest-discovery":
        marker = f"python tools/run_unittest_owner.py --owner {name}"
        assert marker in workflow_text, (
            f"{name}: declared CI workflow does not use owner-driven unittest discovery")
    elif kind == "command":
        command = execution.get("command")
        assert isinstance(command, str) and command, f"{name}: missing execution command"
        assert command in workflow_text, f"{name}: declared execution command not present in workflow"
    else:
        target = execution.get("owner")
        assert isinstance(target, str) and target in owners, f"{name}: invalid delegated owner"
        target_execution = owners[target].get("execution", {})
        assert target_execution.get("kind") != "delegated", f"{name}: delegated owner cannot delegate again"
        if execution.get("required_contracts") is not None:
            assert isinstance(execution.get("required_contracts"), str), \
                f"{name}: required_contracts must name an authority section"
    return execution


def _require_merge_authority() -> dict:
    sentinel_path = ROOT / ".github/workflows/sentinel-safety.yml"
    sharadar_path = ROOT / ".github/workflows/sharadar-daily-replay.yml"
    sentinel = sentinel_path.read_text()
    sharadar = sharadar_path.read_text()
    required = [
        "checks: read",
        "python tools/require_check_run.py",
        '--sha "$GITHUB_SHA"',
        '--name "sharadar-replay-${{ matrix.scope }}"',
        "if: github.event_name == 'pull_request'",
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'",
    ]
    missing = [needle for needle in required if needle not in sentinel]
    assert not missing, f"Sentinel required-check bridge is incomplete: {missing}"
    assert "python -m unittest -v tests.host_python38.test_" not in sentinel, (
        "host Python 3.8 ownership regressed to a hand-maintained module list")
    assert "name: sharadar-replay-${{ matrix.scope }}" in sharadar, (
        "Sharadar aggregate checks must have unique stable bridge names")
    return {
        "carrier_contexts": ["sentinel-exact-head", "sentinel-synthetic-merge"],
        "dependency_checks": [
            "sharadar-replay-exact-head",
            "sharadar-replay-synthetic-merge",
        ],
        "commit_binding": "GITHUB_SHA",
    }


def validate(*, base: str | None = None) -> dict:
    authority = load_authority()
    assert authority.get("schema") == SCHEMA
    owners = authority.get("owners")
    assert isinstance(owners, dict), "missing owner map"
    assert REQUIRED_OWNERS.issubset(owners), "required test owner is missing"

    resolved = {}
    resolved_paths = {}
    ci_jobs = {}
    executions = {}
    for name, owner in owners.items():
        assert isinstance(owner, dict), f"{name}: invalid owner declaration"
        scopes = set(owner.get("scopes", []))
        assert REQUIRED_SCOPES.issubset(scopes), f"{name}: exact/synthetic scope ownership missing"
        workflow, job, workflow_text = _require_ci_job(name, owner.get("ci_job"))
        ci_jobs[name] = f"{workflow}#{job}"
        paths = owner_paths(authority, name)
        resolved_paths[name] = paths
        resolved[name] = [relative_posix(path) for path in paths]
        executions[name] = _require_execution_binding(name, owner, workflow_text, owners)

    test_modules = sorted((ROOT / "tests").rglob("test_*.py"))
    unowned_tests = [
        relative_posix(path) for path in test_modules
        if not any(contains(owner_path, path)
                   for paths in resolved_paths.values() for owner_path in paths)
    ]
    assert not unowned_tests, f"test modules without a permanent owner: {unowned_tests}"

    ambiguous_execution = {}
    for path in test_modules:
        declared = [name for name, paths in resolved_paths.items()
                    if any(contains(owner_path, path) for owner_path in paths)]
        effective = set()
        for name in declared:
            execution = executions[name]
            effective.add(execution.get("owner") if execution["kind"] == "delegated" else name)
        if len(effective) != 1:
            ambiguous_execution[relative_posix(path)] = sorted(effective)
    assert not ambiguous_execution, (
        "test modules must have exactly one effective execution owner: "
        f"{ambiguous_execution}")

    for name, execution in executions.items():
        if execution["kind"] != "delegated":
            continue
        target = execution["owner"]
        target_paths = resolved_paths[target]
        escaped = [
            relative_posix(module) for module in owned_test_modules(authority, name)
            if not any(contains(path, module) for path in target_paths)
        ]
        assert not escaped, f"{name}: delegated tests escape execution owner {target}: {escaped}"

    required_contracts = validate_contract_selectors(
        authority.get("alpaca", {}).get("required_contracts"))
    required_mutations = authority.get("alpaca", {}).get("required_mutations")
    assert isinstance(required_mutations, list) and required_mutations, "missing Alpaca mutation authority"
    assert all(isinstance(v, str) and v for v in required_mutations), "invalid Alpaca mutation id"
    assert len(required_mutations) == len(set(required_mutations)), "duplicate Alpaca mutation id"

    merge_authority = _require_merge_authority()

    added_incident_tests = []
    if base:
        git("cat-file", "-e", f"{base}^{{commit}}")
        changed = git("diff", "--name-only", "--diff-filter=A", base, "HEAD", "--", "tests")
        for path in filter(None, changed.splitlines()):
            if incident_named(path):
                added_incident_tests.append(path)
        assert not added_incident_tests, (
            "new incident-named regression files are forbidden; move the regression into its "
            f"permanent behavior owner: {added_incident_tests}"
        )

    return {
        "schema": "stocker.test-responsibility-verdict/2",
        "verdict": "PASS",
        "owners": len(owners),
        "ci_jobs": ci_jobs,
        "executions": executions,
        "test_modules": len(test_modules),
        "unowned_tests": unowned_tests,
        "alpaca_contracts": len(required_contracts),
        "alpaca_mutations": len(required_mutations),
        "base": base,
        "added_incident_tests": added_incident_tests,
        "resolved": resolved,
        "merge_authority": merge_authority,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(base=args.base)
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
