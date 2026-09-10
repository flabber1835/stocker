#!/usr/bin/env python3
"""Prove env regressions fail when selected production guards are removed."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "tests.host_python38.test_env_ingestion.EnvHarness."
MUTANTS = (
    ("duplicate-last-wins", "scripts/sentinel_env.py",
     "if name in values:", "if False and name in values:",
     "test_refuse_canonical_duplicate_conflict"),
    ("nonprinting-accepted", "scripts/sentinel_env.py",
     "return (unicodedata.category(char)", "return False and (unicodedata.category(char)",
     "test_refuse_canonical_nul"),
    ("missing-required-accepted", "scripts/sentinel_env.py",
     "if invalid:", "if False and invalid:",
     "test_required_SHARADAR_API_KEY_0"),
    ("unstable-file-accepted", "scripts/sentinel_env.py",
     "if (_identity(os.fstat(fd))", "if False and (_identity(os.fstat(fd))",
     "test_atomic_replacement_during_read_is_refused"),
    ("installer-preflight-removed", "scripts/sentinel-autonomous-deploy.sh",
     "sentinel_load_environment --profile install", ": # removed preflight",
     "test_launcher_sentinel_autonomous_deploy_sh_missing_required"),
)


def main() -> int:
    baseline = subprocess.run(
        [sys.executable, "-m", "unittest"] + [HARNESS + item[4] for item in MUTANTS],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if baseline.returncode != 0:
        print("REFUSED: env mutant baseline is not green", file=sys.stderr)
        return 2
    for name, relative, old, new, test in MUTANTS:
        with tempfile.TemporaryDirectory(prefix="sentinel-env-mutant-") as temporary:
            mutant = Path(temporary)
            shutil.copytree(ROOT / "scripts", mutant / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            path = mutant / relative
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                print("REFUSED: mutant anchor drift: " + name, file=sys.stderr)
                return 2
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            process = dict(os.environ, SENTINEL_REPO_ROOT=str(mutant))
            result = subprocess.run(
                [sys.executable, "-m", "unittest", HARNESS + test], cwd=str(ROOT),
                env=process, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=30)
            if result.returncode != 1 or "FAIL: " + test not in result.stdout or "ERROR:" in result.stdout:
                print("REFUSED: mutant survived or harness errored: " + name, file=sys.stderr)
                return 1
            print("KILLED: " + name)
    print("environment mutation checks: PASS (%d/%d)" % (len(MUTANTS), len(MUTANTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
