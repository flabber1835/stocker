#!/usr/bin/env python3
"""Promote exactly the runtime proven by this GO invocation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_ci_runtime as ci_runtime  # noqa: E402
import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_phase_entry as phase  # noqa: E402
import sentinel_runtime_selection as runtime  # noqa: E402


def _sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _certified_local_runtime(commit: str) -> str:
    try:
        payload = json.loads(phase.ORDINARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise runtime.RuntimeSelectionRefused(
            "local-full runtime certification binding is unavailable") from exc
    if not isinstance(payload, dict) or payload.get("schema") != phase.ORDINARY_SCHEMA:
        raise runtime.RuntimeSelectionRefused(
            "local-full runtime certification binding schema is invalid")
    supplied = str(payload.get("evidence_sha256") or "")
    evidence = {k: v for k, v in payload.items() if k != "evidence_sha256"}
    if supplied != _sha(evidence) or payload.get("git_commit") != commit:
        raise runtime.RuntimeSelectionRefused(
            "local-full runtime certification binding does not match current commit")
    digest = str(payload.get("ordinary_runtime_image_digest") or "")
    if runtime._DIGEST.fullmatch(digest) is None:
        raise runtime.RuntimeSelectionRefused(
            "local-full runtime binding has no immutable image id")
    return digest


def _current_run_target_pass(commit: str) -> dict:
    token = go_lock.current_run_token()
    if token is None:
        raise runtime.RuntimeSelectionRefused(
            "runtime promotion has no current one-run lifecycle capability")
    try:
        payload = json.loads(go_lock.RUN_PASS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise runtime.RuntimeSelectionRefused(
            "this GO invocation has no successful requested-target proof") from exc
    expected_keys = {
        "schema", "git_commit", "requested_target", "run_token_sha256",
        "host_boot_id_sha256", "passed_at", "evidence_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof has an unexpected schema")
    if payload.get("schema") != go_lock.RUN_PASS_SCHEMA:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof schema is invalid")
    supplied = str(payload.get("evidence_sha256") or "")
    evidence = {k: v for k, v in payload.items() if k != "evidence_sha256"}
    if supplied != phase._sha(evidence):
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof integrity is invalid")
    if payload.get("git_commit") != commit:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof does not match current commit")
    if payload.get("requested_target") not in phase.controller.TARGETS:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof names an unsupported target")
    expected_token = hashlib.sha256(token.encode("ascii")).hexdigest()
    if payload.get("run_token_sha256") != expected_token:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof belongs to a different lifecycle invocation")
    boot = phase._boot_id_sha256()
    if boot is None or payload.get("host_boot_id_sha256") != boot:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof belongs to a different host boot")
    if phase._parse_utc(payload.get("passed_at")) is None:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof has invalid completion time")
    return payload


def _consume_run_pass() -> None:
    try:
        go_lock.RUN_PASS_PATH.unlink()
    except OSError as exc:
        raise runtime.RuntimeSelectionRefused(
            "requested-target GO proof could not be consumed after promotion") from exc


def _promote_local_full(*, head: str, runner) -> str:
    summary = phase._load_with_ordinary(runner, commit=head)
    if summary is None or not summary.complete:
        raise runtime.RuntimeSelectionRefused(
            "complete local-full certification evidence is unavailable at promotion")
    expected = _certified_local_runtime(head)
    candidate = "sentinel-go-runtime:%s" % head
    observed, revision = runtime._inspect(candidate)
    if revision != head or observed != expected:
        raise runtime.RuntimeSelectionRefused(
            "local-full runtime changed after certification")
    runtime._write_pointer(expected)
    return expected


def _promote_ci(*, head: str, runner) -> str:
    try:
        binding = ci_runtime.load_binding(
            commit=head, runner=runner, require_current_run=True)
        result = ci_runtime.verifier.verify_current(
            root=phase.controller.go.ROOT, commit=head)
    except (ci_runtime.CIRuntimeRefused,
            ci_runtime.verifier.CertificationVerificationRefused) as exc:
        raise runtime.RuntimeSelectionRefused(
            "CI-certified runtime could not be reverified at promotion") from exc

    certified_image = str(binding["certified_image"])
    if (result.get("certified_image") != certified_image
            or result.get("image_digest") != binding["registry_digest"]):
        raise runtime.RuntimeSelectionRefused(
            "promotion-time CI certificate differs from validation binding")
    observed, revision = runtime._inspect(certified_image)
    if revision != head or observed != binding["local_image_id"]:
        raise runtime.RuntimeSelectionRefused(
            "local CI-certified runtime changed after financial validation")
    runtime._write_pointer(certified_image)
    return certified_image


def main(argv=None) -> int:
    extra_args = list(argv if argv is not None else sys.argv[1:])
    if "--input" in extra_args or any(str(arg).startswith("--input=") for arg in extra_args):
        print("runtime promotion: SKIPPED for development-input validation", flush=True)
        return 0
    local_full = "--local-full-certification" in extra_args
    try:
        if not go_lock.lifecycle_lock_is_held():
            raise runtime.RuntimeSelectionRefused(
                "runtime promotion is available only inside the verified locked sentinel-go-validate lifecycle")
        runtime._refresh_origin_main()
        head = runtime._clean_main_head()
        run_pass = _current_run_target_pass(head)
        runner = phase.controller.DiagnosticRunner()
        selected = (
            _promote_local_full(head=head, runner=runner)
            if local_full else _promote_ci(head=head, runner=runner)
        )
        text = runtime.POINTER.read_text(encoding="ascii")
        if text != "SENTINEL_RUNTIME_IMAGE_REF=%s\n" % selected:
            raise runtime.RuntimeSelectionRefused(
                "validated runtime pointer verification failed")
        _consume_run_pass()
    except (OSError, runtime.RuntimeSelectionRefused) as exc:
        print("REFUSED: runtime promotion failed: %s" % exc, file=sys.stderr)
        return 2
    print(
        "runtime promotion: BOUND - requested %s GO selected %s from %s"
        % (run_pass["requested_target"],
           "local-full certified image" if local_full else "CI-certified registry digest",
           head[:12]),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
