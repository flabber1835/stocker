from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
LAUNCHER = ROOT / "scripts" / "sentinel-bringup.sh"


_SHIM = r'''#!/usr/bin/env python3
from pathlib import Path
from types import SimpleNamespace
import os
import sys

root = Path(os.environ["SENTINEL_REPO_ROOT"])
target = Path(sys.argv[1]).name if len(sys.argv) > 1 else ""
scenario = os.environ.get("BRINGUP_SCENARIO", "pass")

if target in {
    "sentinel_host_python.py",
    "sentinel_deployment_bootstrap.py",
    "sentinel_go_host_preflight.py",
    "sentinel_runtime_selection.py",
    "sentinel_go_account_preflight.py",
}:
    if scenario == "host_refused" and target == "sentinel_go_host_preflight.py":
        print("fixture host preflight: REFUSED", file=sys.stderr)
        raise SystemExit(2)
    if scenario == "account_refused" and target == "sentinel_go_account_preflight.py":
        print("fixture paper account preflight: REFUSED", file=sys.stderr)
        raise SystemExit(2)
    print("fixture preflight: PASS")
    raise SystemExit(0)

if target != "sentinel_bringup_install_anytime.py":
    raise SystemExit("unexpected bring-up Python target: " + target)

sys.path.insert(0, str(root / "scripts"))
import sentinel_bringup_install_anytime as overlay

base = overlay.base
fake_env = dict(os.environ)
fake_env.update({
    "SHARADAR_API_KEY": "fixture-sharadar",
    "SENTINEL_POSTGRES_PASSWORD": "fixture-postgres",
    "SENTINEL_BACKUP_DIR": "/tmp/sentinel-fixture-backup",
    "SENTINEL_GO_LOCK_HELD": "1",
})
base.go.merged_environment = lambda: dict(fake_env)
base.go_lock.lifecycle_lock_is_held = lambda _env: True
base.go_lock.current_run_token = lambda _env: "fixture-run-token"
base._require_exact_main = lambda _runner: SimpleNamespace(commit="a" * 40)
base._compose_and_database_ready = (
    lambda _runner, env: (dict(env), ["-f", "docker-compose.sentinel.yml"]))
base._backup_checkpoint = (
    (lambda _env: "WAL_ARCHIVE_UNRESOLVED_FAILURE")
    if scenario == "backup_repairable" else (lambda _env: None))
base._runtime_for_commit = (
    lambda _runner, **_kwargs: "sha256:" + "1" * 64)

if scenario == "source_refused":
    report = {
        "status": "REFUSED",
        "reason_code": "SHARADAR_LIVENESS_UNAVAILABLE",
        "detail": "fixture source refusal",
    }
elif scenario == "local_recovery":
    report = {
        "status": "RECOVERY_REQUIRED",
        "reason_code": "LOCAL_DATA_PREPARATION_REQUIRED",
        "local_followup": ["SEP_CURSOR_MISSING"],
        "source_rows": 10,
    }
elif scenario == "source_final":
    report = {
        "status": "PASS",
        "reason_code": "SHARADAR_LIVENESS_OK",
        "source_rows": 10,
    }
else:
    report = {
        "status": "DEFERRED",
        "reason_code": "SHARADAR_SOURCE_NOT_FINAL",
        "source_rows": 10,
    }
base._source_liveness_report = lambda *_args, **_kwargs: dict(report)
overlay.install()
sys.argv = [str(root / "scripts" / target)] + sys.argv[2:]
raise SystemExit(overlay.main())
'''


