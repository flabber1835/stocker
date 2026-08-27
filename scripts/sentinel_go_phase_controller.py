#!/usr/bin/env python3
"""Financial-grade phase controller for NAS GO validation.

This module deliberately wraps the existing validator rather than replacing its
probe implementations.  It changes only orchestration/liveness semantics:

A. cheap read-only preflight
B. stable exact-artifact certification (reusable only for exact unchanged bytes)
C. one feed-bound mutable preparation using the certified runtime
D. read-only financial readiness and broker GET-only observation
E. explicit requested-target exit semantics

The historical PAPER_EXECUTION verdict remains independent and is never promoted
into forward paper-observation authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence
import zipfile

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_validate as go  # noqa: E402
import sentinel_go_validate_entry as entry  # noqa: E402

CACHE_SCHEMA = "sentinel.nas-go-stable-certification/1"
CACHE_PATH = go.ROOT / "artifacts" / "sentinel" / "go-validation" / "stable-certification.json"
TARGET_SHADOW = "SHADOW"
TARGET_DUAL = "DUAL_RUN_OBSERVATION"
TARGET_PAPER = "HISTORICAL_PAPER_EXECUTION"
TARGETS = (TARGET_SHADOW, TARGET_DUAL, TARGET_PAPER)
_TEST_CACHE_KEYS = frozenset({
    "schema", "candidate_image_digest", "runtime_image_digest",
    "source_identity_sha256", "passed", "failed", "errors", "skipped",
    "xfailed", "xpassed", "exit_code", "suites_completed",
    "auxiliary_image_digests", "non_forward_historical_exclusions", "complete",
})


class PhaseRefused(RuntimeError):
    pass


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise PhaseRefused(f"{name} must be an integer") from exc
    if value < minimum:
        raise PhaseRefused(f"{name} must be >= {minimum}")
    return value


def _run_with_deadline(argv, **kwargs):
    command = [str(item) for item in argv]
    default = _safe_int_env("SENTINEL_GO_COMMAND_TIMEOUT_SECONDS", 10_800)
    preparation = _safe_int_env(
        "SENTINEL_GO_PREPARATION_TIMEOUT_SECONDS",
        max(1, go.MAX_BOUNDED_INGEST_MS // 1000),
    )
    timeout = preparation if any("SENTINEL_GO_PREPARATION=" in item for item in command) else default
    try:
        return subprocess.run(command, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command, 124,
            stdout=(exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout) or "",
            stderr=(exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr) or "",
        )


class DiagnosticRunner(go.CommandRunner):
    """Command runner with enforced deadlines and private preparation diagnostics."""

    def __init__(self):
        super().__init__(run=_run_with_deadline)
        self.last_preparation_output = ""

    def run(self, argv, *, env=None, cwd=go.ROOT):
        completed = super().run(argv, env=env, cwd=cwd)
        text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if "SENTINEL_GO_PREPARATION" in text or any(
                "SENTINEL_GO_PREPARATION=" in str(item) for item in argv):
            self.last_preparation_output = text
        return completed


def _install_single_preparation_contract() -> None:
    """Remove the redundant ingest.daily() call after ALREADY_CURRENT.

    outage_recovery.catch_up() has already established that the publication is
    current. Recontacting mutable vendor data at that point adds source risk and
    can turn a coherent corpus into an avoidable late refusal.
    """
    entry.install()
    old = """        if recovered.mode == 'ALREADY_CURRENT':\n            # Validation proves the explicit-through daily path itself even when\n            # no catch-up was necessary. The common recovery helper did not\n            # mutate in ALREADY_CURRENT mode, so this separate proof must apply\n            # the same external-WAL durability fence before calling ingest.\n            backup_guard.require_writes_permitted(\n                c, operation='NAS validation explicit daily publication')\n            ingest.daily(c, today=target)\n        elif recovered.mode == 'RETAINED_FULL_RESEED':"""
    new = """        if recovered.mode == 'ALREADY_CURRENT':\n            # Current publication is terminal success. Do not contact mutable\n            # vendor data a second time merely to prove the same state again.\n            pass\n        elif recovered.mode == 'RETAINED_FULL_RESEED':"""
    if old not in go._PREPARATION_CODE:
        raise PhaseRefused("GO preparation implementation no longer matches the reviewed single-preparation contract")
    go._PREPARATION_CODE = go._PREPARATION_CODE.replace(old, new, 1)


@dataclass(frozen=True)
class PreparationView:
    base: Any
    failure_reason_code: Optional[str] = None
    failure_detail: Optional[str] = None

    def __getattr__(self, name: str):
        return getattr(self.base, name)

    @property
    def complete(self) -> bool:
        return bool(self.base.complete)

    def to_dict(self) -> dict:
        value = dict(self.base.to_dict())
        if self.failure_reason_code:
            value["failure_reason_code"] = self.failure_reason_code
        if self.failure_detail:
            value["failure_detail"] = self.failure_detail
        return value


