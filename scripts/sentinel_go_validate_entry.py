#!/usr/bin/env python3
"""Production entrypoint for NAS GO validation.

The core validator executes its bounded preparation as a custom ``python -c``
Compose command.  That code calls ``ingest.daily()`` and therefore mutates the
corpus, but it is not syntactically the supported ``feed-daily`` CLI command
that ``sentinel-compose.sh`` can classify and bind automatically.

This entrypoint leaves the core validator unchanged and wraps only that one
subprocess boundary.  Immediately before the preparation container starts, it
reuses ``sentinel_feed_gate.py bind`` to prove clean HEAD == candidate image
revision, then forwards exactly the five per-invocation identity variables used
by the normal feed wrapper.  The runtime mutation guard remains unchanged.
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


_CORE_PREPARATION_PROBE = go.probe_prevalidation_preparation
_FEED_ENV_KEYS = (
    "SENTINEL_GIT_COMMIT",
    "SENTINEL_RUNTIME_IMAGE_DIGEST",
    "SENTINEL_FEED_AUTHORIZED",
    "SENTINEL_FEED_GIT_COMMIT",
    "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST",
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
    # These two values are consistency claims only. The feed gate independently
    # reads clean HEAD, the image revision label, and the immutable Docker id.
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
            # The core probe will record a failed preparation, while no mutation
            # container has been started. Raw gate diagnostics remain private.
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

        # Compose services intentionally carry no standing feed authority. Add
        # these names only to this already host-authorized `compose run`, exactly
        # as sentinel-compose.sh does for supported feed mutations.
        try:
            insertion = command.index("--entrypoint")
        except ValueError:
            return subprocess.CompletedProcess(
                command, 2, stdout="", stderr="")
        forwarded = [
            item for key in _FEED_ENV_KEYS for item in ("--env", key)
        ]
        command[insertion:insertion] = forwarded
        return self._runner.run(command, env=run_env, cwd=cwd)


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
    go.probe_prevalidation_preparation = probe_prevalidation_preparation


def main(argv=None) -> int:
    install()
    return go.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
