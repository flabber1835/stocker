"""Isolated policy faults; never edit the running implementation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

FAULTS = {
    "release_after_seven": ('sessions=8', 'sessions=7'),
    "native_cause_removed": ('result["native"]', '1.'),
    "missing_health_ignored": ('healthy and result["native"] == 1.', 'result["native"] == 1.'),
    "owned_ceiling_removed": ('result["native"], result["ceiling"]', 'result["native"], 1.'),
    "checkpoint_commitment_removed": ('value.get("sha256") != digest(', 'False and value.get("sha256") != digest('),
}


def main():
    source = Path("research/recovery_bridge/model.py").read_text()
    results = {}
    with tempfile.TemporaryDirectory(prefix="bridge-mutants-") as temp:
        for name, (before, after) in FAULTS.items():
            assert before in source
            path = Path(temp)/f"{name}.py"
            path.write_text(source.replace(before, after))
            env = dict(os.environ, RECOVERY_BRIDGE_MUTANT_FILE=str(path))
            run = subprocess.run([sys.executable, "-m", "pytest", "research/recovery_bridge/test_model.py", "-q",
                "-p", "no:cacheprovider", "--basetemp", str(Path(temp)/f"test-{name}")], env=env, capture_output=True, text=True)
            killed = run.returncode == 1 and " failed" in run.stdout and "ERROR " not in run.stdout
            results[name] = dict(killed=killed, exit_code=run.returncode, summary=run.stdout.strip().splitlines()[-1])
            if not killed:
                raise AssertionError(run.stdout+run.stderr)
    Path("audit/owned-recovery-bridge/mutations.json").write_text(json.dumps(results, indent=2)+"\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
