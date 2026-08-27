#!/usr/bin/env python3
"""Preflight and promote the ordinary Sentinel runtime selected by Compose."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
POINTER = ROOT / "artifacts" / "sentinel" / "deployment" / "validated-runtime.env"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RuntimeSelectionRefused(RuntimeError):
    pass


def _run(argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(item) for item in argv], cwd=str(ROOT),
        env=dict(env) if env is not None else None,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _git(*args: str) -> str:
    result = _run(["git", *args])
    if result.returncode != 0:
        raise RuntimeSelectionRefused(
            "git %s failed" % " ".join(args))
    return (result.stdout or "").strip()


def _refresh_origin_main() -> None:
    """Refresh upstream immediately before promotion, closing the long-run TOCTOU."""
    result = _run(["git", "fetch", "--quiet", "origin", "main"])
    if result.returncode != 0:
        raise RuntimeSelectionRefused(
            "could not refresh origin/main immediately before runtime promotion")


def _load_dotenv_literal(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeSelectionRefused("local environment file is unreadable") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RuntimeSelectionRefused("local environment file has a malformed line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if _ENV_KEY.fullmatch(key) is None:
            raise RuntimeSelectionRefused("local environment file has an invalid key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            quote_char = value[0]
            value = value[1:-1]
            if quote_char == '"':
                value = value.replace('\\"', '"').replace("\\\\", "\\")
        values[key] = value
    return values


def _merged_environment() -> dict[str, str]:
    values = _load_dotenv_literal()
    values.update(os.environ)
    return values


def _clean_main_head() -> str:
    head = _git("rev-parse", "HEAD")
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    dirty = _git("status", "--porcelain=v1", "--untracked-files=all")
    origin = _git("rev-parse", "origin/main")
    if not _COMMIT.fullmatch(head):
        raise RuntimeSelectionRefused("repository HEAD is not an exact commit")
    if branch != "main":
        raise RuntimeSelectionRefused("runtime promotion requires branch main")
    if dirty:
        raise RuntimeSelectionRefused("runtime promotion requires a clean worktree")
    if origin != head:
        raise RuntimeSelectionRefused(
            "runtime promotion requires HEAD to equal freshly fetched origin/main")
    return head


def _inspect(reference: str) -> tuple[str, str]:
    result = _run(["docker", "image", "inspect", reference])
    if result.returncode != 0:
        raise RuntimeSelectionRefused(
            "selected Sentinel image is not locally inspectable")
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeSelectionRefused("Docker image inspection was invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeSelectionRefused("Docker image inspection was not one exact image")
    image = payload[0]
    digest = str(image.get("Id") or "")
    config = image.get("Config") if isinstance(image.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    revision = str(labels.get("org.opencontainers.image.revision") or "")
    if not _DIGEST.fullmatch(digest):
        raise RuntimeSelectionRefused("selected Sentinel image has no immutable sha256 id")
    if not _COMMIT.fullmatch(revision):
        raise RuntimeSelectionRefused("selected Sentinel image has no exact source revision")
    return digest, revision


def _compose_selected_image(env: Mapping[str, str]) -> str:
    explained = _run(["bash", "scripts/sentinel-compose.sh", "--explain"], env=env)
    if explained.returncode != 0:
        raise RuntimeSelectionRefused("Sentinel Compose graph could not be resolved")
    try:
        compose_args = shlex.split((explained.stdout or "").strip())
    except ValueError as exc:
        raise RuntimeSelectionRefused("Sentinel Compose graph output was malformed") from exc
    result = _run([
        "docker", "compose", *compose_args, "--profile", "cli",
        "config", "--format", "json"], env=env)
    if result.returncode != 0:
        raise RuntimeSelectionRefused("Compose could not resolve the ordinary Sentinel image")
    try:
        model = json.loads(result.stdout or "")
        image = ((model.get("services") or {}).get("sentinel") or {}).get("image")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise RuntimeSelectionRefused("Compose model was malformed") from exc
    if not isinstance(image, str) or not image.strip():
        raise RuntimeSelectionRefused("Compose model has no ordinary Sentinel image")
    return image.strip()


def preflight() -> int:
    try:
        head = _git("rev-parse", "HEAD")
        if not _COMMIT.fullmatch(head):
            raise RuntimeSelectionRefused("repository HEAD is not an exact commit")
        selected = _compose_selected_image(_merged_environment())
        digest, revision = _inspect(selected)
    except RuntimeSelectionRefused as exc:
        print("runtime preflight: UNAVAILABLE - %s" % exc, flush=True)
        return 0
    if revision == head:
        print(
            "runtime preflight: MATCH - ordinary image %s is built from current HEAD %s"
            % (digest[:19] + "...", head[:12]), flush=True)
    else:
        print(
            "runtime preflight: STALE - ordinary image is built from %s, current HEAD is %s; "
            "validation will not promote it and will replace the selector only after a successful run"
            % (revision[:12], head[:12]), flush=True)
    return 0


def _write_pointer(digest: str) -> None:
    POINTER.parent.mkdir(parents=True, exist_ok=True)
    payload = "SENTINEL_RUNTIME_IMAGE_REF=%s\n" % digest
    fd, tmp_name = tempfile.mkstemp(prefix=".validated-runtime-", dir=str(POINTER.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, POINTER)
        try:
            directory_fd = os.open(str(POINTER.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def promote(extra_args: Sequence[str]) -> int:
    if "--input" in extra_args or any(str(arg).startswith("--input=") for arg in extra_args):
        print("runtime promotion: SKIPPED for development-input validation", flush=True)
        return 0
    try:
        # Validation can run for hours. Re-read remote truth now, not the cached
        # origin/main ref observed at the beginning of the run.
        _refresh_origin_main()
        head = _clean_main_head()
        candidate = "sentinel-go-runtime:%s" % head
        digest, revision = _inspect(candidate)
        if revision != head:
            raise RuntimeSelectionRefused(
                "validated ordinary candidate revision disagrees with current HEAD")
        _write_pointer(digest)
        text = POINTER.read_text(encoding="ascii")
        if text != "SENTINEL_RUNTIME_IMAGE_REF=%s\n" % digest:
            raise RuntimeSelectionRefused("validated runtime pointer verification failed")
    except (OSError, RuntimeSelectionRefused) as exc:
        print("REFUSED: runtime promotion failed: %s" % exc, file=sys.stderr)
        return 2
    print(
        "runtime promotion: BOUND - ordinary Sentinel selector now uses %s from %s"
        % (digest[:19] + "...", head[:12]), flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("preflight")
    promotion = sub.add_parser("promote")
    promotion.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)
    if parsed.action == "preflight":
        return preflight()
    args = list(parsed.args)
    if args[:1] == ["--"]:
        args = args[1:]
    return promote(args)


if __name__ == "__main__":
    raise SystemExit(main())
