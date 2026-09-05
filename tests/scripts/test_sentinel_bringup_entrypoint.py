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

# Keep the shell entrypoint real while replacing only external host/broker
# boundaries. The final Python bring-up controller is executed in-process.
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
if scenario == "backup_repairable":
    base._backup_checkpoint = lambda _env: "WAL_ARCHIVE_UNRESOLVED_FAILURE"
else:
    base._backup_checkpoint = lambda _env: None
base._runtime_for_commit = (
    lambda _runner, **_kwargs: "sha256:" + "1" * 64)

if scenario == "source_refused":
    reports = iter([{
        "status": "REFUSED",
        "reason_code": "SOURCE_PUBLICATION_UNSTABLE",
        "detail": "fixture source refusal",
    }])
elif scenario == "already_current":
    reports = iter([
        {"status": "PASS", "reason_code": "SEP_CDC_SOURCE_VALID"},
        {"status": "PASS", "reason_code": "SEP_CDC_SOURCE_VALID"},
    ])
elif scenario == "post_recovery_deferred":
    reports = iter([
        {"status": "DEFERRED", "reason_code": "SHARADAR_SOURCE_NOT_FINAL"},
        {"status": "DEFERRED", "reason_code": "SHARADAR_SOURCE_NOT_FINAL"},
    ])
elif scenario == "post_recovery_refused":
    reports = iter([
        {"status": "DEFERRED", "reason_code": "SHARADAR_SOURCE_NOT_FINAL"},
        {
            "status": "REFUSED",
            "reason_code": "SOURCE_PUBLICATION_UNSTABLE",
            "detail": "fixture post-recovery refusal",
        },
    ])
else:
    reports = iter([
        {
            "status": "DEFERRED",
            "reason_code": "SHARADAR_SOURCE_NOT_FINAL",
        },
        {
            "status": "PASS",
            "reason_code": "SEP_CDC_SOURCE_VALID",
        },
    ])
base._read_only_report = lambda *_args, **_kwargs: next(reports)

def run_recovery(*_args, **_kwargs):
    if scenario == "recovery_refused":
        raise base.BringupRefused(
            "SOURCE_CDC_INVALID - fixture post-seed request-envelope mismatch")
    if scenario == "recovery_interrupted":
        raise base.BringupRefused(
            "PREPARATION_INTERRUPTED - fixture interrupted recovery")
    return SimpleNamespace(
        status=base.go.PASS, complete=True, elapsed_milliseconds=7)

base._run_recovery = run_recovery
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


def test_real_shell_entrypoint_reaches_recovery_and_certification_ready(tmp_path):
    completed = _run(tmp_path, "pass", "--recover")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "=== BRINGUP: CHEAP HOST AUTHORITY ===" in completed.stdout
    assert "=== BRINGUP: PAPER ACCOUNT - GET ONLY ===" in completed.stdout
    assert "=== BRINGUP: DATA + RECOVERY BRING-UP ===" in completed.stdout
    assert "bring-up source: DEFERRED - SHARADAR_SOURCE_NOT_FINAL" in completed.stdout
    assert "bring-up recovery: bounded production data preparation" in completed.stdout
    assert "bring-up recovery: PASS elapsed_ms=7" in completed.stdout
    assert "post-recovery source: PASS - SEP_CDC_SOURCE_VALID" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" in completed.stdout


def test_real_shell_entrypoint_hands_repairable_backup_to_certified_go(tmp_path):
    completed = _run(tmp_path, "backup_repairable", "--recover")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "bring-up source: DEFERRED - SHARADAR_SOURCE_NOT_FINAL" in completed.stdout
    assert (
        "BRINGUP_READY_FOR_CERTIFIED_BACKUP_REFRESH - "
        "WAL_ARCHIVE_UNRESOLVED_FAILURE" in completed.stdout)
    assert "bash scripts/sentinel-go-validate.sh" in completed.stdout
    assert "bring-up recovery: bounded production data preparation" not in completed.stdout
    assert "BRINGUP_BLOCKED" not in completed.stdout + completed.stderr


def test_real_shell_entrypoint_surfaces_recovery_refusal(tmp_path):
    completed = _run(tmp_path, "recovery_refused", "--recover")
    assert completed.returncode == 2
    assert "bring-up recovery: bounded production data preparation" in completed.stdout
    assert "BRINGUP_BLOCKED - SOURCE_CDC_INVALID" in completed.stderr
    assert "BRINGUP_READY_FOR_CERTIFICATION" not in completed.stdout


