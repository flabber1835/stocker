#!/usr/bin/env python3
"""Wall-clock-independent DUAL_RUN_OBSERVATION installation authority.

This import-only overlay separates exact software installation from volatile
session authority.  The public SHADOW/DUAL/PAPER verdicts keep their original
economic meanings.  A separate fenced-installation acceptance may promote the
exact certified runtime while the next decision session is waiting.

The source-final preparation overlay has already caught the corpus up through
the newest causally final session.  This layer never converts an arbitrary
Sharadar readiness failure into a waiting state: a private read-only classifier
must prove that the sole failure is freshness for sessions whose reviewed
source-final not-before has not elapsed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sys
from typing import Mapping, Optional
import zipfile

import sentinel_go_verified_entry as verified


controller = verified.controller
go = verified.go
phase = verified.phase

WAIT_POLICY = "CAUSAL_SESSION_BINDING_AFTER_SOURCE_FINAL_V1"
WAIT_POLICY_SUBJECT = "deployment_wait_policy"
_ALLOWED_WAIT_DUAL_FAILURES = frozenset({
    "GATE_SHARADAR_READINESS_NOT_PASS",
    "SHADOW_STATE_NOT_FRESH",
    "SESSION_TIMING_NOT_READY",
})

_BASE_PHASED = verified._ORIGINAL_PHASED
_BASE_DERIVE = go.derive_verdicts
_BASE_EMIT = phase._ORIGINAL_EMIT
_BASE_TARGET_OK = controller._target_ok


_WAIT_READINESS_CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel.feed import readiness, store
from sentinel.shadow_runtime import publication_not_before

c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    with c.cursor() as cur:
        cur.execute('BEGIN TRANSACTION READ ONLY')
        cur.execute('SHOW transaction_read_only')
        assert str(cur.fetchone()[0]).lower() == 'on'
    result = readiness.check_readiness(c)
    failures = list(result.failures)
    freshness = [item for item in failures if str(item.name) == 'freshness']
    missing = []
    if len(freshness) == 1 and isinstance(freshness[0].value, dict):
        raw = freshness[0].value.get('missing_sessions')
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            missing = raw
    now = datetime.now(timezone.utc)
    nonfinal = bool(
        missing
        and all(now < publication_not_before(session) for session in missing))
    only_nonfinal_freshness = bool(
        not result.ready and len(failures) == 1
        and len(freshness) == 1 and nonfinal)
    print('SENTINEL_GO_WAIT_READINESS=' + json.dumps({
        'ready': bool(result.ready),
        'only_nonfinal_freshness': only_nonfinal_freshness,
        'failure_count': len(failures),
        'missing_session_count': len(missing),
        'transaction_read_only': True,
    }, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()


def _readiness_wait_is_temporal(
        runner, *, env: Mapping[str, str], runtime_ref: Optional[str]) -> bool:
    if (not runtime_ref
            or go._IMAGE_DIGEST.fullmatch(str(runtime_ref)) is None
            or not env.get("SENTINEL_POSTGRES_PASSWORD")):
        return False
    run_env = go._without_broker_authority(env)
    compose_args = go._resolve_compose_args(runner, run_env)
    if compose_args is None:
        return False
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    completed = runner.run([
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
        "-c", _WAIT_READINESS_CODE,
    ], env=run_env)
    marker = "SENTINEL_GO_WAIT_READINESS="
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    expected = {
        "ready", "only_nonfinal_freshness", "failure_count",
        "missing_session_count", "transaction_read_only",
    }
    return bool(
        isinstance(payload, dict)
        and set(payload) == expected
        and payload.get("transaction_read_only") is True
        and type(payload.get("ready")) is bool
        and type(payload.get("only_nonfinal_freshness")) is bool
        and type(payload.get("failure_count")) is int
        and payload["failure_count"] >= 0
        and type(payload.get("missing_session_count")) is int
        and payload["missing_session_count"] >= 0
        and payload.get("only_nonfinal_freshness") is True)


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
            == go.MIN_REMAINING_DEADLINE_MARGIN_MS)


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
                >= go.MIN_REMAINING_DEADLINE_MARGIN_MS)

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
             "base_evidence_sha256": health.base.evidence_sha256})

    subjects = dict(probes.subject_values)
    readiness_pass = gates["sharadar_readiness"].status == go.PASS
    temporal_readiness_wait = False
    if not readiness_pass:
        runner = args[0] if args else kwargs.get("runner")
        if runner is None:
            runner = controller.DiagnosticRunner()
        resolved_env = dict(kwargs.get("env") or go.merged_environment())
        temporal_readiness_wait = _readiness_wait_is_temporal(
            runner, env=resolved_env,
            runtime_ref=probes.tests.runtime_image_digest)

    waiting = (not readiness_pass) or not _session_ready(health)
    safe_wait = readiness_pass or temporal_readiness_wait
    if waiting and safe_wait:
        subjects.pop("data_publication", None)
        subjects[WAIT_POLICY_SUBJECT] = WAIT_POLICY

    return go.ProbeResults(
        git=probes.git, tests=probes.tests, gates=gates,
        subject_values=subjects,
        broker_mutation_attempts=probes.broker_mutation_attempts,
        production_db_writes=probes.production_db_writes,
        input_mode=probes.input_mode,
        preparation=probes.preparation,
        database_health=health)


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
        isinstance(dual, list) and dual
        and len(set(dual)) == len(dual)
        and all(isinstance(item, str) for item in dual)
        and set(dual).issubset(_ALLOWED_WAIT_DUAL_FAILURES))


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
                or prep.get("bounded_sharadar_daily_attempted") is not True
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
            "alpaca_paper_account", "zero_mutation_boundary")
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
        return validation["shadow_state"].get("internally_coherent") is True
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
    except (OSError, KeyError, ValueError, zipfile.BadZipFile,
            go.ValidationRefused):
        return False
    safe = _document_install_safe(validation, tests)
    if safe:
        print(
            "requested DUAL_RUN_OBSERVATION installation: GO - exact runtime "
            "may be promoted fenced; session verdict remains %s"
            % result.dual_run_verdict,
            flush=True)
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


def _install_overlay() -> None:
    phase.StrictDatabaseHealthView = InstallCompatibleDatabaseHealthView
    controller.DatabaseHealthView = InstallCompatibleDatabaseHealthView
    verified.DeploymentCompatibleDatabaseHealthView = InstallCompatibleDatabaseHealthView
    phase._emit_at_completion = emit_installable
    go.derive_verdicts = derive_installable_verdicts
    verified._ORIGINAL_PHASED = run_installable_phased
    controller._target_ok = install_target_ok


def main(argv=None) -> int:
    print(
        "REFUSED: sentinel_go_install_entry.py is internal; use "
        "scripts/sentinel-go-validate.sh",
        file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
