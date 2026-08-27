#!/usr/bin/env python3
"""Finalize successful GO validation without granting broker authority.

The helper verifies the same retained exact-image certification state used by
promotion, recreates the read-only panel on the promoted ordinary runtime, and
writes the exact authorized/test image IDs consumed by the authorized CLI.

It deliberately performs no automatic image deletion.  Old Sentinel images may
still be named by an active signed paper-observation certificate even when no
container is currently running; retention-aware cleanup is a separate
maintenance concern.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_phase_entry as phase  # noqa: E402

OUT = ROOT / "artifacts" / "sentinel" / "deployment" / "validated-artifact-handoff.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def compose_args(env) -> list[str]:
    result = run(["bash", "scripts/sentinel-compose.sh", "--explain"], env=env)
    if result.returncode != 0:
        raise Refused("Sentinel Compose graph unavailable after promotion")
    try:
        return shlex.split((result.stdout or "").strip())
    except ValueError as exc:
        raise Refused("Sentinel Compose graph malformed") from exc


def recreate_panel(env) -> None:
    args = compose_args(env)
    completed = run([
        "docker", "compose", *args, "up", "-d", "--no-deps",
        "--force-recreate", "sentinel-panel",
    ], env=env)
    if completed.returncode != 0:
        raise Refused("promoted read-only panel could not be recreated")


def validate_configured_image_id(env, key: str, expected_id: str):
    configured = str(env.get(key) or "").strip()
    if not configured:
        return None
    if IMAGE_ID.fullmatch(configured) is None:
        raise Refused(f"{key} is set but is not an immutable sha256 image id")
    if configured != expected_id:
        raise Refused(f"{key} does not equal the GO-certified local image id")
    return configured


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
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> int:
    env = dict(os.environ)
    try:
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

        configured_runtime = validate_configured_image_id(
            env, "SENTINEL_RUNTIME_IMAGE_DIGEST", authorized)
        configured_test = validate_configured_image_id(
            env, "SENTINEL_TEST_IMAGE_DIGEST", test)

        atomic_json(OUT, {
            "schema": "sentinel.validated-artifact-handoff/1",
            "git_commit": commit,
            "ordinary_runtime_image_id": ordinary,
            "authorized_runtime_image_id": authorized,
            "test_image_id": test,
            "authorized_cli_exports": {
                "SENTINEL_GIT_COMMIT": commit,
                "SENTINEL_RUNTIME_IMAGE_DIGEST": authorized,
                "SENTINEL_TEST_IMAGE_DIGEST": test,
            },
            "configured_activation_digests_match": bool(
                configured_runtime == authorized and configured_test == test),
            "authority": "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY",
        })
        recreate_panel(env)
    except Refused as exc:
        print(f"REFUSED: GO post-validation handoff failed: {exc}", file=sys.stderr)
        return 2

    print("post-validation: panel recreated on promoted runtime", flush=True)
    print(
        "post-validation: preserved prior authority images; no automatic image cleanup performed",
        flush=True,
    )
    print(
        "post-validation: wrote exact authorized/test sha256 image IDs for the signed activation wrapper",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
