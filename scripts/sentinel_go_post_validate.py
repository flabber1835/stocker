#!/usr/bin/env python3
"""Finalize successful GO validation without granting broker authority.

The helper verifies the retained local exact-image certification state, recreates
the read-only panel through the supported Compose wrapper, proves the running
panel actually uses the promoted ordinary image, and records the local image IDs
that the reviewed autonomous-deploy path must promote unchanged.

Local Docker image IDs are *not* authorized-service RepoDigests. The autonomous
deploy path tags/pushes these exact IDs and freezes the resulting registry
manifest digests before `sentinel-authorized-cli.sh` or automation may consume
them.

It deliberately performs no automatic image deletion. Old Sentinel images may
still back an active signed paper-observation deployment even when no container
is currently running; retention-aware cleanup is a separate maintenance concern.
"""
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

import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_phase_entry as phase  # noqa: E402

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
        raise Refused(f"image is not locally inspectable: {ref}")
    return value


def running_panel_image_id(env) -> str:
    ps = run([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "ps", "-q", "sentinel-panel",
    ], env=env)
    container = (ps.stdout or "").strip()
    if (ps.returncode != 0 or CONTAINER_ID.fullmatch(container) is None
            or "\n" in container):
        raise Refused("recreated read-only panel container is not uniquely running")
    inspected = run([
        "docker", "container", "inspect", "--format", "{{.Image}}", container,
    ], env=env)
    image = (inspected.stdout or "").strip()
    if inspected.returncode != 0 or IMAGE_ID.fullmatch(image) is None:
        raise Refused("recreated read-only panel image identity is unavailable")
    return image


def recreate_panel(env, *, expected_image_id: str) -> None:
    completed = run([
        "bash", "scripts/sentinel-compose.sh", "--run",
        "up", "-d", "--no-deps", "--force-recreate", "sentinel-panel",
    ], env=env)
    if completed.returncode != 0:
        raise Refused("promoted read-only panel could not be recreated")
    observed = running_panel_image_id(env)
    if observed != expected_image_id:
        raise Refused("recreated read-only panel does not use the promoted ordinary image")


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


def main() -> int:
    env = phase.controller.go.merged_environment()
    try:
        if not go_lock.lifecycle_lock_is_held():
            raise Refused(
                "GO finalization is available only inside the verified locked sentinel-go-validate lifecycle")
        commit = git("rev-parse", "HEAD")
        if HEX40.fullmatch(commit) is None:
            raise Refused("HEAD is not an exact commit")

        runner = phase.controller.DiagnosticRunner()
        summary = phase._load_with_ordinary(runner, commit=commit)
        if summary is None or not summary.complete:
            raise Refused(
                "exact retained certification is unavailable at post-validation handoff")

        ordinary = phase._ordinary_id(runner, commit)
        authorized = str(summary.runtime_image_digest or "")
        test = str(summary.candidate_image_digest or "")
        if ordinary is None or not IMAGE_ID.fullmatch(authorized) or not IMAGE_ID.fullmatch(test):
            raise Refused("certified Sentinel image identities are incomplete")
        if inspect_id(f"sentinel-go-runtime:{commit}") != ordinary:
            raise Refused("ordinary runtime tag changed after promotion")
        if inspect_id(f"sentinel-go-authorized:{commit}") != authorized:
            raise Refused("authorized runtime tag changed after certification")
        if inspect_id(f"sentinel-go-test:{commit}") != test:
            raise Refused("test image tag changed after certification")

        handoff = {
            "schema": "sentinel.validated-artifact-handoff/2",
            "git_commit": commit,
            "ordinary_runtime_local_image_id": ordinary,
            "authorized_runtime_local_image_id": authorized,
            "test_local_image_id": test,
            "next_boundary": {
                "operation": "AUTONOMOUS_DEPLOY_REGISTRY_PROMOTION",
                "require_exact_local_ids": True,
                "output_identity_domain": "REGISTRY_REPODIGEST",
                "authorized_compose_requires_repo_digest": True,
            },
            "authority": "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY",
        }

        # Do not publish a fresh handoff artifact until the promoted panel is
        # actually recreated on—and independently proven to use—the exact
        # ordinary image recorded at certification. Otherwise a successful
        # Compose command could still leave stale panel bytes behind.
        recreate_panel(env, expected_image_id=ordinary)
        atomic_json(OUT, handoff)
    except Refused as exc:
        print(f"REFUSED: GO post-validation handoff failed: {exc}", file=sys.stderr)
        return 2

    print("post-validation: panel recreated and verified on validated runtime", flush=True)
    print(
        "post-validation: preserved prior authority images; no automatic image cleanup performed",
        flush=True,
    )
    print(
        "post-validation: local certified IDs recorded; autonomous deploy must promote those exact IDs to registry RepoDigests before authorized execution",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
