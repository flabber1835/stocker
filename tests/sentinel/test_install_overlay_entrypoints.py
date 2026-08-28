from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_autonomous_deploy_install_entry as deploy_overlay  # noqa: E402


def test_deploy_install_overlay_refuses_direct_operator_execution(capsys):
    assert deploy_overlay.main([]) == 2
    captured = capsys.readouterr()
    assert "internal" in captured.err
    assert "scripts/sentinel-autonomous-deploy.sh" in captured.err