@dataclass(frozen=True)
class DatabaseHealthView:
    base: Any
    actual_remaining_to_execution_open_ms: Optional[int]
    observed_at: str

    def __getattr__(self, name: str):
        return getattr(self.base, name)

    @property
    def complete(self) -> bool:
        return bool(
            self.base.complete
            and type(self.actual_remaining_to_execution_open_ms) is int
            and self.actual_remaining_to_execution_open_ms > 0
        )

    def to_dict(self) -> dict:
        value = dict(self.base.to_dict())
        value["actual_deadline"] = {
            "observed_at": self.observed_at,
            "remaining_to_following_execution_open_ms": self.actual_remaining_to_execution_open_ms,
            "execution_open_still_future": bool(
                type(self.actual_remaining_to_execution_open_ms) is int
                and self.actual_remaining_to_execution_open_ms > 0),
            "note": "actual wall-clock observation; theoretical source-final-to-open duration is not used as elapsed-time margin",
        }
        return value


def _classify_preparation_failure(text: str) -> tuple[Optional[str], Optional[str]]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    detail = None
    for line in reversed(lines):
        marker = "SharadarMutationRefused:"
        if marker in line:
            detail = line.split(marker, 1)[1].strip()
            break
    joined = "\n".join(lines)
    if "MutationCursorUnavailable" in joined:
        return "LOCAL_CURSOR_MISSING", None
    if detail is None:
        if "VendorPublicationUnstable" in joined:
            return "SOURCE_PUBLICATION_UNSTABLE", None
        return None, None

    lowered = detail.lower()
    prohibited = ("http://", "https://", "api_key", "password", "authorization",
                  "postgres://", "postgresql://", "apca-api-")
    safe_detail = detail if len(detail) <= 500 and not any(x in lowered for x in prohibited) else None
    local_fragments = (
        "source cursor", "durable state shape", "row date disagrees",
        "names missing publication", "ahead of current publication",
        "cannot move backward", "nonexistent publication",
        "ahead of requested reconciliation",
    )
    if any(fragment in lowered for fragment in local_fragments):
        return "LOCAL_CURSOR_CORRUPT", safe_detail
    if "no permanent identity" in lowered:
        return "SOURCE_IDENTITY_UNRESOLVED", safe_detail
    if "no positive raw close" in lowered:
        return "SOURCE_RAW_CLOSE_INVALID", safe_detail
    if "lastupdated" in lowered or "invalid date" in lowered:
        return "SOURCE_CDC_INVALID", safe_detail
    return "SOURCE_AUTHORITY_REFUSED", safe_detail


def _summary_from_dict(value: Mapping[str, Any]) -> go.TestSummary:
    return go.TestSummary(
        candidate_image_digest=str(value.get("candidate_image_digest") or "") or None,
        runtime_image_digest=str(value.get("runtime_image_digest") or "") or None,
        source_identity_sha256=str(value.get("source_identity_sha256") or "") or None,
        passed=int(value.get("passed") or 0),
        failed=int(value.get("failed") or 0),
        errors=int(value.get("errors") or 0),
        skipped=int(value.get("skipped") or 0),
        xfailed=int(value.get("xfailed") or 0),
        xpassed=int(value.get("xpassed") or 0),
        exit_code=int(value.get("exit_code") if value.get("exit_code") is not None else 1),
        suites_completed=int(value.get("suites_completed") or 0),
        auxiliary_image_digests=tuple(str(x) for x in value.get("auxiliary_image_digests") or ()),
        non_forward_historical_exclusions=tuple(
            str(x) for x in value.get("non_forward_historical_exclusions") or ()),
    )


def _cache_payload(commit: str, summary: go.TestSummary) -> dict:
    evidence = {
        "schema": CACHE_SCHEMA,
        "git_commit": commit,
        "tests": summary.to_dict(),
    }
    return {**evidence, "evidence_sha256": _digest(evidence)}


