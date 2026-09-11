"""Validate the bounded Alpaca contract inventory without re-running Sentinel tests.

The complete Sentinel suite owns ordinary test execution.  This harness proves
that every required Alpaca contract is still collected from the reviewed suite
surface; the companion mutation harness remains the independent falsification
layer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "test-responsibility.json"
SUITES = (
    "test_alpaca_simulation_harness.py",
    "test_alpaca_simulation_cash.py",
    "test_alpaca_simulation_durability.py",
    "test_alpaca_simulation_review_regressions.py",
    "test_alpaca_simulation_sessions.py",
    "test_alpaca_execution_entrypoint.py",
    "test_execution_state_machine_model.py",
    "test_issue_183_alpaca_hardening.py",
    "test_issue_209_alpaca_asset_id.py",
    "test_alpaca_activity_sse_accounting.py",
    "test_alpaca_certification_boundary.py",
    "test_alpaca_restart_day_fence.py",
    "test_guarded_execution_broker.py",
)


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

    suites = [str(ROOT / "tests/sentinel" / name) for name in SUITES]
    authority = json.loads(MANIFEST.read_text())
    if authority.get("schema") != "stocker.test-responsibility/1":
        raise RuntimeError("invalid test-responsibility authority schema")
    required = authority.get("alpaca", {}).get("required_contracts", {})
    if not required or not all(isinstance(k, str) and isinstance(v, str) for k, v in required.items()):
        raise RuntimeError("Alpaca required-contract authority is empty or invalid")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "shared")
    env["ALPACA_HARNESS_REQUIRE_POSTGRES"] = "1"
    started_sha, started_tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    dirty_before = bool(git("status", "--porcelain", "--untracked-files=no"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *suites, "--collect-only", "-q"],
        cwd=ROOT, env=env, check=False, capture_output=True, text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    collected = _collected_nodeids(result.stdout)
    missing_contracts = {
        contract: needle for contract, needle in required.items()
        if not any(needle in nodeid for nodeid in collected)
    }
    missing_suites = [
        name for name in SUITES
        if not any(f"tests/sentinel/{name}::" in nodeid for nodeid in collected)
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
        and not missing_contracts
        and not missing_suites
    )

    files = [
        ROOT / "tests/support/alpaca_simulator.py",
        ROOT / "sentinel/execution/alpaca.py",
        ROOT / "sentinel/execution/broker_cash.py",
        MANIFEST,
        Path(__file__),
        *(Path(p) for p in suites),
    ]
    evidence = {
        "schema": "sentinel.alpaca-contracts/2",
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
        "missing_contracts": missing_contracts,
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
    print(json.dumps({"status": evidence["status"], "collected": len(collected),
                      "missing_contracts": sorted(missing_contracts)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
