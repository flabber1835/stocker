#!/usr/bin/env python3
"""Fast Sentinel bootstrap diagnostics and optional data recovery.

This is intentionally NOT a certification path. It exists to discover/fix
volatile host/source/data blockers before paying the cost of the full certified
suite. Even with ``--recover`` it grants no deployment authority, emits no GO
bundle, writes no requested-target pass, promotes no runtime, and performs no
broker mutation. A final successful ``scripts/sentinel-go-validate.sh`` remains
mandatory before any deployment target can become GO.

The supported launcher installs ``sentinel_bringup_install_anytime`` so a
Sharadar source-final temporal wait cannot block software installation. This
base module retains fail-closed DEFERRED semantics when imported directly; the
launcher overlay is the reviewed operator contract.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_24x7_entry as source_final  # noqa: E402
import sentinel_go_lock as go_lock  # noqa: E402
import sentinel_go_phase_controller as controller  # noqa: E402
import sentinel_go_probe_contract as probe_contract  # noqa: E402
import sentinel_go_readonly_data_preflight as readonly  # noqa: E402
import sentinel_go_validate as go  # noqa: E402
import sentinel_go_validate_entry as entry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
READY = "BRINGUP_READY_FOR_CERTIFICATION"
READY_RECOVERY = "BRINGUP_READY_FOR_RECOVERY"
BLOCKED = "BRINGUP_BLOCKED"
DATA_DONE_WAIT = "BRINGUP_DATA_RECOVERY_COMPLETE_WAIT_SOURCE_FINAL"


class BringupRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceDecision:
    proceed: bool
    status: str
    reason_code: str


def source_decision(report: Mapping[str, object]) -> SourceDecision:
    """Map the read-only source report to a pre-recovery bring-up action.

    The public launcher installs the wall-clock-independent overlay before
    calling ``main``. Without that reviewed overlay, DEFERRED remains a base
    fail-closed state so internal/direct callers cannot silently acquire the
    installation exception.
    """
    status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "READONLY_PREFLIGHT_UNAVAILABLE")
    if status in {"PASS", "RECOVERY_REQUIRED"}:
        return SourceDecision(True, status, reason)
    if status in {"DEFERRED", "REFUSED"}:
        return SourceDecision(False, status, reason)
    raise BringupRefused("read-only Sharadar preflight returned an unknown state")


def post_recovery_source_decision(report: Mapping[str, object]) -> SourceDecision:
    """Require raw post-recovery source authority before certification readiness.

    The install-anytime overlay may normalize a pre-recovery DEFERRED result so
    bounded catch-up can run. That exception must not cross the recovery
    boundary: only an actual raw PASS may advertise readiness for final GO
    certification. DEFERRED, RECOVERY_REQUIRED, and REFUSED remain non-ready.
    """
    status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "READONLY_PREFLIGHT_UNAVAILABLE")
    if status == "PASS":
        return SourceDecision(True, status, reason)
    if status in {"DEFERRED", "RECOVERY_REQUIRED", "REFUSED"}:
        return SourceDecision(False, status, reason)
    raise BringupRefused(
        "post-recovery Sharadar preflight returned an unknown state")


def _print_source_report(report: Mapping[str, object], *, prefix: str) -> None:
    decision = source_decision(report)
    detail = readonly._safe_detail(report.get("detail"))
    text = "%s: %s - %s" % (prefix, decision.status, decision.reason_code)
    if detail:
        text += " - " + detail
    if report.get("detail_sha256"):
        text += " [detail_sha256=%s]" % str(report["detail_sha256"])
    print(text, flush=True)


def _run_visible(argv: Sequence[str], *, env: Mapping[str, str], label: str) -> None:
    completed = subprocess.run(
        [str(item) for item in argv], cwd=str(ROOT), env=dict(env), check=False)
    if completed.returncode != 0:
        raise BringupRefused("%s failed (exit %d)" % (label, completed.returncode))


def _require_exact_main(runner: go.CommandRunner):
    now_text = go._utc_text(datetime.now(timezone.utc))
    git, gate = go.probe_git(runner, now_text=now_text)
    if gate.status != go.PASS or git.commit is None:
        raise BringupRefused(
            "bring-up recovery requires clean current main exactly equal to origin/main")
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


def _require_backup_ready(env: Mapping[str, str]) -> None:
    _run_visible(
        ["bash", "scripts/sentinel-backup-status.sh"],
        env=env, label="backup durability checkpoint")


def _read_only_report(
        runner: go.CommandRunner, *, env: Mapping[str, str],
        runtime_ref: str, compose_args: Sequence[str]) -> Mapping[str, object]:
    run_env = go._without_broker_authority(dict(env))
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    completed = runner.run([
        "docker", "compose", *[str(item) for item in compose_args],
        "--profile", "cli", "run", "--rm", "-T", "--no-deps",
        "--entrypoint", "python", "sentinel", "-c", readonly._READ_ONLY_CODE,
    ], env=run_env)
    report = readonly._payload(completed)
    if completed.returncode != 0 or report is None:
        evidence = (
            probe_contract.subprocess_evidence(completed, context="BRINGUP_READONLY")
            if completed.returncode != 0
            else probe_contract.malformed_report_evidence(
                completed, context="BRINGUP_READONLY"))
        probe_contract.emit_probe_failure(evidence)
        raise BringupRefused(
            "read-only Sharadar bring-up probe failed (%s)" % evidence["reason"])
    return report


def _runtime_for_commit(
        runner: go.CommandRunner, *, env: Mapping[str, str], commit: str) -> str:
    """Reuse an already-proven exact runtime; rebuild only when it is unavailable."""
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
    return readonly._build_exact_ordinary(runner, commit)


def _run_recovery(
        runner: controller.DiagnosticRunner, *, env: Mapping[str, str],
        runtime_ref: str, commit: str):
    """Run production 24x7 preparation without creating certification authority."""
    if not go_lock.lifecycle_lock_is_held(env):
        raise BringupRefused("GO lifecycle lock is not proven")
    if go_lock.current_run_token(env) is None:
        raise BringupRefused("current bring-up lifecycle capability is unavailable")

    # Install exactly the same 24x7 source-final preparation string used by GO.
    # The verified feed-bound runner still proves clean-head image/source binding
    # for the one mutating subprocess and strips broker authority from it.
    source_final.install()
    bound_runner = entry.FeedBoundPreparationRunner(
        runner, runtime_ref=str(runtime_ref), commit=str(commit))
    result = source_final._deployment_preparation_probe(
        bound_runner,
        env=go._without_broker_authority(dict(env)),
        runtime_ref=str(runtime_ref),
        commit=str(commit),
    )
    if result.status != go.PASS or not result.complete:
        reason, detail = controller._classify_preparation_failure(
            runner.last_preparation_output)
        text = reason or "PREPARATION_NOT_PASS"
        if detail:
            text += " - " + detail
        raise BringupRefused(text)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fast non-authoritative Sentinel bring-up loop")
    parser.add_argument(
        "--recover", action="store_true",
        help="after all cheap gates pass, run bounded production data recovery")
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
        _require_backup_ready(env)

        print("bring-up gate: exact ordinary runtime", flush=True)
        runtime_ref = _runtime_for_commit(runner, env=env, commit=git.commit)

        print("bring-up gate: volatile Sharadar/source authority", flush=True)
        report = _read_only_report(
            runner, env=env, runtime_ref=runtime_ref, compose_args=compose_args)
        _print_source_report(report, prefix="bring-up source")
        decision = source_decision(report)
        if not decision.proceed:
            print("%s - %s" % (BLOCKED, decision.reason_code), flush=True)
            return 3

        if not args.recover:
            print("%s - %s" % (READY_RECOVERY, decision.reason_code), flush=True)
            print(
                "No certification or deployment authority was created. "
                "Re-run with --recover to perform bounded data recovery.",
                flush=True,
            )
            return 0

        print("bring-up recovery: bounded production data preparation", flush=True)
        preparation = _run_recovery(
            runner, env=env, runtime_ref=runtime_ref, commit=git.commit)
        print(
            "bring-up recovery: PASS elapsed_ms=%d" % preparation.elapsed_milliseconds,
            flush=True,
        )

        print("bring-up gate: post-recovery source/data state", flush=True)
        after = _read_only_report(
            runner, env=env, runtime_ref=runtime_ref, compose_args=compose_args)
        _print_source_report(after, prefix="post-recovery source")
        final = post_recovery_source_decision(after)
        if final.status == "PASS":
            print(READY, flush=True)
            print(
                "Final certification is still required: "
                "bash scripts/sentinel-go-validate.sh",
                flush=True,
            )
            return 0
        if final.status == "DEFERRED":
            print("%s - %s" % (DATA_DONE_WAIT, final.reason_code), flush=True)
            return 3
        print("%s - %s" % (BLOCKED, final.reason_code), flush=True)
        return 3
    except BringupRefused as exc:
        print("%s - %s" % (BLOCKED, exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
