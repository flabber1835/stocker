from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])


def test_actual_restore_launcher_forwards_receipt_key_without_secret_arguments(tmp_path):
    script = (ROOT / "scripts/sentinel-restore-drill.sh").read_text()
    start = script.index('export SENTINEL_RESTORE_DATABASE_PASSWORD=')
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
    "secret_in_arguments": any(secret in arg for arg in args for secret in (os.environ[key], os.environ["SENTINEL_POSTGRES_PASSWORD"])),
    "password_matches": forwarded.get("SENTINEL_RESTORE_DATABASE_PASSWORD") == os.environ["SENTINEL_POSTGRES_PASSWORD"],
    "forwarded_names": sorted(forwarded),
    "tmpfs": args[args.index("--tmpfs") + 1],
    "tmpdir": forwarded.get("TMPDIR"),
    "runtime_facts": {name: forwarded.get(name) for name in json.loads(os.environ["EXPECTED_RUNTIME_NAMES"])},
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
    runtime_facts = {
        "SENTINEL_GIT_COMMIT": "b" * 40,
        "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "a" * 64,
        "SENTINEL_TEST_IMAGE_DIGEST": "sha256:" + "a" * 64,
        "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        "SENTINEL_LOCAL_PAPER_MODE": "OWNER_AUTHORIZED_FUNCTION_FIRST_V1",
        "SENTINEL_LOCAL_PAPER_ACCOUNT_ID": "PAfixture",
        "SENTINEL_LOCAL_PAPER_BACKUP_POLICY": "REQUIRED_V1",
        "SENTINEL_PAPER_BUY_POLICY": "PROTECTED_LIMIT_DAY_V1",
        "SENTINEL_PAPER_BUY_CAP_BPS": "100",
        "SENTINEL_REVIEWED_DEPLOYMENT_MODE": "dual",
        "SENTINEL_SHADOW_OBSERVATION_ID": "retained-observation",
        "SENTINEL_SHADOW_STARTING_CASH": "50000",
        "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY": "CURRENT_CONTEXT_V1",
        "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": "f" * 64,
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": "c" * 64,
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": "d" * 64,
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": "e" * 64,
    }
    env.update(runtime_facts)
    env["EXPECTED_RUNTIME_NAMES"] = json.dumps(sorted(runtime_facts))
    env.update(SENTINEL_DATABASE_URL="must-not-forward",
               SENTINEL_DEPLOY_SIGNING_KEY_FILE="must-not-forward",
               SENTINEL_PAPER_ACCOUNT_ID="must-not-forward")
    result = subprocess.run(["bash", "-eu", "-c", adapter + script[start:end]],
                            env=env, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["receipt_matches"] is True
    assert report["password_matches"] is True
    assert report["secret_in_arguments"] is False
    assert report["runtime_facts"] == runtime_facts
    assert report["tmpdir"] == "/tmp/sentinel-restore"
    assert report["tmpfs"] == "/tmp/sentinel-restore:rw,noexec,nosuid,size=16m"
    assert report["forwarded_names"] == sorted([
        "SENTINEL_PUBLICATION_RECEIPT_KEY", "SENTINEL_RESTORE_DATABASE_HOST",
        "SENTINEL_RESTORE_DATABASE_PASSWORD", "TMPDIR", *runtime_facts])
