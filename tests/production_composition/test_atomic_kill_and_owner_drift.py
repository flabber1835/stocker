from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_runtime_selection as runtime  # noqa: E402

OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64


def test_overpermissive_selector_mode_is_repaired_by_atomic_rewrite(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    pointer.write_text("SENTINEL_RUNTIME_IMAGE_REF=" + OLD + "\n", encoding="ascii")
    pointer.chmod(0o666)
    monkeypatch.setattr(runtime, "POINTER", pointer)

    runtime._write_pointer(NEW)

    assert runtime._pointer_digest(pointer) == NEW
    assert stat.S_IMODE(pointer.stat().st_mode) == 0o600


def test_foreign_owner_selector_is_replaced_with_current_process_owner(monkeypatch, tmp_path):
    pointer = tmp_path / "validated-runtime.env"
    pointer.write_text("SENTINEL_RUNTIME_IMAGE_REF=" + OLD + "\n", encoding="ascii")
    before = pointer.stat()
    chown = subprocess.run(
        ["sudo", "-n", "chown", "0:0", str(pointer)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert chown.returncode == 0, chown.stderr
    assert pointer.stat().st_uid == 0
    monkeypatch.setattr(runtime, "POINTER", pointer)

    runtime._write_pointer(NEW)

    after = pointer.stat()
    assert runtime._pointer_digest(pointer) == NEW
    assert after.st_uid == os.getuid()
    assert stat.S_IMODE(after.st_mode) == 0o600
    assert after.st_ino != before.st_ino


def _kill_script(kind: str, target: Path) -> str:
    scripts = repr(str(SCRIPTS))
    target_text = repr(str(target))
    common = (
        "import os,signal,sys; from pathlib import Path; "
        f"sys.path.insert(0,{scripts}); target=Path({target_text}); "
    )
    killer = "lambda src,dst: os.kill(os.getpid(),signal.SIGKILL)"
    if kind == "pointer":
        return common + (
            "import sentinel_runtime_selection as m; m.POINTER=target; "
            f"m.os.replace={killer}; m._write_pointer('sha256:'+'b'*64)")
    if kind == "binding":
        return common + (
            "import sentinel_go_ci_runtime as m; "
            f"m.os.replace={killer}; m._atomic_json(target,{{'new':True}})")
    if kind == "handoff":
        return common + (
            "import sentinel_go_post_validate as m; "
            f"m.os.replace={killer}; m.atomic_json(target,{{'new':True}})")
    if kind == "phase":
        return common + (
            "import sentinel_go_phase_entry as m; "
            f"m.os.replace={killer}; m._atomic_write(target,{{'new':True}})")
    raise AssertionError(kind)


def _retry_script(kind: str, target: Path) -> str:
    scripts = repr(str(SCRIPTS))
    target_text = repr(str(target))
    if kind == "pointer":
        return (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0,{scripts}); import sentinel_runtime_selection as m; "
            f"m.POINTER=Path({target_text}); m._write_pointer('sha256:'+'b'*64)")
    if kind == "binding":
        return (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0,{scripts}); import sentinel_go_ci_runtime as m; "
            f"m._atomic_json(Path({target_text}),{{'recovered':True}})")
    if kind == "handoff":
        return (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0,{scripts}); import sentinel_go_post_validate as m; "
            f"m.atomic_json(Path({target_text}),{{'recovered':True}})")
    if kind == "phase":
        return (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0,{scripts}); import sentinel_go_phase_entry as m; "
            f"m._atomic_write(Path({target_text}),{{'recovered':True}})")
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["pointer", "binding", "handoff", "phase"])
def test_sigkill_at_atomic_replace_preserves_previous_authority_record(tmp_path, kind):
    if kind == "pointer":
        target = tmp_path / "validated-runtime.env"
        old_bytes = ("SENTINEL_RUNTIME_IMAGE_REF=" + OLD + "\n").encode("ascii")
    else:
        target = tmp_path / (kind + ".json")
        old_bytes = b'{"old":true}\n'
    target.write_bytes(old_bytes)
    target.chmod(0o600)

    child = subprocess.run(
        [sys.executable, "-c", _kill_script(kind, target)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=15, check=False)

    assert child.returncode in {-9, 137}, (kind, child.returncode, child.stderr)
    assert target.read_bytes() == old_bytes
    if kind == "pointer":
        assert runtime._pointer_digest(target) == OLD
    else:
        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}

    retry = subprocess.run(
        [sys.executable, "-c", _retry_script(kind, target)], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
    assert retry.returncode == 0, (kind, retry.stderr)
    if kind == "pointer":
        assert runtime._pointer_digest(target) == NEW
    else:
        assert json.loads(target.read_text(encoding="utf-8")) == {"recovered": True}
