#!/usr/bin/env python3
"""Race-aware, permission-preserving writer for Sentinel's secrets-bearing .env."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import stat
from typing import Callable, Mapping, Optional, Tuple

import sentinel_env


_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class EnvWriteRefused(RuntimeError):
    """Raised when an atomic managed update cannot prove its source observation."""


def _identity(entry) -> Tuple[int, int, int, int, int, int]:
    return (
        entry.st_dev,
        entry.st_ino,
        entry.st_mode,
        entry.st_size,
        entry.st_mtime_ns,
        entry.st_ctime_ns,
    )


def _snapshot(path: Path):
    """Return stable bytes, identity and mode, or a proven missing observation."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None, None, 0o600
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise EnvWriteRefused(".env is not a regular non-symlink file")
    try:
        raw = sentinel_env.read_bytes(path, required=True)
        after = path.lstat()
    except (OSError, sentinel_env.EnvRefused) as exc:
        raise EnvWriteRefused(".env could not be observed stably") from exc
    if _identity(before) != _identity(after):
        raise EnvWriteRefused(".env changed while the managed update was reading it")
    return raw, _identity(after), stat.S_IMODE(after.st_mode)


def _render(original: Optional[bytes], updates: Mapping[str, str]) -> bytes:
    if original is None:
        text = ""
    else:
        try:
            text = original.decode("utf-8-sig")
        except UnicodeError as exc:
            raise EnvWriteRefused(".env is not valid UTF-8") from exc

    managed = {}
    for raw_key, raw_value in updates.items():
        key = str(raw_key)
        value = str(raw_value)
        if _KEY.fullmatch(key) is None:
            raise EnvWriteRefused("managed .env key is invalid: %s" % key)
        if any(char in value for char in ("\0", "\r", "\n")):
            raise EnvWriteRefused(
                "managed .env value contains a line/control boundary: %s" % key)
        managed[key] = value

    lines = text.splitlines()
    emitted = set()
    out = []
    for line in lines:
        stripped = line.strip()
        candidate = re.sub(r"^export[ \t]+", "", stripped)
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else None
        if key in managed:
            if key not in emitted:
                out.append("%s=%s" % (key, managed[key]))
                emitted.add(key)
            continue
        out.append(line)

    remaining = sorted(set(managed) - emitted)
    if remaining:
        if out and out[-1] != "":
            out.append("")
        out.append("# Managed by scripts/sentinel-autonomous-deploy.sh after PASS.")
        out.extend("%s=%s" % (key, managed[key]) for key in remaining)
    return ("\n".join(out) + "\n").encode("utf-8")


def safe_update_dotenv(
        path: Path,
        updates: Mapping[str, str],
        *,
        before_commit: Optional[Callable[[], None]] = None) -> None:
    """Serialize managed writers and commit only a still-current observation.

    Existing permission bits are preserved exactly. A newly created file is 0600.
    The lock serializes all supported managed writers; the final stable-source
    observation still refuses concurrent external replacement or in-place edits.
    """
    path = Path(path)
    lock_path = path.with_name(path.name + ".deploy-safe.lock")
    lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        original, identity, mode = _snapshot(path)
        payload = _render(original, updates)
        temporary = path.with_name(path.name + ".deploy-safe.%d.tmp" % os.getpid())

        try:
            fd = os.open(
                str(temporary),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode if identity is not None else 0o600,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(str(temporary), mode if identity is not None else 0o600)

            if before_commit is not None:
                before_commit()

            current, current_identity, _current_mode = _snapshot(path)
            if identity is None:
                if current_identity is not None:
                    raise EnvWriteRefused(
                        ".env appeared concurrently; refusing to overwrite a new operator file")
            elif current_identity != identity or current != original:
                raise EnvWriteRefused(
                    ".env changed after the managed update snapshot; refusing stale replacement")

            os.replace(str(temporary), str(path))
            os.chmod(str(path), mode if identity is not None else 0o600)

            directory_fd = os.open(
                str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
