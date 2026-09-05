from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
MODULE = ROOT / "scripts" / "sentinel_bringup.py"
LAUNCHER = ROOT / "scripts" / "sentinel-bringup.sh"

spec = importlib.util.spec_from_file_location(
    "sentinel_bringup_test_module", MODULE)
bringup = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bringup
spec.loader.exec_module(bringup)


def test_base_source_final_deferred_is_non_authoritative_without_overlay():
    decision = bringup.source_decision({
        "status": "DEFERRED",
        "reason_code": "SHARADAR_SOURCE_NOT_FINAL",
    })
    assert decision.proceed is False
    assert decision.reason_code == "SHARADAR_SOURCE_NOT_FINAL"


def test_recovery_required_may_reach_bounded_data_recovery():
    decision = bringup.source_decision({
        "status": "RECOVERY_REQUIRED",
        "reason_code": "SOURCE_IDENTITY_HISTORY_MUTATION",
    })
    assert decision.proceed is True


def test_clean_readonly_pass_may_reach_bounded_data_recovery():
    decision = bringup.source_decision({
        "status": "PASS",
        "reason_code": "SEP_CDC_SOURCE_VALID",
    })
    assert decision.proceed is True


def test_refused_source_never_reaches_data_recovery():
    decision = bringup.source_decision({
        "status": "REFUSED",
        "reason_code": "SOURCE_PUBLICATION_UNSTABLE",
    })
    assert decision.proceed is False


def test_unknown_source_state_fails_closed():
    with pytest.raises(bringup.BringupRefused):
        bringup.source_decision({"status": "MAYBE", "reason_code": "UNKNOWN"})


def test_post_recovery_only_raw_pass_is_ready():
    decision = bringup.post_recovery_source_decision({
        "status": "PASS",
        "reason_code": "SEP_CDC_SOURCE_VALID",
    })
    assert decision.proceed is True
    assert decision.status == "PASS"


def test_post_recovery_deferred_is_never_normalized_to_ready():
    decision = bringup.post_recovery_source_decision({
        "status": "DEFERRED",
        "reason_code": "SHARADAR_SOURCE_NOT_FINAL",
    })
    assert decision.proceed is False
    assert decision.status == "DEFERRED"


def test_post_recovery_recovery_required_is_not_ready():
    decision = bringup.post_recovery_source_decision({
        "status": "RECOVERY_REQUIRED",
        "reason_code": "SOURCE_IDENTITY_HISTORY_MUTATION",
    })
    assert decision.proceed is False
    assert decision.status == "RECOVERY_REQUIRED"


def test_post_recovery_unknown_state_fails_closed():
    with pytest.raises(bringup.BringupRefused):
        bringup.post_recovery_source_decision(
            {"status": "MAYBE", "reason_code": "UNKNOWN"})


def _backup_status(code: str, *, returncode: int = 4):
    return subprocess.CompletedProcess(
        ["bash", "scripts/sentinel-backup-status.sh"],
        returncode,
        stdout="",
        stderr=(
            "SENTINEL_BACKUP_STATUS_REASON=%s\n"
            "REFUSED: fixture backup status\n" % code),
    )


@pytest.mark.parametrize("code", sorted(bringup.backup_refresh._REPAIRABLE_CODES))
def test_every_certified_repairable_backup_state_is_a_bringup_handoff(code):
    decision = bringup.backup_decision(_backup_status(code))
    assert decision.healthy is False
    assert decision.repairable is True
    assert decision.reason_code == code


def test_structural_backup_failure_remains_a_bringup_refusal():
    decision = bringup.backup_decision(_backup_status("ARCHIVE_MODE_DISABLED"))
    assert decision.healthy is False
    assert decision.repairable is False
    assert decision.reason_code == "ARCHIVE_MODE_DISABLED"


def test_unclassified_backup_failure_fails_closed():
    with pytest.raises(bringup.BringupRefused, match="unclassified failure"):
        bringup.backup_decision(subprocess.CompletedProcess(
            ["bash", "scripts/sentinel-backup-status.sh"],
            4, stdout="", stderr="unexpected failure\n"))


def test_launcher_uses_go_lifecycle_lock_but_never_runs_certification_or_promotion():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "scripts/sentinel_go_lock.py" in source
    assert "scripts/sentinel_bringup_install_anytime.py" in source
    assert "sentinel-go-validate.sh" not in "\n".join(
        line for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#"))
    assert "sentinel_go_verified_entry.py" not in source
    assert "sentinel_go_promote.py" not in source
    assert "sentinel_go_post_validate.py" not in source


def test_bringup_module_has_no_deployment_authority_surface():
    source = MODULE.read_text(encoding="utf-8")
    forbidden = (
        "emit_bundle(",
        "sentinel_go_promote",
        "sentinel_go_post_validate",
        "_write_run_pass",
        "SHADOW_GO",
        "DUAL_RUN_GO",
        "PAPER_EXECUTION_GO",
        "ensure_recent_verified_base_backup(",
        "sentinel-base-backup.sh",
    )
    for token in forbidden:
        assert token not in source


def test_recovery_is_explicit_and_reuses_reviewed_24x7_feed_bound_path():
    source = MODULE.read_text(encoding="utf-8")
    assert 'parser.add_argument(\n        "--recover"' in source
    assert "source_final._deployment_preparation_probe" in source
    assert "entry.FeedBoundPreparationRunner" in source
    assert "go._without_broker_authority" in source
    assert "go_lock.lifecycle_lock_is_held" in source


def test_repairable_backup_handoff_reuses_certified_go_classifier():
    source = MODULE.read_text(encoding="utf-8")
    assert "backup_refresh._repairable_reason" in source
    assert 'READY_CERTIFIED_BACKUP_REFRESH = "BRINGUP_READY_FOR_CERTIFIED_BACKUP_REFRESH"' in source
    assert "Fast bring-up will not mutate backup durability before exact" in source


def test_ready_message_still_requires_official_go():
    source = MODULE.read_text(encoding="utf-8")
    assert 'READY = "BRINGUP_READY_FOR_CERTIFICATION"' in source
    assert "Final certification is still required" in source
    assert "bash scripts/sentinel-go-validate.sh" in source
