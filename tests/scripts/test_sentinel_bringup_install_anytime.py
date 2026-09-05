from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
MODULE = ROOT / "scripts" / "sentinel_bringup_install_anytime.py"
LAUNCHER = ROOT / "scripts" / "sentinel-bringup.sh"

spec = importlib.util.spec_from_file_location(
    "sentinel_bringup_install_anytime_test_module", MODULE)
overlay = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = overlay
spec.loader.exec_module(overlay)


def test_source_not_final_never_blocks_bringup_installation():
    decision = overlay.source_decision({
        "status": "DEFERRED",
        "reason_code": "SHARADAR_SOURCE_NOT_FINAL",
    })
    assert decision.proceed is True
    assert decision.status == "PASS"
    assert decision.reason_code == "SHARADAR_SOURCE_NOT_FINAL"


def test_real_source_refusal_still_blocks():
    decision = overlay.source_decision({
        "status": "REFUSED",
        "reason_code": "SOURCE_PUBLICATION_UNSTABLE",
    })
    assert decision.proceed is False
    assert decision.status == "REFUSED"


def test_deferred_status_remains_truthful_in_operator_output(capsys):
    overlay._print_source_report({
        "status": "DEFERRED",
        "reason_code": "SHARADAR_SOURCE_NOT_FINAL",
    }, prefix="bring-up source")
    output = capsys.readouterr().out
    assert "bring-up source: DEFERRED - SHARADAR_SOURCE_NOT_FINAL" in output
    assert "bring-up source: PASS" not in output


def test_launcher_uses_wallclock_independent_overlay_and_no_time_stop_hint():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "scripts/sentinel_bringup_install_anytime.py" in source
    assert "sentinel_bringup_source_hint.py" not in source


def test_overlay_cannot_create_deployment_authority():
    source = MODULE.read_text(encoding="utf-8")
    forbidden = (
        "emit_bundle(",
        "sentinel_go_promote",
        "sentinel_go_post_validate",
        "_write_run_pass",
        "SHADOW_GO",
        "DUAL_RUN_GO",
        "PAPER_EXECUTION_GO",
    )
    for token in forbidden:
        assert token not in source


def test_overlay_delegates_only_to_pre_recovery_non_authoritative_bringup():
    source = MODULE.read_text(encoding="utf-8")
    assert "import sentinel_bringup as base" in source
    assert "return base.main()" in source
    assert "base.source_decision = source_decision" in source
    assert "base._print_source_report = _print_source_report" in source
    assert "base.post_recovery_source_decision" not in source
