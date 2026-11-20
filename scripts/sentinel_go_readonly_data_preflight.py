#!/usr/bin/env python3
"""Inspect the installed rolling publication in a read-only database transaction."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Mapping, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_bringup_source_liveness as frontier_probe
import sentinel_go_probe_contract as probe_contract  # noqa: E402
import sentinel_go_validate as go  # noqa: E402
import sentinel_probe_output as probe_output  # noqa: E402

MARKER = "SENTINEL_GO_READONLY_DATA_PREFLIGHT="

_READ_ONLY_CODE = frontier_probe._CODE.replace(frontier_probe.MARKER, MARKER)


class PreflightRefused(RuntimeError):
    pass


def _safe_detail(value: object) -> Optional[str]:
    return probe_output.safe_detail(value)


def _payload(completed) -> Optional[Mapping[str, object]]:
    return probe_output.payload(completed, marker=MARKER)


def _build_exact_ordinary(runner: go.CommandRunner, commit: str) -> str:
    ref = "sentinel-go-runtime:%s" % commit
    built = runner.run([
        "docker", "build", "--network", "host", "--build-arg",
        "SOURCE_GIT_SHA=" + commit, "-t", ref,
        "-f", "Dockerfile.sentinel", ".",
    ])
    if built.returncode != 0:
        evidence = probe_contract.subprocess_evidence(
            built, context="READONLY_RUNTIME_BUILD")
        probe_contract.emit_probe_failure(evidence)
        raise PreflightRefused(
            "exact ordinary Sentinel image build failed (%s)" % evidence["reason"])
    digest = go._inspect_image_id(runner, ref)
    if digest is None or go._IMAGE_DIGEST.fullmatch(str(digest)) is None:
        raise PreflightRefused("exact ordinary Sentinel image identity is unavailable")
    return str(digest)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _ = list(argv if argv is not None else sys.argv[1:])
    runner = go.CommandRunner()
    env = go.merged_environment()
    now_text = go._utc_text(datetime.now(timezone.utc))
    try:
        git, gate = go.probe_git(runner, now_text=now_text)
        if gate.status != go.PASS or git.commit is None:
            raise PreflightRefused(
                "read-only data preflight requires clean current main equal to origin/main")
        if not str(env.get("SENTINEL_POSTGRES_PASSWORD") or "").strip():
            raise PreflightRefused("Sentinel database authority is unavailable")

        run_env = go._without_broker_authority(env)
        compose_args = go._resolve_compose_args(runner, run_env)
        if compose_args is None:
            raise PreflightRefused("Sentinel Compose graph is unavailable")
        database_failure = probe_contract.ensure_postgres_ready(
            runner, env=run_env, compose_args=compose_args)
        if database_failure is not None:
            raise PreflightRefused(
                "Sentinel PostgreSQL is unavailable (%s)"
                % database_failure["reason"])

        runtime = _build_exact_ordinary(runner, git.commit)
        run_env["SENTINEL_RUNTIME_IMAGE_REF"] = runtime
        completed = runner.run([
            "docker", "compose", *compose_args, "--profile", "cli", "run",
            "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
            "-c", _READ_ONLY_CODE,
        ], env=run_env)
        report = _payload(completed)
        if completed.returncode != 0 or report is None:
            evidence = (probe_contract.subprocess_evidence(
                completed, context="READONLY_PREFLIGHT")
                if completed.returncode != 0
                else probe_contract.malformed_report_evidence(
                    completed, context="READONLY_PREFLIGHT"))
            probe_contract.emit_probe_failure(evidence)
            raise PreflightRefused(
                "read-only rolling publication diagnostic failed (%s)" % evidence["reason"])
        status = str(report.get("status") or "")
        code = str(report.get("reason_code") or "READONLY_PREFLIGHT_UNAVAILABLE")
        detail = _safe_detail(report.get("detail"))
        if status == "REFUSED":
            text = "REFUSED: read-only rolling publication preflight %s" % code
            if detail:
                text += " - " + detail
            if report.get("detail_sha256"):
                text += " [detail_sha256=%s]" % str(report["detail_sha256"])
            print(text, file=sys.stderr)
            return 2
        if status == "PASS" and code == "ROLLING_PUBLICATION_CURRENT":
            print("read-only rolling publication preflight: PASS - %s" % code, flush=True)
            return 0
        if status == "RECOVERY_REQUIRED" and code in {
                "CORPUS_SCHEMA_NOT_INSTALLED", "ROLLING_PUBLICATION_REQUIRED", "ROLLING_PUBLICATION_BEHIND"}:
            text = (
                "read-only rolling publication preflight: RECOVERY_REQUIRED - %s; certified recovery will decide the write path"
                % code)
            if detail:
                text += " - " + detail
            if report.get("detail_sha256"):
                text += " [detail_sha256=%s]" % str(report["detail_sha256"])
            print(text, flush=True)
            return 0
        raise PreflightRefused("read-only rolling publication diagnostic returned unknown state")
    except PreflightRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
