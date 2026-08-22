#!/usr/bin/env python3
"""Produce the sanitized NAS financial validation bundle.

The production path gathers facts itself.  It never accepts a hand-authored
PASS record and never sends a broker mutation. Before the zero-write evidence
boundary, it uses the exact candidate runtime for one explicit, bounded
schema-migration + Sharadar-daily preparation. The later parity/readiness
validation is read-only and reports zero production DB writes. A small
development-input seam exists for deterministic tests, but is permanently
ineligible for either deployment verdict.

Only derived booleans, counts, timestamps, and one-way digests cross into the
ZIP.  Raw command logs, API responses, identifiers, paths, and credentials do
not.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote, quote_plus
import urllib.error
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sentinel.nas-go-validation/1"
INPUT_SCHEMA = "sentinel.nas-go-validation-input/1"
TEST_SCHEMA = "sentinel.nas-go-test-summary/1"
NON_FORWARD_HISTORICAL_EXCLUSIONS = (
    "tests/wealth_core/test_golden_fixture.py::"
    "test_the_result_matches_the_pinned_fixture",
    "tests/wealth_core/test_golden_fixture.py::"
    "TestTheHashesAreInterpreterIndependent::"
    "test_the_run_hash_is_stable_in_a_FRESH_INTERPRETER",
    "tests/wealth_core/test_performance_integration.py::"
    "test_measuring_does_not_move_the_pinned_result_hash",
)
MANIFEST_SCHEMA = "sentinel.nas-go-validation-manifest/1"
SCAN_SCHEMA = "sentinel.nas-go-secret-scan/1"
PREPARATION_SCHEMA = "sentinel.nas-go-preparation/1"
DATABASE_HEALTH_SCHEMA = "sentinel.nas-financial-db-health/1"
SHADOW_CONFIG_SCHEMA = "sentinel.shadow-reviewed-config/1"
DATA_PUBLICATION_SCHEMA = "sentinel.data-publication-binding/1"
SHADOW_EXECUTION_MODEL = "PROSPECTIVE_CONCORDANCE_SCALAR_CORE_BIL_V3"
SHADOW_CUTOFF_POLICY = "STRICT_BEFORE_OFFICIAL_NEXT_XNYS_OPEN_V1"
SHADOW_PUBLICATION_TIMING_POLICY = (
    "SHARADAR_SEP_SFP_SECOND_UPDATE_PLUS_15M_2345_AMERICA_NEW_YORK_V1")

GATE_IDS = (
    "git_identity",
    "certified_suite_no_skips",
    "database_financial_health",
    "wealth_core_nas_parity",
    "sharadar_readiness",
    "preopen_share_unit_authority",
    "alpaca_paper_account",
    "official_close_nav",
    "account_fill_interval",
    "close_cash_finality",
    "paper_dividend_attribution",
    "zero_mutation_boundary",
)
SHADOW_GATE_IDS = (
    "git_identity",
    "certified_suite_no_skips",
    "database_financial_health",
    "wealth_core_nas_parity",
    "sharadar_readiness",
    "zero_mutation_boundary",
)
DUAL_RUN_GATE_IDS = SHADOW_GATE_IDS + (
    "alpaca_paper_account",
)
ALLOWED_MEMBERS = frozenset({
    "validation.json",
    "test-summary.json",
    "manifest.json",
    "README.txt",
    "SHA256SUMS",
    "secret-scan.json",
})

PASS = "PASS"
FAIL = "FAIL"
NOT_PROVEN = "NOT_PROVEN"
GATE_STATUSES = frozenset({PASS, FAIL, NOT_PROVEN})
SHADOW_GO = "SHADOW_GO"
SHADOW_NO_GO = "SHADOW_NO_GO"
DUAL_RUN_GO = "DUAL_RUN_GO"
DUAL_RUN_NO_GO = "DUAL_RUN_NO_GO"
PAPER_GO = "PAPER_EXECUTION_GO"
PAPER_NO_GO = "PAPER_EXECUTION_NO_GO"

# The fixed reviewed source-final boundary is 23:45 New York and the normal
# following XNYS open is 09:30 New York: 9h45m, or 35,100 seconds.  Certification
# spends at most half of that shortest window on the three measured database
# workloads, leaving at least another 4h52m30s before the trading cutoff.  A
# weekend/holiday may provide more time but may never relax this weekday bound.
MIN_SOURCE_FINAL_TO_OPEN_MS = 35_100_000
MAX_BOUNDED_INGEST_MS = 7_200_000
MAX_FULL_FORWARD_DECISION_REPLAY_MS = 14_400_000
MAX_WARMUP_REVISION_SCAN_MS = 1_800_000
MAX_COMBINED_PRETRADE_WORK_MS = MIN_SOURCE_FINAL_TO_OPEN_MS // 2
MIN_REMAINING_DEADLINE_MARGIN_MS = (
    MIN_SOURCE_FINAL_TO_OPEN_MS - MAX_COMBINED_PRETRADE_WORK_MS)

DATABASE_CHECK_IDS = (
    "behavioral_schema_exact",
    "feed_schema_exact",
    "publication_complete",
    "publication_chain_unique_and_gap_free",
    "recent_xnys_axis_exact",
    "frontier_security_keys_unique",
    "repeatable_read_only",
    "publication_pin_excludes_writers",
    "publication_stable_under_pin",
    "required_indexes_exact",
    "predecessor_query_plan_indexed",
    "frontier_query_plan_indexed",
    "warmup_revision_input_complete",
    "prospective_trading_window",
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUMMARY_COUNT = re.compile(
    r"(?P<count>[0-9]+) (?P<kind>passed|failed|skipped|xfailed|xpassed|errors?)")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_OBSERVATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$")
_SECRET_NAMES = frozenset({
    "SHARADAR_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "SENTINEL_POSTGRES_PASSWORD",
    "BT_POSTGRES_PASSWORD",
    "SENTINEL_DATABASE_URL",
    "BT_DATABASE_URL",
    "SENTINEL_PAPER_ACCOUNT_ID",
})
_BROKER_AUTH_ENV = frozenset({
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "SENTINEL_PAPER_ACCOUNT_ID",
})
_PROHIBITED_PUBLIC_PATTERNS = (
    re.compile(rb"(?i)postgres(?:ql)?://"),
    re.compile(rb"(?i)APCA-API-(?:KEY-ID|SECRET-KEY)"),
    re.compile(rb"(?i)(?:api[_-]?key|password|authorization)\s*[:=]\s*[^\s<]+"),
    re.compile(rb"https?://[^\s?]+\?[^\s]+"),
    re.compile(rb"(?:^|[\s\"'])(?:/home/|/root/|/volume[0-9]*/|[A-Za-z]:\\\\)"),
)


class ValidationRefused(RuntimeError):
    """A validation input or artifact cannot support a safe result."""


@dataclass(frozen=True)
class Gate:
    gate_id: str
    status: str
    evidence_sha256: str
    observed_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.gate_id,
            "status": self.status,
            "evidence_sha256": self.evidence_sha256,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class GitIdentity:
    commit: Optional[str]
    branch_is_main: bool
    clean: bool
    origin_main: Optional[str]

    @property
    def matches_origin_main(self) -> bool:
        return bool(self.commit and self.origin_main == self.commit)


@dataclass(frozen=True)
class TestSummary:
    candidate_image_digest: Optional[str]
    runtime_image_digest: Optional[str]
    source_identity_sha256: Optional[str]
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    exit_code: int = 1
    suites_completed: int = 0
    auxiliary_image_digests: tuple[str, ...] = ()
    non_forward_historical_exclusions: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return (
            self.exit_code == 0
            and self.passed > 0
            and self.failed == 0
            and self.errors == 0
            and self.skipped == 0
            and self.xfailed == 0
            and self.xpassed == 0
            and self.suites_completed == 6
            and self.non_forward_historical_exclusions
            == NON_FORWARD_HISTORICAL_EXCLUSIONS
            and self.candidate_image_digest is not None
            and self.runtime_image_digest is not None
            and self.source_identity_sha256 is not None
            and len(self.auxiliary_image_digests) == 2
            and all(_IMAGE_DIGEST.fullmatch(item)
                    for item in self.auxiliary_image_digests)
        )

    def to_dict(self) -> dict:
        return {
            "schema": TEST_SCHEMA,
            "candidate_image_digest": self.candidate_image_digest,
            "runtime_image_digest": self.runtime_image_digest,
            "source_identity_sha256": self.source_identity_sha256,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "xfailed": self.xfailed,
            "xpassed": self.xpassed,
            "exit_code": self.exit_code,
            "suites_completed": self.suites_completed,
            "auxiliary_image_digests": list(self.auxiliary_image_digests),
            "non_forward_historical_exclusions": list(
                self.non_forward_historical_exclusions),
            "complete": self.complete,
        }


@dataclass(frozen=True)
class ProbeResults:
    git: GitIdentity
    tests: TestSummary
    gates: Mapping[str, Gate]
    subject_values: Mapping[str, str]
    broker_mutation_attempts: int
    production_db_writes: int
    input_mode: str = "PRODUCTION"
    preparation: Optional["PreparationSummary"] = None
    database_health: Optional["DatabaseHealthSummary"] = None


@dataclass(frozen=True)
class PreparationSummary:
    status: str
    runtime_image_digest: Optional[str]
    schema_migration_attempted: bool
    bounded_sharadar_daily_attempted: bool
    broker_mutation_attempts: int
    evidence_sha256: str
    # Kept out of the preparation document because the separate database-health
    # record publishes the measurement together with its exact deadline budget.
    elapsed_milliseconds: Optional[int] = None

    @property
    def complete(self) -> bool:
        return (
            self.status == PASS
            and self.runtime_image_digest is not None
            and _IMAGE_DIGEST.fullmatch(self.runtime_image_digest) is not None
            and self.schema_migration_attempted
            and self.bounded_sharadar_daily_attempted
            and self.broker_mutation_attempts == 0
            and _HEX64.fullmatch(self.evidence_sha256) is not None
        )

    def to_dict(self) -> dict:
        return {
            "schema": PREPARATION_SCHEMA,
            "status": self.status,
            "runtime_image_digest": self.runtime_image_digest,
            "schema_migration_attempted": self.schema_migration_attempted,
            "bounded_sharadar_daily_attempted": (
                self.bounded_sharadar_daily_attempted),
            "database_mutation_scope": [
                "SCHEMA_MIGRATION", "BOUNDED_SHARADAR_DAILY_INGEST"],
            "broker_mutation_attempts": self.broker_mutation_attempts,
            "completed_before_validation_boundary": self.complete,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True)
class DatabaseHealthSummary:
    """Sanitized, reviewable database correctness and deadline evidence."""

    status: str
    runtime_image_digest: Optional[str]
    checks: Mapping[str, bool]
    counts: Mapping[str, int]
    measured_milliseconds: Mapping[str, int]
    threshold_milliseconds: Mapping[str, int]
    deadline_milliseconds: Mapping[str, int]
    production_db_writes: int
    evidence_sha256: str

    @property
    def complete(self) -> bool:
        expected_counts = {
            "publication_versions",
            "publication_chain_gaps",
            "duplicate_publication_run_ids",
            "recent_xnys_sessions",
            "frontier_security_rows",
            "frontier_duplicate_security_keys",
            "warmup_revision_sessions",
        }
        expected_measured = {
            "bounded_sharadar_ingest",
            "full_forward_decision_replay",
            "warmup_revision_scan",
            "combined_pretrade_work",
        }
        expected_thresholds = {
            "bounded_sharadar_ingest",
            "full_forward_decision_replay",
            "warmup_revision_scan",
            "combined_pretrade_work",
        }
        expected_deadline = {
            "minimum_source_final_to_following_open",
            "observed_source_final_to_following_open",
            "minimum_remaining_margin",
            "measured_remaining_margin",
        }
        numeric_maps = (
            (self.counts, expected_counts),
            (self.measured_milliseconds, expected_measured),
            (self.threshold_milliseconds, expected_thresholds),
            (self.deadline_milliseconds, expected_deadline),
        )
        if any(set(values) != keys for values, keys in numeric_maps):
            return False
        if any(type(value) is not int or value < 0
               for values, _keys in numeric_maps for value in values.values()):
            return False
        thresholds = self.threshold_milliseconds
        measured = self.measured_milliseconds
        deadline = self.deadline_milliseconds
        return (
            self.status == PASS
            and self.runtime_image_digest is not None
            and _IMAGE_DIGEST.fullmatch(self.runtime_image_digest) is not None
            and set(self.checks) == set(DATABASE_CHECK_IDS)
            and all(value is True for value in self.checks.values())
            and self.counts["publication_chain_gaps"] == 0
            and self.counts["duplicate_publication_run_ids"] == 0
            and self.counts["publication_versions"] > 0
            and self.counts["recent_xnys_sessions"] == 252
            and self.counts["frontier_security_rows"] > 0
            and self.counts["frontier_duplicate_security_keys"] == 0
            and self.counts["warmup_revision_sessions"] == 252
            and thresholds == {
                "bounded_sharadar_ingest": MAX_BOUNDED_INGEST_MS,
                "full_forward_decision_replay": (
                    MAX_FULL_FORWARD_DECISION_REPLAY_MS),
                "warmup_revision_scan": MAX_WARMUP_REVISION_SCAN_MS,
                "combined_pretrade_work": MAX_COMBINED_PRETRADE_WORK_MS,
            }
            and all(measured[name] <= thresholds[name]
                    for name in expected_thresholds)
            and measured["combined_pretrade_work"] == sum(
                measured[name] for name in (
                    "bounded_sharadar_ingest",
                    "full_forward_decision_replay",
                    "warmup_revision_scan"))
            and deadline["minimum_source_final_to_following_open"]
                == MIN_SOURCE_FINAL_TO_OPEN_MS
            and deadline["observed_source_final_to_following_open"]
                >= MIN_SOURCE_FINAL_TO_OPEN_MS
            and deadline["minimum_remaining_margin"]
                == MIN_REMAINING_DEADLINE_MARGIN_MS
            and deadline["measured_remaining_margin"]
                == MIN_SOURCE_FINAL_TO_OPEN_MS - measured[
                    "combined_pretrade_work"]
            and deadline["measured_remaining_margin"]
                >= MIN_REMAINING_DEADLINE_MARGIN_MS
            and self.production_db_writes == 0
            and _HEX64.fullmatch(self.evidence_sha256) is not None
        )

    def to_dict(self) -> dict:
        return {
            "schema": DATABASE_HEALTH_SCHEMA,
            "status": self.status,
            "runtime_image_digest": self.runtime_image_digest,
            "checks": {
                name: bool(self.checks.get(name, False))
                for name in DATABASE_CHECK_IDS
            },
            "counts": dict(self.counts),
            "measured_milliseconds": dict(self.measured_milliseconds),
            "threshold_milliseconds": dict(self.threshold_milliseconds),
            "deadline_milliseconds": dict(self.deadline_milliseconds),
            "production_db_writes": self.production_db_writes,
            "evidence_sha256": self.evidence_sha256,
        }


def unavailable_database_health(
        *, runtime_image_digest: Optional[str], reason: str,
        status: str = NOT_PROVEN) -> DatabaseHealthSummary:
    measured = {
        "bounded_sharadar_ingest": 0,
        "full_forward_decision_replay": 0,
        "warmup_revision_scan": 0,
        "combined_pretrade_work": 0,
    }
    return DatabaseHealthSummary(
        status=status,
        runtime_image_digest=runtime_image_digest,
        checks={name: False for name in DATABASE_CHECK_IDS},
        counts={
            "publication_versions": 0,
            "publication_chain_gaps": 0,
            "duplicate_publication_run_ids": 0,
            "recent_xnys_sessions": 0,
            "frontier_security_rows": 0,
            "frontier_duplicate_security_keys": 0,
            "warmup_revision_sessions": 0,
        },
        measured_milliseconds=measured,
        threshold_milliseconds={
            "bounded_sharadar_ingest": MAX_BOUNDED_INGEST_MS,
            "full_forward_decision_replay": (
                MAX_FULL_FORWARD_DECISION_REPLAY_MS),
            "warmup_revision_scan": MAX_WARMUP_REVISION_SCAN_MS,
            "combined_pretrade_work": MAX_COMBINED_PRETRADE_WORK_MS,
        },
        deadline_milliseconds={
            "minimum_source_final_to_following_open": (
                MIN_SOURCE_FINAL_TO_OPEN_MS),
            "observed_source_final_to_following_open": 0,
            "minimum_remaining_margin": MIN_REMAINING_DEADLINE_MARGIN_MS,
            "measured_remaining_margin": MIN_SOURCE_FINAL_TO_OPEN_MS,
        },
        production_db_writes=0,
        evidence_sha256=_evidence_digest({
            "schema": DATABASE_HEALTH_SCHEMA,
            "status": status,
            "reason": reason,
            "runtime_known": runtime_image_digest is not None,
        }),
    )


@dataclass(frozen=True)
class BundleResult:
    path: Path
    sha256: str
    shadow_verdict: str
    dual_run_verdict: str
    paper_execution_verdict: str
    upload_permitted: bool


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationRefused("validation clock must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValidationRefused("validation evidence is not canonical JSON") from exc


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _evidence_digest(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def make_gate(gate_id: str, status: str, observed_at: str,
              evidence: Optional[Mapping[str, Any]] = None) -> Gate:
    if gate_id not in GATE_IDS:
        raise ValidationRefused("unknown validation gate")
    if status not in GATE_STATUSES:
        raise ValidationRefused("invalid validation gate status")
    # Evidence stays private.  Only its canonical digest is published.
    safe_binding = {
        "gate": gate_id,
        "status": status,
        "observed_at": observed_at,
        "evidence": dict(evidence or {}),
    }
    return Gate(gate_id, status, _evidence_digest(safe_binding), observed_at)


def _subject_digest(kind: str, raw: str) -> str:
    if not raw:
        raise ValidationRefused("empty validation subject")
    # This subject is consumed directly by the runtime. Its value is already
    # the exact one-way SHA-256 contract over the canonical reviewed config;
    # applying the generic envelope would create an incompatible second hash.
    if kind == "shadow_configuration":
        if _HEX64.fullmatch(raw) is None:
            raise ValidationRefused("shadow configuration digest is malformed")
        return raw
    return hashlib.sha256(
        b"sentinel-nas-subject/v1\0" + kind.encode("ascii") + b"\0"
        + raw.encode("utf-8")).hexdigest()


def shadow_configuration_document(
        env: Mapping[str, str], *, source_identity_sha256: str) -> dict:
    """Canonical, non-broker model inputs that define one shadow lineage."""
    source = str(source_identity_sha256 or "")
    if _HEX64.fullmatch(source) is None:
        raise ValidationRefused("validated source identity is malformed")
    observation_id = str(env.get(
        "SENTINEL_SHADOW_OBSERVATION_ID", "primary")).strip()
    if _OBSERVATION_ID.fullmatch(observation_id) is None:
        raise ValidationRefused(
            "shadow observation id must be 1-64 ASCII letters, digits, dots or hyphens")
    try:
        amount = Decimal(str(env.get(
            "SENTINEL_SHADOW_STARTING_CASH", "100000")).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationRefused(
            "shadow starting cash must be a positive decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValidationRefused(
            "shadow starting cash must be a positive decimal")
    publication_policy = str(env.get(
        "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY",
        SHADOW_PUBLICATION_TIMING_POLICY)).strip()
    if publication_policy != SHADOW_PUBLICATION_TIMING_POLICY:
        raise ValidationRefused(
            "shadow publication timing policy differs from the certified policy")
    return {
        "schema": SHADOW_CONFIG_SCHEMA,
        "observation_id": observation_id,
        "starting_cash": format(amount.normalize(), "f"),
        "execution_model": SHADOW_EXECUTION_MODEL,
        "cutoff_policy": SHADOW_CUTOFF_POLICY,
        "publication_timing_policy": publication_policy,
        "validated_source_identity_sha256": source,
    }


def shadow_configuration_sha256(
        env: Mapping[str, str], *, source_identity_sha256: str) -> str:
    document = shadow_configuration_document(
        env, source_identity_sha256=source_identity_sha256)
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def data_publication_subject_value(value: Mapping[str, Any]) -> str:
    """Canonical private preimage for the held publication/frontier subject."""
    if (not isinstance(value, Mapping)
            or set(value) != {"publication_fingerprint", "visible_frontier"}
            or _HEX64.fullmatch(
                str(value.get("publication_fingerprint") or "")) is None
            or re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}",
                str(value.get("visible_frontier") or "")) is None):
        raise ValidationRefused("held data publication binding is malformed")
    return json.dumps({
        "schema": DATA_PUBLICATION_SCHEMA,
        "publication_fingerprint": str(value["publication_fingerprint"]),
        "visible_frontier": str(value["visible_frontier"]),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False)


def _gate_map(gates: Mapping[str, Gate]) -> Dict[str, Gate]:
    if set(gates) != set(GATE_IDS):
        raise ValidationRefused("validation does not contain the exact gate set")
    for gate_id, gate in gates.items():
        if gate.gate_id != gate_id or gate.status not in GATE_STATUSES:
            raise ValidationRefused("validation gate binding is malformed")
        if _HEX64.fullmatch(gate.evidence_sha256) is None:
            raise ValidationRefused("validation evidence digest is malformed")
    return {gate_id: gates[gate_id] for gate_id in GATE_IDS}


def derive_verdicts(probes: ProbeResults) -> tuple[str, str, str, dict]:
    gates = _gate_map(probes.gates)
    if (type(probes.broker_mutation_attempts) is not int
            or type(probes.production_db_writes) is not int
            or probes.broker_mutation_attempts < 0
            or probes.production_db_writes < 0):
        raise ValidationRefused("mutation counters are malformed")

    shadow_fresh = gates["sharadar_readiness"].status == PASS
    shadow_coherent = gates["wealth_core_nas_parity"].status == PASS
    shadow_failures = [
        "GATE_%s_NOT_PASS" % gate_id.upper()
        for gate_id in SHADOW_GATE_IDS if gates[gate_id].status != PASS
    ]
    if not shadow_fresh:
        shadow_failures.append("SHADOW_STATE_NOT_FRESH")
    if not shadow_coherent:
        shadow_failures.append("SHADOW_STATE_NOT_COHERENT")

    # Dual-run authorizes only the already-certified shadow strategy plus a
    # non-authoritative PAPER transport/display sidecar. The paper-only NAV,
    # fill-finality and dividend gates remain mandatory for PAPER_EXECUTION_GO.
    # Runtime plan-vs-shadow and broker-book reconciliation are independent
    # activation/operation gates and cannot promote PAPER accounting here.
    dual_failures = [
        "GATE_%s_NOT_PASS" % gate_id.upper()
        for gate_id in DUAL_RUN_GATE_IDS if gates[gate_id].status != PASS
    ]
    if not shadow_fresh:
        dual_failures.append("SHADOW_STATE_NOT_FRESH")
    if not shadow_coherent:
        dual_failures.append("SHADOW_STATE_NOT_COHERENT")

    paper_failures = [
        "GATE_%s_NOT_PASS" % gate_id.upper()
        for gate_id in GATE_IDS if gates[gate_id].status != PASS
    ]
    if probes.broker_mutation_attempts:
        shadow_failures.append("BROKER_MUTATION_BOUNDARY_BREACHED")
        dual_failures.append("BROKER_MUTATION_BOUNDARY_BREACHED")
        paper_failures.append("BROKER_MUTATION_BOUNDARY_BREACHED")
    if probes.production_db_writes:
        shadow_failures.append("PRODUCTION_DB_WRITE_BOUNDARY_BREACHED")
        dual_failures.append("PRODUCTION_DB_WRITE_BOUNDARY_BREACHED")
        paper_failures.append("PRODUCTION_DB_WRITE_BOUNDARY_BREACHED")
    if probes.input_mode != "PRODUCTION":
        shadow_failures.append("DEVELOPMENT_INPUT_NOT_DEPLOYABLE")
        dual_failures.append("DEVELOPMENT_INPUT_NOT_DEPLOYABLE")
        paper_failures.append("DEVELOPMENT_INPUT_NOT_DEPLOYABLE")
    if probes.preparation is None or not probes.preparation.complete:
        shadow_failures.append("PREVALIDATION_PREPARATION_NOT_PASS")
        dual_failures.append("PREVALIDATION_PREPARATION_NOT_PASS")
        paper_failures.append("PREVALIDATION_PREPARATION_NOT_PASS")
    if probes.database_health is None or not probes.database_health.complete:
        shadow_failures.append("DATABASE_FINANCIAL_HEALTH_NOT_PASS")
        dual_failures.append("DATABASE_FINANCIAL_HEALTH_NOT_PASS")
        paper_failures.append("DATABASE_FINANCIAL_HEALTH_NOT_PASS")

    shadow_failures = sorted(set(shadow_failures))
    dual_failures = sorted(set(dual_failures))
    paper_failures = sorted(set(paper_failures))
    return (
        SHADOW_GO if not shadow_failures else SHADOW_NO_GO,
        DUAL_RUN_GO if not dual_failures else DUAL_RUN_NO_GO,
        PAPER_GO if not paper_failures else PAPER_NO_GO,
        {
            "shadow": shadow_failures,
            "dual_run": dual_failures,
            "paper_execution": paper_failures,
        },
    )


def build_validation_document(probes: ProbeResults, *, created_at: datetime,
                              valid_for: timedelta) -> dict:
    if valid_for <= timedelta(0) or valid_for > timedelta(hours=72):
        raise ValidationRefused("validation lifetime must be in (0,72h]")
    gates = _gate_map(probes.gates)
    shadow, dual, paper, failures = derive_verdicts(probes)
    created_text = _utc_text(created_at)
    valid_text = _utc_text(created_at + valid_for)
    git_commit = probes.git.commit if (
        probes.git.commit and _HEX40.fullmatch(probes.git.commit)) else None
    origin_main = probes.git.origin_main if (
        probes.git.origin_main and _HEX40.fullmatch(probes.git.origin_main)) else None
    subjects = [
        {"kind": kind, "digest": _subject_digest(kind, raw)}
        for kind, raw in sorted(probes.subject_values.items()) if raw
    ]
    for row in subjects:
        if _SAFE_CODE.fullmatch(row["kind"].upper()) is None:
            raise ValidationRefused("validation subject kind is not safe")

    return {
        "schema": SCHEMA,
        "created_at": created_text,
        "valid_until": valid_text,
        "input_mode": probes.input_mode,
        "git": {
            "commit": git_commit,
            "branch": "main" if probes.git.branch_is_main else "OTHER",
            "clean": bool(probes.git.clean),
            "origin_main": origin_main,
            "matches_origin_main": bool(probes.git.matches_origin_main),
        },
        "runtime": {
            "candidate_image_digest": probes.tests.candidate_image_digest,
            "runtime_image_digest": probes.tests.runtime_image_digest,
            "source_identity_sha256": probes.tests.source_identity_sha256,
        },
        "preparation": (
            probes.preparation.to_dict() if probes.preparation is not None
            else PreparationSummary(
                status=NOT_PROVEN, runtime_image_digest=None,
                schema_migration_attempted=False,
                bounded_sharadar_daily_attempted=False,
                broker_mutation_attempts=0,
                evidence_sha256=_evidence_digest({
                    "reason": "PREPARATION_NOT_RECORDED"})).to_dict()),
        "database_financial_health": (
            probes.database_health.to_dict()
            if probes.database_health is not None
            else unavailable_database_health(
                runtime_image_digest=probes.tests.runtime_image_digest,
                reason="DATABASE_HEALTH_NOT_RECORDED").to_dict()),
        "subjects": subjects,
        "boundary": {
            "scope": "POST_PREPARATION_VALIDATION",
            "broker_environment": "ALPACA_PAPER",
            "allowed_financial_http_methods": ["GET"],
            "broker_mutation_attempts": probes.broker_mutation_attempts,
            "production_db_writes": probes.production_db_writes,
        },
        "shadow_state": {
            "fresh": gates["sharadar_readiness"].status == PASS,
            "internally_coherent": (
                gates["wealth_core_nas_parity"].status == PASS),
        },
        "gates": [gates[gate_id].to_dict() for gate_id in GATE_IDS],
        "shadow_verdict": shadow,
        "dual_run_verdict": dual,
        "paper_execution_verdict": paper,
        "machine_failures": failures,
        "review": {
            "status": "UNREVIEWED",
            "reviewed_bundle_digest": None,
        },
    }


def load_dotenv_literal(path: Path) -> Dict[str, str]:
    """Read KEY=VALUE without evaluating shell syntax or printing values."""
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValidationRefused("local environment file is unreadable") from exc
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValidationRefused("local environment file has a malformed line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise ValidationRefused("local environment file has an invalid key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            quote_char = value[0]
            value = value[1:-1]
            if quote_char == '"':
                value = value.replace('\\"', '"').replace("\\\\", "\\")
        values[key] = value
    return values


def merged_environment(path: Path = ROOT / ".env") -> Dict[str, str]:
    values = load_dotenv_literal(path)
    values.update(os.environ)
    return values


class CommandRunner:
    """Subprocess seam whose captured output never enters the public bundle."""

    def __init__(self, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self._run = run

    def run(self, argv: Sequence[str], *, env: Optional[Mapping[str, str]] = None,
            cwd: Path = ROOT) -> subprocess.CompletedProcess:
        command = [str(item) for item in argv]
        try:
            return self._run(
                command, cwd=str(cwd),
                env=dict(env) if env is not None else None,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False)
        except OSError:
            # A missing local executable is a failed observation, not a reason
            # to lose the rest of the evidence bundle.  Every caller treats a
            # non-zero result as FAIL/NOT_PROVEN, so this remains fail closed
            # without publishing an exception string, command path, or host
            # detail.
            return subprocess.CompletedProcess(
                command, 127, stdout="", stderr="")


def probe_git(runner: CommandRunner, *, now_text: str) -> tuple[GitIdentity, Gate]:
    def output(*args: str) -> tuple[int, str]:
        result = runner.run(["git", *args])
        return result.returncode, (result.stdout or "").strip()

    # A locally cached remote-tracking ref is not evidence of current GitHub
    # identity. Refresh only origin/main before comparing exact candidate bytes.
    rc_fetch, _fetch_output = output("fetch", "--prune", "origin", "main")
    rc_head, head = output("rev-parse", "HEAD")
    rc_branch, branch = output("symbolic-ref", "--quiet", "--short", "HEAD")
    rc_origin, origin = output("rev-parse", "origin/main")
    rc_dirty, dirty = output("status", "--porcelain", "--untracked-files=all")
    identity = GitIdentity(
        commit=head if rc_head == 0 and _HEX40.fullmatch(head) else None,
        branch_is_main=rc_branch == 0 and branch == "main",
        clean=rc_dirty == 0 and not dirty,
        origin_main=origin if rc_origin == 0 and _HEX40.fullmatch(origin) else None,
    )
    passed = (
        rc_fetch == 0 and identity.commit is not None and identity.branch_is_main
        and identity.clean and identity.matches_origin_main)
    gate = make_gate(
        "git_identity", PASS if passed else FAIL, now_text,
        {"remote_ref_refreshed": rc_fetch == 0,
         "commit_known": identity.commit is not None,
         "branch_is_main": identity.branch_is_main,
         "clean": identity.clean,
         "matches_origin_main": identity.matches_origin_main})
    return identity, gate


def _inspect_image_id(runner: CommandRunner, reference: str) -> Optional[str]:
    result = runner.run([
        "docker", "image", "inspect", "--format={{.Id}}", reference])
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and _IMAGE_DIGEST.fullmatch(value) else None


def _parse_pytest_summary(output: str) -> dict:
    counts = {
        "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
        "xfailed": 0, "xpassed": 0,
    }
    for match in _SUMMARY_COUNT.finditer("\n".join(output.splitlines()[-8:])):
        kind = match.group("kind")
        if kind in {"error", "errors"}:
            kind = "errors"
        counts[kind] = int(match.group("count"))
    return counts


def probe_certified_suite(runner: CommandRunner, *, commit: Optional[str],
                          now_text: str) -> tuple[TestSummary, Gate]:
    if commit is None:
        summary = TestSummary(None, None, None)
        return summary, make_gate(
            "certified_suite_no_skips", NOT_PROVEN, now_text,
            {"reason": "GIT_COMMIT_UNAVAILABLE"})

    runtime_ref = "sentinel-go-runtime:%s" % commit
    authorized_ref = "sentinel-go-authorized:%s" % commit
    test_ref = "sentinel-go-test:%s" % commit
    bt_engine_ref = "stocker-go-bt-engine:%s" % commit
    bt_engine_test_ref = "stocker-go-bt-engine-test:%s" % commit
    bt_data_ref = "stocker-go-bt-data:%s" % commit
    bt_data_test_ref = "stocker-go-bt-data-test:%s" % commit
    commands = (
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", runtime_ref,
         "-f", "Dockerfile.sentinel", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SENTINEL_RUNTIME_BASE_IMAGE=" + runtime_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", authorized_ref,
         "-f", "Dockerfile.sentinel-authorized", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SENTINEL_IMAGE=" + authorized_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", test_ref,
         "-f", "Dockerfile.sentinel-test", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", "stocker-base:latest",
         "-f", "Dockerfile.base", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_engine_ref,
         "-f", "services/bt-engine/Dockerfile", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "BT_ENGINE_IMAGE=" + bt_engine_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_engine_test_ref,
         "-f", "services/bt-engine/Dockerfile.test", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_data_ref,
         "-f", "services/bt-data/Dockerfile", "."],
        ["docker", "build", "--network", "host", "--build-arg",
         "BT_DATA_IMAGE=" + bt_data_ref, "--build-arg",
         "SOURCE_GIT_SHA=" + commit, "-t", bt_data_test_ref,
         "-f", "services/bt-data/Dockerfile.test", "."],
    )
    for command in commands:
        if runner.run(command).returncode != 0:
            summary = TestSummary(None, None, None)
            return summary, make_gate(
                "certified_suite_no_skips", FAIL, now_text,
                {"reason": "CANDIDATE_IMAGE_BUILD_FAILED"})

    runtime_digest = _inspect_image_id(runner, authorized_ref)
    candidate_digest = _inspect_image_id(runner, test_ref)
    bt_engine_digest = _inspect_image_id(runner, bt_engine_test_ref)
    bt_data_digest = _inspect_image_id(runner, bt_data_test_ref)
    if not all((runtime_digest, candidate_digest,
                bt_engine_digest, bt_data_digest)):
        summary = TestSummary(
            candidate_image_digest=candidate_digest,
            runtime_image_digest=runtime_digest,
            source_identity_sha256=None,
            auxiliary_image_digests=tuple(
                item for item in (bt_engine_digest, bt_data_digest) if item),
        )
        return summary, make_gate(
            "certified_suite_no_skips", FAIL, now_text,
            {"reason": "CANDIDATE_IMAGE_IDENTITY_UNAVAILABLE"})
    identity = runner.run([
        "docker", "run", "--rm", "--network", "none",
        "--entrypoint", "python", runtime_digest,
        "-m", "sentinel", "identity", "--require-certified"])
    identity_hash = None
    if identity.returncode == 0:
        try:
            payload = json.loads(identity.stdout or "")
            candidate = str(payload.get("identity_hash") or "")
            if _HEX64.fullmatch(candidate):
                identity_hash = candidate
        except (AttributeError, json.JSONDecodeError):
            identity_hash = None

    suite_commands = (
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/sentinel", "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/wealth_core",
         *(item for node in NON_FORWARD_HISTORICAL_EXCLUSIONS
           for item in ("--deselect", node)),
         "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/scripts/test_sentinel_go_validate.py",
         "tests/scripts/test_sentinel_reviewed_deploy_gate.py",
         "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", candidate_digest,
         "tests/backtester/test_cold_boot_identity.py",
         "tests/backtester/test_wealth_core_replay.py",
         "tests/backtester/test_price_volume_domain_gate.py", "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", bt_data_digest,
         "tests/bt_data/test_sharadar_adapter.py",
         "tests/bt_data/test_schema_bootstrap.py",
         "tests/bt_data/test_sf1_coverage.py",
         "tests/bt_data/test_issue_185_volume_domain_migration.py",
         "-q", "-ra"],
        ["docker", "run", "--rm", "--network", "none", bt_engine_digest,
         "tests/bt_engine/test_wealth_core_api.py",
         "tests/bt_engine/test_wealth_core_warmup.py",
         "tests/bt_engine/test_price_volume_domain_gate.py",
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
        counts = _parse_pytest_summary(
            (suite.stdout or "") + "\n" + (suite.stderr or ""))
        for key in aggregate:
            aggregate[key] += counts[key]
        if suite.returncode != 0:
            # Signals are negative return codes.  ``max(0, -9)`` would
            # otherwise turn a killed suite into a successful aggregate.
            combined_exit = int(suite.returncode) or 1
        if counts["passed"] > 0:
            suites_completed += 1
    summary = TestSummary(
        candidate_image_digest=candidate_digest,
        runtime_image_digest=runtime_digest,
        source_identity_sha256=identity_hash,
        exit_code=combined_exit,
        suites_completed=suites_completed,
        auxiliary_image_digests=tuple(
            item for item in (bt_engine_digest, bt_data_digest) if item),
        non_forward_historical_exclusions=(
            NON_FORWARD_HISTORICAL_EXCLUSIONS),
        **aggregate,
    )
    gate = make_gate(
        "certified_suite_no_skips", PASS if summary.complete else FAIL,
        now_text,
        {"passed": summary.passed, "failed": summary.failed,
         "errors": summary.errors, "skipped": summary.skipped,
         "xfailed": summary.xfailed, "xpassed": summary.xpassed,
         "exit_code": summary.exit_code,
         "suites_completed": summary.suites_completed,
         "auxiliary_images_known": len(summary.auxiliary_image_digests) == 2,
         "non_forward_historical_exclusions": list(
             summary.non_forward_historical_exclusions),
         "image_known": candidate_digest is not None,
         "runtime_known": runtime_digest is not None,
         "identity_known": identity_hash is not None})
    return summary, gate


def probe_retained_wealth_parity(*, commit: Optional[str], now_text: str,
                                 artifact_root: Path = ROOT / "artifacts" / "sentinel") -> Gate:
    """Diagnostic fallback for retained evidence; never used for production GO."""
    matches = []
    if commit and artifact_root.is_dir():
        for path in artifact_root.glob("manifest-*.json"):
            try:
                raw = path.read_bytes()
                value = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            parity = value.get("parity_generations")
            if (value.get("lifecycle") == "FINALIZED"
                    and value.get("verdict") == "PASS"
                    and value.get("git_commit") == commit
                    and isinstance(parity, dict)
                    and parity.get("sentinel_data_version")
                    and parity.get("canonical_data_version")
                    and value.get("final_corpus_hash")):
                matches.append(sha256_bytes(raw))
    status = PASS if matches else NOT_PROVEN
    return make_gate(
        "wealth_core_nas_parity", status, now_text,
        {"matching_finalized_manifests": len(matches),
         "manifest_digests": sorted(matches)})


def _resolve_compose_args(runner: CommandRunner,
                          env: Mapping[str, str]) -> Optional[list[str]]:
    explained = runner.run(
        ["bash", "scripts/sentinel-compose.sh", "--explain"], env=env)
    if explained.returncode != 0:
        return None
    try:
        compose_args = shlex.split((explained.stdout or "").strip())
    except ValueError:
        return None
    if not compose_args or "-f" not in compose_args:
        return None
    return compose_args


def _without_broker_authority(env: Mapping[str, str]) -> Dict[str, str]:
    """Remove every broker-auth value from a broker-free child process."""
    return {key: value for key, value in env.items()
            if key not in _BROKER_AUTH_ENV}


_PREPARATION_CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel import schema
from sentinel.feed import calendar, ingest, publication, store
from sentinel.shadow_runtime import publication_not_before
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    schema.ensure_schema(c)
    store.migrate_schema(c)
    target = calendar.latest_closed_session()
    now = datetime.now(timezone.utc)
    execution_session = calendar.next_session(target)
    execution_open, _execution_close = calendar.session_window(execution_session)
    source_final = now >= publication_not_before(target)
    prospective = now < execution_open.astimezone(timezone.utc)
    eligible = source_final and prospective
    progress = ingest.daily(c, today=target) if eligible else None
    after = publication.current(c)
    visible = store.latest_visible_session(c)
    current = (
        after is not None and after.window_end is not None
        and after.window_end >= target and visible == target
        and publication.chain_gaps(c) == [])
    print('SENTINEL_GO_PREPARATION=' + json.dumps({
        'schema_migrated': True,
        'source_not_before_satisfied': source_final,
        'following_open_future': prospective,
        'bounded_sharadar_daily': (
            progress is not None and progress.kind == 'daily'),
        'publication_current': current,
    }, sort_keys=True))
finally:
    c.close()
'''.strip()


def probe_prevalidation_preparation(
        runner: CommandRunner, *, env: Mapping[str, str],
        runtime_ref: Optional[str],
        monotonic: Callable[[], float] = time.monotonic) -> PreparationSummary:
    """Prepare only schema + bounded Sharadar tail, before read-only review."""
    prerequisites = (
        bool(str(env.get("SHARADAR_API_KEY") or "").strip())
        and bool(env.get("SENTINEL_POSTGRES_PASSWORD"))
        and runtime_ref is not None
        and _IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None)
    if not prerequisites:
        evidence = {
            "reason": "PREPARATION_AUTHORITY_UNAVAILABLE",
            "runtime_known": runtime_ref is not None,
        }
        return PreparationSummary(
            status=NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=_evidence_digest(evidence))
    run_env = _without_broker_authority(env)
    compose_args = _resolve_compose_args(runner, run_env)
    if compose_args is None:
        return PreparationSummary(
            status=NOT_PROVEN, runtime_image_digest=runtime_ref,
            schema_migration_attempted=False,
            bounded_sharadar_daily_attempted=False,
            broker_mutation_attempts=0,
            evidence_sha256=_evidence_digest({
                "reason": "PREPARATION_COMPOSE_GRAPH_UNAVAILABLE"}))
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    started = monotonic()
    completed = runner.run([
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
        "-c", _PREPARATION_CODE,
    ], env=run_env)
    elapsed_milliseconds = max(
        0, int(math.ceil((monotonic() - started) * 1000.0)))
    marker = "SENTINEL_GO_PREPARATION="
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    valid = (
        isinstance(payload, dict)
        and set(payload) == {
            "schema_migrated", "source_not_before_satisfied",
            "following_open_future", "bounded_sharadar_daily",
            "publication_current"}
        and all(payload.get(field) is True for field in payload))
    evidence = {
        "exit_code": int(completed.returncode),
        "schema_migrated": bool(
            isinstance(payload, dict) and payload.get("schema_migrated") is True),
        "bounded_sharadar_daily": bool(
            isinstance(payload, dict)
            and payload.get("bounded_sharadar_daily") is True),
        "source_not_before_satisfied": bool(
            isinstance(payload, dict)
            and payload.get("source_not_before_satisfied") is True),
        "following_open_future": bool(
            isinstance(payload, dict)
            and payload.get("following_open_future") is True),
        "publication_current": bool(
            isinstance(payload, dict)
            and payload.get("publication_current") is True),
        "broker_authority_removed": not bool(
            _BROKER_AUTH_ENV.intersection(run_env)),
    }
    return PreparationSummary(
        status=PASS if valid else FAIL,
        runtime_image_digest=runtime_ref,
        schema_migration_attempted=bool(
            isinstance(payload, dict)
            and payload.get("schema_migrated") is True),
        bounded_sharadar_daily_attempted=bool(
            isinstance(payload, dict)
            and payload.get("bounded_sharadar_daily") is True),
        broker_mutation_attempts=0,
        evidence_sha256=_evidence_digest(evidence),
        elapsed_milliseconds=elapsed_milliseconds)


def probe_active_wealth_parity(
        runner: CommandRunner, *, env: Mapping[str, str],
        commit: Optional[str], candidate_image_digest: Optional[str],
        now_text: str,
        subject_values: Optional[Dict[str, str]] = None,
        timing_values: Optional[Dict[str, int]] = None,
        monotonic: Callable[[], float] = time.monotonic) -> Gate:
    """Run the canonical forward differential in one read-only DB snapshot."""
    if (not commit or not candidate_image_digest
            or _IMAGE_DIGEST.fullmatch(candidate_image_digest) is None
            or not env.get("SENTINEL_POSTGRES_PASSWORD")):
        return make_gate(
            "wealth_core_nas_parity", NOT_PROVEN, now_text,
            {"reason": "FORWARD_CHAIN_DATABASE_AUTHORITY_UNAVAILABLE"})
    run_env = _without_broker_authority(env)
    compose_args = _resolve_compose_args(runner, run_env)
    if compose_args is None:
        return make_gate(
            "wealth_core_nas_parity", NOT_PROVEN, now_text,
            {"reason": "COMPOSE_GRAPH_UNAVAILABLE"})
    # The Compose service supplies the exact production DB connection and no
    # broker credentials.  Its image is replaced by the candidate test lens,
    # whose /app package is the candidate production runtime.
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = candidate_image_digest
    started = monotonic()
    completed = runner.run([
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
        "-m", "tools.sentinel_forward_chain", "--quiet",
    ], env=run_env)
    elapsed_milliseconds = max(
        0, int(math.ceil((monotonic() - started) * 1000.0)))
    if timing_values is not None:
        timing_values["full_forward_decision_replay"] = elapsed_milliseconds
    try:
        report = json.loads(completed.stdout or "")
    except json.JSONDecodeError:
        report = None
    if not isinstance(report, dict):
        status = FAIL if completed.returncode == 1 else NOT_PROVEN
        return make_gate(
            "wealth_core_nas_parity", status, now_text,
            {"reason": "FORWARD_CHAIN_REPORT_UNAVAILABLE",
             "exit_code": int(completed.returncode)})

    transaction = report.get("transaction")
    comparison = report.get("comparison")
    coherence = report.get("publication_coherence")
    corpus = report.get("corpus_identity")
    source = report.get("source_identity")
    environment = source.get("environment") if isinstance(source, dict) else None
    held_publication = report.get("held_publication")
    try:
        publication_subject = data_publication_subject_value(held_publication)
    except ValidationRefused:
        publication_subject = None
    safe_counts = (
        isinstance(comparison, dict)
        and type(comparison.get("reference_sessions_compared")) is int
        and type(comparison.get("expected_reference_sessions")) is int
        and type(comparison.get("field_comparisons")) is int
        and type(comparison.get("expected_full_pass_field_comparisons")) is int
    )
    coherent = (
        isinstance(coherence, dict)
        and coherence.get("coherent") is True
        and coherence.get("enumeration") == "exhaustive"
        and all(coherence.get(field) == 0 for field in (
            "unpublished_rows", "unpublished_bars", "unpublished_actions",
            "unpublished_spy", "unpublished_defensive",
            "unpublished_universe", "unpublished_repairs",
            "unpublished_anomalies"))
        and coherence.get("unpublished_runs") == []
    )
    certified_environment = (
        isinstance(environment, dict)
        and environment.get("certified") is True
        and environment.get("pins_match") is True
        and environment.get("sources_known") is True
        and environment.get("lock_present") is True
        and environment.get("pin_drift") == {}
    )
    passed = (
        completed.returncode == 0
        and report.get("schema") == "sentinel.production-forward-chain/2"
        and report.get("differential_verdict") == "PASS"
        and report.get("authority_effect") == "NONE"
        and report.get("runtime_authority_changed") is False
        and transaction == {"isolation": "repeatable read", "read_only": "on"}
        and coherent
        and isinstance(corpus, dict)
        and corpus.get("postgres_certified") is True
        and safe_counts
        and comparison.get("first_divergence") is None
        and comparison.get("reference_sessions_compared")
            == comparison.get("expected_reference_sessions")
        and comparison.get("field_comparisons")
            == comparison.get("expected_full_pass_field_comparisons")
        and certified_environment
        and publication_subject is not None
    )
    evidence = {
        "report_sha256": sha256_bytes((completed.stdout or "").encode("utf-8")),
        "exit_code": int(completed.returncode),
        "read_only_repeatable_read": transaction == {
            "isolation": "repeatable read", "read_only": "on"},
        "publication_coherent": coherent,
        "certified_environment": certified_environment,
        "sessions_complete": bool(
            safe_counts and comparison.get("reference_sessions_compared")
            == comparison.get("expected_reference_sessions")),
        "fields_complete": bool(
            safe_counts and comparison.get("field_comparisons")
            == comparison.get("expected_full_pass_field_comparisons")),
        "first_divergence_absent": bool(
            isinstance(comparison, dict)
            and comparison.get("first_divergence") is None),
        "held_publication_bound": publication_subject is not None,
    }
    if passed and subject_values is not None:
        subject_values["data_publication"] = publication_subject
    return make_gate(
        "wealth_core_nas_parity", PASS if passed else FAIL,
        now_text, evidence)


_READINESS_CODE = r'''
import json, os
from sentinel.feed import readiness, store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    with c.cursor() as cur:
        cur.execute('BEGIN TRANSACTION READ ONLY')
        cur.execute('SHOW transaction_read_only')
        assert str(cur.fetchone()[0]).lower() == 'on'
    result = readiness.check_readiness(c)
    print('SENTINEL_GO_READINESS=' + json.dumps({
        'ready': bool(result.ready),
        'checks_total': len(result.checks),
        'checks_passed': sum(1 for item in result.checks if item.ok),
        'failures': len(result.failures),
        'transaction_read_only': True,
    }, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()


def probe_sharadar_readiness(runner: CommandRunner, *, env: Mapping[str, str],
                             runtime_ref: Optional[str], now_text: str) -> Gate:
    if not str(env.get("SHARADAR_API_KEY") or "").strip():
        return make_gate(
            "sharadar_readiness", NOT_PROVEN, now_text,
            {"reason": "SHARADAR_AUTHORITY_UNAVAILABLE"})
    if (not env.get("SENTINEL_POSTGRES_PASSWORD") or not runtime_ref
            or _IMAGE_DIGEST.fullmatch(runtime_ref) is None):
        return make_gate(
            "sharadar_readiness", NOT_PROVEN, now_text,
            {"reason": "DATABASE_AUTHORITY_UNAVAILABLE"})
    run_env = _without_broker_authority(env)
    compose_args = _resolve_compose_args(runner, run_env)
    if compose_args is None:
        return make_gate(
            "sharadar_readiness", NOT_PROVEN, now_text,
            {"reason": "COMPOSE_GRAPH_UNAVAILABLE"})
    if runtime_ref:
        run_env["SENTINEL_RUNTIME_IMAGE_REF"] = runtime_ref
    command = [
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
        "-c", _READINESS_CODE,
    ]
    completed = runner.run(command, env=run_env)
    marker = "SENTINEL_GO_READINESS="
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    valid = (
        isinstance(payload, dict)
        and payload.get("transaction_read_only") is True
        and type(payload.get("checks_total")) is int
        and type(payload.get("checks_passed")) is int
        and type(payload.get("failures")) is int
    )
    passed = bool(valid and payload.get("ready") is True
                  and payload.get("failures") == 0
                  and payload.get("checks_total") == payload.get("checks_passed"))
    evidence = ({
        "transaction_read_only": True,
        "ready": bool(payload.get("ready")),
        "checks_total": payload["checks_total"],
        "checks_passed": payload["checks_passed"],
        "failures": payload["failures"],
    } if valid else {"reason": "READ_ONLY_READINESS_UNAVAILABLE"})
    return make_gate(
        "sharadar_readiness",
        PASS if passed else (FAIL if valid else NOT_PROVEN),
        now_text, evidence)


_DATABASE_HEALTH_CODE = r'''
import json, math, os, time
from datetime import datetime, timezone
from sentinel import schema
from sentinel import shadow_runtime
from sentinel.feed import calendar, publication, store

def nodes(root):
    yield root
    for child in root.get('Plans', ()):
        yield from nodes(child)

def plan_root(value):
    if isinstance(value, str):
        value = json.loads(value)
    return value[0]['Plan']

c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
contender = None
try:
    # Both validators are catalog-only and fail on missing/drifted columns,
    # constraints, migration witnesses, views, or unusable critical indexes.
    schema.require_runtime_schema(c)
    store.require_feed_schema(c)
    with c.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute('SHOW transaction_isolation')
        isolation = str(cur.fetchone()[0]).lower()
        cur.execute('SHOW transaction_read_only')
        read_only = str(cur.fetchone()[0]).lower()

    with publication.pinned(c, commit=False) as held:
        coherent = publication.assert_coherent(c, exhaustive=True)
        gaps = publication.chain_gaps(c)
        frontier = store.latest_visible_session(c)
        if frontier is None:
            raise RuntimeError('published visible frontier is unavailable')
        current_before = publication.require_current(c)
        expected_axis = calendar.previous_sessions(frontier, 252)
        if len(expected_axis) != 252 or expected_axis[-1] != frontier:
            raise RuntimeError('canonical recent XNYS axis is unavailable')
        visible = publication.visible_predicate('b')
        with c.cursor() as cur:
            cur.execute(
                'SELECT DISTINCT session FROM sentinel_bars b'
                ' WHERE session BETWEEN %s AND %s AND ' + visible +
                ' ORDER BY session', (expected_axis[0], frontier))
            actual_axis = [str(row[0]) for row in cur.fetchall()]
            cur.execute(
                'SELECT COUNT(*),COUNT(DISTINCT security_id)'
                ' FROM sentinel_bars b WHERE session=%s AND ' + visible,
                (frontier,))
            frontier_rows, frontier_unique = map(int, cur.fetchone())
            cur.execute('SELECT COUNT(*) FROM sentinel_corpus_publications')
            publication_versions = int(cur.fetchone()[0])
            cur.execute(
                'SELECT COUNT(*) FROM ('
                ' SELECT run_id FROM sentinel_corpus_publications'
                ' WHERE run_id IS NOT NULL GROUP BY run_id HAVING COUNT(*)>1'
                ') duplicate_runs')
            duplicate_publication_run_ids = int(cur.fetchone()[0])
            key = publication.CORPUS_LOCK_KEY
            cur.execute(
                "SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory'"
                " AND pid=pg_backend_pid() AND granted"
                " AND ((classid::bigint << 32) | objid::bigint)=%s"
                " AND mode='ShareLock'", (key,))
            shared_pin_held = int(cur.fetchone()[0]) == 1

            cur.execute(
                'EXPLAIN (FORMAT JSON) ' + store._PREVIOUS_OBSERVATIONS_SQL,
                (frontier,))
            predecessor_plan = list(nodes(plan_root(cur.fetchone()[0])))
            cur.execute(
                'EXPLAIN (FORMAT JSON) SELECT b.security_id,b.ticker,'
                ' b.close_unadjusted,b.open_unadjusted,b.volume'
                ' FROM sentinel_bars b WHERE b.session=%s AND ' + visible +
                ' ORDER BY b.security_id', (frontier,))
            frontier_plan = list(nodes(plan_root(cur.fetchone()[0])))

        contender = store.connect(os.environ['SENTINEL_DATABASE_URL'])
        with contender.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)',
                        (publication.CORPUS_LOCK_KEY,))
            writer_acquired = bool(cur.fetchone()[0])
            if writer_acquired:
                cur.execute('SELECT pg_advisory_unlock(%s)',
                            (publication.CORPUS_LOCK_KEY,))
        contender.rollback(); contender.close(); contender = None

        _controller, strategy_identity = shadow_runtime._strategy()
        scan_started = time.monotonic()
        warmup = shadow_runtime._current_warmup_input_identity(
            c, first_session=frontier,
            strategy_identity=strategy_identity)
        revision_ms = max(
            0, int(math.ceil((time.monotonic() - scan_started) * 1000.0)))

        current_after = publication.require_current(c)
        frontier_after = store.latest_visible_session(c)
        now = datetime.now(timezone.utc)
        source_final_at = shadow_runtime.publication_not_before(frontier)
        execution_session = calendar.next_session(frontier)
        execution_open, _execution_close = calendar.session_window(
            execution_session)
        execution_open = execution_open.astimezone(timezone.utc)
        source_window_ms = max(0, int(
            (execution_open - source_final_at).total_seconds() * 1000))

        def relation_has_seq_scan(plan, relation):
            return any(
                node.get('Relation Name') == relation
                and node.get('Node Type') in {'Seq Scan', 'Parallel Seq Scan'}
                for node in plan)

        predecessor_indexes = {
            node.get('Index Name') for node in predecessor_plan
            if node.get('Index Name')}
        frontier_indexes = {
            node.get('Index Name') for node in frontier_plan
            if node.get('Index Name')}
        predecessor_bad_shape = any(
            node.get('Node Type') in {'Sort', 'Gather Merge'}
            for node in predecessor_plan)
        checks = {
            'behavioral_schema_exact': True,
            'feed_schema_exact': True,
            'publication_complete': bool(
                coherent.coherent and coherent.enumeration == 'exhaustive'
                and held.window_end == frontier),
            'publication_chain_unique_and_gap_free': bool(
                not gaps and duplicate_publication_run_ids == 0),
            'recent_xnys_axis_exact': actual_axis == expected_axis,
            'frontier_security_keys_unique': bool(
                frontier_rows > 0 and frontier_rows == frontier_unique),
            'repeatable_read_only': bool(
                isolation == 'repeatable read' and read_only in {'on', 'true'}),
            'publication_pin_excludes_writers': bool(
                shared_pin_held and not writer_acquired),
            'publication_stable_under_pin': bool(
                current_before.to_dict() == held.to_dict()
                and current_after.to_dict() == held.to_dict()
                and frontier_after == frontier),
            'required_indexes_exact': True,
            'predecessor_query_plan_indexed': bool(
                'idx_sentinel_bars_predecessor' in predecessor_indexes
                and not relation_has_seq_scan(
                    predecessor_plan, 'sentinel_bars')
                and not predecessor_bad_shape),
            'frontier_query_plan_indexed': bool(
                'idx_sentinel_bars_session' in frontier_indexes
                and not relation_has_seq_scan(frontier_plan, 'sentinel_bars')),
            'warmup_revision_input_complete': bool(
                warmup.get('schema') == shadow_runtime.WARMUP_INPUT_SCHEMA
                and warmup.get('session_count') == 252
                and isinstance(warmup.get('warmup_input_sha256'), str)
                and len(warmup['warmup_input_sha256']) == 64),
            'prospective_trading_window': bool(
                now >= source_final_at and now < execution_open),
        }
        print('SENTINEL_GO_DATABASE_HEALTH=' + json.dumps({
            'checks': checks,
            'publication_versions': publication_versions,
            'publication_chain_gaps': len(gaps),
            'duplicate_publication_run_ids': duplicate_publication_run_ids,
            'recent_xnys_sessions': len(actual_axis),
            'frontier_security_rows': frontier_rows,
            'frontier_duplicate_security_keys': (
                frontier_rows - frontier_unique),
            'warmup_revision_sessions': int(
                warmup.get('session_count') or 0),
            'warmup_revision_scan_ms': revision_ms,
            'source_final_to_following_open_ms': source_window_ms,
            'transaction_db_writes': 0,
        }, sort_keys=True))
finally:
    if contender is not None:
        contender.rollback(); contender.close()
    c.rollback(); c.close()
'''.strip()


def probe_database_financial_health(
        runner: CommandRunner, *, env: Mapping[str, str],
        runtime_ref: Optional[str], now_text: str,
        bounded_ingest_milliseconds: Optional[int],
        full_forward_decision_replay_milliseconds: Optional[int],
        ) -> tuple[DatabaseHealthSummary, Gate]:
    """Prove financial DB correctness and measured pretrade timing margin."""
    prerequisites = (
        bool(env.get("SENTINEL_POSTGRES_PASSWORD"))
        and runtime_ref is not None
        and _IMAGE_DIGEST.fullmatch(str(runtime_ref)) is not None
        and type(bounded_ingest_milliseconds) is int
        and bounded_ingest_milliseconds >= 0
        and type(full_forward_decision_replay_milliseconds) is int
        and full_forward_decision_replay_milliseconds >= 0)
    if not prerequisites:
        summary = unavailable_database_health(
            runtime_image_digest=runtime_ref,
            reason="DATABASE_HEALTH_AUTHORITY_OR_TIMING_UNAVAILABLE")
        return summary, make_gate(
            "database_financial_health", NOT_PROVEN, now_text,
            summary.to_dict())
    run_env = _without_broker_authority(env)
    compose_args = _resolve_compose_args(runner, run_env)
    if compose_args is None:
        summary = unavailable_database_health(
            runtime_image_digest=runtime_ref,
            reason="DATABASE_HEALTH_COMPOSE_GRAPH_UNAVAILABLE")
        return summary, make_gate(
            "database_financial_health", NOT_PROVEN, now_text,
            summary.to_dict())
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = str(runtime_ref)
    completed = runner.run([
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
        "-c", _DATABASE_HEALTH_CODE,
    ], env=run_env)
    marker = "SENTINEL_GO_DATABASE_HEALTH="
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    expected_payload = {
        "checks", "publication_versions", "publication_chain_gaps",
        "duplicate_publication_run_ids", "recent_xnys_sessions",
        "frontier_security_rows", "frontier_duplicate_security_keys",
        "warmup_revision_sessions", "warmup_revision_scan_ms",
        "source_final_to_following_open_ms", "transaction_db_writes",
    }
    valid = (
        isinstance(payload, dict)
        and set(payload) == expected_payload
        and isinstance(payload.get("checks"), dict)
        and set(payload["checks"]) == set(DATABASE_CHECK_IDS)
        and all(type(value) is bool for value in payload["checks"].values())
        and all(type(payload.get(name)) is int and payload[name] >= 0
                for name in expected_payload - {"checks"}))
    if not valid:
        summary = unavailable_database_health(
            runtime_image_digest=runtime_ref,
            reason="DATABASE_HEALTH_REPORT_UNAVAILABLE",
            status=FAIL if completed.returncode != 127 else NOT_PROVEN)
        return summary, make_gate(
            "database_financial_health", summary.status, now_text,
            {**summary.to_dict(), "exit_code": int(completed.returncode)})

    measured = {
        "bounded_sharadar_ingest": int(bounded_ingest_milliseconds),
        "full_forward_decision_replay": int(
            full_forward_decision_replay_milliseconds),
        "warmup_revision_scan": int(payload["warmup_revision_scan_ms"]),
    }
    measured["combined_pretrade_work"] = sum(measured.values())
    thresholds = {
        "bounded_sharadar_ingest": MAX_BOUNDED_INGEST_MS,
        "full_forward_decision_replay": (
            MAX_FULL_FORWARD_DECISION_REPLAY_MS),
        "warmup_revision_scan": MAX_WARMUP_REVISION_SCAN_MS,
        "combined_pretrade_work": MAX_COMBINED_PRETRADE_WORK_MS,
    }
    deadline = {
        "minimum_source_final_to_following_open": MIN_SOURCE_FINAL_TO_OPEN_MS,
        "observed_source_final_to_following_open": int(
            payload["source_final_to_following_open_ms"]),
        "minimum_remaining_margin": MIN_REMAINING_DEADLINE_MARGIN_MS,
        "measured_remaining_margin": max(
            0, MIN_SOURCE_FINAL_TO_OPEN_MS
            - measured["combined_pretrade_work"]),
    }
    counts = {
        "publication_versions": int(payload["publication_versions"]),
        "publication_chain_gaps": int(payload["publication_chain_gaps"]),
        "duplicate_publication_run_ids": int(
            payload["duplicate_publication_run_ids"]),
        "recent_xnys_sessions": int(payload["recent_xnys_sessions"]),
        "frontier_security_rows": int(payload["frontier_security_rows"]),
        "frontier_duplicate_security_keys": int(
            payload["frontier_duplicate_security_keys"]),
        "warmup_revision_sessions": int(
            payload["warmup_revision_sessions"]),
    }
    checks = {name: bool(payload["checks"][name])
              for name in DATABASE_CHECK_IDS}
    passed = (
        all(checks.values())
        and counts["publication_versions"] > 0
        and counts["publication_chain_gaps"] == 0
        and counts["duplicate_publication_run_ids"] == 0
        and counts["recent_xnys_sessions"] == 252
        and counts["frontier_security_rows"] > 0
        and counts["frontier_duplicate_security_keys"] == 0
        and counts["warmup_revision_sessions"] == 252
        and all(measured[name] <= thresholds[name] for name in thresholds)
        and deadline["observed_source_final_to_following_open"]
            >= MIN_SOURCE_FINAL_TO_OPEN_MS
        and deadline["measured_remaining_margin"]
            >= MIN_REMAINING_DEADLINE_MARGIN_MS
        and payload["transaction_db_writes"] == 0)
    evidence = {
        "schema": DATABASE_HEALTH_SCHEMA,
        "status": PASS if passed else FAIL,
        "runtime_image_digest": runtime_ref,
        "checks": checks,
        "counts": counts,
        "measured_milliseconds": measured,
        "threshold_milliseconds": thresholds,
        "deadline_milliseconds": deadline,
        "production_db_writes": int(payload["transaction_db_writes"]),
    }
    summary = DatabaseHealthSummary(
        status=PASS if passed else FAIL,
        runtime_image_digest=runtime_ref,
        checks=checks, counts=counts,
        measured_milliseconds=measured,
        threshold_milliseconds=thresholds,
        deadline_milliseconds=deadline,
        production_db_writes=int(payload["transaction_db_writes"]),
        evidence_sha256=_evidence_digest(evidence))
    return summary, make_gate(
        "database_financial_health", summary.status, now_text, evidence)


def probe_alpaca_account(*, env: Mapping[str, str], now_text: str,
                         urlopen: Callable[..., Any] = urllib.request.urlopen,
                         mutation_counter: Optional[list[int]] = None,
                         timeout: int = 20) -> tuple[Gate, Mapping[str, str]]:
    base = str(env.get(
        "ALPACA_BASE_URL", "https://paper-api.alpaca.markets")).rstrip("/")
    key = str(env.get("ALPACA_API_KEY", "")).strip()
    secret = str(env.get("ALPACA_SECRET_KEY", "")).strip()
    if base != "https://paper-api.alpaca.markets" or not key or not secret:
        return (make_gate(
            "alpaca_paper_account", NOT_PROVEN, now_text,
            {"paper_endpoint": base == "https://paper-api.alpaca.markets",
             "credentials_present": bool(key and secret)}), {})
    request = urllib.request.Request(
        base + "/v2/account",
        headers={"APCA-API-KEY-ID": key,
                 "APCA-API-SECRET-KEY": secret,
                 "Accept": "application/json"},
        method="GET")
    if request.get_method() != "GET":
        if mutation_counter is not None:
            mutation_counter[0] += 1
        return make_gate(
            "alpaca_paper_account", FAIL, now_text,
            {"reason": "NON_GET_FINANCIAL_REQUEST"}), {}
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.HTTPError):
        return make_gate(
            "alpaca_paper_account", NOT_PROVEN, now_text,
            {"reason": "PAPER_ACCOUNT_READ_UNAVAILABLE"}), {}
    if not isinstance(payload, dict):
        return make_gate(
            "alpaca_paper_account", FAIL, now_text,
            {"reason": "PAPER_ACCOUNT_MALFORMED"}), {}
    account_number = str(payload.get("account_number") or "").strip()
    account_uuid = str(payload.get("id") or "").strip()
    identities = {item for item in (account_number, account_uuid) if item}
    configured_id = str(env.get("SENTINEL_PAPER_ACCOUNT_ID") or "").strip()
    identity_matches_binding = not configured_id or configured_id in identities
    observed_account_id = account_number or account_uuid
    try:
        multiplier = Decimal(str(payload["multiplier"]))
        cash = Decimal(str(payload["cash"]))
        buying_power = Decimal(str(payload["buying_power"]))
        numeric = all(item.is_finite() for item in (multiplier, cash, buying_power))
    except (KeyError, InvalidOperation):
        multiplier = cash = buying_power = Decimal("NaN")
        numeric = False
    passed = (
        bool(observed_account_id) and identity_matches_binding
        and numeric and multiplier == 1 and cash >= 0
        and buying_power >= 0 and abs(buying_power - cash) <= Decimal("1.00")
        and str(payload.get("status") or "").upper() == "ACTIVE"
        and payload.get("trading_blocked") is False
        and payload.get("account_blocked") is False
        and payload.get("trade_suspended_by_user") is False
    )
    gate = make_gate(
        "alpaca_paper_account", PASS if passed else FAIL, now_text,
        {"identity_present": bool(identities),
         "identity_matches_configured_binding": identity_matches_binding,
         "cash_only": bool(
            numeric and multiplier == 1 and cash >= 0 and buying_power >= 0
            and abs(buying_power - cash) <= Decimal("1.00")),
         "active_unblocked": bool(
             str(payload.get("status") or "").upper() == "ACTIVE"
             and payload.get("trading_blocked") is False
             and payload.get("account_blocked") is False
             and payload.get("trade_suspended_by_user") is False)})
    subjects = ({"alpaca_paper_account": observed_account_id}
                if observed_account_id else {})
    if configured_id:
        subjects["configured_paper_account"] = configured_id
    return gate, subjects


def _unproven_paper_gates(now_text: str) -> Dict[str, Gate]:
    reasons = {
        "preopen_share_unit_authority":
            "FULL_UNIVERSE_NO_EVENT_AUTHORITY_NOT_PROVEN",
        "official_close_nav": "OFFICIAL_CLOSE_FINALITY_NOT_PROVEN",
        "account_fill_interval": "ACCOUNT_WIDE_FILL_FINALITY_NOT_PROVEN",
        "close_cash_finality": "CLOSE_CASH_WATERMARK_NOT_PROVEN",
        "paper_dividend_attribution": "PAPER_DIVIDEND_ATTRIBUTION_NOT_PROVEN",
    }
    return {
        gate_id: make_gate(gate_id, NOT_PROVEN, now_text, {"reason": reason})
        for gate_id, reason in reasons.items()
    }


def run_production_probes(*, runner: Optional[CommandRunner] = None,
                          env: Optional[Mapping[str, str]] = None,
                          now: Optional[datetime] = None,
                          urlopen: Callable[..., Any] = urllib.request.urlopen,
                          run_suite: bool = True) -> ProbeResults:
    runner = runner or CommandRunner()
    resolved_env = dict(env) if env is not None else merged_environment()
    instant = now or datetime.now(timezone.utc)
    now_text = _utc_text(instant)
    git, git_gate = probe_git(runner, now_text=now_text)
    if run_suite:
        tests, suite_gate = probe_certified_suite(
            runner, commit=git.commit, now_text=now_text)
    else:
        tests = TestSummary(None, None, None)
        suite_gate = make_gate(
            "certified_suite_no_skips", NOT_PROVEN, now_text,
            {"reason": "CERTIFIED_SUITE_NOT_RUN"})
    preparation = probe_prevalidation_preparation(
        runner, env=resolved_env,
        runtime_ref=tests.runtime_image_digest)
    subjects: Dict[str, str] = {}
    timing_values: Dict[str, int] = {}
    parity = probe_active_wealth_parity(
        runner, env=resolved_env, commit=git.commit,
        candidate_image_digest=tests.candidate_image_digest,
        now_text=now_text, subject_values=subjects,
        timing_values=timing_values)
    # Readiness is executed by the exact deployable authorized runtime digest
    # recorded in TestSummary, never by a mutable tag or build-stage image.
    readiness = probe_sharadar_readiness(
        runner, env=resolved_env, runtime_ref=tests.runtime_image_digest,
        now_text=now_text)
    database_health, database_gate = probe_database_financial_health(
        runner, env=resolved_env, runtime_ref=tests.runtime_image_digest,
        now_text=now_text,
        bounded_ingest_milliseconds=preparation.elapsed_milliseconds,
        full_forward_decision_replay_milliseconds=timing_values.get(
            "full_forward_decision_replay"))
    mutation_counter = [0]
    alpaca, account_subjects = probe_alpaca_account(
        env=resolved_env, now_text=now_text, urlopen=urlopen,
        mutation_counter=mutation_counter)
    subjects.update(account_subjects)
    if tests.source_identity_sha256 is not None:
        subjects["shadow_configuration"] = shadow_configuration_sha256(
            resolved_env,
            source_identity_sha256=tests.source_identity_sha256)
    gates = {
        "git_identity": git_gate,
        "certified_suite_no_skips": suite_gate,
        "database_financial_health": database_gate,
        "wealth_core_nas_parity": parity,
        "sharadar_readiness": readiness,
        "alpaca_paper_account": alpaca,
        **_unproven_paper_gates(now_text),
    }
    writes = 0
    gates["zero_mutation_boundary"] = make_gate(
        "zero_mutation_boundary",
        PASS if mutation_counter[0] == 0 and writes == 0 else FAIL,
        now_text,
        {"broker_mutation_attempts": mutation_counter[0],
         "production_db_writes": writes,
         "allowed_financial_http_methods": ["GET"]})
    return ProbeResults(
        git=git, tests=tests, gates=gates, subject_values=subjects,
        broker_mutation_attempts=mutation_counter[0],
        production_db_writes=writes,
        input_mode="PRODUCTION", preparation=preparation,
        database_health=database_health)


def load_dev_input(path: Path, *, now: datetime) -> ProbeResults:
    """Test/dev-only seam.  Its verdict can never authorize deployment."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationRefused("development input is not readable JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != INPUT_SCHEMA:
        raise ValidationRefused("development input has the wrong schema")
    now_text = _utc_text(now)
    git_value = value.get("git") if isinstance(value.get("git"), dict) else {}
    git = GitIdentity(
        commit=(str(git_value.get("commit"))
                if _HEX40.fullmatch(str(git_value.get("commit") or "")) else None),
        branch_is_main=git_value.get("branch_is_main") is True,
        clean=git_value.get("clean") is True,
        origin_main=(str(git_value.get("origin_main"))
                     if _HEX40.fullmatch(str(git_value.get("origin_main") or ""))
                     else None),
    )
    tests_value = value.get("tests") if isinstance(value.get("tests"), dict) else {}
    tests = TestSummary(
        candidate_image_digest=_optional_image_digest(
            tests_value.get("candidate_image_digest")),
        runtime_image_digest=_optional_image_digest(
            tests_value.get("runtime_image_digest")),
        source_identity_sha256=_optional_hex64(
            tests_value.get("source_identity_sha256")),
        passed=_safe_nonnegative_int(tests_value.get("passed")),
        failed=_safe_nonnegative_int(tests_value.get("failed")),
        errors=_safe_nonnegative_int(tests_value.get("errors")),
        skipped=_safe_nonnegative_int(tests_value.get("skipped")),
        xfailed=_safe_nonnegative_int(tests_value.get("xfailed")),
        xpassed=_safe_nonnegative_int(tests_value.get("xpassed")),
        exit_code=_safe_nonnegative_int(tests_value.get("exit_code"), default=1),
        suites_completed=_safe_nonnegative_int(
            tests_value.get("suites_completed")),
        auxiliary_image_digests=tuple(
            value for value in (
                _optional_image_digest(item)
                for item in (tests_value.get("auxiliary_image_digests") or []))
            if value is not None),
    )
    raw_gates = value.get("gates") if isinstance(value.get("gates"), dict) else {}
    gates = {}
    for gate_id in GATE_IDS:
        status = str(raw_gates.get(gate_id) or NOT_PROVEN)
        if status not in GATE_STATUSES:
            status = NOT_PROVEN
        gates[gate_id] = make_gate(
            gate_id, status, now_text, {"development_input": True})
    return ProbeResults(
        git=git, tests=tests, gates=gates, subject_values={},
        broker_mutation_attempts=_safe_nonnegative_int(
            value.get("broker_mutation_attempts")),
        production_db_writes=_safe_nonnegative_int(
            value.get("production_db_writes")),
        input_mode="DEVELOPMENT", preparation=None, database_health=None)


