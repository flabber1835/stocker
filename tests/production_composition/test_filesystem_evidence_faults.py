from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_ci_runtime as ci  # noqa: E402
import sentinel_go_post_validate as post  # noqa: E402
import sentinel_runtime_selection as runtime  # noqa: E402

OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64


def _temps(parent: Path, prefix: str):
    return list(parent.glob(prefix + "*"))


def test_runtime_pointer_replace_failure_preserves_previous_selector(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    pointer.write_text("SENTINEL_RUNTIME_IMAGE_REF=" + OLD + "\n", encoding="ascii")
    monkeypatch.setattr(runtime, "POINTER", pointer)

    def fail_replace(_src, _dst):
        raise OSError("simulated atomic rename failure")

    monkeypatch.setattr(runtime.os, "replace", fail_replace)
    with pytest.raises(OSError, match="rename failure"):
        runtime._write_pointer(NEW)

    assert runtime._pointer_digest(pointer) == OLD
    assert _temps(tmp_path, ".validated-runtime-") == []


def test_runtime_pointer_file_fsync_failure_preserves_previous_selector(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    pointer.write_text("SENTINEL_RUNTIME_IMAGE_REF=" + OLD + "\n", encoding="ascii")
    monkeypatch.setattr(runtime, "POINTER", pointer)

    def fail_fsync(_fd):
        raise OSError("No space left on device")

    monkeypatch.setattr(runtime.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="No space"):
        runtime._write_pointer(NEW)

    assert runtime._pointer_digest(pointer) == OLD
    assert _temps(tmp_path, ".validated-runtime-") == []


def test_runtime_pointer_directory_fsync_failure_leaves_complete_selector(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(runtime, "POINTER", pointer)
    calls = 0
    real_fsync = os.fsync

    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_fsync(fd)
        raise OSError("directory fsync unavailable")

    monkeypatch.setattr(runtime.os, "fsync", fsync)
    runtime._write_pointer(NEW)

    assert calls >= 2
    assert runtime._pointer_digest(pointer) == NEW
    assert _temps(tmp_path, ".validated-runtime-") == []


def test_runtime_pointer_parent_is_not_a_directory_fails_without_new_selector(monkeypatch, tmp_path):
    parent = tmp_path / "deployment"
    parent.write_text("not-a-directory", encoding="ascii")
    monkeypatch.setattr(runtime, "POINTER", parent / "validated-runtime.env")
    with pytest.raises(OSError):
        runtime._write_pointer(NEW)


def test_runtime_pointer_is_mode_0600(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    monkeypatch.setattr(runtime, "POINTER", pointer)
    runtime._write_pointer(NEW)
    assert stat.S_IMODE(pointer.stat().st_mode) == 0o600


def test_handoff_replace_failure_preserves_previous_evidence(monkeypatch, tmp_path):
    path = tmp_path / "handoff.json"
    path.write_text('{"old":true}\n', encoding="utf-8")

    def fail_replace(_src, _dst):
        raise OSError("simulated handoff rename failure")

    monkeypatch.setattr(post.os, "replace", fail_replace)
    with pytest.raises(OSError, match="rename failure"):
        post.atomic_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert _temps(tmp_path, ".handoff-") == []


def test_handoff_file_fsync_failure_preserves_previous_evidence(monkeypatch, tmp_path):
    path = tmp_path / "handoff.json"
    path.write_text('{"old":true}\n', encoding="utf-8")
    monkeypatch.setattr(post.os, "fsync", lambda _fd: (_ for _ in ()).throw(
        OSError("read-only file system")))

    with pytest.raises(OSError, match="read-only"):
        post.atomic_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert _temps(tmp_path, ".handoff-") == []


def test_handoff_directory_fsync_failure_never_exposes_partial_json(monkeypatch, tmp_path):
    path = tmp_path / "handoff.json"
    calls = 0
    real_fsync = os.fsync

    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_fsync(fd)
        raise OSError("directory fsync unavailable")

    monkeypatch.setattr(post.os, "fsync", fsync)
    post.atomic_json(path, {"new": True, "sequence": [1, 2, 3]})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "new": True, "sequence": [1, 2, 3]}
    assert _temps(tmp_path, ".handoff-") == []


def test_handoff_is_mode_0600(tmp_path):
    path = tmp_path / "handoff.json"
    post.atomic_json(path, {"ok": True})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_ci_binding_replace_failure_preserves_previous_binding(monkeypatch, tmp_path):
    path = tmp_path / "ci-binding.json"
    path.write_text('{"old":true}\n', encoding="utf-8")

    def fail_replace(_src, _dst):
        raise OSError("simulated binding rename failure")

    monkeypatch.setattr(ci.os, "replace", fail_replace)
    with pytest.raises(OSError, match="rename failure"):
        ci._atomic_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert _temps(tmp_path, ".ci-runtime-") == []


def test_ci_binding_file_fsync_failure_preserves_previous_binding(monkeypatch, tmp_path):
    path = tmp_path / "ci-binding.json"
    path.write_text('{"old":true}\n', encoding="utf-8")
    monkeypatch.setattr(ci.os, "fsync", lambda _fd: (_ for _ in ()).throw(
        OSError("No space left on device")))

    with pytest.raises(OSError, match="No space"):
        ci._atomic_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert _temps(tmp_path, ".ci-runtime-") == []


def test_ci_binding_directory_fsync_failure_still_has_one_complete_record(monkeypatch, tmp_path):
    path = tmp_path / "ci-binding.json"
    calls = 0
    real_fsync = os.fsync

    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_fsync(fd)
        raise OSError("directory fsync unavailable")

    monkeypatch.setattr(ci.os, "fsync", fsync)
    ci._atomic_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert _temps(tmp_path, ".ci-runtime-") == []


@pytest.mark.parametrize("writer,prefix", [
    (post.atomic_json, ".handoff-"),
    (ci._atomic_json, ".ci-runtime-"),
])
def test_stale_temporary_files_do_not_become_authority(tmp_path, writer, prefix):
    target = tmp_path / "authority.json"
    stale = tmp_path / (prefix + "stale")
    stale.write_text('{"stale":true}\n', encoding="utf-8")

    writer(target, {"current": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"current": True}
    assert stale.exists()
    assert json.loads(stale.read_text(encoding="utf-8")) == {"stale": True}
