#!/usr/bin/env python3
"""Run bounded GO data preparation before the expensive certification suite."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402
import sentinel_go_validate_entry as entry  # noqa: E402


def _build_runtime(runner: go.CommandRunner, commit: str) -> str | None:
    reference = "sentinel-go-runtime:%s" % commit
    completed = runner.run([
        "docker", "build", "--network", "host", "--build-arg",
        "SOURCE_GIT_SHA=" + commit, "-t", reference,
        "-f", "Dockerfile.sentinel", ".",
    ])
    if completed.returncode != 0:
        return None
    return go._inspect_image_id(runner, reference)


def main() -> int:
    runner = go.CommandRunner()
    env = go.merged_environment()
    now_text = go._utc_text(datetime.now(timezone.utc))

    git, gate = go.probe_git(runner, now_text=now_text)
    if gate.status != go.PASS or git.commit is None:
        print(
            "REFUSED: GO data preflight requires clean current main equal to origin/main",
            file=sys.stderr,
        )
        return 2

    print(
        "GO data preflight: building/checking exact current runtime before full certification...",
        flush=True,
    )
    runtime_digest = _build_runtime(runner, git.commit)
    if runtime_digest is None:
        print("REFUSED: GO data preflight runtime build failed", file=sys.stderr)
        return 2

    entry.install()
    preparation = entry.probe_prevalidation_preparation(
        runner,
        env=env,
        runtime_ref=runtime_digest,
        commit=git.commit,
    )
    if preparation.status != go.PASS:
        print(
            "REFUSED: GO data preflight failed; expensive certification was not started",
            file=sys.stderr,
        )
        return 2

    print(
        "GO data preflight: PASS - volatile data/session preparation is ready; starting full certification",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
