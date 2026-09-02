#!/usr/bin/env python3
"""Feed-bound preparation implementation for the supported phased GO lifecycle.

This module is intentionally import-only for production orchestration. The
supported operator entry is ``scripts/sentinel-go-validate.sh``. The bounded
financial-database preparation proves both the host GO lifecycle flock and an
in-process verified-orchestration capability at its own mutation boundary;
clean HEAD/image binding alone is not sufficient.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_validate as go  # noqa: E402


_RECOVERY_PREPARATION_CODE = r'''
import hashlib
import json, os

SUCCESS_MARKER = 'SENTINEL_GO_PREPARATION='
RECOVERY_MARKER = 'SENTINEL_GO_PREPARATION_RECOVERY='
FAILURE_MARKER = 'SENTINEL_GO_PREPARATION_FAILURE='


def failure_detail(exc):
    raw = str(exc).strip()
    if not raw:
        return {}
    digest = hashlib.sha256(raw.encode('utf-8', errors='replace')).hexdigest()
    lowered = raw.lower()
    prohibited = ('http://', 'https://', 'api_key', 'api-key', 'password',
                  'authorization', 'postgres://', 'postgresql://', 'apca-api-')
    value = {'detail_sha256': digest}
    if any(item in lowered for item in prohibited) or '\n' in raw or '\r' in raw:
        return value
    if len(raw) > 420:
        raw = raw[:365] + ' ... [sha256:%s]' % digest[:16]
    value['detail'] = raw
    return value


def reason_code(phase, exc):
    name = type(exc).__name__
    lowered = str(exc).lower()
    if name == 'VendorPublicationUnstable':
        return 'SOURCE_PUBLICATION_UNSTABLE'
    if name == 'MutationCursorUnavailable':
        return 'LOCAL_CURSOR_MISSING'
    if name == 'HistoricalIdentityMutation':
        return 'SOURCE_IDENTITY_HISTORY_MUTATION'
    if name in {'SharadarMutationRefused', 'SepMutationIdentityRefused',
                'SourceAuthorityRefused'}:
        if 'source cursor' in lowered:
            return 'LOCAL_CURSOR_CORRUPT'
        if 'no positive raw close' in lowered:
            return 'SOURCE_RAW_CLOSE_INVALID'
        if 'lastupdated' in lowered or 'invalid date' in lowered:
            return 'SOURCE_CDC_INVALID'
        return 'SOURCE_AUTHORITY_REFUSED'
    return {
        'RUNTIME_IMPORT': 'PREPARATION_RUNTIME_IMPORT_FAILURE',
        'DATABASE_CONNECT': 'PREPARATION_DATABASE_CONNECT_FAILURE',
        'BACKUP_DURABILITY': 'PREPARATION_BACKUP_DURABILITY_REFUSED',
        'SCHEMA_MIGRATION': 'PREPARATION_SCHEMA_MIGRATION_FAILED',
        'DAILY_CATCHUP': 'PREPARATION_DAILY_CATCHUP_FAILED',
        'PUBLICATION_CHECK': 'PREPARATION_PUBLICATION_CHECK_FAILED',
    }.get(str(phase), 'PREPARATION_RUNTIME_FAILURE')


def emit_failure(phase, exc):
    value = {
        'phase': str(phase),
        'error_type': type(exc).__name__,
        'reason_code': reason_code(phase, exc),
    }
    value.update(failure_detail(exc))
    print(FAILURE_MARKER + json.dumps(value, sort_keys=True), flush=True)


c = None
phase = 'RUNTIME_IMPORT'
try:
    from datetime import datetime, timezone
    from sentinel import backup_guard, schema
    from sentinel.feed import calendar, outage_recovery, publication, store
    from sentinel.shadow_runtime import publication_not_before

    phase = 'DATABASE_CONNECT'
    c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
    # Schema bootstrap/migration is PostgreSQL WAL mutation just like market-data
    # publication. Prove the external archive target *before* the validator may
    # change even one financial-database row.
    phase = 'BACKUP_DURABILITY'
    backup_guard.require_writes_permitted(
        c, operation='NAS validation schema migration')
    phase = 'SCHEMA_MIGRATION'
    schema.ensure_schema(c)
    store.migrate_schema(c)
    target = calendar.latest_closed_session()
    now = datetime.now(timezone.utc)
    execution_session = calendar.next_session(target)
    execution_open, _execution_close = calendar.session_window(execution_session)
    source_final = now >= publication_not_before(target)
    prospective = now < execution_open.astimezone(timezone.utc)
    eligible = source_final and prospective
    daily_attempted = False
    if eligible:
        phase = 'DAILY_CATCHUP'
        recovered = outage_recovery.catch_up(c, target_session=target)
        daily_attempted = True
        if recovered.mode == 'ALREADY_CURRENT':
            # Current publication is terminal success. Re-contacting mutable
            # vendor data adds source risk without proving a new condition.
            pass
        elif recovered.mode == 'RETAINED_FULL_RESEED':
            print(RECOVERY_MARKER + json.dumps({
                'mode': recovered.mode,
                'trigger': recovered.recovered_from,
            }, sort_keys=True), flush=True)
    phase = 'PUBLICATION_CHECK'
    after = publication.current(c)
    visible = store.latest_visible_session(c)
    current = (
        after is not None and after.window_end is not None
        and after.window_end >= target and visible == target
        and publication.chain_gaps(c) == [])
    print(SUCCESS_MARKER + json.dumps({
        'schema_migrated': True,
        'source_not_before_satisfied': source_final,
        'following_open_future': prospective,
        'bounded_sharadar_daily': daily_attempted,
        'publication_current': current,
    }, sort_keys=True), flush=True)
except BaseException as exc:
    if c is not None:
        try:
            c.rollback()
        except BaseException:
            pass
    emit_failure(phase, exc)
    raise
finally:
    if c is not None:
        c.close()
'''.strip()

# Install before saving the original probe reference so the core probe uses the
# recovery-aware code string while retaining its existing evidence schema.
go._PREPARATION_CODE = _RECOVERY_PREPARATION_CODE
_CORE_PREPARATION_PROBE = go.probe_prevalidation_preparation
_FEED_ENV_KEYS = (
    "SENTINEL_GIT_COMMIT",
    "SENTINEL_RUNTIME_IMAGE_DIGEST",
    "SENTINEL_FEED_AUTHORIZED",
    "SENTINEL_FEED_GIT_COMMIT",
    "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST",
)
_DIAGNOSTIC_PREFIXES = (
    "SENTINEL_GO_PREPARATION_RECOVERY=",
    "SENTINEL_GO_PREPARATION_FAILURE=",
)
_PREPARATION_FAILURE_PREFIX = "SENTINEL_GO_PREPARATION_FAILURE="
# Process-local capability. It is deliberately not an environment variable and
# is set only by sentinel_go_verified_entry after that entry proves the inherited
# kernel flock. Importing this module or manually acquiring the lock is therefore
# insufficient to reach financial mutation.
_VERIFIED_ORCHESTRATION = False


def authorize_verified_orchestration() -> None:
    global _VERIFIED_ORCHESTRATION
    if not go_lock.lifecycle_lock_is_held():
        raise RuntimeError("verified GO orchestration requires the held lifecycle lock")
    _VERIFIED_ORCHESTRATION = True


def _is_preparation_command(argv: Sequence[str]) -> bool:
    command = [str(item) for item in argv]
    return bool(
        command[:2] == ["docker", "compose"]
        and "--entrypoint" in command
        and "-c" in command
        and command[-1] == go._PREPARATION_CODE)


def _binding_or_none(
        runner: go.CommandRunner, *, env: Mapping[str, str], cwd: Path,
        runtime_ref: str, commit: str) -> Optional[tuple[str, str]]:
    """Ask the existing host feed gate for the binding; never mint it locally."""
    binding_env = go._without_broker_authority(env)
    binding_env["SENTINEL_GIT_COMMIT"] = str(commit)
    binding_env["SENTINEL_RUNTIME_IMAGE_DIGEST"] = str(runtime_ref)
    completed = runner.run([
        sys.executable, "scripts/sentinel_feed_gate.py", "bind",
        "--repo", str(go.ROOT), "--image", str(runtime_ref),
    ], env=binding_env, cwd=cwd)
    if completed.returncode != 0:
        return None
    lines = [line.strip() for line in (completed.stdout or "").splitlines()
             if line.strip()]
    if len(lines) != 2:
        return None
    bound_commit, bound_digest = lines
    if (go._HEX40.fullmatch(bound_commit) is None
            or go._IMAGE_DIGEST.fullmatch(bound_digest) is None
            or bound_commit != str(commit)
            or bound_digest != str(runtime_ref)):
        return None
    return bound_commit, bound_digest


def _preparation_refusal_completed(
        command: Sequence[str], *, phase: str, reason_code: str,
        error_type: str) -> subprocess.CompletedProcess:
    payload = {
        "phase": str(phase),
        "reason_code": str(reason_code),
        "error_type": str(error_type),
    }
    marker = _PREPARATION_FAILURE_PREFIX + json.dumps(payload, sort_keys=True)
    return subprocess.CompletedProcess(
        [str(item) for item in command], 2, stdout="", stderr=marker + "\n")


def _emit_sanitized_preparation_diagnostics(completed) -> None:
    for stream in (completed.stdout or "", completed.stderr or ""):
        for line in stream.splitlines():
            text = line.strip()
            if any(text.startswith(prefix) for prefix in _DIAGNOSTIC_PREFIXES):
                print(text, file=sys.stderr, flush=True)


def _retain_preparation_diagnostics(runner, completed) -> None:
    if not hasattr(runner, "last_preparation_output"):
        return
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    current = str(getattr(runner, "last_preparation_output") or "")
    setattr(runner, "last_preparation_output", current + "\n" + text)


def _lifecycle_refusal(runtime_ref: Optional[str], *, reason: str = "GO_LIFECYCLE_LOCK_NOT_PROVEN_NO_MUTATION"):
    evidence = {
        "reason": reason,
        "mutation_attempted": False,
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


class FeedBoundPreparationRunner:
    """Delegate every command except the one mutating preparation subprocess."""

    def __init__(self, runner: go.CommandRunner, *, runtime_ref: str,
                 commit: str):
        self._runner = runner
        self._runtime_ref = str(runtime_ref)
        self._commit = str(commit)

    def run(self, argv: Sequence[str], *, env=None, cwd: Path = go.ROOT):
        command = [str(item) for item in argv]
        if not _is_preparation_command(command):
            return self._runner.run(command, env=env, cwd=cwd)

        run_env = go._without_broker_authority(dict(env or {}))
        binding = _binding_or_none(
            self._runner, env=run_env, cwd=cwd,
            runtime_ref=self._runtime_ref, commit=self._commit)
        if binding is None:
            completed = _preparation_refusal_completed(
                command, phase="FEED_BINDING",
                reason_code="FEED_BINDING_UNAVAILABLE",
                error_type="FeedBindingUnavailable")
            _retain_preparation_diagnostics(self._runner, completed)
            _emit_sanitized_preparation_diagnostics(completed)
            return completed

        bound_commit, bound_digest = binding
        run_env.pop("SENTINEL_FEED_SERVICE_MODE", None)
        run_env.update({
            "SENTINEL_GIT_COMMIT": bound_commit,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": bound_digest,
            "SENTINEL_FEED_AUTHORIZED": "CLEAN_HEAD_IMAGE_V1",
            "SENTINEL_FEED_GIT_COMMIT": bound_commit,
            "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": bound_digest,
        })

        try:
            insertion = command.index("--entrypoint")
        except ValueError:
            completed = _preparation_refusal_completed(
                command, phase="COMMAND_CONTRACT",
                reason_code="PREPARATION_COMMAND_CONTRACT_INVALID",
                error_type="PreparationCommandContractInvalid")
            _retain_preparation_diagnostics(self._runner, completed)
            _emit_sanitized_preparation_diagnostics(completed)
            return completed
        forwarded = [
            item for key in _FEED_ENV_KEYS for item in ("--env", key)
        ]
        command[insertion:insertion] = forwarded
        completed = self._runner.run(command, env=run_env, cwd=cwd)
        _emit_sanitized_preparation_diagnostics(completed)
        return completed


def probe_prevalidation_preparation(
        runner: go.CommandRunner, *, env: Mapping[str, str],
        runtime_ref: Optional[str], commit: Optional[str], **kwargs):
    """Run one preparation only inside the verified serialized GO lifecycle."""
    if not _VERIFIED_ORCHESTRATION:
        return _lifecycle_refusal(
            runtime_ref, reason="GO_VERIFIED_ORCHESTRATION_NOT_PROVEN_NO_MUTATION")
    if not go_lock.lifecycle_lock_is_held(env):
        return _lifecycle_refusal(runtime_ref)
    if (runtime_ref is None or commit is None
            or go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is None
            or go._HEX40.fullmatch(str(commit)) is None):
        return _lifecycle_refusal(
            runtime_ref, reason="GO_CERTIFIED_IDENTITY_INVALID_NO_MUTATION")
    bound_runner = FeedBoundPreparationRunner(
        runner, runtime_ref=str(runtime_ref), commit=str(commit))
    return _CORE_PREPARATION_PROBE(
        bound_runner, env=env, runtime_ref=runtime_ref, commit=commit, **kwargs)


def install() -> None:
    go._PREPARATION_CODE = _RECOVERY_PREPARATION_CODE
    go.probe_prevalidation_preparation = probe_prevalidation_preparation


def main(argv=None) -> int:
    # The legacy direct producer bypasses the phased certification/preparation
    # ordering even if it happens to be launched under a lock. Keep the module
    # importable, but refuse it as an operator entrypoint.
    print(
        "REFUSED: sentinel_go_validate_entry.py is internal; use scripts/sentinel-go-validate.sh",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
