from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "sentinel-go-validate.sh"

STAGES = (
    ("bootstrap", "scripts/sentinel_deployment_bootstrap.py"),
    ("host_preflight", "scripts/sentinel_go_host_preflight.py"),
    ("runtime_preflight", "scripts/sentinel_runtime_selection.py"),
    ("account_preflight", "scripts/sentinel_go_account_preflight.py"),
    # output_guard owns certification, Phase C schema/Sharadar/publication work,
    # read-only readiness, and final validation-bundle creation.
    ("validation_phase_c_bundle", "scripts/sentinel_go_output_guard.py"),
    ("promotion_pointer", "scripts/sentinel_go_promote.py"),
    ("panel_handoff", "scripts/sentinel_go_post_validate.py"),
)


def _write_env(path: Path):
    path.write_text("\n".join([
        "SENTINEL_BACKUP_DIR=/tmp/sentinel-composition-backup",
        "SENTINEL_POSTGRES_PASSWORD=compositionpassword",
        "SHARADAR_API_KEY=composition-sharadar",
        "ALPACA_API_KEY=composition-alpaca-key",
        "ALPACA_SECRET_KEY=composition-alpaca-secret",
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL=https://example.invalid/sentinel",
        "SENTINEL_GITHUB_READ_TOKEN=github_pat_composition_fixture",
        "",
    ]), encoding="utf-8")


def _shim(tmp_path: Path):
    path = tmp_path / "python-shim"
    path.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$COMPOSITION_KILL_LOG"
script="${1:-}"
case "$script" in
  scripts/sentinel_host_python.py|scripts/sentinel_go_lock.py|scripts/sentinel_env.py)
    exec "$REAL_PYTHON" "$@"
    ;;
esac
if [ -n "${COMPOSITION_KILL_SCRIPT:-}" ] && [ "$script" = "$COMPOSITION_KILL_SCRIPT" ]; then
  exit "${COMPOSITION_KILL_RC:-137}"
fi
exit 0
""", encoding="utf-8")
    path.chmod(0o755)
    return path


def _clean(env):
    for key in list(env):
        if key.startswith("COMPOSE_") or key.startswith("DOCKER_"):
            env.pop(key, None)
    for key in (
        "SENTINEL_GO_LOCK_HELD", "SENTINEL_GO_LOCK_FD", "SENTINEL_GO_RUN_TOKEN",
        "SENTINEL_GITHUB_READ_TOKEN", "GITHUB_TOKEN", "GH_TOKEN",
    ):
        env.pop(key, None)


def _run(tmp_path: Path, *, kill_script=None, kill_rc=None):
    env_file = ROOT / ".env"
    original = env_file.read_bytes() if env_file.exists() else None
    _write_env(env_file)
    log = tmp_path / "kill-calls.log"
    env = dict(os.environ)
    _clean(env)
    env.update({
        "SENTINEL_HOST_PYTHON": str(_shim(tmp_path)),
        "REAL_PYTHON": sys.executable,
        "COMPOSITION_KILL_LOG": str(log),
    })
    if kill_script:
        env["COMPOSITION_KILL_SCRIPT"] = kill_script
        env["COMPOSITION_KILL_RC"] = str(kill_rc)
    try:
        completed = subprocess.run(
            ["bash", str(LAUNCHER)], cwd=ROOT, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False)
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return completed, calls
    finally:
        if original is None:
            try:
                env_file.unlink()
            except FileNotFoundError:
                pass
        else:
            env_file.write_bytes(original)


def _index(calls, script):
    for index, line in enumerate(calls):
        if line.startswith(script):
            return index
    raise AssertionError((script, calls))


@pytest.mark.parametrize("signal_rc", [137, 143])
@pytest.mark.parametrize(("name", "script"), STAGES)
def test_sigkill_or_sigterm_stops_exactly_at_first_boundary(
        tmp_path, name, script, signal_rc):
    completed, calls = _run(tmp_path, kill_script=script, kill_rc=signal_rc)
    assert completed.returncode == signal_rc, (name, completed.stderr)
    killed_at = _index(calls, script)
    stage_scripts = [value for _label, value in STAGES]
    for later in stage_scripts[stage_scripts.index(script) + 1:]:
        assert not any(line.startswith(later) for line in calls), (
            name, signal_rc, later, calls)
    assert killed_at >= 0


@pytest.mark.parametrize(("name", "script"), STAGES)
def test_retry_after_killed_boundary_starts_a_fresh_complete_lifecycle(tmp_path, name, script):
    killed, _calls = _run(tmp_path, kill_script=script, kill_rc=137)
    assert killed.returncode == 137, name

    retried, calls = _run(tmp_path)
    assert retried.returncode == 0, (name, retried.stderr)
    for _label, expected in STAGES:
        _index(calls, expected)
    assert "GO lifecycle completed successfully" in retried.stdout
