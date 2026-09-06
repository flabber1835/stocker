from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_validate.py"
spec = importlib.util.spec_from_file_location("single_runtime_go_validate", SCRIPT)
go = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = go
spec.loader.exec_module(go)

COMMIT = "a" * 40
RUNTIME_ID = "sha256:" + "b" * 64
TEST_ID = "sha256:" + "c" * 64
IDENTITY = "d" * 64


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def run(self, argv, *, env=None, cwd=ROOT):
        command = [str(x) for x in argv]
        self.commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            ref = command[-1]
            value = TEST_ID if ref.startswith("sentinel-go-test:") else RUNTIME_ID
            return subprocess.CompletedProcess(command, 0, stdout=value + "\n", stderr="")
        if command[:4] == ["docker", "run", "--rm", "--network"] and "identity" in command:
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps({"identity_hash": IDENTITY}), stderr="")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, stdout="1 passed in 0.01s\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_production_go_certification_builds_runtime_then_test_lens_only():
    runner = RecordingRunner()
    summary, gate = go.probe_certified_suite(
        runner, commit=COMMIT, now_text="2026-09-06T17:00:00Z")

    build_commands = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "build"]]
    assert len(build_commands) == 2
    joined = "\n".join(" ".join(cmd) for cmd in build_commands)
    assert "Dockerfile.sentinel-authorized" not in joined
    assert "sentinel-go-authorized:" not in joined
    assert "SENTINEL_RUNTIME_BASE_IMAGE=" not in joined
    assert "-f Dockerfile.sentinel ." in joined
    assert "-f Dockerfile.sentinel-test ." in joined
    assert "SENTINEL_IMAGE=sentinel-go-runtime:" + COMMIT in joined
    assert summary.runtime_image_digest == RUNTIME_ID
    assert summary.candidate_image_digest == TEST_ID
    assert summary.auxiliary_image_digests == ()
    assert summary.complete
    assert gate.status == go.PASS
