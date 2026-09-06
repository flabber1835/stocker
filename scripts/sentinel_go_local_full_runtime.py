#!/usr/bin/env python3
"""Explicit one-runtime local software certification for NAS GO."""
from __future__ import annotations

import json
from typing import Optional

import sentinel_go_validate as go


def certify_local_full(runner: go.CommandRunner, *, commit: Optional[str],
                       now_text: str):
    if commit is None:
        summary = go.TestSummary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.NOT_PROVEN, now_text,
            {"reason": "GIT_COMMIT_UNAVAILABLE"})

    runtime_ref = "sentinel-go-runtime:%s" % commit
    test_ref = "sentinel-go-test:%s" % commit
    commands = (
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", runtime_ref,
         "-f", "Dockerfile.sentinel", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SENTINEL_IMAGE=" + runtime_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", test_ref,
         "-f", "Dockerfile.sentinel-test", "."],
    )
    for command in commands:
        if runner.run(command).returncode != 0:
            summary = go.TestSummary(None, None, None)
            return summary, go.make_gate(
                "certified_suite_no_skips", go.FAIL, now_text,
                {"reason": "CANDIDATE_IMAGE_BUILD_FAILED"})

    runtime_digest = go._inspect_image_id(runner, runtime_ref)
    candidate_digest = go._inspect_image_id(runner, test_ref)
    if not runtime_digest or not candidate_digest:
        summary = go.TestSummary(
            candidate_image_digest=candidate_digest,
            runtime_image_digest=runtime_digest,
            source_identity_sha256=None,
        )
        return summary, go.make_gate(
            "certified_suite_no_skips", go.FAIL, now_text,
            {"reason": "CANDIDATE_IMAGE_IDENTITY_UNAVAILABLE"})

    identity = runner.run([
        "docker", "run", "--rm", "--network", "none",
        "--entrypoint", "python", runtime_digest,
        "-m", "sentinel", "identity", "--require-environment-compatible"])
    identity_hash = None
    if identity.returncode == 0:
        try:
            payload = json.loads(identity.stdout or "")
            candidate = str(payload.get("identity_hash") or "")
            if go._HEX64.fullmatch(candidate):
                identity_hash = candidate
        except (AttributeError, json.JSONDecodeError):
            identity_hash = None

    suite_commands = (
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/sentinel", "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/wealth_core",
         *(item for node in go.NON_FORWARD_HISTORICAL_EXCLUSIONS
           for item in ("--deselect", node)),
         "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/scripts/test_sentinel_go_validate.py",
         "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
         "-q", "-ra"],
    )
    aggregate = {
        "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
        "xfailed": 0, "xpassed": 0,
    }
    combined_exit = 0
    suites_completed = 0
    for command in suite_commands:
        suite = runner.run(command)
        counts = go._parse_pytest_summary(
            (suite.stdout or "") + "\n" + (suite.stderr or ""))
        for key in aggregate:
            aggregate[key] += counts[key]
        if suite.returncode != 0:
            combined_exit = int(suite.returncode) or 1
        if counts["passed"] > 0:
            suites_completed += 1

    summary = go.TestSummary(
        candidate_image_digest=candidate_digest,
        runtime_image_digest=runtime_digest,
        source_identity_sha256=identity_hash,
        exit_code=combined_exit,
        suites_completed=suites_completed,
        auxiliary_image_digests=(),
        non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS,
        **aggregate,
    )
    return summary, go.make_gate(
        "certified_suite_no_skips", go.PASS if summary.complete else go.FAIL,
        now_text,
        {"local_full_certification": True,
         "passed": summary.passed,
         "failed": summary.failed,
         "errors": summary.errors,
         "skipped": summary.skipped,
         "xfailed": summary.xfailed,
         "xpassed": summary.xpassed,
         "exit_code": summary.exit_code,
         "suites_completed": summary.suites_completed,
         "runtime_known": runtime_digest is not None,
         "test_lens_known": candidate_digest is not None,
         "identity_known": identity_hash is not None})
