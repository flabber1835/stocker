#!/usr/bin/env python3
"""Wall-clock-independent DUAL_RUN_OBSERVATION installation authority.

The retained GO verdicts remain session/economic verdicts.  This entry adds a
separate requested-target rule for installing the exact certified dual-run
software while it is fenced and waiting for a causally eligible session.

A waiting installation never becomes SHADOW_GO, DUAL_RUN_GO, or
PAPER_EXECUTION_GO merely because the software can be installed.  Those verdicts
continue to require current Sharadar readiness and the reviewed pre-open timing
window.  Runtime promotion is permitted from a waiting bundle only when every
non-session installation invariant is independently proved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sys
from typing import Mapping, Optional, Sequence
import zipfile

import sentinel_go_verified_entry as verified


controller = verified.controller
go = verified.go
phase = verified.phase

WAIT_POLICY = "CAUSAL_SESSION_BINDING_AFTER_SOURCE_FINAL_V1"
WAIT_POLICY_SUBJECT = "deployment_wait_policy"
_PREPARATION_MARKER = "SENTINEL_GO_PREPARATION="
_PREPARATION_FAILURE_MARKER = "SENTINEL_GO_PREPARATION_FAILURE="
_ALLOWED_WAIT_DUAL_FAILURES = frozenset({
    "GATE_SHARADAR_READINESS_NOT_PASS",
    "SHADOW_STATE_NOT_FRESH",
    "SESSION_TIMING_NOT_READY",
})

_BASE_PHASED = verified._ORIGINAL_PHASED
_BASE_DERIVE = go.derive_verdicts
_BASE_EMIT = phase._ORIGINAL_EMIT
_BASE_TARGET_OK = controller._target_ok


@dataclass(frozen=True)
class DeploymentPreparationView:
    """Installation-complete preparation with session catch-up explicitly deferred."""

    base: object
    deferred: bool
    deferred_reason: Optional[str] = None

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def status(self):
        return go.PASS if self.deferred else self.base.status

    @property
    def elapsed_milliseconds(self):
        # No Sharadar ingest occurred in the deferred case.  The base elapsed
        # measurement includes schema/bootstrap work and must not be relabelled
        # as bounded vendor-ingest latency by the downstream database probe.
        return 0 if self.deferred else self.base.elapsed_milliseconds

    @property
    def complete(self):
        if not self.deferred:
            return bool(self.base.complete)
        return bool(
            self.base.runtime_image_digest is not None
            and go._IMAGE_DIGEST.fullmatch(
                str(self.base.runtime_image_digest)) is not None
            and self.base.schema_migration_attempted is True
            and self.base.bounded_sharadar_daily_attempted is False
            and self.base.broker_mutation_attempts == 0
            and go._HEX64.fullmatch(
                str(self.base.evidence_sha256 or "")) is not None
        )

    def to_dict(self):
        value = dict(self.base.to_dict())
        if not self.deferred:
            return value
        value["status"] = go.PASS
        value["completed_before_validation_boundary"] = True
        value["bounded_sharadar_daily_attempted"] = False
        value["evidence_sha256"] = go._evidence_digest({
            "base_preparation_evidence_sha256": self.base.evidence_sha256,
            "installation_policy": WAIT_POLICY,
            "deferred_reason": self.deferred_reason,
        })
        return value


def _preparation_payload(runner) -> Optional[Mapping[str, object]]:
    text = str(getattr(runner, "last_preparation_output", "") or "")
    if _PREPARATION_FAILURE_MARKER in text:
        return None
    payload = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(_PREPARATION_MARKER):
            continue
        try:
            candidate = json.loads(line[len(_PREPARATION_MARKER):])
        except (TypeError, ValueError):
            return None
        payload = candidate if isinstance(candidate, dict) else None
    return payload


def _deferred_preparation(result, runner) -> Optional[str]:
    """Return the exact benign timing reason; None keeps the base hard failure."""
    payload = _preparation_payload(runner)
    expected = {
        "schema_migrated", "source_not_before_satisfied",
        "following_open_future", "bounded_sharadar_daily",
        "publication_current",
    }
    if (not isinstance(payload, dict) or set(payload) != expected
            or payload.get("schema_migrated") is not True
            or payload.get("bounded_sharadar_daily") is not False
            or type(payload.get("source_not_before_satisfied")) is not bool
            or type(payload.get("following_open_future")) is not bool
            or type(payload.get("publication_current")) is not bool
            or result.schema_migration_attempted is not True
            or result.bounded_sharadar_daily_attempted is not False
            or result.broker_mutation_attempts != 0):
        return None
    source_final = payload["source_not_before_satisfied"]
    prospective = payload["following_open_future"]
    if source_final and prospective:
        return None
    if not source_final:
        return "SHARADAR_SOURCE_NOT_FINAL"
    return "FOLLOWING_EXECUTION_OPEN_NOT_FUTURE"


def _preparation_guarded(*args, **kwargs):
    if not phase._PHASE["certified"]:
        phase._PHASE["prepared"] = False
        return phase._unavailable_preparation(
            kwargs.get("runtime_ref"), "CERTIFICATION_NOT_PASS_NO_MUTATION")
    result = phase._ORIGINAL_PREPARATION(*args, **kwargs)
    runner = args[0] if args else kwargs.get("runner")
    reason = _deferred_preparation(result, runner)
    view = DeploymentPreparationView(
        result, deferred=reason is not None, deferred_reason=reason)
    phase._PHASE["prepared"] = bool(view.complete)
    if view.deferred:
        print(
            "GO installation preparation: PASS - %s; session catch-up deferred"
            % reason,
            flush=True,
        )
    return view


def _structural_database_complete(base) -> bool:
    """Database properties invariant with respect to the current wall clock."""
    try:
        checks = dict(base.checks)
        counts = dict(base.counts)
        measured = dict(base.measured_milliseconds)
        thresholds = dict(base.threshold_milliseconds)
        deadline = dict(base.deadline_milliseconds)
    except (AttributeError, TypeError, ValueError):
        return False

    if (base.runtime_image_digest is None
            or go._IMAGE_DIGEST.fullmatch(
                str(base.runtime_image_digest)) is None
            or go._HEX64.fullmatch(str(base.evidence_sha256 or "")) is None
            or base.production_db_writes != 0
            or set(checks) != set(go.DATABASE_CHECK_IDS)
            or any(type(value) is not bool for value in checks.values())):
        return False
    structural_checks = set(go.DATABASE_CHECK_IDS) - {"prospective_trading_window"}
    if any(checks[name] is not True for name in structural_checks):
        return False

    expected_counts = {
        "publication_versions", "publication_chain_gaps",
        "duplicate_publication_run_ids", "recent_xnys_sessions",
        "frontier_security_rows", "frontier_duplicate_security_keys",
        "warmup_revision_sessions",
    }
    expected_timings = {
        "bounded_sharadar_ingest", "full_forward_decision_replay",
        "warmup_revision_scan", "combined_pretrade_work",
    }
    expected_deadline = {
        "minimum_source_final_to_following_open",
        "observed_source_final_to_following_open",
        "minimum_remaining_margin", "measured_remaining_margin",
    }
    if (set(counts) != expected_counts
            or set(measured) != expected_timings
            or set(thresholds) != expected_timings
            or set(deadline) != expected_deadline):
        return False
    for values in (counts, measured, thresholds, deadline):
        if any(type(value) is not int or value < 0 for value in values.values()):
            return False

    fixed_thresholds = {
        "bounded_sharadar_ingest": go.MAX_BOUNDED_INGEST_MS,
        "full_forward_decision_replay": go.MAX_FULL_FORWARD_DECISION_REPLAY_MS,
        "warmup_revision_scan": go.MAX_WARMUP_REVISION_SCAN_MS,
        "combined_pretrade_work": go.MAX_COMBINED_PRETRADE_WORK_MS,
    }
    return bool(
        counts["publication_versions"] > 0
        and counts["publication_chain_gaps"] == 0
        and counts["duplicate_publication_run_ids"] == 0
        and counts["recent_xnys_sessions"] == 252
        and counts["frontier_security_rows"] > 0
        and counts["frontier_duplicate_security_keys"] == 0
        and counts["warmup_revision_sessions"] == 252
        and thresholds == fixed_thresholds
        and all(measured[name] <= thresholds[name] for name in expected_timings)
        and measured["combined_pretrade_work"] == sum(
            measured[name] for name in (
                "bounded_sharadar_ingest", "full_forward_decision_replay",
                "warmup_revision_scan"))
        and deadline["minimum_source_final_to_following_open"]
            == go.MIN_SOURCE_FINAL_TO_OPEN_MS
        and deadline["observed_source_final_to_following_open"]
            >= go.MIN_SOURCE_FINAL_TO_OPEN_MS
        and deadline["minimum_remaining_margin"]
            == go.MIN_REMAINING_DEADLINE_MARGIN_MS
    )


@dataclass(frozen=True)
class InstallCompatibleDatabaseHealthView:
    base: object
    actual_remaining_to_execution_open_ms: Optional[int]
    observed_at: str

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def complete(self):
        return _structural_database_complete(self.base)

    @property
    def session_ready(self):
        return bool(
            self.base.complete
            and type(self.actual_remaining_to_execution_open_ms) is int
            and self.actual_remaining_to_execution_open_ms
                >= go.MIN_REMAINING_DEADLINE_MARGIN_MS
        )

    def remaining_now_ms(self):
        if type(self.actual_remaining_to_execution_open_ms) is not int:
            return None
        observed = phase._parse_utc(self.observed_at)
        if observed is None:
            return None
        elapsed = max(
            0, int((datetime.now(timezone.utc) - observed).total_seconds() * 1000))
        return max(0, self.actual_remaining_to_execution_open_ms - elapsed)

    def to_dict(self):
        value = dict(self.base.to_dict())
        if self.complete:
            value["status"] = go.PASS
            value["evidence_sha256"] = go._evidence_digest({
                "base_database_evidence_sha256": self.base.evidence_sha256,
                "installation_policy": WAIT_POLICY,
                "prospective_trading_window": bool(
                    self.base.checks.get("prospective_trading_window")),
            })
        return value


def _session_ready(health) -> bool:
    return bool(getattr(health, "session_ready", False))


def run_installable_phased(*args, **kwargs):
    probes = _BASE_PHASED(*args, **kwargs)
    gates = dict(probes.gates)
    health = probes.database_health
    if health is not None and health.complete:
        gates["database_financial_health"] = go.make_gate(
            "database_financial_health", go.PASS,
            go._utc_text(datetime.now(timezone.utc)),
            {"installation_structural_health": True,
             "session_timing_ready": _session_ready(health),
             "base_evidence_sha256": health.base.evidence_sha256},
        )

    subjects = dict(probes.subject_values)
    waiting = bool(
        isinstance(probes.preparation, DeploymentPreparationView)
        and probes.preparation.deferred)
    waiting = waiting or gates["sharadar_readiness"].status != go.PASS
    waiting = waiting or not _session_ready(health)
    if waiting:
        subjects.pop("data_publication", None)
        subjects[WAIT_POLICY_SUBJECT] = WAIT_POLICY

    return go.ProbeResults(
        git=probes.git, tests=probes.tests, gates=gates,
        subject_values=subjects,
        broker_mutation_attempts=probes.broker_mutation_attempts,
        production_db_writes=probes.production_db_writes,
        input_mode=probes.input_mode,
        preparation=probes.preparation,
        database_health=health,
    )


def derive_installable_verdicts(probes):
    shadow, dual, paper, failures = _BASE_DERIVE(probes)
    failures = {key: list(value) for key, value in failures.items()}
    health = probes.database_health
    if health is None or not _session_ready(health):
        shadow = go.SHADOW_NO_GO
        dual = go.DUAL_RUN_NO_GO
        paper = go.PAPER_NO_GO
        for key in ("shadow", "dual_run", "paper_execution"):
            failures[key].append("SESSION_TIMING_NOT_READY")
            failures[key] = sorted(set(failures[key]))
    return shadow, dual, paper, failures


def _wait_failures_safe(validation: Mapping) -> bool:
    failures = validation.get("machine_failures")
    if not isinstance(failures, dict):
        return False
    dual = failures.get("dual_run")
    return bool(
        isinstance(dual, list)
        and dual
        and len(set(dual)) == len(dual)
        and all(isinstance(item, str) for item in dual)
        and set(dual).issubset(_ALLOWED_WAIT_DUAL_FAILURES)
    )


def _document_install_safe(validation: Mapping, tests: Mapping) -> bool:
    try:
        if (validation.get("dual_run_verdict") != go.DUAL_RUN_NO_GO
                or not _wait_failures_safe(validation)):
            return False
        subjects = {
            str(item["kind"]): str(item["digest"])
            for item in validation["subjects"]
            if isinstance(item, dict) and set(item) == {"kind", "digest"}
        }
        expected_wait = go._subject_digest(WAIT_POLICY_SUBJECT, WAIT_POLICY)
        if (subjects.get(WAIT_POLICY_SUBJECT) != expected_wait
                or "data_publication" in subjects):
            return False
        prep = validation["preparation"]
        if (prep.get("status") != go.PASS
                or prep.get("schema_migration_attempted") is not True
                or type(prep.get("bounded_sharadar_daily_attempted")) is not bool
                or prep.get("completed_before_validation_boundary") is not True
                or prep.get("broker_mutation_attempts") != 0):
            return False
        database = validation["database_financial_health"]
        if database.get("status") != go.PASS:
            return False
        checks = database["checks"]
        structural = set(go.DATABASE_CHECK_IDS) - {"prospective_trading_window"}
        if (set(checks) != set(go.DATABASE_CHECK_IDS)
                or any(checks[name] is not True for name in structural)
                or type(checks["prospective_trading_window"]) is not bool):
            return False
        gates = {item["id"]: item["status"] for item in validation["gates"]}
        install_gates = (
            "git_identity", "certified_suite_no_skips",
            "database_financial_health", "wealth_core_nas_parity",
            "alpaca_paper_account", "zero_mutation_boundary",
        )
        if (set(gates) != set(go.GATE_IDS)
                or any(gates[name] != go.PASS for name in install_gates)):
            return False
        git = validation["git"]
        runtime = validation["runtime"]
        if (git.get("branch") != "main" or git.get("clean") is not True
                or git.get("matches_origin_main") is not True
                or go._HEX40.fullmatch(str(git.get("commit") or "")) is None
                or go._IMAGE_DIGEST.fullmatch(
                    str(runtime.get("candidate_image_digest") or "")) is None
                or go._IMAGE_DIGEST.fullmatch(
                    str(runtime.get("runtime_image_digest") or "")) is None
                or go._HEX64.fullmatch(
                    str(runtime.get("source_identity_sha256") or "")) is None):
            return False
        if (tests.get("complete") is not True
                or tests.get("candidate_image_digest")
                    != runtime.get("candidate_image_digest")
                or tests.get("runtime_image_digest")
                    != runtime.get("runtime_image_digest")
                or tests.get("source_identity_sha256")
                    != runtime.get("source_identity_sha256")):
            return False
        shadow_state = validation["shadow_state"]
        return bool(shadow_state.get("internally_coherent") is True)
    except (KeyError, TypeError, ValueError):
        return False


def install_target_ok(result, target: str) -> bool:
    if _BASE_TARGET_OK(result, target):
        return True
    if target != controller.TARGET_DUAL or not result.upload_permitted:
        return False
    try:
        if go.sha256_bytes(result.path.read_bytes()) != result.sha256:
            return False
        go.validate_zip_members(result.path)
        with zipfile.ZipFile(result.path, "r") as archive:
            validation = json.loads(archive.read("validation.json").decode("ascii"))
            tests = json.loads(archive.read("test-summary.json").decode("ascii"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, go.ValidationRefused):
        return False
    safe = _document_install_safe(validation, tests)
    if safe:
        print(
            "requested DUAL_RUN_OBSERVATION installation: GO - runtime may be "
            "promoted fenced; session verdict remains %s"
            % result.dual_run_verdict,
            flush=True,
        )
    return safe


def emit_installable(*args, **kwargs):
    """Cap session-ready evidence; waiting installation evidence is not windowed."""
    completed_at = datetime.now(timezone.utc).replace(microsecond=0)
    kwargs["created_at"] = completed_at
    probes = args[0] if args else None
    health = getattr(probes, "database_health", None)
    if health is not None and _session_ready(health):
        remaining = health.remaining_now_ms()
        if type(remaining) is int:
            usable = remaining - go.MIN_REMAINING_DEADLINE_MARGIN_MS
            if usable <= 0:
                raise go.ValidationRefused(
                    "GO session evidence lost its minimum pre-open margin before emission")
            requested = kwargs.get("valid_for", timedelta(hours=24))
            kwargs["valid_for"] = min(
                requested, timedelta(milliseconds=usable))
    return _BASE_EMIT(*args, **kwargs)


def _install_overlay():
    phase._preparation_guarded = _preparation_guarded
    phase.StrictDatabaseHealthView = InstallCompatibleDatabaseHealthView
    controller.DatabaseHealthView = InstallCompatibleDatabaseHealthView
    verified.DeploymentCompatibleDatabaseHealthView = InstallCompatibleDatabaseHealthView
    phase._emit_at_completion = emit_installable
    go.derive_verdicts = derive_installable_verdicts
    verified._ORIGINAL_PHASED = run_installable_phased
    controller._target_ok = install_target_ok


def main(argv: Optional[Sequence[str]] = None) -> int:
    _install_overlay()
    return verified.main(list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
