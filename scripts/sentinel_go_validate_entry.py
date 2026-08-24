#!/usr/bin/env python3
"""Production entrypoint for NAS GO validation.

The core validator intentionally executes its bounded preparation as a custom
Python command so it can prove schema, source-final, publication and timing
facts in one subprocess.  That command is still a corpus mutation and therefore
must cross the same clean-HEAD/image binding membrane as ``feed-daily``.

This entrypoint installs the production preparation probe that obtains that
binding from ``sentinel_feed_gate.py`` and forwards only the five certified feed
identity variables into the one Compose run.  Broker authority is removed before
both the host binding and container invocation.  The mutation guard itself is
not weakened or bypassed.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Mapping, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402


_FEED_ENV_KEYS = (
    "SENTINEL_GIT_COMMIT",
    "SENTINEL_RUNTIME_IMAGE_DIGEST",
    "SENTINEL_FEED_AUTHORIZED",
    "SENTINEL_FEED_GIT_COMMIT",
    "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST",
)


def _clean_head_feed_binding(
        runner: go.CommandRunner, *, run_env: Mapping[str, str],
        runtime_ref: str, commit: str) -> Optional[tuple[str, str]]:
    """Re-use the host feed gate; never mint feed authority in the validator."""
    binding_env = dict(run_env)
    # These are consistency claims only. sentinel_feed_gate independently reads
    # clean HEAD, the image revision label and the immutable Docker image id.
    binding_env["SENTINEL_GIT_COMMIT"] = str(commit)
    binding_env["SENTINEL_RUNTIME_IMAGE_DIGEST"] = str(runtime_ref)
    completed = runner.run([
        sys.executable, "scripts/sentinel_feed_gate.py", "bind",
        "--repo", str(go.ROOT), "--image", str(runtime_ref),
    ], env=binding_env)
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


def probe_prevalidation_preparation(
        runner: go.CommandRunner, *, env: Mapping[str, str],
        runtime_ref: Optional[str], commit: Optional[str],
        monotonic: Callable[[], float] = time.monotonic) -> go.PreparationSummary:
    """Prepare schema + Sharadar tail under the certified feed mutation gate."""
    prerequisites = (
        bool(str(env.get("SHARADAR_API_KEY") or "").strip())
        and bool(env.get("SENTINEL_POSTGRES_PASSWORD"))
        and commit is not None
        and go._HEX40.fullmatch(str(commit)) is not None
        and runtime_ref is not None
        and go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None)
    if not prerequisites:
        evidence = {
            "reason": "PREPARATION_AUTHORITY_UNAVAILABLE",
            "runtime_known": runtime_ref is not None,
        }
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest(evidence))

    run_env = go._without_broker_authority(env)
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest({
                "reason": "PREPARATION_COMPOSE_GRAPH_UNAVAILABLE"}))

    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    binding = _clean_head_feed_binding(
        runner, run_env=run_env, runtime_ref=str(runtime_ref),
        commit=str(commit))
    if binding is None:
        return go.PreparationSummary(
            status=go.NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=go._evidence_digest({
                "reason": "PREPARATION_CLEAN_HEAD_FEED_BINDING_UNAVAILABLE",
                "runtime_known": runtime_ref is not None,
            }))

    bound_commit, bound_digest = binding
    run_env.update({
        "SENTINEL_GIT_COMMIT": bound_commit,
        "SENTINEL_RUNTIME_IMAGE_DIGEST": bound_digest,
        "SENTINEL_FEED_AUTHORIZED": "CLEAN_HEAD_IMAGE_V1",
        "SENTINEL_FEED_GIT_COMMIT": bound_commit,
        "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": bound_digest,
    })

    started = monotonic()
    completed = runner.run([
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps",
        *(item for key in _FEED_ENV_KEYS for item in ("--env", key)),
        "--entrypoint", "python", "sentinel", "-c", go._PREPARATION_CODE,
    ], env=run_env)
    elapsed_milliseconds = max(
        0, int(math.ceil((monotonic() - started) * 1000.0)))

    marker = "SENTINEL_GO_PREPARATION="
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None

    valid = (
        isinstance(payload, dict)
        and set(payload) == {
            "schema_migrated", "source_not_before_satisfied",
            "following_open_future", "bounded_sharadar_daily",
            "publication_current"}
        and all(payload.get(field) is True for field in payload))
    evidence = {
        "exit_code": int(completed.returncode),
        "schema_migrated": bool(
            isinstance(payload, dict) and payload.get("schema_migrated") is True),
        "bounded_sharadar_daily": bool(
            isinstance(payload, dict)
            and payload.get("bounded_sharadar_daily") is True),
        "source_not_before_satisfied": bool(
            isinstance(payload, dict)
            and payload.get("source_not_before_satisfied") is True),
        "following_open_future": bool(
            isinstance(payload, dict)
            and payload.get("following_open_future") is True),
        "publication_current": bool(
            isinstance(payload, dict)
            and payload.get("publication_current") is True),
        "clean_head_feed_binding": True,
        "feed_authority_forwarded": all(
            key in run_env for key in _FEED_ENV_KEYS),
        "broker_authority_removed": not bool(
            go._BROKER_AUTH_ENV.intersection(run_env)),
    }
    return go.PreparationSummary(
        status=go.PASS if valid else go.FAIL,
        runtime_image_digest=runtime_ref,
        schema_migration_attempted=bool(
            isinstance(payload, dict)
            and payload.get("schema_migrated") is True),
        bounded_sharadar_daily_attempted=bool(
            isinstance(payload, dict)
            and payload.get("bounded_sharadar_daily") is True),
        broker_mutation_attempts=0,
        evidence_sha256=go._evidence_digest(evidence),
        elapsed_milliseconds=elapsed_milliseconds)


def install() -> None:
    """Install the production preparation boundary before the probe graph runs."""
    go.probe_prevalidation_preparation = probe_prevalidation_preparation


def main(argv=None) -> int:
    install()
    return go.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
