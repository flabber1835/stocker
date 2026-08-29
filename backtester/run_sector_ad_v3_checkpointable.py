#!/usr/bin/env python3
"""Checkpoint-capable A/D v3 causal replay launcher.

This composes the exact v3 terminal/split research overlays with the generic
checkpoint engine. Segment jobs use the same pinned strategy commit and the same
research commit. A segment that stops at a checkpoint emits no headline metrics;
only the final resumed segment emits the ordinary v3 certified result bundle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from backtester import checkpoint_runner
from backtester import run_sector_ad_causal_terminal_splits_v3 as v3


runner = v3.runner
v2 = v3.v2


def _arg_value(flag: str):
    args = sys.argv[1:]
    for i, value in enumerate(args):
        if value == flag and i + 1 < len(args):
            return args[i + 1]
        prefix = flag + "="
        if value.startswith(prefix):
            return value[len(prefix):]
    return None


def _strip_option(flag: str) -> None:
    out = [sys.argv[0]]
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        value = args[i]
        if value == flag:
            if i + 1 >= len(args):
                raise RuntimeError(f"{flag} requires a value")
            i += 2
            continue
        if value.startswith(flag + "="):
            i += 1
            continue
        out.append(value)
        i += 1
    sys.argv[:] = out


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _checkpoint_payload(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = raw.get("payload")
    return payload if isinstance(payload, dict) else {}


resume_text = _arg_value("--resume-checkpoint")
expected_resume_sha = _arg_value("--resume-checkpoint-sha256")
if expected_resume_sha is not None:
    if resume_text is None:
        raise RuntimeError("--resume-checkpoint-sha256 requires --resume-checkpoint")
    resume_path = Path(resume_text).resolve()
    observed = _sha(resume_path)
    if observed != expected_resume_sha:
        raise RuntimeError(
            f"resume checkpoint SHA256 mismatch: {observed} != {expected_resume_sha}")
    _strip_option("--resume-checkpoint-sha256")

# The v2 provenance wrapper keeps one small historical witness outside the
# production SessionState. Persist it in the checkpoint's extra-identity block.
# On resume it is seeded before the generic contract validator compares that
# block; the checkpoint itself is subsequently payload-hash and file-hash checked.
if resume_text is not None:
    payload = _checkpoint_payload(Path(resume_text).resolve())
    extra = payload.get("extra_identity") or {}
    v2._boundary_witness = extra.get("terminal_boundary_witness")


def _extra_identity() -> dict:
    return {
        "terminal_terms_json_sha256": _sha(v2.TERMS_PATH),
        "terminal_terms_checksum_sha256": _sha(v2.TERMS_CHECKSUM_PATH),
        "split_overrides_json_sha256": _sha(v3.SPLIT_DATA),
        "split_overrides_checksum_sha256": _sha(v3.SPLIT_SUMS),
        "terminal_boundary_witness": v2._boundary_witness,
    }


def _on_resume(payload, accounts) -> None:
    v2._progress_sessions = int(payload["expected_pointer"])
    v2._account_refs.clear()
    v2._account_refs.update(accounts)


runner.CHECKPOINT_EXTRA_IDENTITY = _extra_identity
runner.CHECKPOINT_ON_RESUME = _on_resume


def main() -> int:
    global runner
    stopped = _arg_value("--stop-after-session") is not None
    try:
        rc = int(checkpoint_runner.run(runner))
        if rc != 0 or stopped:
            return rc
        v2._postprocess_ad_bundle()
        v2._postprocess_provenance()
        v3._augment_split_provenance()
        print(
            "[PASS] checkpoint-capable A/D v3 causal terminal + split replay completed",
            flush=True,
        )
        return 0
    finally:
        if v3._real_split_decide is not None:
            v3.split_module.SplitStreamReconciler.decide = v3._real_split_decide
            v3._real_split_decide = None


if __name__ == "__main__":
    raise SystemExit(main())
