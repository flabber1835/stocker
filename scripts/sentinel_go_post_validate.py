#!/usr/bin/env python3
"""Finalize a successful GO validation without granting broker authority.

The local GO suite validates local immutable image IDs. Signed paper activation
binds registry-qualified RepoDigests. This helper makes that handoff explicit,
recreates the read-only panel on the promoted ordinary runtime, and garbage
collects only old GO scratch tags (never force-removing an image in use).
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
OUT = ROOT / "artifacts" / "sentinel" / "deployment" / "validated-artifact-handoff.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
REPO_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


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


def validated_repo_digest(env, key: str, expected_id: str):
    ref = str(env.get(key) or "").strip()
    if not ref:
        return None
    if REPO_DIGEST.fullmatch(ref) is None:
        raise Refused(f"{key} is set but is not a registry-qualified RepoDigest")
    if inspect_id(ref) != expected_id:
        raise Refused(f"{key} does not resolve to the GO-certified local image")
    return ref


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


def cleanup_old_go_tags(commit: str) -> None:
    result = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    if result.returncode != 0:
        return
    prefixes = (
        "sentinel-go-runtime:", "sentinel-go-authorized:", "sentinel-go-test:",
        "stocker-go-bt-engine:", "stocker-go-bt-engine-test:",
        "stocker-go-bt-data:", "stocker-go-bt-data-test:",
    )
    current = {prefix + commit for prefix in prefixes}
    for ref in sorted(set((result.stdout or "").splitlines())):
        ref = ref.strip()
        if not ref or ref in current or not ref.startswith(prefixes):
            continue
        # Deliberately no --force. If an old container still uses an image,
        # Docker refuses and we preserve it rather than disrupting a process.
        run(["docker", "image", "rm", ref])


def main() -> int:
    env = dict(os.environ)
    try:
        commit = git("rev-parse", "HEAD")
        if HEX40.fullmatch(commit) is None:
            raise Refused("HEAD is not an exact commit")
        ordinary = inspect_id(f"sentinel-go-runtime:{commit}")
        authorized = inspect_id(f"sentinel-go-authorized:{commit}")
        test = inspect_id(f"sentinel-go-test:{commit}")

        runtime_repo = validated_repo_digest(
            env, "SENTINEL_RUNTIME_IMAGE_DIGEST", authorized)
        test_repo = validated_repo_digest(
            env, "SENTINEL_TEST_IMAGE_DIGEST", test)

        atomic_json(OUT, {
            "schema": "sentinel.validated-artifact-handoff/1",
            "git_commit": commit,
            "local_image_ids": {
                "ordinary_runtime": ordinary,
                "authorized_runtime": authorized,
                "test_lens": test,
            },
            "activation_repo_digests": {
                "runtime": runtime_repo,
                "test": test_repo,
            },
            "activation_repo_digest_bound": bool(runtime_repo and test_repo),
            "authority": "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY",
        })
        recreate_panel(env)
        cleanup_old_go_tags(commit)
    except Refused as exc:
        print(f"REFUSED: GO post-validation handoff failed: {exc}", file=sys.stderr)
        return 2

    print("post-validation: panel recreated on promoted runtime", flush=True)
    if runtime_repo and test_repo:
        print("post-validation: activation RepoDigest handoff VERIFIED", flush=True)
    else:
        print(
            "post-validation: local GO images verified; signed activation still requires "
            "registry-qualified SENTINEL_RUNTIME_IMAGE_DIGEST and SENTINEL_TEST_IMAGE_DIGEST",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