def _safe_nonnegative_int(value: Any, *, default: int = 0) -> int:
    if type(value) is int and value >= 0:
        return value
    return default


def _optional_image_digest(value: Any) -> Optional[str]:
    text = str(value or "")
    return text if _IMAGE_DIGEST.fullmatch(text) else None


def _optional_hex64(value: Any) -> Optional[str]:
    text = str(value or "")
    return text if _HEX64.fullmatch(text) else None


def secret_candidates(env: Mapping[str, str],
                      subjects: Mapping[str, str]) -> tuple[bytes, ...]:
    raw_values = [str(env.get(name) or "") for name in _SECRET_NAMES]
    # The shadow subject is itself a one-way SHA-256 intentionally published
    # verbatim for runtime comparison; it is not a raw model input or secret.
    raw_values.extend(
        str(value) for kind, value in subjects.items()
        if kind != "shadow_configuration")
    encoded: set[bytes] = set()
    for value in raw_values:
        if len(value) < 6:
            continue
        data = value.encode("utf-8")
        variants = {
            value,
            quote(value, safe=""),
            quote_plus(value, safe=""),
            base64.b64encode(data).decode("ascii"),
            base64.urlsafe_b64encode(data).decode("ascii"),
            base64.b64encode(data).decode("ascii").rstrip("="),
            data.hex(),
        }
        encoded.update(item.encode("utf-8") for item in variants if len(item) >= 6)
    return tuple(sorted(encoded))


