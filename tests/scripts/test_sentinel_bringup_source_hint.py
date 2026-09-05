from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
MODULE = ROOT / "scripts" / "sentinel_bringup_source_hint.py"
LAUNCHER = ROOT / "scripts" / "sentinel-bringup.sh"

spec = importlib.util.spec_from_file_location(
    "sentinel_bringup_source_hint_test_module", MODULE)
hint = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = hint
spec.loader.exec_module(hint)


def _completed(status, reason):
    payload = json.dumps({"status": status, "reason_code": reason})
    return subprocess.CompletedProcess(
        args=["docker"], returncode=0,
        stdout=hint.MARKER + payload + "\n", stderr="")


def test_deferred_retained_runtime_stops_before_exact_build(monkeypatch):
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(hint.selection, "_pointer_digest", lambda: digest)
    monkeypatch.setattr(
        hint.selection, "_inspect", lambda _ref: (digest, "b" * 40))
    monkeypatch.setattr(
        hint.subprocess, "run",
        lambda *args, **kwargs: _completed(
            "DEFERRED", "SHARADAR_SOURCE_NOT_FINAL"))

    assert hint.main() == 3


def test_ready_retained_runtime_only_allows_exact_checks(monkeypatch):
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(hint.selection, "_pointer_digest", lambda: digest)
    monkeypatch.setattr(
        hint.selection, "_inspect", lambda _ref: (digest, "b" * 40))
    monkeypatch.setattr(
        hint.subprocess, "run",
        lambda *args, **kwargs: _completed(
            "READY", "SOURCE_FINAL_HINT_READY"))

    assert hint.main() == 0


def test_missing_or_broken_retained_runtime_never_replaces_exact_checks(monkeypatch):
    monkeypatch.setattr(hint.selection, "_pointer_digest", lambda: None)
    assert hint.main() == 0

    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(hint.selection, "_pointer_digest", lambda: digest)
    monkeypatch.setattr(
        hint.selection, "_inspect",
        lambda _ref: (_ for _ in ()).throw(RuntimeError("broken")))
    assert hint.main() == 0


def test_hint_is_networkless_and_runs_before_exact_bringup_controller():
    helper = MODULE.read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")

    assert '"docker", "run", "--rm", "--network", "none"' in helper
    assert "SHARADAR_API_KEY" not in helper
    assert "SENTINEL_POSTGRES_PASSWORD" not in helper
    assert "sentinel_go_promote" not in helper
    assert "sentinel-go-validate.sh" not in helper

    hint_pos = launcher.index("scripts/sentinel_bringup_source_hint.py")
    exact_pos = launcher.index("scripts/sentinel_bringup.py")
    assert hint_pos < exact_pos
