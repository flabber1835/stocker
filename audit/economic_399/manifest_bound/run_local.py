"""Reproduce offline bounded-manifest regression and guard falsifiers."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", choices=("regression", "backup", "mutations", "measure"))
    parser.add_argument("--image", default="sentinel-test:ci")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    command = (["-m", "tools.sentinel_manifest_bound_falsifiers"]
               if args.campaign == "mutations" else [
                   "-m", "pytest", "tests/backup/test_manifest_admission.py",
                   "tests/backup/test_runtime_backup_integrity.py",
                   "tests/backup/test_runtime_backup_authority.py",
                   "tests/sentinel/test_backup_manifest_bound.py",
                   "tests/sentinel/test_reboot_outage_recovery.py",
                   "tests/sentinel/test_backup_contract.py",
                   "-q", "--tb=short", "-p", "no:cacheprovider"])
    if args.campaign == "backup":
        command = ["-m", "pytest", "tests/backup",
                   "tests/sentinel/test_backup_manifest_bound.py",
                   "tests/internal_state/test_physical.py",
                   "-q", "--tb=short", "-p", "no:cacheprovider"]
    if args.campaign == "measure":
        command = ["audit/economic_399/manifest_bound/measure_manifest.py"]
    with tempfile.TemporaryDirectory(prefix="sentinel-offline-") as directory:
        empty = Path(directory) / "empty.env"
        empty.write_bytes(b"")
        docker = ["docker", "run", "--rm", "--network", "none",
                  "--mount", f"type=bind,source={root.as_posix()},target=/repo,readonly",
                  "--workdir", "/repo"]
        docker += ["--memory", "2g", "--cpus", "2"]
        if (root / ".env").exists():
            docker += ["--mount", f"type=bind,source={empty.as_posix()},target=/repo/.env,readonly"]
        docker += ["-e", "SENTINEL_REPO_ROOT=/repo", "-e", "PYTHONPATH=/repo:/repo/shared",
                   "-e", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint", "python", args.image,
                   "-u", *command]
        print(json.dumps(docker), flush=True)
        return subprocess.run(docker).returncode


if __name__ == "__main__":
    raise SystemExit(main())
