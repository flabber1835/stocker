from __future__ import annotations

import inspect
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


def test_core_producer_rejects_historical_daily(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import sentinel_go_preparation_runtime as child
    import sentinel_go_validate as host

    assert '"SENTINEL_FEED_SERVICE_MODE": "GO_VALIDATION"' in inspect.getsource(host.probe_prevalidation_preparation)
    assert host._PREPARATION_CODE is child.CODE
    assert "schema.ensure_schema(c)" in child.CODE
    assert "retained_go.prepare(c, target_session=target," in child.CODE
    assert "absolute_deadline=rolling_go_inputs.deadline_from_host(" in child.CODE
    assert "ingest.daily" not in child.CODE
