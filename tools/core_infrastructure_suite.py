#!/usr/bin/env python3
"""Run every small infrastructure suite assigned by test-responsibility authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]

from tests.support.postgres import _EphemeralPostgres
from tools.test_responsibility_lib import load_authority, owner_paths, relative_posix


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def owned_suites() -> tuple[str, ...]:
    authority = load_authority()
    suites = tuple(
        relative_posix(path)
        for path in owner_paths(authority, "core.infrastructure")
    )
    if not suites:
        raise RuntimeError("core.infrastructure owner has no suites")
    return suites


def main() -> int:
    output = ROOT / "artifacts" / "core-infrastructure"
    output.mkdir(parents=True, exist_ok=False)
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("core infrastructure gate requires a clean tested commit")
    suites = owned_suites()

    server = _EphemeralPostgres()
    result = None
    try:
        server.start()
        env = dict(
            os.environ,
            PYTHONPATH=str(ROOT / "shared"),
            SENTINEL_DATABASE_URL=server.sync_dsn,
            ALPACA_HARNESS_REQUIRE_POSTGRES="1",
            SENTINEL_PUBLICATION_RECEIPT_KEY="core-infrastructure-synthetic-receipt-key",
            INTERNAL_STATE_SUITE_EVIDENCE=str(output / "suites"),
            PYTEST_ADDOPTS="-p tests.internal_state.ci_gate",
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *suites, "-q", "-ra",
             f"--junitxml={output / 'junit.xml'}"],
            cwd=ROOT,
            env=env,
            check=False,
        )
    finally:
        server.stop()

    status = 1 if result is None else result.returncode
    evidence = {
        "schema": "stocker.core-infrastructure/2",
        "verdict": "PASS" if status == 0 else "FAIL",
        "commit": commit,
        "tree": tree,
        "suites": list(suites),
        "suite_authority": "tests/test-responsibility.json#core.infrastructure",
        "pytest_exit_code": status,
    }
    (output / "evidence.json").write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
