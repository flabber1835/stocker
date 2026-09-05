#!/usr/bin/env python3
"""Fast non-authoritative Sentinel bootstrap diagnostics.

Bring-up is intentionally cheap and read-only with respect to financial data. It
checks host/runtime/database/backup prerequisites plus a bounded Sharadar liveness
probe, then hands full source validation, bounded data preparation, backup refresh,
and certification to ``scripts/sentinel-go-validate.sh``.

The legacy ``--recover`` flag remains accepted for operator compatibility but no
longer mutates the corpus. Recovery authority belongs exclusively to certified GO.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_bringup_source_liveness as liveness  # noqa: E402
import sentinel_go_backup_refresh as backup_refresh  # noqa: E402
import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_phase_controller as controller  # noqa: E402
import sentinel_go_probe_contract as probe_contract  # noqa: E402
import sentinel_go_validate as go  # noqa: E402
import sentinel_go_validate_entry as entry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
READY = "BRINGUP_READY_FOR_CERTIFICATION"
READY_CERTIFIED_BACKUP_REFRESH = "BRINGUP_READY_FOR_CERTIFIED_BACKUP_REFRESH"
BLOCKED = "BRINGUP_BLOCKED"


class BringupRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceDecision:
    proceed: bool
    status: str
    reason_code: str


@dataclass(frozen=True)
class BackupDecision:
    healthy: bool
    repairable: bool
    reason_code: str


def source_decision(report: Mapping[str, object]) -> SourceDecision:
    """Map the lightweight source report to a bring-up handoff action."""
    status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "BRINGUP_LIVENESS_UNAVAILABLE")
    if status in {"PASS", "RECOVERY_REQUIRED"}:
        return SourceDecision(True, status, reason)
    if status in {"DEFERRED", "REFUSED"}:
        return SourceDecision(False, status, reason)
    raise BringupRefused("source liveness probe returned an unknown state")


def backup_decision(completed: subprocess.CompletedProcess) -> BackupDecision:
    """Classify the read-only backup checkpoint using certified GO's contract."""
    if int(completed.returncode) == 0:
        return BackupDecision(True, False, "BACKUP_HEALTHY")
    repairable = backup_refresh._repairable_reason(completed)
    if repairable is not None:
        return BackupDecision(False, True, repairable)
    reason = backup_refresh._status_reason(completed)
    if reason is not None:
        return BackupDecision(False, False, reason)
    raise BringupRefused(
        "backup durability checkpoint returned an unclassified failure (exit %d)"
        % int(completed.returncode))


def _print_source_report(report: Mapping[str, object], *, prefix: str) -> None:
    decision = source_decision(report)
    detail = liveness.safe_detail(report.get("detail"))
    text = "%s: %s - %s" % (prefix, decision.status, decision.reason_code)
    if detail:
        text += " - " + detail
    if report.get("detail_sha256"):
        text += " [detail_sha256=%s]" % str(report["detail_sha256"])
    followup = report.get("local_followup")
    if isinstance(followup, list) and followup:
        text += " [local_followup=%s]" % ",".join(str(item) for item in followup)
    print(text, flush=True)


def _require_exact_main(runner: go.CommandRunner):
    now_text = go._utc_text(datetime.now(timezone.utc))
    git, gate = go.probe_git(runner, now_text=now_text)
    if gate.status != go.PASS or git.commit is None:
        raise BringupRefused(
            "bring-up requires clean current main exactly equal to origin/main")
    return git


def _require_environment(env: Mapping[str, str]) -> None:
    required = (
        "SHARADAR_API_KEY",
        "SENTINEL_POSTGRES_PASSWORD",
        "SENTINEL_BACKUP_DIR",
    )
    missing = [name for name in required if not str(env.get(name) or "").strip()]
    if missing:
        raise BringupRefused(
            "bring-up environment is missing required authority: %s"
            % ", ".join(missing))


def _compose_and_database_ready(runner: go.CommandRunner, env: Mapping[str, str]):
    run_env = go._without_broker_authority(dict(env))
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        raise BringupRefused("Sentinel Compose graph is unavailable")
    failure = probe_contract.ensure_postgres_ready(
        runner, env=run_env, compose_args=compose_args)
    if failure is not None:
        raise BringupRefused(
            "Sentinel PostgreSQL is unavailable (%s)" % failure["reason"])
    return run_env, compose_args


