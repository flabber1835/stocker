#!/usr/bin/env python3
"""Cheap non-authoritative Sharadar source-final hint for Sentinel bring-up.

This probe deliberately uses only the previously validated ordinary runtime and
runs with Docker networking disabled. It may stop bring-up when that retained
runtime says the latest closed session is not yet past the reviewed Sharadar
publication not-before. A READY result is only a liveness hint: the current
commit must still build its exact runtime and repeat the authoritative source
checks before any data recovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_runtime_selection as selection  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MARKER = "SENTINEL_BRINGUP_SOURCE_HINT="

_HINT_CODE = r'''
from datetime import datetime, timezone
import json
from sentinel.feed import calendar
from sentinel.shadow_runtime import publication_not_before

now = datetime.now(timezone.utc)
target = calendar.latest_closed_session()
not_before = publication_not_before(target)
status = 'READY' if now >= not_before else 'DEFERRED'
print('SENTINEL_BRINGUP_SOURCE_HINT=' + json.dumps({
    'status': status,
    'reason_code': ('SOURCE_FINAL_HINT_READY'
                    if status == 'READY' else 'SHARADAR_SOURCE_NOT_FINAL'),
    'target_session': target,
    'not_before_utc': not_before.isoformat(),
}, sort_keys=True), flush=True)
'''.strip()


def _payload(stdout: str) -> Optional[dict]:
    matches = []
    for line in (stdout or "").splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            value = json.loads(line[len(MARKER):])
        except ValueError:
            return None
        if isinstance(value, dict):
            matches.append(value)
    return matches[0] if len(matches) == 1 else None


def main() -> int:
    try:
        digest = selection._pointer_digest()
        if digest is None:
            print(
                "source-final hint: UNAVAILABLE - no prior validated runtime; "
                "continuing to exact preflight",
                flush=True,
            )
            return 0
        # Require the pointer to resolve to one locally inspectable immutable image.
        inspected, revision = selection._inspect(digest)
        if inspected != digest:
            print(
                "source-final hint: UNAVAILABLE - retained runtime identity changed; "
                "continuing to exact preflight",
                flush=True,
            )
            return 0
        completed = subprocess.run(
            [
                "docker", "run", "--rm", "--network", "none",
                "--entrypoint", "python", digest, "-c", _HINT_CODE,
            ],
            cwd=str(ROOT), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        report = _payload(completed.stdout or "")
        if completed.returncode != 0 or report is None:
            print(
                "source-final hint: UNAVAILABLE - retained runtime probe failed; "
                "continuing to exact preflight",
                flush=True,
            )
            return 0
        status = str(report.get("status") or "")
        reason = str(report.get("reason_code") or "SOURCE_FINAL_HINT_UNKNOWN")
        if status == "DEFERRED":
            print("BRINGUP_BLOCKED - %s" % reason, flush=True)
            return 3
        if status == "READY":
            print(
                "source-final hint: READY - retained runtime %s; "
                "current commit will now perform exact source checks"
                % revision[:12],
                flush=True,
            )
            return 0
        print(
            "source-final hint: UNAVAILABLE - unknown retained-runtime result; "
            "continuing to exact preflight",
            flush=True,
        )
        return 0
    except Exception:
        # This is only an optimization. Its inability to prove a negative must
        # never replace the authoritative current-commit checks.
        print(
            "source-final hint: UNAVAILABLE - continuing to exact preflight",
            flush=True,
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
