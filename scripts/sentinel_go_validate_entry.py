#!/usr/bin/env python3
"""Production entrypoint for NAS GO validation.

The core validator executes its bounded preparation as a custom ``python -c``
Compose command. This entrypoint binds that mutation to clean HEAD + the exact
candidate image and installs the same retained-range outage recovery primitive
used by unattended runtime. Vendor/network/source-authority failures never
trigger a reseed by guess.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Mapping, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402


_RECOVERY_PREPARATION_CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel import backup_guard, schema
from sentinel.feed import calendar, ingest, outage_recovery, publication, store
from sentinel.shadow_runtime import publication_not_before

SUCCESS_MARKER = 'SENTINEL_GO_PREPARATION='
RECOVERY_MARKER = 'SENTINEL_GO_PREPARATION_RECOVERY='
FAILURE_MARKER = 'SENTINEL_GO_PREPARATION_FAILURE='


def emit_failure(phase, exc):
    print(FAILURE_MARKER + json.dumps({
        'phase': str(phase),
        'error_type': type(exc).__name__,
    }, sort_keys=True), flush=True)


c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
phase = 'SCHEMA_MIGRATION'
try:
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
            # Validation proves the explicit-through daily path itself even when
            # no catch-up was necessary. The common recovery helper did not
            # mutate in ALREADY_CURRENT mode, so this separate proof must apply
            # the same external-WAL durability fence before calling ingest.
            backup_guard.require_writes_permitted(
                c, operation='NAS validation explicit daily publication')
            ingest.daily(c, today=target)
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
    try:
        c.rollback()
    except BaseException:
        pass
    emit_failure(phase, exc)
    raise
finally:
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
    """Ask the existing host gate for the binding; never mint it locally."""
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


def _emit_sanitized_preparation_diagnostics(completed) -> None:
    for stream in (completed.stdout or "", completed.stderr or ""):
        for line in stream.splitlines():
            text = line.strip()
            if any(text.startswith(prefix) for prefix in _DIAGNOSTIC_PREFIXES):
                print(text, file=sys.stderr, flush=True)


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
            return subprocess.CompletedProcess(
                command, 2, stdout="", stderr="")

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
            return subprocess.CompletedProcess(
                command, 2, stdout="", stderr="")
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
    """Run the core probe with feed binding enforced at its mutation boundary."""
    if (runtime_ref is None or commit is None
            or go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is None
            or go._HEX40.fullmatch(str(commit)) is None):
        return _CORE_PREPARATION_PROBE(
            runner, env=env, runtime_ref=runtime_ref, commit=commit, **kwargs)
    bound_runner = FeedBoundPreparationRunner(
        runner, runtime_ref=str(runtime_ref), commit=str(commit))
    return _CORE_PREPARATION_PROBE(
        bound_runner, env=env, runtime_ref=runtime_ref, commit=commit, **kwargs)


def install() -> None:
    go._PREPARATION_CODE = _RECOVERY_PREPARATION_CODE
    go.probe_prevalidation_preparation = probe_prevalidation_preparation


def main(argv=None) -> int:
    install()
    return go.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