def scan_public_members(members: Mapping[str, bytes], *,
                        candidates: Iterable[bytes]) -> dict:
    if set(members) != set(ALLOWED_MEMBERS):
        raise ValidationRefused("bundle member allowlist is not exact")
    surfaces = [(name.encode("utf-8"), payload)
                for name, payload in sorted(members.items())]
    candidate_matches = 0
    pattern_matches = 0
    candidate_values = tuple(candidates)
    for name, payload in surfaces:
        combined = name + b"\n" + payload
        candidate_matches += sum(1 for item in candidate_values if item in combined)
        pattern_matches += sum(
            len(pattern.findall(combined)) for pattern in _PROHIBITED_PUBLIC_PATTERNS)
    return {
        "candidate_values_checked": len(candidate_values),
        "candidate_matches": candidate_matches,
        "prohibited_pattern_matches": pattern_matches,
        "members_scanned": len(surfaces),
        "findings": candidate_matches + pattern_matches,
    }


def _manifest_bytes(payloads: Mapping[str, bytes]) -> bytes:
    files = [
        {"name": name, "sha256": sha256_bytes(payload), "bytes": len(payload)}
        for name, payload in sorted(payloads.items())
    ]
    return canonical_json_bytes({"schema": MANIFEST_SCHEMA, "files": files})


