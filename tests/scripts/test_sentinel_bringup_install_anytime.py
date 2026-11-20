from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
MODULE = ROOT / "scripts" / "sentinel_bringup.py"
LAUNCHER = ROOT / "scripts" / "sentinel-bringup.sh"

def test_launcher_uses_wallclock_independent_diagnostic():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "scripts/sentinel_bringup.py" in source
    assert "sentinel_bringup_source_hint.py" not in source


def test_diagnostic_cannot_create_deployment_authority():
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
