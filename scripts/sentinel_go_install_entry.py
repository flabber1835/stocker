#!/usr/bin/env python3
"""Wall-clock-independent DUAL_RUN_OBSERVATION installation authority.

The existing GO implementation correctly proves session-level causal authority,
but it historically used those volatile facts as prerequisites for selecting and
installing an exact certified runtime.  That made installation possible only in
the narrow source-final -> following-open window.

This entry keeps every session/economic gate fail-closed and adds one narrower
meaning for DUAL_RUN_GO: the reviewed dual-run services may be installed while
fenced and wait for a causally eligible session.  SHADOW_GO and
PAPER_EXECUTION_GO retain their original session-level semantics.

A deferred installation is allowed only when:
* exact artifact certification passed;
* backup durability and schema migration actually ran;
* the preparation subprocess returned its normal success marker and skipped the
  daily catch-up only because source-finality or the following-open window was
  not currently eligible;
* structural database health, the full forward differential, Git identity,
  Alpaca PAPER GET-only inspection, and the zero-mutation boundary pass.

The resulting public bundle states that bounded Sharadar daily ingest was not
attempted and omits a stale data-publication genesis binding.  The autonomous
installer must re-earn readiness/parity and bind the exact publication before it
may create observation authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sys
from typing import Mapping, Optional, Sequence

import sentinel_go_verified_entry as verified


controller = verified.controller
go = verified.go
phase = verified.phase

WAIT_POLICY = "CAUSAL_SESSION_BINDING_AFTER_SOURCE_FINAL_V1"
WAIT_POLICY_SUBJECT = "deployment_wait_policy"
_PREPARATION_MARKER = "SENTINEL_GO_PREPARATION="
_PREPARATION_FAILURE_MARKER = "SENTINEL_GO_PREPARATION_FAILURE="

_BASE_PHASED = verified._ORIGINAL_PHASED
_BASE_DERIVE = go.derive_verdicts
_BASE_EMIT = phase._ORIGINAL_EMIT


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
        # Keep the economically important fact visible.  PASS here means the
        # *installation* preparation completed; it never claims a daily ingest.
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
    """Return the exact benign timing reason; None means no relaxation."""
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
        # Both timing prerequisites were available.  Skipping the daily path in
        # that state is not benign and must remain a hard failure.
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
    """Database properties that are invariant with respect to current wall clock."""
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
        try:
            observed = phase._parse_utc(self.observed_at)
        except Exception:  # fail closed on a malformed clock witness
            return None
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
        # A current publication may be perfectly coherent yet already be too
        # late for genesis, or it may be one source-final session behind.  Never
        # freeze that transient publication into a deployment that is explicitly
        # going to wait for a later causal session.
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
        paper = go.PAPER_NO_GO
        for key in ("shadow", "paper_execution"):
            failures[key].append("SESSION_TIMING_NOT_READY")
            failures[key] = sorted(set(failures[key]))

    gates = go._gate_map(probes.gates)
    install_gates = (
        "git_identity", "certified_suite_no_skips",
        "database_financial_health", "wealth_core_nas_parity",
        "alpaca_paper_account", "zero_mutation_boundary",
    )
    install_safe = bool(
        probes.input_mode == "PRODUCTION"
        and probes.broker_mutation_attempts == 0
        and probes.production_db_writes == 0
        and probes.preparation is not None
        and probes.preparation.complete
        and health is not None and health.complete
        and all(gates[name].status == go.PASS for name in install_gates)
        and probes.tests.complete
        and probes.git.branch_is_main
        and probes.git.clean
        and probes.git.matches_origin_main
    )
    if install_safe:
        dual = go.DUAL_RUN_GO
        failures["dual_run"] = []
    return shadow, dual, paper, failures


def emit_installable(*args, **kwargs):
    """Cap session-ready bundles; waiting installation evidence is not time-windowed."""
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
    # phase.install() resolves these globals when called by the verified entry.
    phase._preparation_guarded = _preparation_guarded
    phase.StrictDatabaseHealthView = InstallCompatibleDatabaseHealthView
    controller.DatabaseHealthView = InstallCompatibleDatabaseHealthView
    verified.DeploymentCompatibleDatabaseHealthView = InstallCompatibleDatabaseHealthView
    phase._emit_at_completion = emit_installable
    go.derive_verdicts = derive_installable_verdicts
    verified._ORIGINAL_PHASED = run_installable_phased


def main(argv: Optional[Sequence[str]] = None) -> int:
    _install_overlay()
    return verified.main(list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
