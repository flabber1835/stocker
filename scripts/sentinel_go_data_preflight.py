#!/usr/bin/env python3
"""Run bounded GO data preparation before the expensive certification suite."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402
import sentinel_go_validate_entry as entry  # noqa: E402


class CapturingRunner(go.CommandRunner):
    """Keep the local traceback only long enough to extract a controlled reason."""

    def __init__(self):
        super().__init__()
        self.preparation_stderr = ""

    def run(self, argv, *, env=None, cwd=go.ROOT):
        completed = super().run(argv, env=env, cwd=cwd)
        combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if "SENTINEL_GO_PREPARATION_FAILURE=" in combined:
            self.preparation_stderr = completed.stderr or ""
        return completed


def _controlled_sharadar_reason(stderr: str) -> str | None:
    """Return only Sentinel-authored SharadarMutationRefused detail.

    The exception messages in maintenance_impl are controlled source/corpus
    diagnostics. Refuse to echo anything that looks like transport credentials,
    a URL, or a database DSN even if a future exception chain changes shape.
    """
    marker = "SharadarMutationRefused:"
    for raw in reversed((stderr or "").splitlines()):
        if marker not in raw:
            continue
        detail = raw.split(marker, 1)[1].strip()
        if not detail or len(detail) > 600:
            return None
        lowered = detail.lower()
        prohibited = (
            "http://", "https://", "api_key", "password", "authorization",
            "postgres://", "postgresql://", "apca-api-",
        )
        if any(item in lowered for item in prohibited):
            return None
        if re.search(r"[\r\n\x00]", detail):
            return None
        return detail
    return None


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
    runner = CapturingRunner()
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
        detail = _controlled_sharadar_reason(runner.preparation_stderr)
        if detail:
            print("GO data preflight Sharadar refusal: %s" % detail, file=sys.stderr)
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
