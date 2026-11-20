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
LIVENESS = ROOT / "scripts" / "sentinel_bringup_source_liveness.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_bringup_test_module", MODULE)
bringup = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bringup
spec.loader.exec_module(bringup)


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


def test_launcher_uses_go_lifecycle_lock_but_never_runs_certification_or_recovery():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "scripts/sentinel_go_lock.py" in source
    assert "scripts/sentinel_bringup.py" in source
    assert 'phase "LOCAL DURABILITY + IMAGE"' in source
    assert "sentinel-go-validate.sh" not in "\n".join(
        line for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#"))
    assert "sentinel_go_verified_entry.py" not in source
    assert "sentinel_go_promote.py" not in source
    assert "sentinel_go_post_validate.py" not in source


def test_bringup_module_has_no_financial_mutation_or_deployment_authority_surface():
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
        "_deployment_preparation_probe",
        "FeedBoundPreparationRunner",
        "_run_recovery",
        "post_recovery_source_decision",
    )
    for token in forbidden:
        assert token not in source


def test_recover_flag_is_compatibility_only_and_go_owns_recovery():
    source = MODULE.read_text(encoding="utf-8")
    assert 'parser.add_argument(\n        "--recover"' in source
    assert "compatibility mode only; no financial data" in source
    assert "Certified GO owns bounded recovery" in source
    assert "Alpaca/OpenFIGI acquisition, rolling publication" in source


def test_source_report_does_not_grant_network_or_broker_authority():
    source = MODULE.read_text()
    assert "_source_liveness_report" not in source
    assert "go._with_market_data_authority" not in source


def test_repairable_backup_handoff_reuses_certified_go_classifier():
    source = MODULE.read_text(encoding="utf-8")
    assert "backup_refresh._repairable_reason" in source
    assert 'READY_CERTIFIED_BACKUP_REFRESH = "BRINGUP_READY_FOR_CERTIFIED_BACKUP_REFRESH"' in source
    assert "Certified GO owns the backup refresh" in source


def test_ready_message_requires_official_go():
    source = MODULE.read_text(encoding="utf-8")
    assert 'READY = "BRINGUP_READY_FOR_CERTIFICATION"' in source
    assert "No certification or deployment authority was created" in source
    assert "bash scripts/sentinel-go-validate.sh" in source
