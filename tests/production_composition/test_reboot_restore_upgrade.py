from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_ci_runtime as ci  # noqa: E402
import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_promote as promote  # noqa: E402
import sentinel_runtime_selection as runtime  # noqa: E402

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
REGISTRY = "sha256:" + "c" * 64
LOCAL = "sha256:" + "d" * 64
IDENTITY = "e" * 64
IMMUTABLE = "ghcr.io/flabber1835/stocker/sentinel@" + REGISTRY
TOKEN = "1" * 64
OTHER_TOKEN = "2" * 64
BOOT = "3" * 64
OTHER_BOOT = "4" * 64


def _binding_result():
    return {
        "certified_image": IMMUTABLE,
        "image_digest": REGISTRY,
        "test_workflow_run": 101,
        "publication_workflow_run": 202,
    }


def _write_run_pass(path: Path, *, commit=COMMIT, token=TOKEN, boot=BOOT):
    evidence = {
        "schema": go_lock.RUN_PASS_SCHEMA,
        "git_commit": commit,
        "requested_target": "DUAL_RUN_OBSERVATION",
        "run_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
        "host_boot_id_sha256": boot,
        "passed_at": "2026-09-11T05:00:00Z",
    }
    payload = dict(evidence)
    payload["evidence_sha256"] = promote.phase._sha(evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def test_validated_runtime_pointer_survives_cold_process_restart(tmp_path, monkeypatch):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(runtime, "POINTER", pointer)

    runtime._write_pointer(IMMUTABLE)

    assert runtime._pointer_digest(pointer) == IMMUTABLE
    assert stat.S_IMODE(pointer.stat().st_mode) == 0o600
    assert pointer.read_text(encoding="ascii") == (
        "SENTINEL_RUNTIME_IMAGE_REF=" + IMMUTABLE + "\n")


@pytest.mark.parametrize("payload", [
    "",
    "SENTINEL_RUNTIME_IMAGE_REF=",
    "SENTINEL_RUNTIME_IMAGE_REF=sentinel:latest\n",
    "SENTINEL_RUNTIME_IMAGE_REF=sha256:abc\n",
    "SENTINEL_RUNTIME_IMAGE_REF=" + IMMUTABLE + "\nTRUNCATED=1\n",
])
def test_restored_runtime_pointer_corruption_fails_closed(tmp_path, payload):
    pointer = tmp_path / "validated-runtime.env"
    pointer.write_text(payload, encoding="ascii")
    with pytest.raises(runtime.RuntimeSelectionRefused):
        runtime._pointer_digest(pointer)


def test_reboot_has_no_inherited_go_lifecycle_authority(monkeypatch, tmp_path):
    monkeypatch.setattr(go_lock, "LOCK", tmp_path / "go.lock")
    env = {
        go_lock.LOCK_HELD_ENV: "1",
        go_lock.LOCK_FD_ENV: "999999",
        go_lock.RUN_TOKEN_ENV: TOKEN,
    }
    assert go_lock.lifecycle_lock_is_held(env) is False
    assert go_lock.current_run_token({}) is None


def test_ci_runtime_binding_from_previous_boot_is_rejected(monkeypatch, tmp_path):
    path = tmp_path / "ci-runtime.json"
    monkeypatch.setattr(ci, "BINDING_PATH", path)
    monkeypatch.setattr(ci.go_lock, "current_run_token", lambda: TOKEN)
    ci._write_binding(
        commit=COMMIT, result=_binding_result(), local_id=LOCAL,
        source_identity=IDENTITY, passed_tests=5000,
        token=TOKEN, boot_hash=BOOT)
    monkeypatch.setattr(ci, "_boot_hash", lambda: OTHER_BOOT)

    with pytest.raises(ci.CIRuntimeRefused, match="another host boot"):
        ci.load_binding(commit=COMMIT)


def test_ci_runtime_binding_from_restored_old_commit_is_rejected(monkeypatch, tmp_path):
    path = tmp_path / "ci-runtime.json"
    monkeypatch.setattr(ci, "BINDING_PATH", path)
    monkeypatch.setattr(ci.go_lock, "current_run_token", lambda: TOKEN)
    monkeypatch.setattr(ci, "_boot_hash", lambda: BOOT)
    ci._write_binding(
        commit=OTHER_COMMIT, result=_binding_result(), local_id=LOCAL,
        source_identity=IDENTITY, passed_tests=5000,
        token=TOKEN, boot_hash=BOOT)

    with pytest.raises(ci.CIRuntimeRefused, match="another commit"):
        ci.load_binding(commit=COMMIT)


def test_restored_target_pass_cannot_cross_into_new_go_invocation(monkeypatch, tmp_path):
    path = tmp_path / "run-pass.json"
    _write_run_pass(path)
    monkeypatch.setattr(go_lock, "RUN_PASS_PATH", path)
    monkeypatch.setattr(go_lock, "current_run_token", lambda: OTHER_TOKEN)
    monkeypatch.setattr(promote.phase, "_boot_id_sha256", lambda: BOOT)

    with pytest.raises(runtime.RuntimeSelectionRefused, match="different lifecycle invocation"):
        promote._current_run_target_pass(COMMIT)


def test_restored_target_pass_cannot_cross_host_reboot(monkeypatch, tmp_path):
    path = tmp_path / "run-pass.json"
    _write_run_pass(path)
    monkeypatch.setattr(go_lock, "RUN_PASS_PATH", path)
    monkeypatch.setattr(go_lock, "current_run_token", lambda: TOKEN)
    monkeypatch.setattr(promote.phase, "_boot_id_sha256", lambda: OTHER_BOOT)

    with pytest.raises(runtime.RuntimeSelectionRefused, match="different host boot"):
        promote._current_run_target_pass(COMMIT)


def test_restored_target_pass_cannot_authorize_new_code_revision(monkeypatch, tmp_path):
    path = tmp_path / "run-pass.json"
    _write_run_pass(path, commit=OTHER_COMMIT)
    monkeypatch.setattr(go_lock, "RUN_PASS_PATH", path)
    monkeypatch.setattr(go_lock, "current_run_token", lambda: TOKEN)
    monkeypatch.setattr(promote.phase, "_boot_id_sha256", lambda: BOOT)

    with pytest.raises(runtime.RuntimeSelectionRefused, match="current commit"):
        promote._current_run_target_pass(COMMIT)


def test_persisted_selector_never_implies_current_run_authority(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(runtime, "POINTER", pointer)
    runtime._write_pointer(IMMUTABLE)
    assert runtime._pointer_digest(pointer) == IMMUTABLE
    monkeypatch.delenv(go_lock.LOCK_HELD_ENV, raising=False)
    monkeypatch.delenv(go_lock.LOCK_FD_ENV, raising=False)
    monkeypatch.delenv(go_lock.RUN_TOKEN_ENV, raising=False)
    assert go_lock.lifecycle_lock_is_held() is False
    assert go_lock.current_run_token() is None
