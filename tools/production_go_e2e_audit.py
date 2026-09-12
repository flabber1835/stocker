#!/usr/bin/env python3
"""Audit the true canonical production GO lifecycle and stage sensitivity.

This wrapper reuses the deterministic external fixtures from
production_go_e2e_harness, but performs an independent proof over the artifacts
left by the real production entrypoint. It also injects one causal failure at
each top-level production stage while every non-faulted stage executes the real
implementation.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import production_go_e2e_harness as base

ROOT = base.ROOT
POINTER = ROOT / "artifacts" / "sentinel" / "deployment" / "validated-runtime.env"
RUN_PASS = ROOT / "artifacts" / "sentinel" / "go-validation" / "current-run-requested-target-pass.json"
LOCK = ROOT / "artifacts" / "sentinel" / "go-validation" / "go-validation.lock"

IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
BUNDLE_RE = re.compile(r"^bundle: (.+)$", re.MULTILINE)
BUNDLE_SHA_RE = re.compile(r"^sha256: ([0-9a-f]{64})$", re.MULTILINE)

EXPECTED_PHASE_SEQUENCE = (
    "HOST COMPATIBILITY",
    "ACQUIRE SINGLE GO LIFECYCLE LOCK",
    "HOST COMPATIBILITY",
    "DEPLOYMENT SECRETS BOOTSTRAP",
    "HOST GO IDENTITY PREFLIGHT",
    "RUNTIME SELECTION PREFLIGHT",
    "PAPER ACCOUNT PREFLIGHT - GET ONLY",
    "READ-ONLY SHARADAR PREFLIGHT",
    "CERTIFICATION + FINANCIAL READINESS",
    "PROMOTE EXACT CERTIFIED RUNTIME",
    "POST-VALIDATION HANDOFF",
)

SHADOW_GATES = frozenset({
    "git_identity",
    "certified_suite_no_skips",
    "database_financial_health",
    "wealth_core_nas_parity",
    "sharadar_readiness",
    "zero_mutation_boundary",
})

FAULTS = (
    ("host-compatibility", "HOST COMPATIBILITY", "scripts/sentinel_host_python.py"),
    ("deployment-bootstrap", "DEPLOYMENT SECRETS BOOTSTRAP", "scripts/sentinel_deployment_bootstrap.py"),
    ("host-identity-preflight", "HOST GO IDENTITY PREFLIGHT", "scripts/sentinel_go_host_preflight.py"),
    ("runtime-selection-preflight", "RUNTIME SELECTION PREFLIGHT", "scripts/sentinel_runtime_selection.py"),
    ("paper-account-preflight", "PAPER ACCOUNT PREFLIGHT - GET ONLY", "scripts/sentinel_go_account_preflight.py"),
    ("readonly-sharadar-preflight", "READ-ONLY SHARADAR PREFLIGHT", "scripts/sentinel_go_readonly_data_preflight.py"),
    ("certification-financial-readiness", "CERTIFICATION + FINANCIAL READINESS", "scripts/sentinel_go_verified_entry.py"),
    ("runtime-promotion", "PROMOTE EXACT CERTIFIED RUNTIME", "scripts/sentinel_go_promote.py"),
    ("post-validation-handoff", "POST-VALIDATION HANDOFF", "scripts/sentinel_go_post_validate.py"),
)


class AuditFailure(RuntimeError):
    pass


def _run(argv, *, env=None, timeout=120, cwd=ROOT):
    return subprocess.run(
        [str(x) for x in argv],
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditFailure(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_validation_from_log(log: str) -> tuple[dict, str, str]:
    match = BUNDLE_RE.search(log)
    _require(match is not None, "canonical GO log has no validation bundle path")
    raw = match.group(1).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    _require(path.is_file(), f"validation bundle is unavailable: {raw}")
    digest = _sha256_file(path)
    printed = BUNDLE_SHA_RE.search(log)
    _require(printed is not None and printed.group(1) == digest,
             "validation bundle digest does not match canonical GO transcript")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            validation = json.loads(archive.read("validation.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise AuditFailure("validation bundle cannot be independently inspected") from exc
    _require(isinstance(validation, dict), "validation document is not an object")
    return validation, raw, digest


def _pointer() -> str:
    try:
        lines = POINTER.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AuditFailure("promoted runtime pointer is unavailable") from exc
    prefix = "SENTINEL_RUNTIME_IMAGE_REF="
    _require(len(lines) == 1 and lines[0].startswith(prefix),
             "promoted runtime pointer is malformed")
    value = lines[0][len(prefix):]
    _require(IMAGE_ID.fullmatch(value) is not None,
             "local-full promoted runtime pointer is not an immutable image id")
    return value


def _panel_image_id() -> str:
    selected = _run(
        ["bash", "scripts/sentinel-compose.sh", "--run", "ps", "-q", "sentinel-panel"],
        timeout=120,
    )
    containers = [x.strip() for x in selected.stdout.splitlines() if x.strip()]
    _require(selected.returncode == 0 and len(containers) == 1,
             "recreated panel container is not uniquely running")
    inspected = _run(
        ["docker", "container", "inspect", "--format", "{{.Image}}", containers[0]],
        timeout=60,
    )
    value = inspected.stdout.strip()
    _require(inspected.returncode == 0 and IMAGE_ID.fullmatch(value) is not None,
             "recreated panel image identity is unavailable")
    return value


def _success_evidence(completed: subprocess.CompletedProcess[str], commit: str) -> dict:
    log = completed.stdout or ""
    phases = base._phase_names(log)
    _require(completed.returncode == 0 and base.SUCCESS in log,
             f"canonical GO did not complete successfully (rc={completed.returncode})")
    _require(tuple(phases) == EXPECTED_PHASE_SEQUENCE,
             f"canonical GO phase sequence changed or bypassed a stage: {phases!r}")
    _require("requested target verdict: GO (SHADOW)" in log,
             "canonical GO did not prove the requested SHADOW target")
    _require("runtime promotion: BOUND - requested SHADOW GO selected " in log,
             "promotion did not consume the current SHADOW GO proof")
    _require(
        "post-validation: panel recreated and verified on the one validated runtime" in log,
        "post-validation did not verify the recreated panel runtime",
    )

    validation, bundle_path, bundle_sha256 = _load_validation_from_log(log)
    _require(validation.get("schema") == "sentinel.nas-go-validation/1",
             "validation bundle schema changed")
    git = validation.get("git") if isinstance(validation.get("git"), dict) else {}
    _require(git.get("commit") == commit and git.get("origin_main") == commit,
             "validation bundle is not bound to the tested commit")
    _require(git.get("branch") == "main" and git.get("clean") is True
             and git.get("matches_origin_main") is True,
             "validation did not pass exact clean main identity")
    _require(validation.get("input_mode") == "PRODUCTION",
             "validation did not execute production input mode")
    _require(validation.get("shadow_verdict") == "SHADOW_GO",
             "validation did not produce SHADOW_GO")
    failures = validation.get("machine_failures")
    _require(isinstance(failures, dict) and failures.get("shadow") == [],
             "SHADOW validation has machine failures")

    gates = {
        row.get("id"): row
        for row in validation.get("gates", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    _require(SHADOW_GATES.issubset(gates),
             "validation omitted one or more SHADOW authority gates")
    _require(all(gates[name].get("status") == "PASS" for name in SHADOW_GATES),
             "one or more SHADOW authority gates did not PASS")

    prep = validation.get("preparation")
    _require(isinstance(prep, dict) and prep.get("status") == "PASS",
             "Phase C schema/feed preparation did not PASS")
    _require(prep.get("schema_migration_attempted") is True,
             "schema migration was not exercised by the successful GO")
    _require(prep.get("bounded_sharadar_daily_attempted") is True,
             "bounded Sharadar preparation was not exercised by the successful GO")

    health = validation.get("database_financial_health")
    _require(isinstance(health, dict) and health.get("status") == "PASS",
             "database financial health did not PASS")
    checks = health.get("checks") if isinstance(health.get("checks"), dict) else {}
    _require(bool(checks) and all(value is True for value in checks.values()),
             "database financial health omitted or failed a required check")
    state = validation.get("shadow_state")
    _require(isinstance(state, dict) and state.get("fresh") is True
             and state.get("internally_coherent") is True,
             "publication/readiness/parity state is not fresh and coherent")
    boundary = validation.get("boundary")
    _require(isinstance(boundary, dict)
             and boundary.get("broker_mutation_attempts") == 0
             and boundary.get("production_db_writes") == 0,
             "post-preparation validation crossed the zero-mutation boundary")
    subjects = {
        row.get("kind"): row.get("digest")
        for row in validation.get("subjects", [])
        if isinstance(row, dict)
    }
    _require(bool(subjects.get("data_publication")),
             "validation bundle has no bound publication identity")

    handoff = base._load_json(base.HANDOFF)
    _require(handoff.get("git_commit") == commit,
             "handoff is not bound to the tested commit")
    _require(handoff.get("mode") == "LOCAL_FULL_CERTIFICATION"
             and handoff.get("software_certification") == "LOCAL_FULL_VERIFIED",
             "handoff is not bound to local-full software certification")
    _require(handoff.get("authority") == "EVIDENCE_ONLY_NOT_BROKER_AUTHORITY",
             "handoff authority changed")

    runtime = validation.get("runtime") if isinstance(validation.get("runtime"), dict) else {}
    runtime_id = runtime.get("runtime_image_digest")
    test_id = runtime.get("candidate_image_digest")
    _require(IMAGE_ID.fullmatch(str(runtime_id or "")) is not None,
             "validation runtime identity is unavailable")
    _require(IMAGE_ID.fullmatch(str(test_id or "")) is not None,
             "validation test-lens identity is unavailable")
    _require(handoff.get("runtime_local_image_id") == runtime_id,
             "handoff runtime differs from validated runtime")
    _require(handoff.get("test_lens_local_image_id") == test_id,
             "handoff test lens differs from validated certification lens")
    pointer = _pointer()
    _require(pointer == runtime_id, "promoted runtime pointer differs from validated runtime")
    panel = _panel_image_id()
    _require(panel == runtime_id, "recreated panel is not running the validated runtime")
    _require(not RUN_PASS.exists(),
             "one-run requested-target proof was not consumed by promotion")

    return {
        "returncode": completed.returncode,
        "phases": phases,
        "target": "SHADOW",
        "runtime_identity": runtime_id,
        "test_lens_identity": test_id,
        "validation_bundle": {
            "path": bundle_path,
            "sha256": bundle_sha256,
            "shadow_verdict": validation["shadow_verdict"],
            "publication_subject_digest": subjects["data_publication"],
            "passed_shadow_gates": sorted(SHADOW_GATES),
            "preparation_status": prep["status"],
            "database_financial_health_status": health["status"],
        },
        "promotion": {
            "runtime_pointer": pointer,
            "run_pass_consumed": True,
        },
        "panel": {
            "running_image_id": panel,
            "matches_validated_runtime": True,
        },
        "handoff": handoff,
    }


def _write_python_proxy(path: Path) -> Path:
    proxy = path / "python-stage-fault"
    proxy.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
script="${1:-}"
if [ -n "${E2E_FAIL_SCRIPT:-}" ] && [ "$script" = "$E2E_FAIL_SCRIPT" ]; then
  printf 'E2E_STAGE_FAULT:%s\\n' "$script" >&2
  exit 97
fi
exec "$E2E_REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    proxy.chmod(0o755)
    return proxy


def _assert_fault(name: str, expected_phase: str, completed, *,
                  marker: str | None = None, forbid_phase: str | None = None) -> dict:
    output = completed.stdout or ""
    phases = base._phase_names(output)
    _require(completed.returncode != 0,
             f"sensitivity {name} unexpectedly succeeded")
    _require(expected_phase in phases,
             f"sensitivity {name} did not reach {expected_phase}")
    if marker is not None:
        _require(marker in output,
                 f"sensitivity {name} did not prove the intended causal fault")
    if forbid_phase is not None:
        _require(forbid_phase not in phases,
                 f"sensitivity {name} continued into later phase {forbid_phase}")
    return {
        "name": name,
        "status": "EXPECTED_REFUSAL",
        "returncode": completed.returncode,
        "expected_phase": expected_phase,
        "observed_phases": phases,
    }


def _environment_fault() -> dict:
    completed = base._invoke(
        extra_env={"DOCKER_HOST": "tcp://127.0.0.1:2375"},
        timeout=120,
    )
    return _assert_fault(
        "environment-loading",
        "HOST COMPATIBILITY",
        completed,
        marker="ambient Docker selector",
        forbid_phase="DEPLOYMENT SECRETS BOOTSTRAP",
    )


def _lock_fault() -> dict:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+", encoding="ascii") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = base._invoke(timeout=120)
    return _assert_fault(
        "lifecycle-lock",
        "ACQUIRE SINGLE GO LIFECYCLE LOCK",
        completed,
        marker="another Sentinel GO validation is already running on this host",
        forbid_phase="DEPLOYMENT SECRETS BOOTSTRAP",
    )


def _proxy_fault(proxy: Path, name: str, expected_phase: str, script: str) -> dict:
    env = {
        "SENTINEL_HOST_PYTHON": str(proxy),
        "E2E_REAL_PYTHON": sys.executable,
        "E2E_FAIL_SCRIPT": script,
    }
    completed = base._invoke(extra_env=env, timeout=1800)
    phase_index = EXPECTED_PHASE_SEQUENCE.index(expected_phase)
    later = None
    for candidate in EXPECTED_PHASE_SEQUENCE[phase_index + 1:]:
        if candidate != expected_phase:
            later = candidate
            break
    return _assert_fault(
        name,
        expected_phase,
        completed,
        marker=f"E2E_STAGE_FAULT:{script}",
        forbid_phase=later,
    )


def _git(argv, *, check=True) -> str:
    completed = _run(["git", *argv], timeout=120)
    if check and completed.returncode != 0:
        raise AuditFailure(f"git {' '.join(argv)} failed: {completed.stdout[-1000:]}")
    return completed.stdout.strip()


def _initialize_backup_target(backup: Path) -> None:
    for name in ("wal", "base"):
        child = backup / name
        child.mkdir(parents=True, exist_ok=True)
        child.chmod(0o777)
    completed = _run(
        ["bash", "scripts/sentinel-compose.sh", "--initialize-backup"],
        timeout=180,
    )
    _require(
        completed.returncode == 0
        and "initialized_backup_target:" in (completed.stdout or ""),
        "canonical backup target initialization failed "
        f"(rc={completed.returncode}): {(completed.stdout or '')[-1200:]}",
    )


@contextlib.contextmanager
def _ci_main_authority(work: Path, commit: str):
    """Present the tested CI commit as the local origin/main authority.

    Production GO intentionally requires branch main == freshly fetched
    origin/main. A PR head and a synthetic merge are detached CI identities, so
    the harness supplies a deterministic local Git remote whose main ref is
    exactly the already-recorded tested commit. Production Git checks themselves
    are unchanged.
    """
    original_origin = _git(["remote", "get-url", "origin"])
    original_branch = _git(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False) or None
    original_main = _git(["rev-parse", "--verify", "refs/heads/main"], check=False) or None
    bare = work / "ci-origin.git"
    try:
        _git(["init", "--bare", str(bare)])
        _git(["push", str(bare), f"{commit}:refs/heads/main"])
        _git(["remote", "set-url", "origin", str(bare)])
        _git(["switch", "-C", "main", commit])
        _git(["fetch", "--prune", "origin", "main"])
        _git(["update-ref", "refs/remotes/origin/main", commit])
        _require(_git(["rev-parse", "HEAD"]) == commit,
                 "CI main authority changed the tested commit")
        yield
    finally:
        _git(["remote", "set-url", "origin", original_origin], check=False)
        if original_branch:
            _git(["switch", original_branch], check=False)
        else:
            _git(["checkout", "--detach", commit], check=False)
        if original_main:
            _git(["update-ref", "refs/heads/main", original_main], check=False)
        elif original_branch != "main":
            _git(["update-ref", "-d", "refs/heads/main"], check=False)


def run(*, output: Path, sensitivity: bool) -> dict:
    commit = base._git_head()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sentinel-go-e2e-audit-"))
    backup = work / "backup"
    backup.mkdir(parents=True)
    result = {
        "schema": "sentinel.production-go-e2e/1",
        "git_commit": commit,
        "canonical_entrypoint": list(base.ENTRYPOINT),
        "ci_git_authority": "local_bare_origin_main_bound_to_tested_commit",
        "success": None,
        "sensitivity": [],
        "all_pass": False,
    }
    try:
        with _ci_main_authority(work, commit):
            with base._source_server() as port, base._temporary_environment_file(
                    port=port, backup_dir=backup):
                _initialize_backup_target(backup)
                base._clean_runtime()
                try:
                    completed = base._invoke()
                    (output.parent / "canonical-go.log").write_text(
                        completed.stdout or "", encoding="utf-8")
                    result["success"] = _success_evidence(completed, commit)

                    if sensitivity:
                        proxy = _write_python_proxy(work)
                        result["sensitivity"].append(_environment_fault())
                        result["sensitivity"].append(_lock_fault())
                        for spec in FAULTS:
                            result["sensitivity"].append(_proxy_fault(proxy, *spec))
                finally:
                    base._clean_runtime()

        result["all_pass"] = True
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except Exception as exc:
        result["failure"] = {
            "type": type(exc).__name__,
            "detail": str(exc)[-5000:],
        }
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sensitivity", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(output=args.output, sensitivity=args.sensitivity)
    except (AuditFailure, base.HarnessFailure, OSError, subprocess.SubprocessError) as exc:
        print(f"REFUSED: production GO E2E audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "schema": result["schema"],
        "git_commit": result["git_commit"],
        "sensitivity_cases": len(result["sensitivity"]),
        "all_pass": result["all_pass"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())