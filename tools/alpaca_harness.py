"""Run the bounded Alpaca regression gate and retain reviewable evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    "test_alpaca_simulation_harness.py",
    "test_alpaca_simulation_cash.py",
    "test_alpaca_simulation_durability.py",
    "test_issue_183_alpaca_hardening.py",
    "test_issue_209_alpaca_asset_id.py",
    "test_alpaca_activity_sse_accounting.py",
    "test_alpaca_certification_boundary.py",
    "test_alpaca_restart_day_fence.py",
    "test_guarded_execution_broker.py",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    junit = output / "junit.xml"
    suites = [str(ROOT / "tests/sentinel" / name) for name in SUITES]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "shared")
    env["ALPACA_HARNESS_REQUIRE_POSTGRES"] = "1"
    started_sha, started_tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    dirty_before = bool(git("status", "--porcelain", "--untracked-files=no"))
    result = subprocess.run([sys.executable, "-m", "pytest", *suites,
                             "-q", "--tb=short", f"--junitxml={junit}"],
                            cwd=ROOT, env=env, check=False)
    cases = list(ET.parse(junit).getroot().iter("testcase")) if junit.exists() else []
    counts = {tag: sum(c.find(tag) is not None for c in cases)
              for tag in ("failure", "error", "skipped")}
    counts["total"] = len(cases)
    counts["passed"] = len(cases) - sum(counts[t] for t in ("failure", "error", "skipped"))
    stable = (git("rev-parse", "HEAD") == started_sha
              and git("rev-parse", "HEAD^{tree}") == started_tree
              and not git("status", "--porcelain", "--untracked-files=no"))
    passed = (result.returncode == 0 and len(cases) >= 264 and stable
              and not dirty_before and not any(counts[t] for t in ("failure", "error", "skipped")))
    files = [ROOT / "tests/support/alpaca_simulator.py",
             ROOT / "sentinel/execution/alpaca.py",
             ROOT / "sentinel/execution/broker_cash.py", Path(__file__),
             *(Path(p) for p in suites)]
    evidence = dict(schema="sentinel.alpaca-simulation/1", status="PASS" if passed else "FAIL",
                    git_sha=started_sha, git_tree=started_tree,
                    source_stable=stable, tracked_changes=dirty_before,
                    python=sys.version, tests=counts, pytest_exit_code=result.returncode,
                    profiles=["PAPER", "LIVE_CASH"], transport="httpx.MockTransport",
                    source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in files},
                    limitations=["SIMULATION_ONLY", "LIVE_ENDPOINT_REFUSED",
                                 "CANDIDATE_ACTIVITY_AUTHORITY_UNPROMOTED",
                                 "VENDOR_FINALITY_NOT_PROVEN"])
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"status": evidence["status"], "tests": counts}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
