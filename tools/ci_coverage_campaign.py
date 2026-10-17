"""Advisory, source-authenticated coverage using the pinned local test runner.

This campaign never produces release, deployment or broker authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import site
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import repository_code_coverage as reporter
from tools.test_responsibility_lib import load_authority


def selected_owners(authority: dict, requested: str = "") -> list[str]:
    eligible = {
        name for name, owner in authority["owners"].items()
        if owner.get("execution", {}).get("kind") == "pytest-junit"
    }
    names = requested.split(",") if requested else sorted(eligible)
    if (not names or any(not name or name != name.strip() for name in names)
            or len(names) != len(set(names)) or not set(names) <= eligible):
        raise ValueError("coverage owners must be distinct explicit pytest owner names")
    return sorted(names)


def write_config(evidence: Path) -> Path:
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "raw").mkdir(exist_ok=True)
    config = evidence / "coverage.ini"
    config.write_text(
        "[run]\nbranch = True\nparallel = True\n"
        "concurrency = multiprocessing\n"
        "source = /app/sentinel, /app/tools, stock_strategy_shared, /work/tools, /work/scripts, /work/repo, "
        "/work/research, /work/audit, /work/docs\n"
        f"data_file = {(evidence / 'raw' / 'coverage').as_posix()}\n"
        "[report]\nexclude_lines =\nexclude_also =\n"
        "partial_branches =\npartial_also =\n", encoding="utf-8")
    return config


def install_child_startup(directory: Path) -> Path:
    """Only a disposable CI lens may acquire the subprocess startup hook."""
    if os.environ.get("SENTINEL_IN_IMAGE") != "1":
        raise RuntimeError("coverage subprocess startup requires the disposable test lens")
    path = directory / "sentinel_advisory_coverage.pth"
    content = "import coverage; coverage.process_startup()\n"
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise RuntimeError("refusing to replace another interpreter startup hook")
    path.write_text(content, encoding="utf-8")
    return path


def inventory(root: Path) -> dict:
    # This exact read-only checkout belongs to the host runner, whereas the
    # disposable lens is root-owned. Trust only this resolved path per command.
    git = ["git", "-c", "safe.directory=" + str(root.resolve())]
    names = subprocess.check_output([*git, "ls-files", "-z"], cwd=root)
    revision = subprocess.check_output(
        [*git, "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("coverage source has no exact Git revision")
    return reporter.source_inventory(
        root, (name.decode("utf-8") for name in names.split(b"\0") if name),
        revision=revision)


def write_report(root: Path, evidence: Path, data_root: Path,
                 expected_owners: list[str]) -> dict:
    manifest = inventory(root)
    counters = sorted(data_root.rglob("coverage.*"))
    counters = [p for p in counters if p.is_file() and p.name != "coverage.ini"]
    if not counters:
        raise ValueError("no coverage counters were retained")
    result = reporter.report(root, manifest, counters)
    if not any(item["status"] == "BRANCH_MEASUREMENTS" for item in result["inputs"]):
        raise ValueError("no executed branch measurements were retained")
    result["campaign_scope"] = "ADVISORY_TEST_PATH_MEASUREMENT"
    result["test_execution"] = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(data_root.rglob("coverage-execution.json"))]
    observed = [receipt.get("owner") for receipt in result["test_execution"]]
    if (sorted(observed) != sorted(expected_owners)
            or len(observed) != len(set(observed))):
        raise ValueError("coverage owner receipts do not equal the selected owner union")
    for receipt in result["test_execution"]:
        if (receipt.get("schema") != "sentinel.advisory-coverage-execution/1"
                or receipt.get("revision") != manifest["revision"]
                or type(receipt.get("exit_code")) is not int):
            raise ValueError("coverage execution receipt is not bound to this source")
    result["claims_release_authority"] = False
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "source-inventory.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (evidence / "coverage-report.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    rows = ["# Advisory repository coverage", "",
            "Source: `" + manifest["revision"] + "`", "",
            "Selected pytest owners: " + ", ".join("`" + owner + "`" for owner in expected_owners), "",
            "Coverage measures executed paths; it is not release or broker authority.",
            "Missing statements, branches and unmeasured languages remain visible.", "",
            "| Domain | Statements | Missing | Branches | Missing | Combined |",
            "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for domain, values in sorted(result["domains"].items()):
        percent = values["combined_percent"]
        rows.append("| %s | %s | %s | %s | %s | %s |" % (
            domain, values["statements"], values["missing_statements"],
            values["branches"], values["missing_branches"],
            "unmeasured" if percent is None else f"{percent:.2f}%"))
    rows += ["", "Unmeasured languages: " + ", ".join(result["unmeasured_languages"]),
             "", "Execution receipts: " + str(len(result["test_execution"]))]
    (evidence / "coverage-summary.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return result


def run(root: Path, evidence: Path, owner: str) -> int:
    selected_owners(load_authority(), owner)
    source = inventory(root)  # Refuse source/setup problems before expensive tests.
    config = write_config(evidence)
    install_child_startup(Path(site.getsitepackages()[0]))
    env = dict(os.environ, COVERAGE_PROCESS_START=str(config),
               COVERAGE_FILE=str(evidence / "raw" / "coverage"))
    command = [sys.executable, str(ROOT / "tools/local_test_runner.py"),
               "--owner", owner, "--coverage", "--coverage-config", str(config),
               "--evidence", str(evidence / "test-results")]
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    receipt = {"schema": "sentinel.advisory-coverage-execution/1", "owner": owner,
               "revision": source["revision"],
               "exit_code": completed.returncode, "command": command,
               "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest()}
    (evidence / "coverage-execution.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    write_report(root, evidence, evidence, [owner])
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run", "report"))
    parser.add_argument("--owners", default="")
    parser.add_argument("--owner")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "plan":
        result = {"owner": selected_owners(load_authority(), args.owners)}
        payload = json.dumps(result)
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.root is None or args.evidence is None:
        parser.error("run/report require exact source root and evidence directory")
    if args.action == "run":
        if args.owner is None:
            parser.error("run requires one explicit owner")
        return run(args.root.resolve(), args.evidence.resolve(), args.owner)
    result = write_report(args.root.resolve(), args.evidence.resolve(),
                          (args.data_root or args.evidence).resolve(),
                          selected_owners(load_authority(), args.owners))
    return int(any(receipt["exit_code"] != 0 for receipt in result["test_execution"]))


if __name__ == "__main__":
    raise SystemExit(main())