def _backup_checkpoint(env: Mapping[str, str]) -> Optional[str]:
    """Return a repairable reason or prove current backup durability."""
    completed = subprocess.run(
        ["bash", "scripts/sentinel-backup-status.sh"],
        cwd=str(ROOT), env=go._without_broker_authority(dict(env)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False)
    if completed.stdout:
        sys.stdout.write(completed.stdout)
        sys.stdout.flush()
    if completed.stderr:
        sys.stderr.write(completed.stderr)
        sys.stderr.flush()
    decision = backup_decision(completed)
    if decision.healthy:
        return None
    if decision.repairable:
        print(
            "bring-up backup: REPAIRABLE - %s" % decision.reason_code,
            flush=True,
        )
        return decision.reason_code
    raise BringupRefused(
        "%s - backup durability requires operator repair" % decision.reason_code)


def _build_exact_ordinary(runner: go.CommandRunner, commit: str) -> str:
    ref = "sentinel-go-runtime:%s" % commit
    built = runner.run([
        "docker", "build", "--network", "host", "--build-arg",
        "SOURCE_GIT_SHA=" + commit, "-t", ref,
        "-f", "Dockerfile.sentinel", ".",
    ])
    if built.returncode != 0:
        evidence = probe_contract.subprocess_evidence(
            built, context="BRINGUP_RUNTIME_BUILD")
        probe_contract.emit_probe_failure(evidence)
        raise BringupRefused(
            "exact ordinary Sentinel image build failed (%s)" % evidence["reason"])
    digest = go._inspect_image_id(runner, ref)
    if digest is None or go._IMAGE_DIGEST.fullmatch(str(digest)) is None:
        raise BringupRefused("exact ordinary Sentinel image identity is unavailable")
    return str(digest)


def _runtime_for_commit(
        runner: go.CommandRunner, *, env: Mapping[str, str], commit: str) -> str:
    """Reuse an already-proven exact runtime; rebuild only when unavailable."""
    ref = "sentinel-go-runtime:%s" % commit
    digest = go._inspect_image_id(runner, ref)
    if digest is not None and go._IMAGE_DIGEST.fullmatch(str(digest)) is not None:
        binding = entry._binding_or_none(
            runner,
            env=go._without_broker_authority(dict(env)),
            cwd=ROOT,
            runtime_ref=str(digest),
            commit=str(commit),
        )
        if binding is not None:
            print("bring-up runtime: REUSED exact clean-head image", flush=True)
            return str(digest)
    print("bring-up runtime: building exact clean-head image", flush=True)
    return _build_exact_ordinary(runner, commit)


def _source_liveness_report(
        runner: go.CommandRunner, *, env: Mapping[str, str],
        runtime_ref: str, compose_args: Sequence[str]) -> Mapping[str, object]:
    """Run one bounded liveness read; no CDC stability/identity/recovery work."""
    run_env = go._without_broker_authority(dict(env))
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    # Prevent a diagnostic liveness probe from inheriting production-scale retry
    # budgets. GO retains the normal authoritative source policy.
    run_env["SHARADAR_FETCH_TIMEOUT"] = "15"
    run_env["SHARADAR_FETCH_RETRIES"] = "2"
    run_env["SHARADAR_FETCH_BACKOFF"] = "1"
    run_env["SHARADAR_429_BACKOFF_CAP"] = "15"
    run_env["SHARADAR_FETCH_MAX_PAGES"] = "2"
    completed = runner.run([
        "docker", "compose", *[str(item) for item in compose_args],
        "--profile", "cli", "run", "--rm", "-T", "--no-deps",
        "--entrypoint", "python", "sentinel", "-c", liveness._CODE,
    ], env=run_env)
    report = liveness.payload(completed)
    if completed.returncode != 0 or report is None:
        evidence = (
            probe_contract.subprocess_evidence(completed, context="BRINGUP_LIVENESS")
            if completed.returncode != 0
            else probe_contract.malformed_report_evidence(
                completed, context="BRINGUP_LIVENESS"))
        probe_contract.emit_probe_failure(evidence)
        raise BringupRefused(
            "Sharadar/local liveness probe failed (%s)" % evidence["reason"])
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fast non-authoritative Sentinel bring-up diagnostics")
    parser.add_argument(
        "--recover", action="store_true",
        help=("compatibility flag; bounded financial-data recovery is now owned "
              "exclusively by certified GO"))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(list(argv if argv is not None else sys.argv[1:]))
    env = go.merged_environment()
    try:
        if not go_lock.lifecycle_lock_is_held(env):
            raise BringupRefused(
                "sentinel_bringup.py must run through scripts/sentinel-bringup.sh")
        if go_lock.current_run_token(env) is None:
            raise BringupRefused("bring-up lifecycle capability is unavailable")

        _require_environment(env)
        runner = controller.DiagnosticRunner()
        git = _require_exact_main(runner)
        _run_env, compose_args = _compose_and_database_ready(runner, env)

        print("bring-up gate: backup durability", flush=True)
        backup_repair_reason = _backup_checkpoint(env)

        print("bring-up gate: exact ordinary runtime", flush=True)
        runtime_ref = _runtime_for_commit(runner, env=env, commit=git.commit)

        print("bring-up gate: lightweight Sharadar/local liveness", flush=True)
        report = _source_liveness_report(
            runner, env=env, runtime_ref=runtime_ref, compose_args=compose_args)
        _print_source_report(report, prefix="bring-up liveness")
        decision = source_decision(report)
        if not decision.proceed:
            print("%s - %s" % (BLOCKED, decision.reason_code), flush=True)
            return 3

        if backup_repair_reason is not None:
            print(
                "%s - %s" % (
                    READY_CERTIFIED_BACKUP_REFRESH, backup_repair_reason),
                flush=True,
            )
            print(
                "Certified GO owns the backup refresh, full source validation, "
                "bounded data preparation, and final certification. Run: "
                "bash scripts/sentinel-go-validate.sh",
                flush=True,
            )
            return 0

        if args.recover:
            print(
                "bring-up --recover: compatibility mode only; no financial data "
                "was mutated. Certified GO owns bounded recovery.",
                flush=True,
            )

        print(READY, flush=True)
        print(
            "No certification or deployment authority was created. Certified GO "
            "owns full stable SEP observation, TICKERS/history validation, bounded "
            "data recovery, post-recovery validation, and certification. Run: "
            "bash scripts/sentinel-go-validate.sh",
            flush=True,
        )
        return 0
    except BringupRefused as exc:
        print("%s - %s" % (BLOCKED, exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
