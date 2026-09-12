from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_HELPER = ROOT / "scripts" / "sentinel_go_lock.py"
SCRIPTS = ROOT / "scripts"
COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
MARKER = "PHASE_C_RESULT="


def _env_file(tmp_path: Path) -> Path:
    path = tmp_path / "composition.env"
    path.write_text(
        "\n".join([
            "SENTINEL_BACKUP_DIR=/tmp/sentinel-composition-backup",
            "SENTINEL_POSTGRES_PASSWORD=compositionpassword",
            "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL=https://example.invalid/sentinel",
            "SENTINEL_GITHUB_READ_TOKEN=github_pat_composition_fixture",
            "SHARADAR_API_KEY=composition-sharadar",
            "ALPACA_API_KEY=composition-alpaca-key",
            "ALPACA_SECRET_KEY=composition-alpaca-secret",
            "",
        ]),
        encoding="utf-8",
    )
    return path


def _child_code() -> str:
    return f'''
import json, os, subprocess, sys
sys.path.insert(0, {str(SCRIPTS)!r})
import sentinel_go_validate_entry as entry

COMMIT = {COMMIT!r}
DIGEST = {DIGEST!r}

class Runner:
    def __init__(self):
        self.calls = []
        self.last_preparation_output = ""

    def run(self, argv, *, env=None, cwd=entry.go.ROOT):
        command = [str(item) for item in argv]
        self.calls.append(command)
        if command[:3] == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="-f docker-compose.sentinel.yml\\n", stderr="")
        if "scripts/sentinel_feed_gate.py" in command:
            return subprocess.CompletedProcess(
                command, 0, stdout=COMMIT + "\\n" + DIGEST + "\\n", stderr="")
        if command[:2] == ["docker", "compose"]:
            payload = {{
                "schema_migrated": True,
                "source_not_before_satisfied": True,
                "following_open_future": True,
                "bounded_sharadar_daily": True,
                "publication_current": True,
            }}
            return subprocess.CompletedProcess(
                command, 0,
                stdout="SENTINEL_GO_PREPARATION=" + json.dumps(payload) + "\\n",
                stderr="")
        raise AssertionError("unexpected command: %r" % command)

entry.authorize_verified_orchestration()
env = entry.go.merged_environment()
env["SHARADAR_API_KEY"] = "composition-sharadar"
env["SENTINEL_POSTGRES_PASSWORD"] = "compositionpassword"
if os.environ.get("PHASE_C_DROP_LOCK") == "1":
    env.pop(entry.go_lock.LOCK_HELD_ENV, None)
    env.pop(entry.go_lock.LOCK_FD_ENV, None)
runner = Runner()
result = entry.probe_prevalidation_preparation(
    runner, env=env, runtime_ref=DIGEST, commit=COMMIT)
print({MARKER!r} + json.dumps({{
    "status": result.status,
    "complete": bool(result.complete),
    "schema_migration_attempted": bool(result.schema_migration_attempted),
    "bounded_sharadar_daily_attempted": bool(result.bounded_sharadar_daily_attempted),
    "lock_in_merged_env": bool(entry.go_lock.lifecycle_lock_is_held(env)),
    "diagnostic": runner.last_preparation_output,
    "calls": runner.calls,
}}, sort_keys=True))
'''.strip()


def _clean_host_controls(env):
    for key in list(env):
        if key.startswith("COMPOSE_") or key.startswith("DOCKER_"):
            env.pop(key, None)
    for key in (
        "SENTINEL_GO_LOCK_HELD", "SENTINEL_GO_LOCK_FD", "SENTINEL_GO_RUN_TOKEN",
        "SENTINEL_GITHUB_READ_TOKEN", "GITHUB_TOKEN", "GH_TOKEN",
    ):
        env.pop(key, None)


def _run(tmp_path: Path, *, drop_lock=False):
    env = dict(os.environ)
    _clean_host_controls(env)
    env.update({
        "COMPOSITION_ENV_FILE": str(_env_file(tmp_path)),
        "REAL_PYTHON": sys.executable,
        "PHASE_C_CODE": _child_code(),
        "PHASE_C_DROP_LOCK": "1" if drop_lock else "0",
    })
    shell = r'''
set -euo pipefail
PYTHON="$REAL_PYTHON"
. scripts/sentinel-env.sh
sentinel_load_environment --profile go --env-file "$COMPOSITION_ENV_FILE"
"$REAL_PYTHON" -c "$PHASE_C_CODE"
'''
    completed = subprocess.run(
        [sys.executable, str(LOCK_HELPER), "bash", "-c", shell],
        cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=30, check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith(MARKER)]
    payload = json.loads(lines[-1][len(MARKER):]) if lines else None
    return completed, payload


def test_real_lock_and_real_env_bridge_authorize_phase_c_boundary(tmp_path):
    completed, payload = _run(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert payload is not None
    assert payload["lock_in_merged_env"] is True
    assert payload["status"] == "PASS"
    assert payload["complete"] is True
    assert payload["schema_migration_attempted"] is True
    assert payload["bounded_sharadar_daily_attempted"] is True
    assert any("sentinel_feed_gate.py" in " ".join(call) for call in payload["calls"])
    assert any(call[:2] == ["docker", "compose"] for call in payload["calls"])


def test_dropping_inherited_lock_from_phase_c_environment_refuses_without_mutation(
        tmp_path):
    completed, payload = _run(tmp_path, drop_lock=True)
    assert completed.returncode == 0, completed.stderr
    assert payload is not None
    assert payload["lock_in_merged_env"] is False
    assert payload["status"] == "NOT_PROVEN"
    assert payload["complete"] is False
    assert payload["schema_migration_attempted"] is False
    assert payload["bounded_sharadar_daily_attempted"] is False
    assert "GO_LIFECYCLE_LOCK_NOT_PROVEN_NO_MUTATION" in payload["diagnostic"]
    assert payload["calls"] == []


def test_phase_c_process_diagnostic_never_contains_test_credentials(tmp_path):
    completed, payload = _run(tmp_path, drop_lock=True)
    assert completed.returncode == 0, completed.stderr
    surface = (completed.stdout or "") + (completed.stderr or "")
    assert "composition-sharadar" not in payload["diagnostic"]
    assert "compositionpassword" not in payload["diagnostic"]
    assert "github_pat_composition_fixture" not in payload["diagnostic"]
    # The loader and Phase-C refusal may print status/diagnostic metadata, but no
    # configured secret value may cross their public output boundary.
    assert "composition-sharadar" not in surface
    assert "compositionpassword" not in surface
    assert "github_pat_composition_fixture" not in surface
