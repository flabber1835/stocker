from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sentinel_runtime_selection.py"
spec = importlib.util.spec_from_file_location("sentinel_runtime_selection", SCRIPT)
selection = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = selection
spec.loader.exec_module(selection)

HEAD = "a" * 40
OLD = "b" * 40
DIGEST = "sha256:" + "c" * 64


def test_preflight_reports_stale_runtime_before_validation(monkeypatch, capsys):
    monkeypatch.setattr(selection, "_git", lambda *args: HEAD)
    monkeypatch.setattr(selection, "_merged_environment", lambda: {"X": "1"})
    monkeypatch.setattr(selection, "_compose_selected_image", lambda env: "sentinel:latest")
    monkeypatch.setattr(selection, "_inspect", lambda reference: (DIGEST, OLD))

    assert selection.preflight() == 0
    output = capsys.readouterr().out
    assert "runtime preflight: STALE" in output
    assert OLD[:12] in output
    assert HEAD[:12] in output


def test_preflight_match_is_explicit(monkeypatch, capsys):
    monkeypatch.setattr(selection, "_git", lambda *args: HEAD)
    monkeypatch.setattr(selection, "_merged_environment", lambda: {})
    monkeypatch.setattr(selection, "_compose_selected_image", lambda env: DIGEST)
    monkeypatch.setattr(selection, "_inspect", lambda reference: (DIGEST, HEAD))

    assert selection.preflight() == 0
    assert "runtime preflight: MATCH" in capsys.readouterr().out


def test_successful_promotion_writes_exact_ordinary_digest(monkeypatch, tmp_path, capsys):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(selection, "POINTER", pointer)
    monkeypatch.setattr(selection, "_clean_main_head", lambda: HEAD)

    inspected = []
    def inspect(reference):
        inspected.append(reference)
        return DIGEST, HEAD
    monkeypatch.setattr(selection, "_inspect", inspect)

    assert selection.promote([]) == 0
    assert inspected == ["sentinel-go-runtime:" + HEAD]
    assert pointer.read_text(encoding="ascii") == (
        "SENTINEL_RUNTIME_IMAGE_REF=" + DIGEST + "\n")
    assert "runtime promotion: BOUND" in capsys.readouterr().out


def test_development_input_never_promotes(monkeypatch, tmp_path, capsys):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(selection, "POINTER", pointer)

    assert selection.promote(["--input", "fixture.json", "--dev-input"]) == 0
    assert not pointer.exists()
    assert "SKIPPED" in capsys.readouterr().out


def test_launcher_orders_preflight_before_validator_and_promotion_after_success():
    text = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    preflight = text.index("sentinel_runtime_selection.py preflight")
    validator = text.index("sentinel_go_validate_entry.py")
    promote = text.index("sentinel_runtime_selection.py promote")
    assert preflight < validator < promote
    assert 'if [ "$VALIDATION_RC" -ne 0 ]' in text


def test_compose_prefers_validated_runtime_pointer():
    text = (ROOT / "scripts" / "sentinel-compose.sh").read_text(encoding="utf-8")
    pointer = text.index("validated-runtime.env")
    export = text.index("export SENTINEL_RUNTIME_IMAGE_REF")
    compose = text.index("docker compose", export)
    assert pointer < export < compose
    assert "sha256:[0-9a-f]{64}" in text
