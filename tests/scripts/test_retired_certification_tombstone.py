from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel-certify.sh"


def test_retired_certification_entrypoint_remains_fail_closed():
    body = SCRIPT.read_text(encoding="utf-8")
    active = [line for line in body.splitlines()
              if not line.lstrip().startswith("#")]

    assert "REFUSED: the standalone historical certification system is not installed." in body
    assert "exit 2" in active
    assert not any("docker compose" in line for line in active)
    assert not any("sentinel-compose.sh" in line for line in active)
