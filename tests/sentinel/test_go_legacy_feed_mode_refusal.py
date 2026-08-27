from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])


def test_legacy_go_validation_mode_refuses_before_feed_surface_import():
    env = dict(os.environ)
    env["SENTINEL_FEED_SERVICE_MODE"] = "GO_VALIDATION"
    completed = subprocess.run(
        [sys.executable, "-c", "import sentinel.feed; print('UNREACHABLE')"],
        cwd=str(ROOT), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    assert completed.returncode != 0
    assert "UNREACHABLE" not in completed.stdout
    assert "legacy GO_VALIDATION feed mode is disabled" in completed.stderr


def test_supported_verified_preparation_removes_legacy_service_mode():
    text = (ROOT / "scripts" / "sentinel_go_validate_entry.py").read_text(
        encoding="utf-8")
    assert 'run_env.pop("SENTINEL_FEED_SERVICE_MODE", None)' in text
    assert '"SENTINEL_FEED_AUTHORIZED": "CLEAN_HEAD_IMAGE_V1"' in text


def test_legacy_core_producer_is_the_retired_mode_source():
    text = (ROOT / "scripts" / "sentinel_go_validate.py").read_text(
        encoding="utf-8")
    assert '"SENTINEL_FEED_SERVICE_MODE": "GO_VALIDATION"' in text
    assert "schema.ensure_schema(c)" in text
    assert "ingest.daily(c, today=target)" in text
