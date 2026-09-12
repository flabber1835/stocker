from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def _env_file(tmp_path: Path, token: str = "file-token-value") -> Path:
    path = tmp_path / "sentinel.env"
    path.write_text(
        "\n".join([
            "SENTINEL_BACKUP_DIR=/tmp/sentinel-composition-backup",
            "SENTINEL_POSTGRES_PASSWORD=compositionpassword",
            "SHARADAR_API_KEY=composition-sharadar",
            f"SENTINEL_GITHUB_READ_TOKEN={token}",
            "",
        ]),
        encoding="utf-8",
    )
    return path


def _load(path: Path, *, process=None):
    env = dict(os.environ)
    env.pop("SENTINEL_GITHUB_READ_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    env.pop("DOCKER_HOST", None)
    env.pop("DOCKER_CONFIG", None)
    env.pop("DOCKER_CERT_PATH", None)
    env.pop("DOCKER_TLS_VERIFY", None)
    env.pop("DOCKER_TLS", None)
    env.pop("DOCKER_API_VERSION", None)
    env.pop("DOCKER_DEFAULT_PLATFORM", None)
    env.pop("BUILDKIT_HOST", None)
    env.pop("BUILDX_BUILDER", None)
    for key in list(env):
        if key.startswith("COMPOSE_"):
            env.pop(key, None)
    env.update(process or {})
    code = r'''
PYTHON="$1"
ENVFILE="$2"
. scripts/sentinel-env.sh
sentinel_load_environment --profile go --target SHADOW --env-file "$ENVFILE"
"$PYTHON" - <<'PY'
import json, os
keys = (
    "SENTINEL_GITHUB_READ_TOKEN",
    "SENTINEL_GO_LOCK_HELD",
    "SENTINEL_GO_LOCK_FD",
    "SENTINEL_GO_RUN_TOKEN",
    "COMPOSE_DISABLE_ENV_FILE",
    "COMPOSE_ENV_FILES",
    "DOCKER_CONTEXT",
)
print(json.dumps({key: os.environ.get(key) for key in keys}, sort_keys=True))
PY
'''
    completed = subprocess.run(
        ["bash", "-c", code, "composition-env", sys.executable, str(path)],
        cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False,
    )
    return completed


def test_real_bash_loader_exports_full_github_read_token(tmp_path):
    completed = _load(_env_file(tmp_path, token="github_pat_test_full_value_123456789"))
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["SENTINEL_GITHUB_READ_TOKEN"] == \
        "github_pat_test_full_value_123456789"
    assert payload["COMPOSE_DISABLE_ENV_FILE"] == "1"
    assert payload["COMPOSE_ENV_FILES"] == "/dev/null"
    assert payload["DOCKER_CONTEXT"] == "default"


def test_process_environment_overrides_env_file_without_losing_key_export(tmp_path):
    completed = _load(
        _env_file(tmp_path, token="file-token"),
        process={"SENTINEL_GITHUB_READ_TOKEN": "process-token"},
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["SENTINEL_GITHUB_READ_TOKEN"] == "process-token"


def test_lock_authority_environment_survives_env_loader(tmp_path):
    process = {
        "SENTINEL_GO_LOCK_HELD": "1",
        "SENTINEL_GO_LOCK_FD": "123",
        "SENTINEL_GO_RUN_TOKEN": "a" * 64,
    }
    completed = _load(_env_file(tmp_path), process=process)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["SENTINEL_GO_LOCK_HELD"] == "1"
    assert payload["SENTINEL_GO_LOCK_FD"] == "123"
    assert payload["SENTINEL_GO_RUN_TOKEN"] == "a" * 64


def test_loader_never_echoes_secret_values_on_success(tmp_path):
    secret = "github_pat_never_print_this_123456789"
    completed = _load(_env_file(tmp_path, token=secret))
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    loader_lines = lines[:-1]
    assert secret not in "\n".join(loader_lines)
    assert secret not in completed.stderr


def test_normal_go_launcher_requires_github_read_credential_before_certification():
    text = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert "SENTINEL_GITHUB_READ_TOKEN" in text
    assert "GITHUB_TOKEN" in text
    credential_gate = text.index("SENTINEL_GITHUB_READ_TOKEN")
    certification = text.index('go_phase "CERTIFICATION + FINANCIAL READINESS"')
    assert credential_gate < certification
