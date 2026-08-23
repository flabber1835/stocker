#!/usr/bin/env python3
"""Authorize a supported Compose feed mutation against the current checkout.

The immutable image selector answers *which bytes will run*.  This gate answers
the separate deployment question: are those bytes the clean source revision
currently checked out here?  It prints only the verified commit and selected
digest, one per line, for ``sentinel-compose.sh`` to inject into the container.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping, Sequence


_GIT_OBJECT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_RUN_FLAGS = {
    "--build", "--detach", "-d", "--interactive", "-i", "--no-deps",
    "--no-TTY", "-T", "--quiet", "-q", "--quiet-build", "--quiet-pull",
    "--remove-orphans", "--rm", "--service-ports", "-P", "--use-aliases",
}
_RUN_OPTIONS = {
    "--cap-add", "--cap-drop", "--entrypoint", "--env", "-e",
    "--env-from-file", "--label", "-l", "--name", "--publish", "-p",
    "--pull", "--user", "-u", "--volume", "-v", "--workdir", "-w",
}


class FeedGateRefused(RuntimeError):
    """The selected image is not authorized to mutate this checkout."""


def _run_service_command(argv: Sequence[str]) -> tuple[str, tuple[str, ...]] | None:
    """Return ``(service, command)`` for a Compose ``run`` invocation.

    Unknown run options refuse classification.  Silently treating a new
    value-taking option as a service could let a mutating command miss the host
    gate; a wrapper update is cheaper than that ambiguity.
    """
    if not argv or argv[0] != "run":
        return None
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            i += 1
            break
        if token in _RUN_FLAGS:
            i += 1
            continue
        if token in _RUN_OPTIONS:
            if i + 1 >= len(argv):
                raise FeedGateRefused(f"Compose run option {token} has no value")
            i += 2
            continue
        if any(token.startswith(option + "=") for option in _RUN_OPTIONS):
            i += 1
            continue
        if token.startswith("-"):
            raise FeedGateRefused(
                f"unrecognized Compose run option {token!r}; refusing to "
                "guess the service/command boundary")
        break
    if i >= len(argv):
        raise FeedGateRefused("Compose run invocation has no service")
    return argv[i], tuple(argv[i + 1:])


def is_feed_mutation(argv: Sequence[str]) -> bool:
    parsed = _run_service_command(argv)
    if parsed is None:
        return False
    service, command = parsed
    if service != "sentinel" or not command:
        return False
    if command[0] in {"feed-seed", "feed-daily"}:
        return True
    return command[0] == "feed-repair" and "--apply" in command[1:]


def selected_digest(image_ref: str, image_id: str) -> str:
    """Name the immutable selector actually used for this invocation."""
    ref = str(image_ref).strip()
    identifier = str(image_id).strip()
    if "@" in ref:
        candidate = ref.rsplit("@", 1)[1]
        if _DIGEST.fullmatch(candidate):
            return candidate
        raise FeedGateRefused(
            f"selected image reference {ref!r} has a non-sha256 digest")
    if _DIGEST.fullmatch(ref):
        return ref
    if not _DIGEST.fullmatch(identifier):
        raise FeedGateRefused(
            "Docker did not report an immutable sha256 image id for the "
            f"selected reference {ref!r}")
    return identifier


def validate_binding(*, head: str, dirty: bool, image_revision: str,
                     image_ref: str, image_id: str,
                     claimed_commit: str = "",
                     claimed_digest: str = "") -> tuple[str, str]:
    commit = str(head).strip()
    revision = str(image_revision).strip()
    if not _GIT_OBJECT.fullmatch(commit):
        raise FeedGateRefused("repository HEAD is not an exact Git object id")
    if dirty:
        raise FeedGateRefused(
            "repository worktree is dirty; a commit cannot identify the source "
            "authorized to mutate the corpus")
    if not _GIT_OBJECT.fullmatch(revision):
        raise FeedGateRefused(
            "selected Sentinel image has no exact "
            "org.opencontainers.image.revision label")
    if revision != commit:
        raise FeedGateRefused(
            f"selected Sentinel image was built from {revision}, but clean "
            f"repository HEAD is {commit}; rebuild/select the HEAD image")
    digest = selected_digest(image_ref, image_id)
    if claimed_commit and claimed_commit.strip() != commit:
        raise FeedGateRefused(
            "SENTINEL_GIT_COMMIT disagrees with the current clean checkout")
    if claimed_digest and claimed_digest.strip() != digest:
        raise FeedGateRefused(
            "SENTINEL_RUNTIME_IMAGE_DIGEST disagrees with the Compose-selected "
            "immutable image")
    return commit, digest


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(repo), text=True, capture_output=True)
    if completed.returncode != 0:
        raise FeedGateRefused(
            f"git {' '.join(args)} failed: "
            f"{(completed.stderr or completed.stdout).strip()}")
    return completed.stdout


def _inspect(image_ref: str) -> Mapping[str, object]:
    completed = subprocess.run(
        ["docker", "image", "inspect", image_ref],
        text=True, capture_output=True)
    if completed.returncode != 0:
        raise FeedGateRefused(
            f"Compose-selected image {image_ref!r} is not locally inspectable: "
            f"{(completed.stderr or completed.stdout).strip()}")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise FeedGateRefused("Docker image inspection was not valid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1 \
            or not isinstance(payload[0], dict):
        raise FeedGateRefused("Docker image inspection was not one exact image")
    return payload[0]


def bind(repo: Path, image_ref: str) -> tuple[str, str]:
    head = _git(repo, "rev-parse", "HEAD").strip()
    dirty = bool(_git(
        repo, "status", "--porcelain=v1", "--untracked-files=all").strip())
    image = _inspect(image_ref)
    config = image.get("Config") if isinstance(image.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    return validate_binding(
        head=head,
        dirty=dirty,
        image_revision=str(labels.get("org.opencontainers.image.revision") or ""),
        image_ref=image_ref,
        image_id=str(image.get("Id") or ""),
        claimed_commit=os.environ.get("SENTINEL_GIT_COMMIT", ""),
        claimed_digest=os.environ.get("SENTINEL_RUNTIME_IMAGE_DIGEST", ""),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    classify = sub.add_parser("classify")
    classify.add_argument("compose_args", nargs=argparse.REMAINDER)
    binding = sub.add_parser("bind")
    binding.add_argument("--repo", type=Path, required=True)
    binding.add_argument("--image", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "classify":
            compose_args = list(args.compose_args)
            if compose_args[:1] == ["--"]:
                compose_args = compose_args[1:]
            return 0 if is_feed_mutation(compose_args) else 1
        commit, digest = bind(args.repo.resolve(), args.image)
        print(commit)
        print(digest)
        return 0
    except FeedGateRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
