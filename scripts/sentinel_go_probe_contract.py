#!/usr/bin/env python3
"""Cold-start and subprocess-diagnostic contract for Sentinel GO probes.

This module owns host orchestration only. It may start the already-reviewed
PostgreSQL service and wait for Docker health, but it never creates schema,
changes financial rows, contacts a broker, or grants execution authority.

Every DB-dependent one-shot probe gets the same guarantees:

* PostgreSQL is explicitly started and healthy before ``compose run --no-deps``;
* child failures are reduced to bounded, credential-safe machine evidence;
* stdout/stderr digests retain a stable forensic binding to the raw local output;
* malformed/missing child reports are distinguishable from semantic FAIL results.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Optional, Sequence


POSTGRES_SERVICE = "sentinel-postgres"
PROBE_FAILURE_MARKER = "SENTINEL_GO_PROBE_FAILURE="
PREPARATION_FAILURE_MARKER = "SENTINEL_GO_PREPARATION_FAILURE="
_INSTALLED_MARKER = "_sentinel_go_probe_contract_installed"
_DEFAULT_POSTGRES_START_TIMEOUT_SECONDS = 120
_MAX_SAFE_LINES = 3
_MAX_SAFE_LINE_LENGTH = 320
_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PROHIBITED = (
    "http://",
    "https://",
    "api_key",
    "api-key",
    "password",
    "authorization",
    "postgres://",
    "postgresql://",
    "apca-api-",
    "alpaca_api_key",
    "alpaca_secret_key",
    "sharadar_api_key",
    "sentinel_postgres_password",
    "sentinel_publication_receipt_key",
)


@dataclass(frozen=True)
class CommandRecord:
    argv: tuple[str, ...]
    completed: Any


class RecordingRunner:
    """Transparent runner proxy that retains subprocess results in memory only."""

    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.records: list[CommandRecord] = []

    def run(self, argv: Sequence[str], *, env=None, cwd=None):
        kwargs = {"env": env}
        if cwd is not None:
            kwargs["cwd"] = cwd
        completed = self.delegate.run(argv, **kwargs)
        self.records.append(CommandRecord(
            tuple(str(item) for item in argv), completed))
        return completed

    def last_compose_run(self) -> Optional[Any]:
        for record in reversed(self.records):
            command = list(record.argv)
            if command[:2] == ["docker", "compose"] and "run" in command:
                return record.completed
        return None


class DeadlineCommandRunner:
    """Small host runner whose explicit timeout bounds the actual subprocess."""

    def __init__(self, *, cwd=None):
        self.cwd = cwd

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    def _execute(self, argv: Sequence[str], *, env=None, cwd=None,
                 timeout_seconds: Optional[float] = None):
        command = [str(item) for item in argv]
        resolved_cwd = self.cwd if cwd is None else cwd
        try:
            return subprocess.run(
                command,
                cwd=(str(resolved_cwd) if resolved_cwd is not None else None),
                env=(dict(env) if env is not None else None),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                command,
                124,
                stdout=self._text(exc.stdout),
                stderr=self._text(exc.stderr),
            )
        except OSError:
            return subprocess.CompletedProcess(
                command, 127, stdout="", stderr="")

    def run(self, argv: Sequence[str], *, env=None, cwd=None):
        return self._execute(argv, env=env, cwd=cwd)

    def run_with_timeout(self, argv: Sequence[str], *, env=None,
                         timeout_seconds: float, cwd=None):
        return self._execute(
            argv, env=env, cwd=cwd,
            timeout_seconds=max(0.001, float(timeout_seconds)))


def _sha(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8", errors="replace")).hexdigest()


def safe_detail(value: object, *, limit: int = 500) -> Optional[str]:
    """Return one bounded line only when it cannot contain obvious authority data."""
    text = _ANSI.sub("", str(value or "")).strip()
    if not text or re.search(r"[\r\n\x00]", text):
        return None
    lowered = text.lower()
    if any(token in lowered for token in _PROHIBITED):
        return None
    if len(text) <= limit:
        return text
    digest = _sha(text)[:16]
    keep = max(1, limit - 35)
    return text[:keep] + " ... [sha256:%s]" % digest


def _safe_tail(stdout: str, stderr: str) -> list[str]:
    found: list[str] = []
    for raw in reversed(((stderr or "") + "\n" + (stdout or "")).splitlines()):
        candidate = safe_detail(raw, limit=_MAX_SAFE_LINE_LENGTH)
        if candidate is None or candidate in found:
            continue
        found.append(candidate)
        if len(found) >= _MAX_SAFE_LINES:
            break
    found.reverse()
    return found


def _classify(completed: Any) -> str:
    rc = int(getattr(completed, "returncode", 1))
    text = ((getattr(completed, "stdout", "") or "") + "\n"
            + (getattr(completed, "stderr", "") or "")).lower()
    if rc == 124:
        return "SUBPROCESS_TIMEOUT"
    if rc == 127:
        return "COMMAND_UNAVAILABLE"
    if rc in {137, 143} or "killed" in text:
        return "PROCESS_TERMINATED"
    if ("modulenotfounderror" in text or "importerror" in text
            or "no module named" in text):
        return "RUNTIME_IMPORT_FAILURE"
    if "password authentication failed" in text or "authentication failed" in text:
        return "DATABASE_AUTHENTICATION_FAILURE"
    connection_terms = (
        "connection refused",
        "could not connect",
        "operationalerror",
        "server closed the connection unexpectedly",
        "could not translate host name",
        "name or service not known",
        "temporary failure in name resolution",
        "network is unreachable",
    )
    if any(term in text for term in connection_terms):
        return "DATABASE_CONNECTION_FAILURE"
    if "permission denied" in text or "operation not permitted" in text:
        return "RUNTIME_PERMISSION_FAILURE"
    if "no space left on device" in text:
        return "RESOURCE_STORAGE_FAILURE"
    return "SUBPROCESS_FAILURE"


def subprocess_evidence(completed: Any, *, context: str,
                        reason: Optional[str] = None) -> dict[str, Any]:
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    classification = _classify(completed)
    resolved_reason = str(reason or (str(context).upper() + "_" + classification))
    if _SAFE_REASON.fullmatch(resolved_reason) is None:
        resolved_reason = "PROBE_SUBPROCESS_FAILURE"
    return {
        "reason": resolved_reason,
        "failure_class": classification,
        "exit_code": int(getattr(completed, "returncode", 1)),
        "stdout_sha256": _sha(stdout),
        "stderr_sha256": _sha(stderr),
        "diagnostic_tail": _safe_tail(stdout, stderr),
    }


def _json_object(value: str) -> Optional[Mapping[str, Any]]:
    try:
        payload = json.loads(value or "")
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _marker_object(value: str, marker: str) -> Optional[Mapping[str, Any]]:
    matches = []
    for raw in (value or "").splitlines():
        if not raw.startswith(marker):
            continue
        try:
            payload = json.loads(raw[len(marker):])
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        matches.append(payload)
    return matches[0] if len(matches) == 1 else None


def malformed_report_evidence(completed: Any, *, context: str) -> dict[str, Any]:
    evidence = subprocess_evidence(
        completed, context=context,
        reason=str(context).upper() + "_REPORT_MALFORMED")
    evidence["failure_class"] = "REPORT_MALFORMED"
    return evidence


def emit_probe_failure(evidence: Mapping[str, Any]) -> None:
    safe = {
        key: value for key, value in dict(evidence).items()
        if key in {
            "reason", "failure_class", "exit_code", "stdout_sha256",
            "stderr_sha256", "diagnostic_tail", "service_status",
        }
    }
    print(
        PROBE_FAILURE_MARKER
        + json.dumps(safe, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def _timeout_seconds(env: Mapping[str, str]) -> Optional[int]:
    raw = str(env.get("SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_POSTGRES_START_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 1 else None


def _runner_deadline_method(runner: Any):
    bounded = getattr(runner, "run_with_timeout", None)
    if callable(bounded):
        return bounded
    # Existing GO CommandRunner/DiagnosticRunner instances expose their
    # subprocess callable as ``_run``. Preserve their reviewed default cwd while
    # adding a real timeout at this infrastructure-only boundary.
    if not hasattr(runner, "_run"):
        return None
    method = getattr(getattr(runner, "run", None), "__func__", None)
    defaults = getattr(method, "__kwdefaults__", None) or {}
    deadline_runner = DeadlineCommandRunner(cwd=defaults.get("cwd"))
    return deadline_runner.run_with_timeout


def ensure_postgres_ready(
        runner: Any, *, env: Mapping[str, str], compose_args: Sequence[str],
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic) -> Optional[dict[str, Any]]:
    """Start PostgreSQL and bound every Docker call by one startup deadline."""
    timeout = _timeout_seconds(env)
    if timeout is None:
        return {
            "reason": "POSTGRES_START_TIMEOUT_CONFIG_INVALID",
            "failure_class": "CONFIGURATION_INVALID",
            "exit_code": 2,
            "stdout_sha256": _sha(""),
            "stderr_sha256": _sha(""),
            "diagnostic_tail": [],
        }

    bounded_run = _runner_deadline_method(runner)
    if bounded_run is None:
        evidence = {
            "reason": "POSTGRES_BOUNDED_RUNNER_UNAVAILABLE",
            "failure_class": "BOUNDED_RUNNER_UNAVAILABLE",
            "exit_code": 2,
            "stdout_sha256": _sha(""),
            "stderr_sha256": _sha(""),
            "diagnostic_tail": [],
        }
        emit_probe_failure(evidence)
        return evidence

    deadline = monotonic() + float(timeout)

    def run_bounded(argv: Sequence[str]):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return subprocess.CompletedProcess(
                [str(item) for item in argv], 124, stdout="", stderr="")
        return bounded_run(
            argv, env=env, timeout_seconds=max(0.001, remaining))

    prefix = ["docker", "compose", *[str(item) for item in compose_args]]
    started = run_bounded(prefix + ["up", "-d", POSTGRES_SERVICE])
    if int(started.returncode) != 0:
        evidence = subprocess_evidence(
            started, context="POSTGRES_START", reason="POSTGRES_START_FAILED")
        emit_probe_failure(evidence)
        return evidence

    selected = run_bounded(prefix + ["ps", "-q", POSTGRES_SERVICE])
    container_ids = [
        line.strip() for line in (selected.stdout or "").splitlines()
        if line.strip()
    ]
    if int(selected.returncode) != 0 or len(container_ids) != 1:
        evidence = subprocess_evidence(
            selected, context="POSTGRES_CONTAINER_ID",
            reason="POSTGRES_CONTAINER_ID_UNAVAILABLE")
        emit_probe_failure(evidence)
        return evidence

    container_id = container_ids[0]
    last_status = "unknown"
    while monotonic() < deadline:
        inspected = run_bounded([
            "docker", "inspect", "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            container_id,
        ])
        if int(inspected.returncode) != 0:
            evidence = subprocess_evidence(
                inspected, context="POSTGRES_HEALTH",
                reason="POSTGRES_HEALTH_UNAVAILABLE")
            emit_probe_failure(evidence)
            return evidence
        status = (inspected.stdout or "").strip().lower()
        last_status = status or "unknown"
        if status == "healthy":
            return None
        if status in {"dead", "exited", "removing"}:
            evidence = {
                "reason": "POSTGRES_EXITED_BEFORE_HEALTHY",
                "failure_class": "SERVICE_EXITED",
                "exit_code": 1,
                "stdout_sha256": _sha(inspected.stdout or ""),
                "stderr_sha256": _sha(inspected.stderr or ""),
                "diagnostic_tail": _safe_tail(
                    inspected.stdout or "", inspected.stderr or ""),
                "service_status": status,
            }
            emit_probe_failure(evidence)
            return evidence
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(1.0, remaining))

    evidence = {
        "reason": "POSTGRES_HEALTH_TIMEOUT",
        "failure_class": "SERVICE_HEALTH_TIMEOUT",
        "exit_code": 124,
        "stdout_sha256": _sha(last_status),
        "stderr_sha256": _sha(""),
        "diagnostic_tail": [],
        "service_status": last_status,
    }
    emit_probe_failure(evidence)
    return evidence


def _append_preparation_failure(runner: Any, evidence: Mapping[str, Any]) -> None:
    payload = {
        "phase": "DATABASE_STARTUP",
        "error_type": str(evidence.get("failure_class") or "InfrastructureUnavailable"),
        "reason_code": str(evidence.get("reason") or "POSTGRES_START_FAILED"),
        "detail_sha256": str(evidence.get("stderr_sha256") or _sha("")),
    }
    marker = PREPARATION_FAILURE_MARKER + json.dumps(payload, sort_keys=True)
    if hasattr(runner, "last_preparation_output"):
        current = str(getattr(runner, "last_preparation_output") or "")
        setattr(runner, "last_preparation_output", current + "\n" + marker + "\n")
    print(marker, file=sys.stderr, flush=True)


def classify_preparation_failure(
        text: str,
        fallback: Callable[[str], tuple[Optional[str], Optional[str]]]
        ) -> tuple[Optional[str], Optional[str]]:
    matches: list[Mapping[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith(PREPARATION_FAILURE_MARKER):
            continue
        try:
            payload = json.loads(line[len(PREPARATION_FAILURE_MARKER):])
        except ValueError:
            continue
        if isinstance(payload, dict):
            matches.append(payload)
    if matches:
        payload = matches[-1]
        reason = str(payload.get("reason_code") or "")
        detail = safe_detail(payload.get("detail"))
        if _SAFE_REASON.fullmatch(reason):
            return reason, detail
    return fallback(text)


def install(*, controller: Any, phase: Any) -> None:
    """Wrap the final phased GO functions after certification/backup overlays."""
    if getattr(controller, _INSTALLED_MARKER, False):
        return
    go = controller.go
    entry = controller.entry

    original_preparation = entry.probe_prevalidation_preparation
    original_parity = go.probe_active_wealth_parity
    original_readiness = go.probe_sharadar_readiness
    original_database = go.probe_database_financial_health
    original_actual = controller._actual_remaining_ms
    original_classify = controller._classify_preparation_failure

    def ready(runner: Any, env: Mapping[str, str]) -> Optional[dict[str, Any]]:
        run_env = go._without_broker_authority(dict(env))
        compose_args = go._resolve_compose_args(runner, run_env)
        if compose_args is None:
            evidence = {
                "reason": "POSTGRES_COMPOSE_GRAPH_UNAVAILABLE",
                "failure_class": "COMPOSE_GRAPH_UNAVAILABLE",
                "exit_code": 2,
                "stdout_sha256": _sha(""),
                "stderr_sha256": _sha(""),
                "diagnostic_tail": [],
            }
            emit_probe_failure(evidence)
            return evidence
        return ensure_postgres_ready(
            runner, env=run_env, compose_args=compose_args)

    def preparation(runner, *, env, runtime_ref, commit, **kwargs):
        if phase._PHASE.get("certified"):
            failure = ready(runner, env)
            if failure is not None:
                _append_preparation_failure(runner, failure)
                return go.PreparationSummary(
                    status=go.NOT_PROVEN,
                    runtime_image_digest=(
                        str(runtime_ref)
                        if runtime_ref is not None
                        and go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None
                        else None),
                    schema_migration_attempted=False,
                    bounded_sharadar_daily_attempted=False,
                    broker_mutation_attempts=0,
                    evidence_sha256=go._evidence_digest({
                        "reason": failure["reason"],
                        "failure_class": failure["failure_class"],
                        "exit_code": failure["exit_code"],
                        "stdout_sha256": failure["stdout_sha256"],
                        "stderr_sha256": failure["stderr_sha256"],
                        "mutation_attempted": False,
                    }),
                )
        return original_preparation(
            runner, env=env, runtime_ref=runtime_ref, commit=commit, **kwargs)

    def parity(runner, *, env, commit, candidate_image_digest, now_text,
               subject_values=None, timing_values=None):
        if phase._PHASE.get("prepared"):
            failure = ready(runner, env)
            if failure is not None:
                return go.make_gate(
                    "wealth_core_nas_parity", go.NOT_PROVEN, now_text, failure)
        recording = RecordingRunner(runner)
        result = original_parity(
            recording, env=env, commit=commit,
            candidate_image_digest=candidate_image_digest,
            now_text=now_text, subject_values=subject_values,
            timing_values=timing_values)
        child = recording.last_compose_run()
        report = _json_object(child.stdout or "") if child is not None else None
        if result.status != go.PASS and child is not None and report is None:
            evidence = (subprocess_evidence(child, context="FORWARD_CHAIN")
                        if int(child.returncode) != 0
                        else malformed_report_evidence(child, context="FORWARD_CHAIN"))
            emit_probe_failure(evidence)
            return go.make_gate(
                "wealth_core_nas_parity",
                go.FAIL if int(child.returncode) not in {124, 127} else go.NOT_PROVEN,
                now_text, evidence)
        return result

    def readiness(runner, *, env, runtime_ref, now_text):
        if phase._PHASE.get("prepared"):
            failure = ready(runner, env)
            if failure is not None:
                return go.make_gate(
                    "sharadar_readiness", go.NOT_PROVEN, now_text, failure)
        recording = RecordingRunner(runner)
        result = original_readiness(
            recording, env=env, runtime_ref=runtime_ref, now_text=now_text)
        child = recording.last_compose_run()
        report = (_marker_object(child.stdout or "", "SENTINEL_GO_READINESS=")
                  if child is not None else None)
        if result.status != go.PASS and child is not None and report is None:
            evidence = (subprocess_evidence(child, context="SHARADAR_READINESS")
                        if int(child.returncode) != 0
                        else malformed_report_evidence(
                            child, context="SHARADAR_READINESS"))
            emit_probe_failure(evidence)
            return go.make_gate(
                "sharadar_readiness",
                go.FAIL if int(child.returncode) not in {124, 127} else go.NOT_PROVEN,
                now_text, evidence)
        return result

    def database(runner, *, env, runtime_ref, now_text,
                 bounded_ingest_milliseconds,
                 full_forward_decision_replay_milliseconds):
        if phase._PHASE.get("prepared"):
            failure = ready(runner, env)
            if failure is not None:
                summary = go.unavailable_database_health(
                    runtime_image_digest=runtime_ref,
                    reason=str(failure["reason"]), status=go.NOT_PROVEN)
                return summary, go.make_gate(
                    "database_financial_health", go.NOT_PROVEN,
                    now_text, failure)
        recording = RecordingRunner(runner)
        summary, gate = original_database(
            recording, env=env, runtime_ref=runtime_ref,
            now_text=now_text,
            bounded_ingest_milliseconds=bounded_ingest_milliseconds,
            full_forward_decision_replay_milliseconds=(
                full_forward_decision_replay_milliseconds))
        child = recording.last_compose_run()
        report = (_marker_object(
            child.stdout or "", "SENTINEL_GO_DATABASE_HEALTH=")
            if child is not None else None)
        if gate.status != go.PASS and child is not None and report is None:
            evidence = (subprocess_evidence(child, context="DATABASE_HEALTH")
                        if int(child.returncode) != 0
                        else malformed_report_evidence(child, context="DATABASE_HEALTH"))
            emit_probe_failure(evidence)
            status = go.FAIL if int(child.returncode) not in {124, 127} else go.NOT_PROVEN
            summary = go.unavailable_database_health(
                runtime_image_digest=runtime_ref,
                reason=str(evidence["reason"]), status=status)
            return summary, go.make_gate(
                "database_financial_health", status, now_text, evidence)
        return summary, gate

    def actual(runner, *, env, runtime_ref):
        if phase._PHASE.get("prepared"):
            failure = ready(runner, env)
            if failure is not None:
                return None
        recording = RecordingRunner(runner)
        result = original_actual(recording, env=env, runtime_ref=runtime_ref)
        if result is None:
            child = recording.last_compose_run()
            if child is not None:
                evidence = (subprocess_evidence(child, context="ACTUAL_DEADLINE")
                            if int(child.returncode) != 0
                            else malformed_report_evidence(
                                child, context="ACTUAL_DEADLINE"))
                emit_probe_failure(evidence)
        return result

    entry.probe_prevalidation_preparation = preparation
    go.probe_active_wealth_parity = parity
    go.probe_sharadar_readiness = readiness
    go.probe_database_financial_health = database
    controller._actual_remaining_ms = actual
    controller._classify_preparation_failure = lambda text: (
        classify_preparation_failure(text, original_classify))
    setattr(controller, _INSTALLED_MARKER, True)
