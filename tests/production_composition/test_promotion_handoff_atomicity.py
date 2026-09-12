from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_post_validate as post  # noqa: E402
import sentinel_go_promote as promote  # noqa: E402
import sentinel_runtime_selection as runtime  # noqa: E402

COMMIT = "a" * 40
REGISTRY = "sha256:" + "b" * 64
LOCAL = "sha256:" + "c" * 64
REF = "ghcr.io/flabber1835/stocker/sentinel@" + REGISTRY
TARGET = "DUAL_RUN_OBSERVATION"


def _promotion_common(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(promote.go_lock, "lifecycle_lock_is_held", lambda: True)
    monkeypatch.setattr(promote.runtime, "_refresh_origin_main", lambda: None)
    monkeypatch.setattr(promote.runtime, "_clean_main_head", lambda: COMMIT)
    monkeypatch.setattr(promote, "_current_run_target_pass", lambda _head: {
        "requested_target": TARGET})
    monkeypatch.setattr(promote.phase.controller, "DiagnosticRunner", lambda: object())
    monkeypatch.setattr(promote.runtime, "POINTER", pointer)
    return pointer


def test_target_proof_precedes_pointer_and_run_pass_consumption(monkeypatch, tmp_path):
    pointer = _promotion_common(monkeypatch, tmp_path)
    events = []

    def select(*, head, runner):
        assert head == COMMIT
        events.append("select")
        promote.runtime._write_pointer(REF)
        events.append("pointer")
        return REF

    monkeypatch.setattr(promote, "_promote_ci", select)
    monkeypatch.setattr(promote, "_consume_run_pass", lambda: events.append("consume"))

    assert promote.main([]) == 0
    assert events == ["select", "pointer", "consume"]
    assert pointer.read_text(encoding="ascii") == "SENTINEL_RUNTIME_IMAGE_REF=" + REF + "\n"


def test_failed_runtime_reverification_cannot_consume_target_proof(monkeypatch, tmp_path):
    pointer = _promotion_common(monkeypatch, tmp_path)
    consumed = []

    def refuse(**_kwargs):
        raise runtime.RuntimeSelectionRefused("certificate changed")

    monkeypatch.setattr(promote, "_promote_ci", refuse)
    monkeypatch.setattr(promote, "_consume_run_pass", lambda: consumed.append(True))

    assert promote.main([]) == 2
    assert consumed == []
    assert not pointer.exists()


def test_pointer_verification_failure_cannot_consume_target_proof(monkeypatch, tmp_path):
    pointer = _promotion_common(monkeypatch, tmp_path)
    consumed = []

    def mismatched(**_kwargs):
        pointer.write_text("SENTINEL_RUNTIME_IMAGE_REF=" + LOCAL + "\n", encoding="ascii")
        return REF

    monkeypatch.setattr(promote, "_promote_ci", mismatched)
    monkeypatch.setattr(promote, "_consume_run_pass", lambda: consumed.append(True))

    assert promote.main([]) == 2
    assert consumed == []


def test_run_pass_consumption_failure_reports_no_success(monkeypatch, tmp_path):
    pointer = _promotion_common(monkeypatch, tmp_path)

    def select(**_kwargs):
        promote.runtime._write_pointer(REF)
        return REF

    def refuse():
        raise runtime.RuntimeSelectionRefused("proof could not be consumed")

    monkeypatch.setattr(promote, "_promote_ci", select)
    monkeypatch.setattr(promote, "_consume_run_pass", refuse)

    assert promote.main([]) == 2
    assert promote.runtime._pointer_digest(pointer) == REF


def _post_common(monkeypatch, tmp_path):
    out = tmp_path / "handoff.json"
    events = []
    handoff = {
        "schema": "sentinel.validated-artifact-handoff/3",
        "mode": "CI_CERTIFIED_RUNTIME",
        "git_commit": COMMIT,
    }
    monkeypatch.setattr(post.go_lock, "lifecycle_lock_is_held", lambda: True)
    monkeypatch.setattr(post, "git", lambda *_args: COMMIT)
    monkeypatch.setattr(post.phase.controller, "DiagnosticRunner", lambda: object())
    monkeypatch.setattr(post, "_ci_handoff", lambda _commit, _runner: (LOCAL, handoff))
    monkeypatch.setattr(post.runtime, "_merged_environment", lambda: {})
    monkeypatch.setattr(post, "OUT", out)
    return out, events, handoff


def test_panel_verification_precedes_handoff_evidence(monkeypatch, tmp_path):
    out, events, handoff = _post_common(monkeypatch, tmp_path)

    def panel(_env, *, expected_image_id):
        assert expected_image_id == LOCAL
        events.append("panel")

    real_atomic = post.atomic_json

    def write(path, value):
        events.append("handoff")
        real_atomic(path, value)

    monkeypatch.setattr(post, "recreate_panel", panel)
    monkeypatch.setattr(post, "atomic_json", write)

    assert post.main([]) == 0
    assert events == ["panel", "handoff"]
    assert out.exists()


@pytest.mark.parametrize("message", [
    "Docker daemon restarted",
    "panel container disappeared",
    "Compose network recreation failed",
    "panel image mismatch",
])
def test_panel_or_docker_failure_cannot_publish_handoff(monkeypatch, tmp_path, message):
    out, _events, _handoff = _post_common(monkeypatch, tmp_path)

    def refuse(_env, *, expected_image_id):
        raise post.Refused(message)

    monkeypatch.setattr(post, "recreate_panel", refuse)

    assert post.main([]) == 2
    assert not out.exists()


def test_handoff_write_failure_reports_no_success_after_verified_panel(monkeypatch, tmp_path):
    out, events, _handoff = _post_common(monkeypatch, tmp_path)
    monkeypatch.setattr(post, "recreate_panel", lambda *_a, **_k: events.append("panel"))

    def refuse(_path, _value):
        raise OSError("read-only file system")

    monkeypatch.setattr(post, "atomic_json", refuse)

    assert post.main([]) == 2
    assert events == ["panel"]
    assert not out.exists()


def test_recreate_panel_refuses_wrong_promoted_image(monkeypatch):
    container = "a" * 12
    calls = []

    def run(argv, *, env=None):
        command = [str(x) for x in argv]
        calls.append(command)
        if "up" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "ps" in command:
            return subprocess.CompletedProcess(command, 0, stdout=container + "\n", stderr="")
        if command[:3] == ["docker", "container", "inspect"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="sha256:" + "d" * 64 + "\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(post, "run", run)
    with pytest.raises(post.Refused, match="does not use the promoted runtime"):
        post.recreate_panel({}, expected_image_id=LOCAL)


def test_recreate_panel_refuses_ambiguous_multiple_containers(monkeypatch):
    def run(argv, *, env=None):
        command = [str(x) for x in argv]
        if "up" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "ps" in command:
            return subprocess.CompletedProcess(
                command, 0, stdout=("a" * 12) + "\n" + ("b" * 12) + "\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(post, "run", run)
    with pytest.raises(post.Refused, match="not uniquely running"):
        post.recreate_panel({}, expected_image_id=LOCAL)
