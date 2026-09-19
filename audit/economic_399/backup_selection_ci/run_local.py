"""Offline, unprivileged regression and lifecycle evidence for PR 410 fixtures."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", choices=("regression", "lifecycle", "falsifiers"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if not args.inside:
        args.output.mkdir(parents=True, exist_ok=False)
        bootstrap = """import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared',SENTINEL_REPO_ROOT='/tmp/repo',ALPACA_HARNESS_REQUIRE_POSTGRES='1',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
"""
        command = ["docker", "run", "--rm", "--network", "none", "--user", "postgres",
            "-e", "USER=postgres", "--mount", f"type=bind,source={root.as_posix()},target=/source,readonly",
            "--mount", f"type=bind,source={args.output.resolve().as_posix()},target=/evidence",
            "--entrypoint", "python", "sentinel-test:ci", "-u", "-c", bootstrap,
            "audit/economic_399/backup_selection_ci/run_local.py", args.campaign,
            "--inside", "--output", "/evidence"]
        print(json.dumps(command), flush=True)
        return subprocess.run(command).returncode

    if root != Path("/tmp/repo") or not Path("/source").is_dir() or not Path("/evidence").is_dir():
        raise RuntimeError("--inside requires the disposable container checkout and mounts")
    os.chdir(root)
    # This is an explicitly synthetic local snapshot, not the reviewed Git head.
    # It lets the lifecycle harness enforce its unchanged-source contract.
    for command in (["git", "init", "-q"], ["git", "add", "."],
            ["git", "-c", "user.name=Local fixture validation", "-c",
             "user.email=fixture@invalid", "commit", "-qm", "Synthetic local fixture snapshot"]):
        subprocess.run(command, check=True, capture_output=True)
    if args.campaign == "regression":
        command = [sys.executable, "-m", "pytest", "tests/internal_state",
            "tests/production_composition", "-q", "-ra", "--tb=short", "-p", "no:cacheprovider",
            f"--junitxml={args.output / 'regression.xml'}"]
    elif args.campaign == "lifecycle":
        command = [sys.executable, "tools/internal_state_harness.py", "--seeds", "2",
            "--output", str(args.output / "lifecycle")]
        for name in ("populated_lifecycle", "backup_loss_after_plan",
                     "wal_corruption_after_plan", "stale_populated_restore",
                     "generated_00000000", "generated_00000001"):
            command += ["--scenario", name]
    else:
        command = [sys.executable, "tools/sentinel_backup_fixture_falsifiers.py"]
    print(json.dumps(command), flush=True)
    with (args.output / "output.log").open("w") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    print((args.output / "output.log").read_text(), flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