def _run(tmp_path: Path, scenario: str, *args: str):
    shim = tmp_path / "bringup-python-shim"
    shim.write_text(_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    env = dict(os.environ)
    env.update({
        "SENTINEL_REPO_ROOT": str(ROOT),
        "SENTINEL_HOST_PYTHON": str(shim),
        "SENTINEL_GO_LOCK_HELD": "1",
        "BRINGUP_SCENARIO": scenario,
    })
    return subprocess.run(
        ["bash", str(LAUNCHER), *args],
        cwd=str(ROOT), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def test_real_shell_entrypoint_is_diagnostic_only_and_hands_recovery_to_go(tmp_path):
    completed = _run(tmp_path, "pass", "--recover")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "=== BRINGUP: CHEAP HOST AUTHORITY ===" in completed.stdout
    assert "=== BRINGUP: PAPER ACCOUNT - GET ONLY ===" in completed.stdout
    assert "=== BRINGUP: LOCAL + SOURCE LIVENESS ===" in completed.stdout
    assert "bring-up liveness: DEFERRED - SHARADAR_SOURCE_NOT_FINAL" in completed.stdout
    assert "bring-up --recover: compatibility mode only" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" in completed.stdout
    assert "Certified GO owns bounded recovery" in completed.stdout
    assert "bring-up recovery:" not in completed.stdout


def test_real_shell_entrypoint_hands_repairable_backup_to_certified_go(tmp_path):
    completed = _run(tmp_path, "backup_repairable", "--recover")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "bring-up liveness: DEFERRED - SHARADAR_SOURCE_NOT_FINAL" in completed.stdout
    assert (
        "BRINGUP_READY_FOR_CERTIFIED_BACKUP_REFRESH - "
        "WAL_ARCHIVE_UNRESOLVED_FAILURE" in completed.stdout)
    assert "Certified GO owns the backup refresh" in completed.stdout
    assert "bring-up recovery:" not in completed.stdout
    assert "BRINGUP_BLOCKED" not in completed.stdout + completed.stderr


def test_real_shell_entrypoint_blocks_true_source_liveness_refusal(tmp_path):
    completed = _run(tmp_path, "source_refused", "--recover")
    assert completed.returncode == 3
    assert "bring-up liveness: REFUSED - SHARADAR_LIVENESS_UNAVAILABLE" in completed.stdout
    assert "BRINGUP_BLOCKED - SHARADAR_LIVENESS_UNAVAILABLE" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" not in completed.stdout


def test_real_shell_entrypoint_stops_on_host_preflight_refusal(tmp_path):
    completed = _run(tmp_path, "host_refused", "--recover")
    assert completed.returncode == 2
    assert "=== BRINGUP: CHEAP HOST AUTHORITY ===" in completed.stdout
    assert "fixture host preflight: REFUSED" in completed.stderr
    assert "=== BRINGUP: PAPER ACCOUNT - GET ONLY ===" not in completed.stdout
    assert "=== BRINGUP: LOCAL + SOURCE LIVENESS ===" not in completed.stdout


def test_real_shell_entrypoint_stops_on_paper_account_preflight_refusal(tmp_path):
    completed = _run(tmp_path, "account_refused", "--recover")
    assert completed.returncode == 2
    assert "=== BRINGUP: PAPER ACCOUNT - GET ONLY ===" in completed.stdout
    assert "fixture paper account preflight: REFUSED" in completed.stderr
    assert "=== BRINGUP: LOCAL + SOURCE LIVENESS ===" not in completed.stdout


def test_real_shell_entrypoint_without_recover_is_ready_for_go_without_mutation(tmp_path):
    completed = _run(tmp_path, "source_final")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "bring-up liveness: PASS - SHARADAR_LIVENESS_OK" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" in completed.stdout
    assert "compatibility mode only" not in completed.stdout
    assert "bring-up recovery:" not in completed.stdout


def test_local_data_lag_is_reported_but_recovery_is_left_to_go(tmp_path):
    completed = _run(tmp_path, "local_recovery", "--recover")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "bring-up liveness: RECOVERY_REQUIRED - LOCAL_DATA_PREPARATION_REQUIRED" in completed.stdout
    assert "local_followup=SEP_CURSOR_MISSING" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" in completed.stdout
    assert "bring-up recovery:" not in completed.stdout
