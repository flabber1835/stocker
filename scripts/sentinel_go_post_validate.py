#!/usr/bin/env python3
"""Finalize successful GO validation without granting broker authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_ci_runtime as ci_runtime  # noqa: E402
import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_phase_entry as phase  # noqa: E402
import sentinel_runtime_selection as runtime  # noqa: E402

OUT = ROOT / "artifacts" / "sentinel" / "deployment" / "validated-artifact-handoff.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")


class Refused(RuntimeError):
    pass


def run(argv, *, env=None):
    return subprocess.run(
        [str(x) for x in argv], cwd=str(ROOT),
        env=dict(env) if env is not None else None,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git(*args):
    result = run(["git", *args])
    if result.returncode != 0:
        raise Refused("git identity unavailable")
    return (result.stdout or "").strip()


def inspect_id(ref: str) -> str:
    result = run(["docker", "image", "inspect", "--format", "{{.Id}}", ref])
    value = (result.stdout or "").strip()
    if result.returncode != 0 or IMAGE_ID.fullmatch(value) is None:
        raise Refused("image is not locally inspectable: %s" % ref)
    return value


def running_panel_image_id(env) -> str:
    ps = run([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "ps", "-q", "sentinel-panel",
    ], env=env)
    container = (ps.stdout or "").strip()
    if (ps.returncode != 0 or CONTAINER_ID.fullmatch(container) is None
            or "\n" in container):
        raise Refused("recreated panel container is not uniquely running")
    inspected = run([
        "docker", "container", "inspect", "--format", "{{.Image}}", container,
    ], env=env)
    image = (inspected.stdout or "").strip()
    if inspected.returncode != 0 or IMAGE_ID.fullmatch(image) is None:
        raise Refused("recreated panel image identity is unavailable")
    return image


def recreate_panel(env, *, expected_image_id: str) -> None:
    completed = run([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "up", "-d", "--no-deps", "--force-recreate", "sentinel-panel",
    ], env=env)
    if completed.returncode != 0:
        raise Refused("promoted panel could not be recreated")
    observed = running_panel_image_id(env)
    if observed != expected_image_id:
        raise Refused("recreated panel does not use the promoted runtime")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".handoff-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _ci_handoff(commit: str, runner) -> tuple[str, dict]:
    try:
        binding = ci_runtime.load_binding(
            commit=commit, runner=runner, require_current_run=True)
    except ci_runtime.CIRuntimeRefused as exc:
        raise Refused("CI-certified runtime binding is unavailable") from exc
    selected = runtime._pointer_digest()
    certified_ref = str(binding["certified_image"])
    if selected != certified_ref:
        raise Refused("validated selector does not name the CI-certified runtime")
    local_id = str(binding["local_image_id"])
    if inspect_id(certified_ref) != local_id:
        raise Refused("CI-certified runtime changed after promotion")
    return local_id, {
        "schema": "sentinel.validated-artifact-handoff/3",
        "mode": "CI_CERTIFIED_RUNTIME",
        "git_commit": commit,
        "runtime_registry_ref": certified_ref,
        "runtime_registry_digest": str(binding["registry_digest"]),
        "runtime_local_image_id": local_id,
        "test_lens_local_image_id": None,
        "software_certification": "CI_VERIFIED",
        "next_boundary": {
            "operation": "CERTIFIED_RUNTIME_READY",
            "registry_promotion_required": False,
            "broker_authority_granted": False,
        },
        "authority": "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY",
    }


def _local_full_handoff(commit: str, runner) -> tuple[str, dict]:
    summary = phase._load_with_ordinary(runner, commit=commit)
    if summary is None or not summary.complete:
        raise Refused("exact local-full certification is unavailable")
    runtime_id = phase._ordinary_id(runner, commit)
    test_id = str(summary.candidate_image_digest or "")
    if runtime_id is None or IMAGE_ID.fullmatch(test_id) is None:
        raise Refused("local-full certified image identities are incomplete")
    if inspect_id("sentinel-go-runtime:%s" % commit) != runtime_id:
        raise Refused("local-full runtime changed after promotion")
    if inspect_id("sentinel-go-test:%s" % commit) != test_id:
        raise Refused("local-full test lens changed after certification")
    if runtime._pointer_digest() != runtime_id:
        raise Refused("validated selector does not name the local-full runtime")
    return runtime_id, {
        "schema": "sentinel.validated-artifact-handoff/3",
        "mode": "LOCAL_FULL_CERTIFICATION",
        "git_commit": commit,
        "runtime_registry_ref": None,
        "runtime_registry_digest": None,
        "runtime_local_image_id": runtime_id,
        "test_lens_local_image_id": test_id,
        "software_certification": "LOCAL_FULL_VERIFIED",
        "next_boundary": {
            "operation": "RUNTIME_REGISTRY_PROMOTION",
            "registry_promotion_required": True,
            "require_exact_local_runtime_id": True,
            "broker_authority_granted": False,
        },
        "authority": "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY",
    }


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    local_full = "--local-full-certification" in args
    try:
        if not go_lock.lifecycle_lock_is_held():
            raise Refused(
                "GO finalization is available only inside the verified locked sentinel-go-validate lifecycle")
        commit = git("rev-parse", "HEAD")
        if HEX40.fullmatch(commit) is None:
            raise Refused("HEAD is not an exact commit")
        runner = phase.controller.DiagnosticRunner()
        expected_image_id, handoff = (
            _local_full_handoff(commit, runner)
            if local_full else _ci_handoff(commit, runner)
        )
        env = runtime._merged_environment()
        recreate_panel(env, expected_image_id=expected_image_id)
        atomic_json(OUT, handoff)
    except (OSError, runtime.RuntimeSelectionRefused, Refused) as exc:
        print("REFUSED: GO post-validation handoff failed: %s" % exc, file=sys.stderr)
        return 2

    print("post-validation: panel recreated and verified on the one validated runtime", flush=True)
    if local_full:
        print(
            "post-validation: local-full runtime recorded for exact registry promotion; test lens remains certification-only",
            flush=True,
        )
    else:
        print(
            "post-validation: CI-certified registry digest retained; no runtime republish is required",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