def _sha_sums(payloads: Mapping[str, bytes]) -> bytes:
    return "".join(
        "%s  %s\n" % (sha256_bytes(payload), name)
        for name, payload in sorted(payloads.items())).encode("ascii")


README = (
    "Sentinel NAS financial validation evidence.\n"
    "Upload this ZIP only when secret-scan.json says upload_permitted=true.\n"
    "Database health publishes sanitized checks, timings, bounds, and deadline margin.\n"
    "Verdicts are independent: DUAL_RUN_GO keeps PAPER accounting non-authoritative.\n"
    "The archive contains derived facts and digests only; raw evidence stays on the NAS.\n"
).encode("ascii")


def build_member_payloads(validation: Mapping[str, Any],
                          tests: TestSummary, *,
                          candidates: Iterable[bytes]) -> tuple[Dict[str, bytes], bool]:
    core = {
        "validation.json": canonical_json_bytes(validation),
        "test-summary.json": canonical_json_bytes(tests.to_dict()),
        "README.txt": README,
    }
    # First scan the content that can be influenced by probes.  The final three
    # members are generated exclusively from fixed keys, counts, and digests.
    pre_members = dict(core)
    placeholder_scan = {
        "schema": SCAN_SCHEMA,
        "members_scanned": len(ALLOWED_MEMBERS),
        "candidate_values_checked": 0,
        "candidate_matches": 0,
        "prohibited_pattern_matches": 0,
        "findings": 0,
        "upload_permitted": True,
    }
    pre_members["secret-scan.json"] = canonical_json_bytes(placeholder_scan)
    pre_members["manifest.json"] = _manifest_bytes(pre_members)
    pre_members["SHA256SUMS"] = _sha_sums(pre_members)
    scan = scan_public_members(pre_members, candidates=candidates)
    upload_permitted = scan["findings"] == 0
    scan_document = {
        "schema": SCAN_SCHEMA,
        **scan,
        "upload_permitted": upload_permitted,
    }
    core["secret-scan.json"] = canonical_json_bytes(scan_document)
    core["manifest.json"] = _manifest_bytes(core)
    core["SHA256SUMS"] = _sha_sums(core)
    if set(core) != set(ALLOWED_MEMBERS):
        raise ValidationRefused("bundle construction violated member allowlist")
    final_scan = scan_public_members(core, candidates=candidates)
    if final_scan["findings"] != scan["findings"]:
        # Generated metadata must not introduce a new sensitive surface.
        raise ValidationRefused("generated bundle metadata failed redaction")
    return core, upload_permitted


