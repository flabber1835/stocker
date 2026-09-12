"""Validate the bounded Alpaca contract inventory without re-running Sentinel tests.

The complete Sentinel suite owns ordinary test execution. This harness proves
that every required Alpaca contract resolves to the exact declared physical
profile/parameter instances on the Alpaca suite surface; the companion mutation
harness remains the independent falsification layer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from test_responsibility_lib import (
    ROOT, load_authority, owned_test_modules, relative_posix, resolve_contracts,
    validate_contract_instances, validate_contract_selectors,
)

MANIFEST = ROOT / "tests" / "test-responsibility.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _collected_nodeids(stdout: str) -> list[str]:
    nodeids = []
    marker = "tests/sentinel/"
    for raw in stdout.splitlines():
        line = raw.strip()
        start = line.find(marker)
        if start >= 0 and "::" in line[start:]:
            nodeids.append(line[start:])
    return sorted(set(nodeids))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    authority = load_authority()
    alpaca = authority.get("alpaca", {})
    required = validate_contract_selectors(alpaca.get("required_contracts"))
    required_instances = validate_contract_instances(
        required, alpaca.get("required_contract_instances"))
    suite_paths = owned_test_modules(authority, "alpaca.contracts")
    if not suite_paths:
        raise RuntimeError("Alpaca contract owner has no test modules")
    suite_names = [relative_posix(path) for path in suite_paths]
    suite_set = set(suite_names)
    escaped = {
        contract: selector for contract, selector in required.items()
        if selector.split("::", 1)[0] not in suite_set
    }
    if escaped:
        raise RuntimeError(
            "Alpaca required contracts escape their declared suite owner: "
            + json.dumps(escaped, sort_keys=True))

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "shared")
    env["ALPACA_HARNESS_REQUIRE_POSTGRES"] = "1"
    started_sha, started_tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    dirty_before = bool(git("status", "--porcelain", "--untracked-files=no"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *suite_names, "--collect-only", "-q"],
        cwd=ROOT, env=env, check=False, capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    collected = _collected_nodeids(result.stdout)

    resolution = {}
    resolution_error = None
    try:
        resolution = resolve_contracts(required, collected)
        if resolution != required_instances:
            raise AssertionError(
                "Alpaca physical contract inventory differs: expected=%s actual=%s" %
                (json.dumps(required_instances, sort_keys=True),
                 json.dumps(resolution, sort_keys=True)))
    except AssertionError as exc:
        resolution_error = str(exc)

    missing_suites = [
        name for name in suite_names
        if not any(nodeid.startswith(name + "::") for nodeid in collected)
    ]
    stable = (
        git("rev-parse", "HEAD") == started_sha
        and git("rev-parse", "HEAD^{tree}") == started_tree
        and not git("status", "--porcelain", "--untracked-files=no")
    )
    passed = (
        result.returncode == 0
        and bool(collected)
        and not dirty_before
        and stable
        and resolution_error is None
        and not missing_suites
    )

    files = [
        ROOT / "tests/support/alpaca_simulator.py",
        ROOT / "sentinel/execution/alpaca.py",
        ROOT / "sentinel/execution/broker_cash.py",
        MANIFEST,
        Path(__file__),
        ROOT / "tools/test_responsibility_lib.py",
        *suite_paths,
    ]
    evidence = {
        "schema": "sentinel.alpaca-contracts/4",
        "status": "PASS" if passed else "FAIL",
        "git_sha": started_sha,
        "git_tree": started_tree,
        "source_stable": stable,
        "tracked_changes": dirty_before,
        "python": sys.version,
        "collection_only": True,
        "execution_owner": "sentinel.complete",
        "pytest_collect_exit_code": result.returncode,
        "collected": len(collected),
        "required_contracts": required,
        "required_contract_instances": required_instances,
        "contract_resolution": resolution,
        "resolution_error": resolution_error,
        "suites": suite_names,
        "missing_suites": missing_suites,
        "profiles": ["PAPER", "LIVE_CASH"],
        "transport": "httpx.MockTransport",
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
        "limitations": [
            "SIMULATION_ONLY",
            "LIVE_ENDPOINT_REFUSED",
            "CANDIDATE_ACTIVITY_AUTHORITY_UNPROMOTED",
            "VENDOR_FINALITY_NOT_PROVEN",
        ],
    }
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    (output / "collected-nodeids.txt").write_text("\n".join(collected) + "\n")
    print(json.dumps({
        "status": evidence["status"],
        "collected": len(collected),
        "contracts": len(resolution),
        "physical_contracts": sum(len(values) for values in required_instances.values()),
        "resolution_error": resolution_error,
    }, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
