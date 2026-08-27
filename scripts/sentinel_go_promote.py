#!/usr/bin/env python3
"""Promote exactly the ordinary runtime bound by successful GO certification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_phase_entry as phase  # noqa: E402
import sentinel_runtime_selection as runtime  # noqa: E402


def _sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _certified_ordinary(commit: str) -> str:
    try:
        payload = json.loads(phase.ORDINARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise runtime.RuntimeSelectionRefused(
            "ordinary-runtime certification binding is unavailable") from exc
    if not isinstance(payload, dict) or payload.get("schema") != phase.ORDINARY_SCHEMA:
        raise runtime.RuntimeSelectionRefused(
            "ordinary-runtime certification binding schema is invalid")
    supplied = str(payload.get("evidence_sha256") or "")
    evidence = {k: v for k, v in payload.items() if k != "evidence_sha256"}
    if supplied != _sha(evidence) or payload.get("git_commit") != commit:
        raise runtime.RuntimeSelectionRefused(
            "ordinary-runtime certification binding does not match current commit")
    digest = str(payload.get("ordinary_runtime_image_digest") or "")
    if runtime._DIGEST.fullmatch(digest) is None:
        raise runtime.RuntimeSelectionRefused(
            "ordinary-runtime certification binding has no immutable image id")
    return digest


def main(argv=None) -> int:
    extra_args = list(argv if argv is not None else sys.argv[1:])
    if "--input" in extra_args or any(str(arg).startswith("--input=") for arg in extra_args):
        print("runtime promotion: SKIPPED for development-input validation", flush=True)
        return 0
    try:
        if not go_lock.lifecycle_lock_is_held():
            raise runtime.RuntimeSelectionRefused(
                "runtime promotion is available only inside the verified locked sentinel-go-validate lifecycle")
        runtime._refresh_origin_main()
        head = runtime._clean_main_head()

        # Require the complete retained suite record and all exact image IDs,
        # not only the companion ordinary-runtime sidecar. This prevents a
        # hand-edited/stale sidecar from becoming runtime-selection authority.
        runner = phase.controller.DiagnosticRunner()
        summary = phase._load_with_ordinary(runner, commit=head)
        if summary is None or not summary.complete:
            raise runtime.RuntimeSelectionRefused(
                "complete exact certification evidence is unavailable at promotion")

        expected = _certified_ordinary(head)
        candidate = "sentinel-go-runtime:%s" % head
        observed, revision = runtime._inspect(candidate)
        if revision != head:
            raise runtime.RuntimeSelectionRefused(
                "ordinary candidate revision disagrees with current HEAD")
        if observed != expected:
            raise runtime.RuntimeSelectionRefused(
                "ordinary candidate image id changed after certification")
        runtime._write_pointer(expected)
        text = runtime.POINTER.read_text(encoding="ascii")
        if text != "SENTINEL_RUNTIME_IMAGE_REF=%s\n" % expected:
            raise runtime.RuntimeSelectionRefused(
                "validated runtime pointer verification failed")
    except (OSError, runtime.RuntimeSelectionRefused) as exc:
        print("REFUSED: runtime promotion failed: %s" % exc, file=sys.stderr)
        return 2
    print(
        "runtime promotion: BOUND - exact certified ordinary image %s from %s"
        % (expected[:19] + "...", head[:12]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
