"""Reproduce the PR 405 CI-fixture and merged-installer regressions offline."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", choices=("regression", "mutations"))
    args = parser.parse_args()
    runtime = json.loads((here.parent / "rolling_admission_403" / "commands.json").read_text())["runtime"]
    command = (["-m", "tools.sentinel_rolling_admission_falsifiers"]
               if args.campaign == "mutations" else [
                   "-m", "pytest", "tests/sentinel/test_empty_account_binding.py",
                   "tests/sentinel/test_rolling_admission_readers.py",
                   "tests/sentinel/test_paper_observation_authority.py",
                   "tests/sentinel/test_autonomous_deploy.py",
                   "tests/sentinel/test_autonomous_deploy_driver.py",
                   "tests/sentinel/test_autonomous_deploy_bootstrap.py",
                   "tests/scripts/test_sentinel_bringup_install_anytime.py",
                   "-q", "--tb=short", "-p", "no:cacheprovider"])
    with tempfile.TemporaryDirectory(prefix="sentinel-offline-") as directory:
        empty = Path(directory) / "empty.env"
        empty.write_bytes(b"")
        docker = ["docker", "run", "--rm", "--network", "none",
                  "--mount", f"type=bind,source={root.as_posix()},target=/repo,readonly",
                  "--workdir", "/repo"]
        if (root / ".env").exists():
            docker += ["--mount", f"type=bind,source={empty.as_posix()},target=/repo/.env,readonly"]
        for key, value in runtime["environment"].items():
            docker += ["-e", key + "=" + value]
        docker += ["--entrypoint", "python", runtime["image"], "-u", *command]
        print(json.dumps(docker), flush=True)
        return subprocess.run(docker).returncode


if __name__ == "__main__":
    raise SystemExit(main())
