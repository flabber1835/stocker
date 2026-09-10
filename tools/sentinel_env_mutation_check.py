#!/usr/bin/env python3
"""Prove env regressions fail when selected production guards are removed."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "tests.host_python38.test_env_ingestion.EnvHarness."
REVIEW_FIXES = "tests.host_python38.test_env_review_fixes"
MUTANTS = (
    ("duplicate-last-wins", "scripts/sentinel_env.py",
     "if name in values:", "if False and name in values:",
     "test_refuse_canonical_duplicate_conflict"),
    ("nonprinting-accepted", "scripts/sentinel_env.py",
     "return (unicodedata.category(char)", "return False and (unicodedata.category(char)",
     "test_refuse_canonical_nul"),
    ("missing-required-accepted", "scripts/sentinel_env.py",
     "if invalid:", "if False and invalid:",
     "test_required_SHARADAR_API_KEY_0"),
    ("unstable-file-accepted", "scripts/sentinel_env.py",
     "if (_identity(os.fstat(fd))", "if False and (_identity(os.fstat(fd))",
     "test_atomic_replacement_during_read_is_refused"),
    ("installer-preflight-removed", "scripts/sentinel-autonomous-deploy.sh",
     "sentinel_load_environment --profile install", ": # removed preflight",
     "test_launcher_sentinel_autonomous_deploy_sh_missing_required"),
    ("file-command-keys-unrestricted", "scripts/sentinel_env.py",
     "for key in values:", "for key in ():",
     "test_control_sentinel_compose_sh_RUN"),
    ("comment-whitespace-lost", "scripts/sentinel_env.py",
     'raw, maxsplit=1)[0].strip(" \\t")', 'raw.strip(" \\t"), maxsplit=1)[0].strip(" \\t")',
     "test_empty_commented_credentials_block_install_before_git"),
    ("go-arguments-reinterpret-preflight", "scripts/sentinel-go-validate.sh",
     "--profile go --go-args", "--profile go",
     "test_go_arguments_cannot_weaken_preflight_or_select_another_file"),
    *tuple(
        (name + "-ingestion-removed", "scripts/" + name + ".sh",
         "sentinel_load_environment --profile maintenance", ": # removed preflight",
         "test_maintenance_" + name.replace("-", "_") + "_sh_valid")
        for name in ("sentinel-base-backup", "sentinel-backup-status", "sentinel-restore-drill",
                     "sentinel-automation-compose", "sentinel-authorized-cli")
    ),
    *tuple(
        ("automation-" + suffix.lower() + "-guard-removed", "scripts/sentinel_env.py",
         'if (automation["SENTINEL_AUTOMATION_' + suffix + '"]',
         'if False and (automation["SENTINEL_AUTOMATION_' + suffix + '"]',
         REVIEW_FIXES + ".EnvReviewFixes."
         "test_single_automation_override_refuses_conflict_with_service_default")
        for suffix in ("HEARTBEAT_SECONDS", "RETRY_BASE_SECONDS", "CALLBACK_DEADLINE_SECONDS")
    ),
    ("automation-lease-model-default", "scripts/sentinel_env.py",
     '"SENTINEL_AUTOMATION_LEASE_SECONDS": (12, 3)',
     '"SENTINEL_AUTOMATION_LEASE_SECONDS": (45, 3)',
     REVIEW_FIXES + ".EnvReviewFixes."
     "test_single_automation_override_refuses_conflict_with_service_default"),
    ("alert-dispatcher-callback-guard-removed", "scripts/sentinel_env.py",
     "if (alert_dispatcher", "if False and (alert_dispatcher",
     REVIEW_FIXES + ".EnvReviewFixes."
     "test_broker_deployment_callback_respects_alert_dispatcher_heartbeat"),
    *tuple(
        ("automation-" + suffix.lower() + "-model-default", "scripts/sentinel_env.py",
         '"SENTINEL_AUTOMATION_' + suffix + '": (' + str(default) + ', 1)',
         '"SENTINEL_AUTOMATION_' + suffix + '": (' + str(model_default) + ', 1)',
         REVIEW_FIXES + ".EnvReviewFixes."
         "test_service_defaults_and_valid_partial_automation_overrides")
        for suffix, default, model_default in (
            ("HEARTBEAT_SECONDS", 3, 10), ("RETRY_BASE_SECONDS", 5, 30))
    ),
)


def _test_id(test: str) -> str:
    return test if test.startswith("tests.") else HARNESS + test


def main() -> int:
    review = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", REVIEW_FIXES],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=60)
    if review.returncode != 0:
        sys.stderr.write(review.stdout)
        print("REFUSED: PR346 review-fix regressions are not green", file=sys.stderr)
        return 2

    baseline = subprocess.run(
        [sys.executable, "-m", "unittest"] + [_test_id(item[4]) for item in MUTANTS],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if baseline.returncode != 0:
        print("REFUSED: env mutant baseline is not green", file=sys.stderr)
        return 2
    for name, relative, old, new, test in MUTANTS:
        with tempfile.TemporaryDirectory(prefix="sentinel-env-mutant-") as temporary:
            mutant = Path(temporary)
            shutil.copytree(ROOT / "scripts", mutant / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            path = mutant / relative
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                print("REFUSED: mutant anchor drift: " + name, file=sys.stderr)
                return 2
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            process = dict(os.environ, SENTINEL_REPO_ROOT=str(mutant))
            result = subprocess.run(
                [sys.executable, "-m", "unittest", _test_id(test)], cwd=str(ROOT),
                env=process, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=30)
            method = test.rsplit(".", 1)[-1]
            if result.returncode != 1 or "FAIL: " + method not in result.stdout or "ERROR:" in result.stdout:
                print("REFUSED: mutant survived or harness errored: " + name, file=sys.stderr)
                return 1
            print("KILLED: " + name)
    print("environment mutation checks: PASS (%d/%d)" % (len(MUTANTS), len(MUTANTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
