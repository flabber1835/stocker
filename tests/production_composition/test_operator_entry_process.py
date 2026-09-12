from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "sentinel-go-validate.sh"

REAL_STAGES = {
    "bootstrap": "scripts/sentinel_deployment_bootstrap.py",
    "host_preflight": "scripts/sentinel_go_host_preflight.py",
    "runtime_preflight": "scripts/sentinel_runtime_selection.py",
    "account_preflight": "scripts/sentinel_go_account_preflight.py",
    "validation": "scripts/sentinel_go_output_guard.py",
    "promotion": "scripts/sentinel_go_promote.py",
    "post_validation": "scripts/sentinel_go_post_validate.py",
}


def _write_env(path: Path, *, include_github=True):
    rows = [
        "SENTINEL_BACKUP_DIR=/tmp/sentinel-composition-backup",
        "SENTINEL_POSTGRES_PASSWORD=compositionpassword",
        "SHARADAR_API_KEY=composition-sharadar",
        "ALPACA_API_KEY=composition-alpaca-key",
        "ALPACA_SECRET_KEY=composition-alpaca-secret",
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL=https://example.invalid/sentinel",
    ]
    if include_github:
        rows.append("SENTINEL_GITHUB_READ_TOKEN=github_pat_composition_fixture")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _shim(tmp_path: Path) -> Path:
    path = tmp_path / "python-shim"
    path.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$COMPOSITION_LOG"
script="${1:-}"
case "$script" in
  -|scripts/sentinel_host_python.py|scripts/sentinel_go_lock.py|scripts/sentinel_env.py)
    exec "$REAL_PYTHON" "$@"
    ;;
esac
if [ -n "${COMPOSITION_FAIL_SCRIPT:-}" ] && [ "$script" = "$COMPOSITION_FAIL_SCRIPT" ]; then
  exit "${COMPOSITION_FAIL_RC:-41}"
fi
exit 0
""", encoding="utf-8")
    path.chmod(0o755)
    return path


def _clean_controls(env):
    for key in ("SENTINEL_GITHUB_READ_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        env.pop(key, None)
    for key in list(env):
        if key.startswith("COMPOSE_") or key.startswith("DOCKER_"):
            env.pop(key, None)


def _run(tmp_path: Path, *, fail_stage=None, include_github=True, args=(),
         process_env=None):
    env_file = ROOT / ".env"
    original = env_file.read_bytes() if env_file.exists() else None
    _write_env(env_file, include_github=include_github)
    log = tmp_path / "calls.log"
    shim = _shim(tmp_path)
    env = dict(os.environ)
    _clean_controls(env)
    env.update({
        "SENTINEL_HOST_PYTHON": str(shim),
        "REAL_PYTHON": sys.executable,
        "COMPOSITION_LOG": str(log),
    })
    env.update(process_env or {})
    if fail_stage:
        env["COMPOSITION_FAIL_SCRIPT"] = REAL_STAGES[fail_stage]
        env["COMPOSITION_FAIL_RC"] = "41"
    try:
        completed = subprocess.run(
            ["bash", str(LAUNCHER), *args],
            cwd=ROOT, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
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
    raise AssertionError(f"{script} not called; calls={calls!r}")


def test_real_operator_shell_crosses_lock_env_validation_promotion_and_handoff(tmp_path):
    completed, calls = _run(tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert any(line.startswith("scripts/sentinel_go_lock.py") for line in calls)
    assert any(line.startswith("scripts/sentinel_env.py") for line in calls)
    order = [
        _index(calls, REAL_STAGES[name])
        for name in (
            "bootstrap", "host_preflight", "runtime_preflight",
            "account_preflight", "validation", "promotion", "post_validation",
        )
    ]
    assert order == sorted(order)
    assert "GO lifecycle completed successfully" in completed.stdout


@pytest.mark.parametrize("fail_stage", [
    "bootstrap",
    "host_preflight",
    "runtime_preflight",
    "account_preflight",
    "validation",
    "promotion",
    "post_validation",
])
def test_real_operator_shell_stops_at_first_causal_failure(tmp_path, fail_stage):
    completed, calls = _run(tmp_path, fail_stage=fail_stage)
    assert completed.returncode == 41
    _index(calls, REAL_STAGES[fail_stage])
    stage_order = list(REAL_STAGES)
    for later in stage_order[stage_order.index(fail_stage) + 1:]:
        assert not any(line.startswith(REAL_STAGES[later]) for line in calls), (
            fail_stage, later, calls)


def test_real_operator_shell_fails_before_bootstrap_without_github_credential(tmp_path):
    completed, calls = _run(tmp_path, include_github=False)
    assert completed.returncode == 2
    assert "requires SENTINEL_GITHUB_READ_TOKEN or GITHUB_TOKEN" in completed.stderr
    assert not any(line.startswith(REAL_STAGES["bootstrap"]) for line in calls)
    assert not any(line.startswith(REAL_STAGES["validation"]) for line in calls)


def test_github_token_process_fallback_allows_normal_ci_certified_path(tmp_path):
    completed, calls = _run(
        tmp_path, include_github=False,
        process_env={"GITHUB_TOKEN": "actions-token-composition-fixture"})
    assert completed.returncode == 0, completed.stderr
    assert any(line.startswith(REAL_STAGES["validation"]) for line in calls)


def test_gh_token_alone_is_not_mistaken_for_certification_credential(tmp_path):
    completed, calls = _run(
        tmp_path, include_github=False,
        process_env={"GH_TOKEN": "cli-token-not-verifier-authority"})
    assert completed.returncode == 2
    assert "requires SENTINEL_GITHUB_READ_TOKEN or GITHUB_TOKEN" in completed.stderr
    assert not any(line.startswith(REAL_STAGES["bootstrap"]) for line in calls)


@pytest.mark.parametrize(("name", "value", "fragment"), [
    ("DOCKER_HOST", "tcp://127.0.0.1:2375", "ambient Docker selector"),
    ("DOCKER_CONTEXT", "remote-context", "Docker context must be the local default context"),
    ("COMPOSE_FILE", "/tmp/foreign-compose.yml", "ambient Compose control"),
    ("COMPOSE_PROJECT_NAME", "foreign-project", "ambient Compose control"),
])
def test_ambient_docker_or_compose_authority_is_refused_before_bootstrap(
        tmp_path, name, value, fragment):
    completed, calls = _run(
        tmp_path, process_env={name: value})
    assert completed.returncode == 2
    assert fragment in completed.stderr
    assert not any(line.startswith(REAL_STAGES["bootstrap"]) for line in calls)


def test_local_full_path_does_not_require_github_credential(tmp_path):
    completed, calls = _run(
        tmp_path, include_github=False, args=("--local-full-certification",))
    assert completed.returncode == 0, completed.stderr
    assert any(line.startswith("scripts/sentinel_go_output_guard.py") for line in calls)
