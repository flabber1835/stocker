#!/usr/bin/env python3
"""Certified GO base-backup freshness self-heal.

The supported production entry remains ``scripts/sentinel-go-validate.sh``.
This module is installed only by the verified GO entry after the exact artifact
suite has passed. It may create a new verified physical base backup only for
explicitly repairable freshness/absence states. Structural backup failures stay
operator refusals.
"""
from __future__ import annotations

import re
import sys
from typing import Mapping, Optional, Sequence

import sentinel_go_lock as go_lock
import sentinel_go_phase_entry as phase

controller = phase.controller
go = controller.go

_REPAIRABLE = (
    (re.compile(r"^REFUSED: latest base backup is [0-9]+h old \(max [0-9]+h\)$"),
     "BASE_BACKUP_STALE"),
    (re.compile(r"^REFUSED: last WAL archive is [0-9]+h old$"),
     "WAL_ARCHIVE_STALE"),
    (re.compile(r"^REFUSED: no base backup exists$"),
     "BASE_BACKUP_MISSING"),
    (re.compile(r"^REFUSED: no successful WAL archive is recorded$"),
     "WAL_ARCHIVE_UNINITIALIZED"),
)
_VERIFIED_BACKUP_PREFIX = "verified_base_backup:"
_ORIGINAL_PREPARATION = None


class BackupRefreshRefused(RuntimeError):
    """GO cannot establish a fresh verified base backup automatically."""

    def __init__(self, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(self.reason_code)


def _output_lines(completed) -> list[str]:
    return [
        line.strip()
        for stream in (completed.stdout or "", completed.stderr or "")
        for line in stream.splitlines()
        if line.strip()
    ]


def _repairable_reason(completed) -> Optional[str]:
    lines = _output_lines(completed)
    if len(lines) != 1:
        return None
    for pattern, code in _REPAIRABLE:
        if pattern.fullmatch(lines[0]):
            return code
    return None


def _created_backup_path(completed) -> Optional[str]:
    matches = [
        line[len(_VERIFIED_BACKUP_PREFIX):].strip()
        for line in (completed.stdout or "").splitlines()
        if line.startswith(_VERIFIED_BACKUP_PREFIX)
    ]
    if len(matches) != 1:
        return None
    value = matches[0]
    if not value.startswith("/") or "\n" in value or "\r" in value:
        return None
    return value


def _require_checkout_exact(runner, *, commit: str, env: Mapping[str, str]) -> None:
    head = runner.run(["git", "rev-parse", "HEAD"], env=env)
    dirty = runner.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], env=env)
    if (head.returncode != 0
            or (head.stdout or "").strip() != str(commit)
            or dirty.returncode != 0
            or bool((dirty.stdout or "").strip())):
        raise BackupRefreshRefused("BACKUP_REFRESH_CHECKOUT_IDENTITY_CHANGED")


def ensure_recent_verified_base_backup(
        runner, *, env: Mapping[str, str], commit: str) -> bool:
    """Return True only when this call created and re-verified a base backup."""
    if go._HEX40.fullmatch(str(commit)) is None:
        raise BackupRefreshRefused("BACKUP_REFRESH_CERTIFIED_COMMIT_INVALID")

    run_env = go._without_broker_authority(dict(env))
    _require_checkout_exact(runner, commit=str(commit), env=run_env)

    status = runner.run(
        ["bash", "scripts/sentinel-backup-status.sh"], env=run_env)
    if status.returncode == 0:
        print("[GO] backup durability checkpoint passed", flush=True)
        return False

    reason = _repairable_reason(status)
    if reason is None:
        raise BackupRefreshRefused("BACKUP_HEALTH_STRUCTURAL_REFUSAL")

    print(
        "[GO] backup durability requires refresh (%s); creating verified base backup"
        % reason,
        flush=True,
    )
    refreshed = runner.run(
        ["bash", "scripts/sentinel-base-backup.sh"], env=run_env)
    if refreshed.returncode != 0:
        raise BackupRefreshRefused("BASE_BACKUP_REFRESH_FAILED")
    path = _created_backup_path(refreshed)
    if path is None:
        raise BackupRefreshRefused("BASE_BACKUP_REFRESH_EVIDENCE_UNAVAILABLE")

    verified = runner.run(
        ["bash", "scripts/sentinel-backup-status.sh", "--backup", path],
        env=run_env)
    if verified.returncode != 0:
        raise BackupRefreshRefused("BASE_BACKUP_POST_REFRESH_NOT_READY")

    _require_checkout_exact(runner, commit=str(commit), env=run_env)
    print("[GO] refreshed base backup verified", flush=True)
    return True


def _unavailable_preparation(runtime_ref, *, reason_code: str):
    evidence = {
        "reason": str(reason_code),
        "backup_refresh_boundary": True,
    }
    return go.PreparationSummary(
        status=go.NOT_PROVEN,
        runtime_image_digest=(
            str(runtime_ref)
            if runtime_ref is not None
            and go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None
            else None),
        schema_migration_attempted=False,
        bounded_sharadar_daily_attempted=False,
        broker_mutation_attempts=0,
        evidence_sha256=go._evidence_digest(evidence),
    )


def _preparation_with_backup_refresh(*args, **kwargs):
    if _ORIGINAL_PREPARATION is None:
        raise RuntimeError("GO backup refresh overlay is not installed")

    # The phase guard is the exact-artifact certification boundary. The kernel
    # lifecycle lock and one-run capability prevent this host mutation from
    # becoming a standalone backup command reachable by importing this module.
    if not phase._PHASE.get("certified"):
        return _ORIGINAL_PREPARATION(*args, **kwargs)
    env = dict(kwargs.get("env") or {})
    if (not go_lock.lifecycle_lock_is_held(env)
            or go_lock.current_run_token() is None):
        return _ORIGINAL_PREPARATION(*args, **kwargs)

    runner = args[0] if args else kwargs.get("runner")
    commit = kwargs.get("commit")
    if runner is None or commit is None:
        return _ORIGINAL_PREPARATION(*args, **kwargs)

    try:
        ensure_recent_verified_base_backup(
            runner, env=env, commit=str(commit))
    except BackupRefreshRefused as exc:
        phase._PHASE["prepared"] = False
        print(
            "GO backup preparation refusal: %s" % exc.reason_code,
            file=sys.stderr,
            flush=True,
        )
        return _unavailable_preparation(
            kwargs.get("runtime_ref"), reason_code=exc.reason_code)
    return _ORIGINAL_PREPARATION(*args, **kwargs)


def install() -> None:
    global _ORIGINAL_PREPARATION
    current = controller.entry.probe_prevalidation_preparation
    if current is _preparation_with_backup_refresh:
        return
    _ORIGINAL_PREPARATION = current
    controller.entry.probe_prevalidation_preparation = (
        _preparation_with_backup_refresh)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _ = argv
    print(
        "REFUSED: sentinel_go_backup_refresh.py is internal; use "
        "scripts/sentinel-go-validate.sh",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