def test_real_shell_entrypoint_blocks_true_source_refusal_before_recovery(tmp_path):
    completed = _run(tmp_path, "source_refused", "--recover")
    assert completed.returncode == 3
    assert "bring-up source: REFUSED - SOURCE_PUBLICATION_UNSTABLE" in completed.stdout
    assert "BRINGUP_BLOCKED - SOURCE_PUBLICATION_UNSTABLE" in completed.stdout
    assert "bring-up recovery: bounded production data preparation" not in completed.stdout


def test_real_shell_entrypoint_stops_on_host_preflight_refusal(tmp_path):
    completed = _run(tmp_path, "host_refused", "--recover")
    assert completed.returncode == 2
    assert "=== BRINGUP: CHEAP HOST AUTHORITY ===" in completed.stdout
    assert "fixture host preflight: REFUSED" in completed.stderr
    assert "=== BRINGUP: PAPER ACCOUNT - GET ONLY ===" not in completed.stdout
    assert "=== BRINGUP: DATA + RECOVERY BRING-UP ===" not in completed.stdout


def test_real_shell_entrypoint_stops_on_paper_account_preflight_refusal(tmp_path):
    completed = _run(tmp_path, "account_refused", "--recover")
    assert completed.returncode == 2
    assert "=== BRINGUP: PAPER ACCOUNT - GET ONLY ===" in completed.stdout
    assert "fixture paper account preflight: REFUSED" in completed.stderr
    assert "=== BRINGUP: DATA + RECOVERY BRING-UP ===" not in completed.stdout


def test_real_shell_entrypoint_without_recover_stops_before_mutation(tmp_path):
    completed = _run(tmp_path, "pass")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "BRINGUP_READY_FOR_RECOVERY - SHARADAR_SOURCE_NOT_FINAL" in completed.stdout
    assert "bring-up recovery: bounded production data preparation" not in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" not in completed.stdout


def test_real_shell_entrypoint_handles_already_current_source_state(tmp_path):
    completed = _run(tmp_path, "already_current", "--recover")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "bring-up source: PASS - SEP_CDC_SOURCE_VALID" in completed.stdout
    assert "bring-up recovery: PASS elapsed_ms=7" in completed.stdout
    assert "post-recovery source: PASS - SEP_CDC_SOURCE_VALID" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" in completed.stdout


def test_real_shell_entrypoint_waits_when_source_is_not_final_after_recovery(tmp_path):
    completed = _run(tmp_path, "post_recovery_deferred", "--recover")
    assert completed.returncode == 3
    assert "bring-up recovery: PASS elapsed_ms=7" in completed.stdout
    assert "post-recovery source: DEFERRED - SHARADAR_SOURCE_NOT_FINAL" in completed.stdout
    assert (
        "BRINGUP_DATA_RECOVERY_COMPLETE_WAIT_SOURCE_FINAL - SHARADAR_SOURCE_NOT_FINAL"
        in completed.stdout)
    assert "BRINGUP_READY_FOR_CERTIFICATION" not in completed.stdout


def test_real_shell_entrypoint_blocks_post_recovery_source_refusal(tmp_path):
    completed = _run(tmp_path, "post_recovery_refused", "--recover")
    assert completed.returncode == 3
    assert "bring-up recovery: PASS elapsed_ms=7" in completed.stdout
    assert "post-recovery source: REFUSED - SOURCE_PUBLICATION_UNSTABLE" in completed.stdout
    assert "BRINGUP_BLOCKED - SOURCE_PUBLICATION_UNSTABLE" in completed.stdout
    assert "BRINGUP_READY_FOR_CERTIFICATION" not in completed.stdout


def test_real_shell_entrypoint_surfaces_interrupted_recovery(tmp_path):
    completed = _run(tmp_path, "recovery_interrupted", "--recover")
    assert completed.returncode == 2
    assert "bring-up recovery: bounded production data preparation" in completed.stdout
    assert "BRINGUP_BLOCKED - PREPARATION_INTERRUPTED" in completed.stderr
    assert "BRINGUP_READY_FOR_CERTIFICATION" not in completed.stdout
