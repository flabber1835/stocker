#!/usr/bin/env python3
"""Certified GO base-backup freshness self-heal.

The supported production entry remains ``scripts/sentinel-go-validate.sh``.
This module is installed only by the verified GO entry after the exact artifact
suite has passed. It may create a new verified physical base backup only for
explicitly repairable durability states. Structural configuration/integrity
failures remain operator refusals.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
import sys
from typing import Mapping, Optional, Sequence

import sentinel_go_lock as go_lock
import sentinel_go_phase_entry as phase

controller = phase.controller
go = controller.go

_STATUS_REASON_PREFIX = "SENTINEL_BACKUP_STATUS_REASON="
_STATUS_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_REPAIRABLE_CODES = frozenset({
    "BASE_BACKUP_STALE",
    "WAL_ARCHIVE_STALE",
    "BASE_BACKUP_MISSING",
    "BASE_BACKUP_NOT_FOUND",
    "WAL_ARCHIVE_UNINITIALIZED",
    # Historical archiver failure is a state observation. A certified base
    # backup can actively prove that the target is healthy now; if it is still
    # broken, the refresh itself fails closed on its post-base WAL proof.
    "WAL_ARCHIVE_UNRESOLVED_FAILURE",
    # A newest artifact left by older software can be safely superseded by one
    # independently verified backup. Exact post-refresh verification remains
    # strict, so a newly created malformed artifact never passes.
    "BASE_BACKUP_MANIFEST_MISSING",
    "BASE_BACKUP_RECOVERY_MARKER_MISSING",
})
_VERIFIED_BACKUP_PREFIX = "verified_base_backup:"
_DB_MUTATION_MARKER = (
    "SENTINEL_BASE_BACKUP_DB_MUTATION=RECOVERY_MARKER_SCHEMA_AND_ROW")
_AUDIT_SCHEMA = "sentinel.go-backup-refresh-audit/1"
_AUDIT_PATH = (
    go.ROOT / "artifacts" / "sentinel" / "go-validation" /
    "backup-refresh-audit.json")
_ORIGINAL_PREPARATION = None


class BackupRefreshRefused(RuntimeError):
    """GO cannot establish a fresh verified base backup automatically."""

    def __init__(self, reason_code: str):
        self.reason_code = str(reason_code)
        super().__init__(self.reason_code)


@dataclass(frozen=True)
class BackupRefreshResult:
    refreshed: bool
    reason_code: str
    backup_path: Optional[str]
    recovery_marker_database_mutation: bool
    post_refresh_exact_path_verified: bool
    checkout_identity_verified: bool

    @property
    def backup_path_sha256(self) -> Optional[str]:
        if self.backup_path is None:
            return None
        return hashlib.sha256(self.backup_path.encode("utf-8")).hexdigest()


def _output_lines(completed) -> list[str]:
    return [
        line.strip()
        for stream in (completed.stdout or "", completed.stderr or "")
        for line in stream.splitlines()
        if line.strip()
    ]


def _status_reason(completed) -> Optional[str]:
    """Parse one machine reason independent of unrelated subprocess diagnostics."""
    if int(completed.returncode) != 4:
        return None
    matches = []
    for line in _output_lines(completed):
        if not line.startswith(_STATUS_REASON_PREFIX):
            continue
        value = line[len(_STATUS_REASON_PREFIX):].strip()
        if _STATUS_REASON.fullmatch(value) is None:
            return None
        matches.append(value)
    if len(matches) != 1:
        return None
    return matches[0]


def _repairable_reason(completed) -> Optional[str]:
    reason = _status_reason(completed)
    return reason if reason in _REPAIRABLE_CODES else None


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


def _created_db_mutation_proven(completed) -> bool:
    matches = [
        line.strip() for line in (completed.stdout or "").splitlines()
        if line.strip() == _DB_MUTATION_MARKER
    ]
    return len(matches) == 1


def _require_go_authority(env: Mapping[str, str]) -> None:
    if not phase._PHASE.get("certified"):
        raise BackupRefreshRefused("BACKUP_REFRESH_CERTIFICATION_NOT_PROVEN")
    if not go_lock.lifecycle_lock_is_held(env):
        raise BackupRefreshRefused("BACKUP_REFRESH_LIFECYCLE_LOCK_NOT_PROVEN")
    process_token = go_lock.current_run_token()
    env_token = go_lock.current_run_token(env)
    if (process_token is None or env_token is None
            or not hmac.compare_digest(process_token, env_token)):
        raise BackupRefreshRefused("BACKUP_REFRESH_RUN_CAPABILITY_NOT_PROVEN")


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
        runner, *, env: Mapping[str, str], commit: str) -> BackupRefreshResult:
    """Establish current backup durability and return auditable local evidence."""
    _require_go_authority(env)
    if go._HEX40.fullmatch(str(commit)) is None:
        raise BackupRefreshRefused("BACKUP_REFRESH_CERTIFIED_COMMIT_INVALID")

    run_env = go._without_broker_authority(dict(env))
    _require_checkout_exact(runner, commit=str(commit), env=run_env)

    status = runner.run(
        ["bash", "scripts/sentinel-backup-status.sh"], env=run_env)
    if status.returncode == 0:
        print("[GO] backup durability checkpoint passed", flush=True)
        return BackupRefreshResult(
            refreshed=False,
            reason_code="BACKUP_HEALTHY",
            backup_path=None,
            recovery_marker_database_mutation=False,
            post_refresh_exact_path_verified=False,
            checkout_identity_verified=True,
        )

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
    if not _created_db_mutation_proven(refreshed):
        raise BackupRefreshRefused("BASE_BACKUP_DB_MUTATION_EVIDENCE_UNAVAILABLE")

    verified = runner.run(
        ["bash", "scripts/sentinel-backup-status.sh", "--backup", path],
        env=run_env)
    if verified.returncode != 0:
        raise BackupRefreshRefused("BASE_BACKUP_POST_REFRESH_NOT_READY")

    _require_checkout_exact(runner, commit=str(commit), env=run_env)
    print("[GO] refreshed base backup verified", flush=True)
    return BackupRefreshResult(
        refreshed=True,
        reason_code=reason,
        backup_path=path,
        recovery_marker_database_mutation=True,
        post_refresh_exact_path_verified=True,
        checkout_identity_verified=True,
    )


def _write_refresh_audit(
        *, commit: str, result: Optional[BackupRefreshResult] = None,
        refusal_reason: Optional[str] = None) -> str:
    """Persist exact local audit facts; only its digest enters public GO evidence."""
    if result is None and refusal_reason is None:
        raise ValueError("backup refresh audit requires a result or refusal")
    evidence = {
        "schema": _AUDIT_SCHEMA,
        "certified_git_commit": str(commit),
        "status": "PASS" if result is not None else "REFUSED",
        "refresh_reason_code": (
            result.reason_code if result is not None else str(refusal_reason)),
        "refreshed": bool(result and result.refreshed),
        # This local artifact is never included in the upload bundle. Retaining
        # the exact path here makes the authorized mutation reproducible while
        # the public preparation record carries only this document's digest.
        "verified_backup_path": (
            result.backup_path if result is not None else None),
        "verified_backup_path_sha256": (
            result.backup_path_sha256 if result is not None else None),
        "recovery_marker_database_mutation": bool(
            result and result.recovery_marker_database_mutation),
        "post_refresh_exact_path_verified": bool(
            result and result.post_refresh_exact_path_verified),
        "checkout_identity_verified": bool(
            result and result.checkout_identity_verified),
    }
    digest = go._evidence_digest(evidence)
    phase._atomic_write(
        _AUDIT_PATH, {**evidence, "evidence_sha256": digest})
    return digest


def _bind_backup_audit(base, *, audit_sha256: str):
    """Bind local backup evidence into the existing public preparation digest."""
    evidence = {
        "base_preparation_evidence_sha256": str(base.evidence_sha256),
        "backup_refresh_audit_sha256": str(audit_sha256),
        "authorized_database_mutation_scopes": [
            "VERIFIED_BASE_BACKUP_RECOVERY_MARKER",
            "SCHEMA_MIGRATION",
            "BOUNDED_SHARADAR_DAILY_INGEST",
        ],
    }
    return go.PreparationSummary(
        status=base.status,
        runtime_image_digest=base.runtime_image_digest,
        schema_migration_attempted=base.schema_migration_attempted,
        bounded_sharadar_daily_attempted=(
            base.bounded_sharadar_daily_attempted),
        broker_mutation_attempts=base.broker_mutation_attempts,
        evidence_sha256=go._evidence_digest(evidence),
        elapsed_milliseconds=base.elapsed_milliseconds,
    )


def _unavailable_preparation(
        runtime_ref, *, reason_code: str,
        backup_refresh_audit_sha256: Optional[str] = None):
    evidence = {
        "reason": str(reason_code),
        "backup_refresh_boundary": True,
        "backup_refresh_audit_sha256": backup_refresh_audit_sha256,
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


def _refused_preparation(
        *, env: Mapping[str, str], commit: Optional[str], runtime_ref,
        reason_code: str):
    phase._PHASE["prepared"] = False
    audit_sha = None
    safe_commit = str(commit or "")
    if go._HEX40.fullmatch(safe_commit) is not None:
        try:
            audit_sha = _write_refresh_audit(
                commit=safe_commit, refusal_reason=reason_code)
        except OSError:
            reason_code = "BACKUP_REFRESH_AUDIT_WRITE_FAILED"
            audit_sha = None
    print(
        "GO backup preparation refusal: %s" % reason_code,
        file=sys.stderr,
        flush=True,
    )
    return _unavailable_preparation(
        runtime_ref, reason_code=reason_code,
        backup_refresh_audit_sha256=audit_sha)


def _preparation_with_backup_refresh(*args, **kwargs):
    if _ORIGINAL_PREPARATION is None:
        raise RuntimeError("GO backup refresh overlay is not installed")

    # Preserve the underlying phase guard for uncertified/development calls.
    if not phase._PHASE.get("certified"):
        return _ORIGINAL_PREPARATION(*args, **kwargs)

    env_value = kwargs.get("env")
    if not isinstance(env_value, Mapping):
        return _refused_preparation(
            env={}, commit=kwargs.get("commit"),
            runtime_ref=kwargs.get("runtime_ref"),
            reason_code="BACKUP_REFRESH_CALL_CONTRACT_INVALID")
    env = dict(env_value)

    # Once exact-artifact certification is active, every missing/mismatched
    # production capability is a fail-closed preparation result. It cannot
    # silently fall through to a mutable preparation path.
    try:
        _require_go_authority(env)
    except BackupRefreshRefused as exc:
        return _refused_preparation(
            env=env, commit=kwargs.get("commit"),
            runtime_ref=kwargs.get("runtime_ref"),
            reason_code=exc.reason_code)

    runner = args[0] if args else kwargs.get("runner")
    commit = kwargs.get("commit")
    runtime_ref = kwargs.get("runtime_ref")
    if (runner is None or not callable(getattr(runner, "run", None))
            or commit is None or runtime_ref is None
            or go._HEX40.fullmatch(str(commit)) is None
            or go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is None):
        return _refused_preparation(
            env=env, commit=commit, runtime_ref=runtime_ref,
            reason_code="BACKUP_REFRESH_CALL_CONTRACT_INVALID")

    try:
        result = ensure_recent_verified_base_backup(
            runner, env=env, commit=str(commit))
        audit_sha = _write_refresh_audit(commit=str(commit), result=result)
    except BackupRefreshRefused as exc:
        return _refused_preparation(
            env=env, commit=str(commit), runtime_ref=runtime_ref,
            reason_code=exc.reason_code)
    except OSError:
        return _refused_preparation(
            env=env, commit=str(commit), runtime_ref=runtime_ref,
            reason_code="BACKUP_REFRESH_AUDIT_WRITE_FAILED")

    base = _ORIGINAL_PREPARATION(*args, **kwargs)
    return _bind_backup_audit(base, audit_sha256=audit_sha)


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