def validate_zip_members(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if (len(names) != len(ALLOWED_MEMBERS)
                    or set(names) != set(ALLOWED_MEMBERS)
                    or any(name.endswith("/") for name in names)):
                raise ValidationRefused("ZIP member allowlist is not exact")
            for info in archive.infolist():
                if info.file_size < 1:
                    raise ValidationRefused("ZIP contains an empty member")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationRefused("validation ZIP is unreadable") from exc


def write_zip_no_clobber(path: Path, members: Mapping[str, bytes]) -> str:
    if set(members) != set(ALLOWED_MEMBERS):
        raise ValidationRefused("refusing to write a non-allowlisted ZIP")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as raw:
            os.chmod(path, 0o600)
            with zipfile.ZipFile(
                    raw, mode="w", compression=zipfile.ZIP_DEFLATED,
                    compresslevel=9) as archive:
                for name in sorted(members):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    info.create_system = 3
                    archive.writestr(info, members[name])
            raw.flush()
            os.fsync(raw.fileno())
    except FileExistsError as exc:
        raise ValidationRefused("validation ZIP already exists; refusing overwrite") from exc
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    validate_zip_members(path)
    return sha256_bytes(path.read_bytes())


def emit_bundle(probes: ProbeResults, *, output_dir: Path,
                created_at: datetime, valid_for: timedelta,
                scan_env: Mapping[str, str]) -> BundleResult:
    validation = build_validation_document(
        probes, created_at=created_at, valid_for=valid_for)
    candidates = secret_candidates(scan_env, probes.subject_values)
    members, upload_permitted = build_member_payloads(
        validation, probes.tests, candidates=candidates)
    # A redaction finding invalidates both verdicts before anything is written.
    if not upload_permitted:
        validation = dict(validation)
        validation["shadow_verdict"] = SHADOW_NO_GO
        validation["dual_run_verdict"] = DUAL_RUN_NO_GO
        validation["paper_execution_verdict"] = PAPER_NO_GO
        validation["machine_failures"] = {
            "shadow": ["REDACTION_SCAN_FAILED"],
            "dual_run": ["REDACTION_SCAN_FAILED"],
            "paper_execution": ["REDACTION_SCAN_FAILED"],
        }
        validation["subjects"] = []
        validation["runtime"] = {
            "candidate_image_digest": None,
            "runtime_image_digest": None,
            "source_identity_sha256": None,
        }
        members, still_permitted = build_member_payloads(
            validation, TestSummary(None, None, None), candidates=candidates)
        if still_permitted:
            # The fallback intentionally remains non-uploadable even though its
            # reduced bytes now scan clean.
            scan = json.loads(members["secret-scan.json"].decode("ascii"))
            scan["upload_permitted"] = False
            scan["initial_redaction_failure"] = True
            members["secret-scan.json"] = canonical_json_bytes(scan)
            base = {k: v for k, v in members.items()
                    if k not in {"manifest.json", "SHA256SUMS"}}
            base["manifest.json"] = _manifest_bytes(base)
            base["SHA256SUMS"] = _sha_sums(base)
            members = base
        upload_permitted = False

    commit = probes.git.commit if probes.git.commit and _HEX40.fullmatch(
        probes.git.commit) else "unknown"
    stamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / (
        "stocker-nas-go-validation-%s-%s.zip" % (commit[:12], stamp))
    digest = write_zip_no_clobber(path, members)
    return BundleResult(
        path=path, sha256=digest,
        shadow_verdict=str(validation["shadow_verdict"]),
        dual_run_verdict=str(validation["dual_run_verdict"]),
        paper_execution_verdict=str(validation["paper_execution_verdict"]),
        upload_permitted=upload_permitted)


def _output_path_text(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        # Do not print a local absolute path into an operator transcript.
        return path.name


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Sentinel NAS financial GO validator")
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "artifacts" / "sentinel" / "go-validation")
    parser.add_argument("--valid-hours", type=int, default=24)
    parser.add_argument("--input", type=Path,
                        help="development/test input; never deployment-authoritative")
    parser.add_argument(
        "--dev-input", action="store_true",
        help="confirm that --input is a non-deployable development seam")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        env = merged_environment()
        if args.input is not None:
            if not args.dev_input:
                raise ValidationRefused(
                    "--input requires --dev-input and can never authorize deployment")
            probes = load_dev_input(args.input, now=now)
        elif args.dev_input:
            raise ValidationRefused("--dev-input requires --input")
        else:
            print(
                "Running NAS financial validation (bounded preparation, then "
                "read-only probes)...", flush=True)
            probes = run_production_probes(env=env, now=now)
        result = emit_bundle(
            probes, output_dir=args.output_dir, created_at=now,
            valid_for=timedelta(hours=args.valid_hours), scan_env=env)
    except ValidationRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("REFUSED: validation interrupted", file=sys.stderr)
        return 130

    print("shadow verdict: %s" % result.shadow_verdict)
    print("dual-run verdict: %s" % result.dual_run_verdict)
    print("paper verdict: %s" % result.paper_execution_verdict)
    print("bundle: %s" % _output_path_text(result.path))
    print("sha256: %s" % result.sha256)
    if result.upload_permitted:
        print("UPLOAD PERMITTED: upload only this ZIP for review")
    else:
        print("DO NOT UPLOAD: the redaction boundary did not pass")
    return 0 if (
        result.upload_permitted and result.shadow_verdict == SHADOW_GO) else 2


if __name__ == "__main__":
    raise SystemExit(main())
