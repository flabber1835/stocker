from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])


def test_actual_restore_launcher_forwards_receipt_key_without_secret_arguments(tmp_path):
    script = (ROOT / "scripts/sentinel-restore-drill.sh").read_text()
    start = script.index("SEMANTIC_STARTED=1\ndocker run")
    end = script.index('\necho "restore_semantics_ready:', start)
    docker = tmp_path / "docker"
    docker.write_text("#!" + sys.executable + "\n" + r'''
import json, os, sys
forwarded = {}
args = sys.argv[1:]
for i, arg in enumerate(args[:-1]):
    if arg == "-e":
        value = args[i+1]
        name, separator, literal = value.partition("=")
        forwarded[name] = literal if separator else os.environ.get(name)
key = "SENTINEL_PUBLICATION_RECEIPT_KEY"
print(json.dumps({
    "receipt_matches": forwarded.get(key) == os.environ[key],
    "secret_in_arguments": any(os.environ[key] in arg for arg in args),
    "forwarded_names": sorted(forwarded),
}))
''')
    adapter = 'docker() { "$RECORDING_PYTHON" "$RECORDING_DOCKER" "$@"; }' + "\n"
    env = {
        "PATH": os.environ["PATH"],
        "RECORDING_PYTHON": sys.executable, "RECORDING_DOCKER": str(docker),
        "NETWORK": "isolated-restore", "CONTAINER": "isolated-restore",
        "RUNTIME_IMAGE": "sentinel@sha256:" + "a" * 64,
        "SENTINEL_POSTGRES_PASSWORD": "synthetic-database-password",
        "SENTINEL_PUBLICATION_RECEIPT_KEY": "synthetic-receipt-key-" + "a" * 32,
        "ALPACA_API_KEY": "must-not-forward", "OPENFIGI_API_KEY": "must-not-forward",
    }
    result = subprocess.run(["bash", "-eu", "-c", adapter + script[start:end]],
                            env=env, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["receipt_matches"] is True
    assert report["secret_in_arguments"] is False
    assert report["forwarded_names"] == sorted([
        "SENTINEL_PUBLICATION_RECEIPT_KEY", "SENTINEL_RESTORE_DATABASE_HOST",
        "SENTINEL_RESTORE_DATABASE_PASSWORD"])