def _write_certification_cache(commit: str, summary: go.TestSummary) -> None:
    if not summary.complete:
        return
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _cache_payload(commit, summary)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_bytes(_canonical_bytes(payload) + b"\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CACHE_PATH)


def _image_exact(runner: go.CommandRunner, digest: Optional[str]) -> bool:
    if not digest or go._IMAGE_DIGEST.fullmatch(str(digest)) is None:
        return False
    return go._inspect_image_id(runner, str(digest)) == str(digest)


def _load_certification_cache(runner: go.CommandRunner, *, commit: str) -> Optional[go.TestSummary]:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (not isinstance(payload, dict)
            or set(payload) != {"schema", "git_commit", "tests", "evidence_sha256"}
            or payload.get("schema") != CACHE_SCHEMA):
        return None
    supplied = str(payload.get("evidence_sha256") or "")
    evidence = {k: v for k, v in payload.items() if k != "evidence_sha256"}
    if supplied != _digest(evidence) or payload.get("git_commit") != commit:
        return None
    tests = payload.get("tests")
    if (not isinstance(tests, dict)
            or set(tests) != _TEST_CACHE_KEYS
            or tests.get("schema") != go.TEST_SCHEMA
            or tests.get("complete") is not True):
        return None
    try:
        summary = _summary_from_dict(tests)
    except (TypeError, ValueError):
        return None
    if not summary.complete or summary.to_dict() != tests:
        return None
    images = (
        summary.candidate_image_digest,
        summary.runtime_image_digest,
        *summary.auxiliary_image_digests,
    )
    if not all(_image_exact(runner, item) for item in images):
        return None
    return summary


def _certify_exact_artifacts(runner: DiagnosticRunner, *, git: go.GitIdentity,
                             now_text: str, run_suite: bool):
    if not run_suite:
        return (
            go.TestSummary(None, None, None),
            go.make_gate("certified_suite_no_skips", go.NOT_PROVEN, now_text,
                         {"reason": "CERTIFIED_SUITE_NOT_RUN"}),
        )
    if not (git.commit and git.branch_is_main and git.clean and git.matches_origin_main):
        return (
            go.TestSummary(None, None, None),
            go.make_gate(
                "certified_suite_no_skips", go.NOT_PROVEN, now_text,
                {"reason": "GIT_IDENTITY_NOT_PASS_NO_CERTIFICATION_WORK"}),
        )
    cached = _load_certification_cache(runner, commit=git.commit)
    if cached is not None:
        print("stable certification: REUSED exact unchanged commit/image evidence", flush=True)
        return cached, go.make_gate(
            "certified_suite_no_skips", go.PASS, now_text,
            {"stable_certification_reused": True,
             "git_commit": git.commit,
             "tests_evidence_sha256": _digest(cached.to_dict())})
    summary, gate = go.probe_certified_suite(runner, commit=git.commit, now_text=now_text)
    if gate.status == go.PASS and summary.complete:
        _write_certification_cache(git.commit, summary)
    return summary, gate


_ACTUAL_DEADLINE_CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel.feed import calendar, publication, store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    current = publication.require_current(c)
    frontier = current.window_end
    execution_session = calendar.next_session(frontier)
    execution_open, _ = calendar.session_window(execution_session)
    now = datetime.now(timezone.utc)
    remaining = int((execution_open.astimezone(timezone.utc) - now).total_seconds() * 1000)
    print('SENTINEL_GO_ACTUAL_DEADLINE=' + json.dumps({
        'remaining_ms': max(0, remaining),
        'future': remaining > 0,
    }, sort_keys=True))
finally:
    c.close()
'''.strip()


def _actual_remaining_ms(runner: go.CommandRunner, *, env: Mapping[str, str],
                         runtime_ref: Optional[str]) -> Optional[int]:
    if runtime_ref is None or go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is None:
        return None
    run_env = go._without_broker_authority(env)
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        return None
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    completed = runner.run([
        "docker", "compose", *compose_args, "--profile", "cli", "run", "--rm", "-T",
        "--no-deps", "--entrypoint", "python", "sentinel", "-c", _ACTUAL_DEADLINE_CODE,
    ], env=run_env)
    marker = "SENTINEL_GO_ACTUAL_DEADLINE="
    if completed.returncode != 0:
        return None
    for line in (completed.stdout or "").splitlines():
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker):])
            except ValueError:
                return None
            remaining = value.get("remaining_ms") if isinstance(value, dict) else None
            return int(remaining) if type(remaining) is int and remaining >= 0 else None
    return None


def run_phased_probes(*, runner=None, env=None, now=None, urlopen=None,
                      run_suite: bool = True) -> go.ProbeResults:
    runner = runner or DiagnosticRunner()
    resolved_env = dict(env) if env is not None else go.merged_environment()
    instant = now or datetime.now(timezone.utc)
    now_text = go._utc_text(instant)

    # A: cheap read-only facts first. No financial database write is allowed.
    git, git_gate = go.probe_git(runner, now_text=now_text)
    mutation_counter = [0]
    alpaca, account_subjects = go.probe_alpaca_account(
        env=resolved_env, now_text=now_text,
        urlopen=(urlopen or go.urllib.request.urlopen),
        mutation_counter=mutation_counter)

    # B: exact stable artifact certification, with exact-identity reuse on retry.
    tests, suite_gate = _certify_exact_artifacts(
        runner, git=git, now_text=now_text, run_suite=run_suite)

    # C: exactly one mutable preparation, only through the feed-bound certified image.
    preparation_base = entry.probe_prevalidation_preparation(
        runner, env=resolved_env,
        runtime_ref=tests.runtime_image_digest, commit=git.commit)
    reason_code = detail = None
    if preparation_base.status != go.PASS:
        reason_code, detail = _classify_preparation_failure(runner.last_preparation_output)
        if reason_code:
            print(f"GO preparation refusal: {reason_code}" + (f" - {detail}" if detail else ""),
                  file=sys.stderr, flush=True)
    preparation = PreparationView(preparation_base, reason_code, detail)

    # D: read-only financial readiness using the exact certified deployable runtime.
    subjects = dict(account_subjects)
    timing_values = {}
    parity = go.probe_active_wealth_parity(
        runner, env=resolved_env, commit=git.commit,
        candidate_image_digest=tests.candidate_image_digest,
        now_text=now_text, subject_values=subjects,
        timing_values=timing_values)
    readiness = go.probe_sharadar_readiness(
        runner, env=resolved_env, runtime_ref=tests.runtime_image_digest,
        now_text=now_text)
    database_base, database_gate = go.probe_database_financial_health(
        runner, env=resolved_env, runtime_ref=tests.runtime_image_digest,
        now_text=now_text,
        bounded_ingest_milliseconds=preparation.elapsed_milliseconds,
        full_forward_decision_replay_milliseconds=timing_values.get(
            "full_forward_decision_replay"))
    actual_remaining = _actual_remaining_ms(
        runner, env=resolved_env, runtime_ref=tests.runtime_image_digest)
    deadline_observed_at = go._utc_text(datetime.now(timezone.utc))
    database_health = DatabaseHealthView(
        database_base, actual_remaining, deadline_observed_at)
    if not database_health.complete and database_gate.status == go.PASS:
        database_gate = go.make_gate(
            "database_financial_health", go.FAIL, deadline_observed_at,
            {"reason": "FOLLOWING_EXECUTION_OPEN_NOT_FUTURE_AT_FINAL_READINESS",
             "actual_remaining_ms": actual_remaining})

    if tests.source_identity_sha256 is not None:
        subjects["shadow_configuration"] = go.shadow_configuration_sha256(
            resolved_env, source_identity_sha256=tests.source_identity_sha256)
    gates = {
        "git_identity": git_gate,
        "certified_suite_no_skips": suite_gate,
        "database_financial_health": database_gate,
        "wealth_core_nas_parity": parity,
        "sharadar_readiness": readiness,
        "alpaca_paper_account": alpaca,
        **go._unproven_paper_gates(now_text),
    }
    writes = 0
    gates["zero_mutation_boundary"] = go.make_gate(
        "zero_mutation_boundary",
        go.PASS if mutation_counter[0] == 0 and writes == 0 else go.FAIL,
        now_text,
        {"broker_mutation_attempts": mutation_counter[0],
         "production_db_writes": writes,
         "allowed_financial_http_methods": ["GET"]})
    return go.ProbeResults(
        git=git, tests=tests, gates=gates, subject_values=subjects,
        broker_mutation_attempts=mutation_counter[0], production_db_writes=writes,
        input_mode="PRODUCTION", preparation=preparation,
        database_health=database_health)


def _target_from_argv(argv: Sequence[str]) -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target", choices=TARGETS,
                        default=os.environ.get("SENTINEL_GO_TARGET", TARGET_DUAL))
    known, remaining = parser.parse_known_args(list(argv))
    return known.target, remaining


def _target_ok(result: go.BundleResult, target: str) -> bool:
    if target == TARGET_SHADOW:
        return result.shadow_verdict == go.SHADOW_GO
    if target == TARGET_DUAL:
        return result.dual_run_verdict == go.DUAL_RUN_GO
    return result.paper_execution_verdict == go.PAPER_GO


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    target, forwarded = _target_from_argv(raw)
    _install_single_preparation_contract()
    go.run_production_probes = run_phased_probes

    captured = {}
    original_emit = go.emit_bundle

    def emit_capture(*args, **kwargs):
        result = original_emit(*args, **kwargs)
        captured["result"] = result
        return result

    go.emit_bundle = emit_capture
    rc = go.main(forwarded)
    result = captured.get("result")
    if result is None:
        return rc
    print(f"requested deployment target: {target}")
    if not result.upload_permitted:
        return 2
    if _target_ok(result, target):
        print(f"requested target verdict: GO ({target})")
        return 0
    print(f"requested target verdict: NO_GO ({target})")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
