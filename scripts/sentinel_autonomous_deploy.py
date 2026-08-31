#!/usr/bin/env python3
"""Convergent, fail-closed fenced installation for Sentinel.

The launcher fast-forwards Git before entering here. This program builds and
tests exact images, promotes them to immutable registry digests, fences old
automation, verifies backup/restore, migrates schema explicitly, and installs
the exact runtime disabled and killed. Financial GO validation and any selected
observation-mode activation are separate transactions.

It NEVER resets/reseeds the behavioral database, never deletes volumes, never
runs migrate-account, never guesses an account binding, and never turns an
inherited unbound book into an empty-account enrollment.  Any failure after the
transition boundary attempts the minimal emergency fence and stops the
unattended container before returning non-zero.

Host requirement: Python 3.8.15+.  Certificate signing itself happens in the
newly built, network-disabled Sentinel test image with the private key mounted
read-only, so the NAS host does not need the cryptography package.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
import urllib.error
import urllib.request
import zipfile


MIN_PYTHON = (3, 8, 15)
if sys.version_info < MIN_PYTHON:  # pragma: no cover - launcher checks first
    sys.stderr.write("REFUSED: autonomous deploy requires Python 3.8.15+\n")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PAPER_URL = "https://paper-api.alpaca.markets"
DEPLOY_SCHEMA = "sentinel.autonomous-paper-deployment/1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
VALIDATION_SCHEMA = "sentinel.nas-go-validation/1"
VALIDATION_TEST_SCHEMA = "sentinel.nas-go-test-summary/1"
NON_FORWARD_HISTORICAL_EXCLUSIONS = (
    "tests/wealth_core/test_golden_fixture.py::"
    "test_the_result_matches_the_pinned_fixture",
    "tests/wealth_core/test_golden_fixture.py::"
    "TestTheHashesAreInterpreterIndependent::"
    "test_the_run_hash_is_stable_in_a_FRESH_INTERPRETER",
    "tests/wealth_core/test_performance_integration.py::"
    "test_measuring_does_not_move_the_pinned_result_hash",
)
VALIDATION_MANIFEST_SCHEMA = "sentinel.nas-go-validation-manifest/1"
VALIDATION_SCAN_SCHEMA = "sentinel.nas-go-secret-scan/1"
VALIDATION_PREPARATION_SCHEMA = "sentinel.nas-go-preparation/1"
VALIDATION_DATABASE_HEALTH_SCHEMA = "sentinel.nas-financial-db-health/1"
SHADOW_CONFIG_SCHEMA = "sentinel.shadow-reviewed-config/1"
DATA_PUBLICATION_SCHEMA = "sentinel.data-publication-binding/1"
SHADOW_EXECUTION_MODEL = "PROSPECTIVE_CONCORDANCE_SCALAR_CORE_BIL_V3"
SHADOW_CUTOFF_POLICY = "STRICT_BEFORE_OFFICIAL_NEXT_XNYS_OPEN_V1"
SHADOW_PUBLICATION_TIMING_POLICY = (
    "SHARADAR_SEP_SFP_SECOND_UPDATE_PLUS_15M_2345_AMERICA_NEW_YORK_V1")
_OBSERVATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$")
VALIDATION_MEMBERS = frozenset({
    "validation.json",
    "test-summary.json",
    "manifest.json",
    "README.txt",
    "SHA256SUMS",
    "secret-scan.json",
})
VALIDATION_GATES = (
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
SHADOW_VALIDATION_GATES = (
    "git_identity",
    "certified_suite_no_skips",
    "database_financial_health",
    "wealth_core_nas_parity",
    "sharadar_readiness",
    "zero_mutation_boundary",
)
DUAL_RUN_VALIDATION_GATES = SHADOW_VALIDATION_GATES + (
    "alpaca_paper_account",
)
VALIDATION_README = (
    "Sentinel NAS financial validation evidence.\n"
    "Upload this ZIP only when secret-scan.json says upload_permitted=true.\n"
    "Database health publishes sanitized checks, timings, bounds, and deadline margin.\n"
    "Verdicts are independent: DUAL_RUN_GO keeps PAPER accounting non-authoritative.\n"
    "The archive contains derived facts and digests only; raw evidence stays on the NAS.\n"
).encode("ascii")

_DATA_PUBLICATION_CODE = r'''
import hashlib, json, os
from sentinel.core.decision import publication_fingerprint
from sentinel.feed import publication, store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    with c.cursor() as cur:
        cur.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        cur.execute('SHOW transaction_read_only')
        assert str(cur.fetchone()[0]).lower() == 'on'
    with publication.pinned(c, commit=False) as held:
        value = {
            'publication_fingerprint': publication_fingerprint(held),
            'visible_frontier': store.latest_visible_session(c),
        }
    print('SENTINEL_DEPLOY_DATA_BINDING=' + json.dumps({
        'transaction_read_only': True,
        'binding': value,
    }, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()


class DeployRefused(RuntimeError):
    pass


class ReviewedValidation:
    """A locally re-derived, explicitly reviewed deployment authorization."""

    __slots__ = (
        "mode", "path", "bundle_sha256", "git_commit",
        "runtime_image_digest", "test_image_digest",
        "source_identity_sha256", "auxiliary_image_digests",
        "shadow_configuration_sha256", "data_publication_sha256",
        "validation", "test_summary",
    )

    def __init__(self, *, mode: str, path: Path, bundle_sha256: str,
                 git_commit: str, runtime_image_digest: str,
                 test_image_digest: str, source_identity_sha256: str,
                 auxiliary_image_digests: Tuple[str, ...],
                 shadow_configuration_sha256: Optional[str],
                 data_publication_sha256: Optional[str],
                 validation: Mapping, test_summary: Mapping) -> None:
        self.mode = mode
        self.path = path
        self.bundle_sha256 = bundle_sha256
        self.git_commit = git_commit
        self.runtime_image_digest = runtime_image_digest
        self.test_image_digest = test_image_digest
        self.source_identity_sha256 = source_identity_sha256
        self.auxiliary_image_digests = auxiliary_image_digests
        self.shadow_configuration_sha256 = shadow_configuration_sha256
        self.data_publication_sha256 = data_publication_sha256
        self.validation = validation
        self.test_summary = test_summary


def _canonical_json(value) -> bytes:
    try:
        return (json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise DeployRefused("validation bundle contains non-canonical JSON") from exc


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_value(raw: bytes, *, label: str):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise DeployRefused(
                    "%s contains duplicate JSON key %r" % (label, key))
            value[key] = item
        return value

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeployRefused("%s is not valid UTF-8 JSON" % label) from exc


def _json_object(raw: bytes, *, label: str) -> Mapping:
    value = _json_value(raw, label=label)
    if not isinstance(value, dict):
        raise DeployRefused("%s is not a JSON object" % label)
    if raw != _canonical_json(value):
        raise DeployRefused("%s is not canonical JSON" % label)
    return value


def _parse_validation_time(value, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DeployRefused("validation %s is not canonical UTC" % field)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise DeployRefused("validation %s is malformed" % field) from exc
    return parsed.replace(tzinfo=timezone.utc)


def _manifest_expected(payloads: Mapping[str, bytes]) -> bytes:
    files = [
        {"name": name, "sha256": _sha256(payload), "bytes": len(payload)}
        for name, payload in sorted(payloads.items())
    ]
    return _canonical_json({
        "schema": VALIDATION_MANIFEST_SCHEMA,
        "files": files,
    })


def _sha_sums_expected(payloads: Mapping[str, bytes]) -> bytes:
    return "".join(
        "%s  %s\n" % (_sha256(payload), name)
        for name, payload in sorted(payloads.items())).encode("ascii")


def _read_validation_members(path: Path) -> Dict[str, bytes]:
    try:
        with zipfile.ZipFile(str(path), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (len(names) != len(VALIDATION_MEMBERS)
                    or set(names) != set(VALIDATION_MEMBERS)
                    or any(name.endswith("/") for name in names)):
                raise DeployRefused(
                    "validation ZIP does not have the exact member allowlist")
            for info in infos:
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000 or info.file_size < 1:
                    raise DeployRefused(
                        "validation ZIP contains a link or empty member")
                if info.file_size > 4 * 1024 * 1024:
                    raise DeployRefused("validation ZIP member is unexpectedly large")
            return {name: archive.read(name) for name in names}
    except (OSError, zipfile.BadZipFile) as exc:
        raise DeployRefused("validation ZIP is unreadable") from exc


def _validation_subject_digest(kind: str, raw: str) -> str:
    return hashlib.sha256(
        b"sentinel-nas-subject/v1\0" + kind.encode("ascii") + b"\0"
        + raw.encode("utf-8")).hexdigest()


def shadow_configuration_document(
        env: Mapping[str, str], *, source_identity_sha256: str) -> Mapping:
    source = str(source_identity_sha256 or "")
    if _HEX64.fullmatch(source) is None:
        raise DeployRefused("validated source identity is malformed")
    observation_id = str(env.get(
        "SENTINEL_SHADOW_OBSERVATION_ID", "primary")).strip()
    if _OBSERVATION_ID.fullmatch(observation_id) is None:
        raise DeployRefused(
            "shadow observation id must be 1-64 ASCII letters, digits, dots or hyphens")
    try:
        amount = Decimal(str(env.get(
            "SENTINEL_SHADOW_STARTING_CASH", "100000")).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DeployRefused(
            "shadow starting cash must be a positive decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise DeployRefused("shadow starting cash must be a positive decimal")
    publication_policy = str(env.get(
        "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY",
        SHADOW_PUBLICATION_TIMING_POLICY)).strip()
    if publication_policy != SHADOW_PUBLICATION_TIMING_POLICY:
        raise DeployRefused(
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
    encoded = json.dumps(
        shadow_configuration_document(
            env, source_identity_sha256=source_identity_sha256),
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def data_publication_subject_value(value: Mapping) -> str:
    if (not isinstance(value, Mapping)
            or set(value) != {"publication_fingerprint", "visible_frontier"}
            or _HEX64.fullmatch(
                str(value.get("publication_fingerprint") or "")) is None
            or re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}",
                str(value.get("visible_frontier") or "")) is None):
        raise DeployRefused("current data publication binding is malformed")
    return json.dumps({
        "schema": DATA_PUBLICATION_SCHEMA,
        "publication_fingerprint": str(value["publication_fingerprint"]),
        "visible_frontier": str(value["visible_frontier"]),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False)


def _require_exact_keys(value: Mapping, expected, *, label: str) -> None:
    if set(value) != set(expected):
        raise DeployRefused("%s has an unexpected field set" % label)


def parse_reviewed_validation_bundle(
        path: Path, *, mode: str, confirmation: str,
        now: Optional[datetime] = None) -> ReviewedValidation:
    """Validate every public bundle byte before consulting deployment state."""
    if mode not in {"shadow", "dual", "paper"}:
        raise DeployRefused("deployment mode must be shadow, dual or paper")
    if _HEX64.fullmatch(str(confirmation or "")) is None:
        raise DeployRefused(
            "--confirm-reviewed-go must be the exact lowercase bundle SHA-256")
    path = Path(path).expanduser().resolve()
    try:
        raw_zip = path.read_bytes()
    except OSError as exc:
        raise DeployRefused("validation bundle is unreadable") from exc
    bundle_digest = _sha256(raw_zip)
    if bundle_digest != confirmation:
        raise DeployRefused(
            "reviewed-GO confirmation does not match the validation bundle")

    members = _read_validation_members(path)
    if members["README.txt"] != VALIDATION_README:
        raise DeployRefused("validation README differs from the fixed contract")
    manifest_inputs = {
        name: payload for name, payload in members.items()
        if name not in {"manifest.json", "SHA256SUMS"}
    }
    if members["manifest.json"] != _manifest_expected(manifest_inputs):
        raise DeployRefused("validation manifest does not match member bytes")
    sha_inputs = {
        name: payload for name, payload in members.items()
        if name != "SHA256SUMS"
    }
    if members["SHA256SUMS"] != _sha_sums_expected(sha_inputs):
        raise DeployRefused("validation SHA256SUMS does not match member bytes")

    manifest = _json_object(members["manifest.json"], label="manifest.json")
    scan = _json_object(members["secret-scan.json"], label="secret-scan.json")
    validation = _json_object(
        members["validation.json"], label="validation.json")
    tests = _json_object(
        members["test-summary.json"], label="test-summary.json")
    if manifest.get("schema") != VALIDATION_MANIFEST_SCHEMA:
        raise DeployRefused("validation manifest schema is unsupported")
    _require_exact_keys(scan, {
        "schema", "members_scanned", "candidate_values_checked",
        "candidate_matches", "prohibited_pattern_matches", "findings",
        "upload_permitted",
    }, label="secret scan")
    if (scan.get("schema") != VALIDATION_SCAN_SCHEMA
            or scan.get("upload_permitted") is not True
            or scan.get("findings") != 0
            or scan.get("candidate_matches") != 0
            or scan.get("prohibited_pattern_matches") != 0
            or scan.get("members_scanned") != len(VALIDATION_MEMBERS)):
        raise DeployRefused("validation secret/redaction scan did not pass")

    _require_exact_keys(validation, {
        "schema", "created_at", "valid_until", "input_mode", "git",
        "runtime", "preparation", "database_financial_health", "subjects",
        "boundary", "shadow_state", "gates",
        "shadow_verdict", "dual_run_verdict", "paper_execution_verdict",
        "machine_failures",
        "review",
    }, label="validation")
    if (validation.get("schema") != VALIDATION_SCHEMA
            or validation.get("input_mode") != "PRODUCTION"):
        raise DeployRefused("validation is not production-authoritative")
    created = _parse_validation_time(
        validation.get("created_at"), field="created_at")
    valid_until = _parse_validation_time(
        validation.get("valid_until"), field="valid_until")
    instant = now or _utcnow()
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise DeployRefused("deployment validation clock must be timezone-aware")
    instant = instant.astimezone(timezone.utc).replace(microsecond=0)
    if valid_until <= created or valid_until - created > timedelta(hours=72):
        raise DeployRefused("validation validity interval is malformed")
    if instant < created or instant >= valid_until:
        raise DeployRefused("validation bundle is not currently fresh")

    git = validation.get("git")
    if not isinstance(git, dict):
        raise DeployRefused("validation Git identity is malformed")
    _require_exact_keys(git, {
        "commit", "branch", "clean", "origin_main", "matches_origin_main",
    }, label="validation Git identity")
    commit = str(git.get("commit") or "")
    if (_HEX40.fullmatch(commit) is None
            or git.get("branch") != "main"
            or git.get("clean") is not True
            or git.get("origin_main") != commit
            or git.get("matches_origin_main") is not True):
        raise DeployRefused("validation does not bind a clean exact main commit")

    runtime = validation.get("runtime")
    if not isinstance(runtime, dict):
        raise DeployRefused("validation runtime identity is malformed")
    _require_exact_keys(runtime, {
        "candidate_image_digest", "runtime_image_digest",
        "source_identity_sha256",
    }, label="validation runtime identity")
    candidate_digest = str(runtime.get("candidate_image_digest") or "")
    runtime_digest = str(runtime.get("runtime_image_digest") or "")
    source_identity = str(runtime.get("source_identity_sha256") or "")
    if (candidate_digest == runtime_digest
            or _DIGEST.fullmatch(candidate_digest) is None
            or _DIGEST.fullmatch(runtime_digest) is None
            or _HEX64.fullmatch(source_identity) is None):
        raise DeployRefused("validation image/runtime identities are malformed")

    preparation = validation.get("preparation")
    if not isinstance(preparation, dict):
        raise DeployRefused("validation preparation record is malformed")
    _require_exact_keys(preparation, {
        "schema", "status", "runtime_image_digest",
        "schema_migration_attempted", "bounded_sharadar_daily_attempted",
        "database_mutation_scope", "broker_mutation_attempts",
        "completed_before_validation_boundary", "evidence_sha256",
    }, label="validation preparation")
    if (preparation.get("schema") != VALIDATION_PREPARATION_SCHEMA
            or preparation.get("status") != "PASS"
            or preparation.get("runtime_image_digest") != runtime_digest
            or preparation.get("schema_migration_attempted") is not True
            or preparation.get("bounded_sharadar_daily_attempted") is not True
            or preparation.get("database_mutation_scope") != [
                "SCHEMA_MIGRATION", "BOUNDED_SHARADAR_DAILY_INGEST"]
            or preparation.get("broker_mutation_attempts") != 0
            or preparation.get("completed_before_validation_boundary") is not True
            or _HEX64.fullmatch(
                str(preparation.get("evidence_sha256") or "")) is None):
        raise DeployRefused(
            "prevalidation schema/Sharadar preparation is not complete")

    database_health = validation.get("database_financial_health")
    if not isinstance(database_health, dict):
        raise DeployRefused("validation database financial health is malformed")
    _require_exact_keys(database_health, {
        "schema", "status", "runtime_image_digest", "checks", "counts",
        "measured_milliseconds", "threshold_milliseconds",
        "deadline_milliseconds", "production_db_writes", "evidence_sha256",
    }, label="validation database financial health")
    checks = database_health.get("checks")
    required_checks = {
        "behavioral_schema_exact", "feed_schema_exact",
        "publication_complete", "publication_chain_unique_and_gap_free",
        "recent_xnys_axis_exact", "frontier_security_keys_unique",
        "repeatable_read_only", "publication_pin_excludes_writers",
        "publication_stable_under_pin", "required_indexes_exact",
        "predecessor_query_plan_indexed", "frontier_query_plan_indexed",
        "warmup_revision_input_complete", "prospective_trading_window",
    }
    counts = database_health.get("counts")
    measured = database_health.get("measured_milliseconds")
    thresholds = database_health.get("threshold_milliseconds")
    deadline = database_health.get("deadline_milliseconds")
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
    numeric = (
        (counts, expected_counts), (measured, expected_timings),
        (thresholds, expected_timings), (deadline, expected_deadline),
    )
    numeric_valid = all(
        isinstance(values, dict) and set(values) == keys
        and all(type(value) is int and value >= 0
                for value in values.values())
        for values, keys in numeric)
    fixed_thresholds = {
        "bounded_sharadar_ingest": 7_200_000,
        "full_forward_decision_replay": 14_400_000,
        "warmup_revision_scan": 1_800_000,
        "combined_pretrade_work": 17_550_000,
    }
    if (database_health.get("schema") != VALIDATION_DATABASE_HEALTH_SCHEMA
            or database_health.get("status") != "PASS"
            or database_health.get("runtime_image_digest") != runtime_digest
            or not isinstance(checks, dict)
            or set(checks) != required_checks
            or any(value is not True for value in checks.values())
            or not numeric_valid
            or counts["publication_versions"] <= 0
            or counts["publication_chain_gaps"] != 0
            or counts["duplicate_publication_run_ids"] != 0
            or counts["recent_xnys_sessions"] != 252
            or counts["frontier_security_rows"] <= 0
            or counts["frontier_duplicate_security_keys"] != 0
            or counts["warmup_revision_sessions"] != 252
            or thresholds != fixed_thresholds
            or any(measured[name] > thresholds[name]
                   for name in expected_timings)
            or measured["combined_pretrade_work"] != sum(
                measured[name] for name in (
                    "bounded_sharadar_ingest",
                    "full_forward_decision_replay",
                    "warmup_revision_scan"))
            or deadline["minimum_source_final_to_following_open"] != 35_100_000
            or deadline["observed_source_final_to_following_open"] < 35_100_000
            or deadline["minimum_remaining_margin"] != 17_550_000
            or deadline["measured_remaining_margin"]
                != 35_100_000 - measured["combined_pretrade_work"]
            or deadline["measured_remaining_margin"] < 17_550_000
            or database_health.get("production_db_writes") != 0
            or _HEX64.fullmatch(
                str(database_health.get("evidence_sha256") or "")) is None):
        raise DeployRefused(
            "validation database financial health did not pass exact bounds")

    boundary = validation.get("boundary")
    if not isinstance(boundary, dict):
        raise DeployRefused("validation mutation boundary is malformed")
    _require_exact_keys(boundary, {
        "scope", "broker_environment", "allowed_financial_http_methods",
        "broker_mutation_attempts", "production_db_writes",
    }, label="validation mutation boundary")
    if (boundary.get("scope") != "POST_PREPARATION_VALIDATION"
            or boundary.get("broker_environment") != "ALPACA_PAPER"
            or boundary.get("allowed_financial_http_methods") != ["GET"]
            or boundary.get("broker_mutation_attempts") != 0
            or boundary.get("production_db_writes") != 0):
        raise DeployRefused("validation did not preserve the zero-mutation boundary")

    gates = validation.get("gates")
    if not isinstance(gates, list) or len(gates) != len(VALIDATION_GATES):
        raise DeployRefused("validation gate set is malformed")
    statuses = {}
    for expected, gate in zip(VALIDATION_GATES, gates):
        if not isinstance(gate, dict):
            raise DeployRefused("validation gate record is malformed")
        _require_exact_keys(
            gate, {"id", "status", "evidence_sha256", "observed_at"},
            label="validation gate")
        if (gate.get("id") != expected
                or gate.get("status") not in {"PASS", "FAIL", "NOT_PROVEN"}
                or _HEX64.fullmatch(
                    str(gate.get("evidence_sha256") or "")) is None):
            raise DeployRefused("validation gate binding is malformed")
        _parse_validation_time(gate.get("observed_at"), field="gate observed_at")
        statuses[expected] = gate["status"]
    required = (
        SHADOW_VALIDATION_GATES if mode == "shadow"
        else DUAL_RUN_VALIDATION_GATES if mode == "dual"
        else VALIDATION_GATES)
    if any(statuses[gate] != "PASS" for gate in required):
        raise DeployRefused("reviewed bundle does not pass every %s gate" % mode)
    expected_verdict = (
        "SHADOW_GO" if mode == "shadow"
        else "DUAL_RUN_GO" if mode == "dual"
        else "PAPER_EXECUTION_GO")
    actual_verdict = validation.get(
        "shadow_verdict" if mode == "shadow"
        else "dual_run_verdict" if mode == "dual"
        else "paper_execution_verdict")
    if actual_verdict != expected_verdict:
        raise DeployRefused(
            "reviewed bundle verdict is not %s" % expected_verdict)
    failures = validation.get("machine_failures")
    failure_key = (
        "shadow" if mode == "shadow"
        else "dual_run" if mode == "dual"
        else "paper_execution")
    if (not isinstance(failures, dict)
            or failures.get(failure_key) != []):
        raise DeployRefused("validation machine failures block %s mode" % mode)
    shadow_state = validation.get("shadow_state")
    if (mode in {"shadow", "dual"}
            and (not isinstance(shadow_state, dict)
                 or shadow_state.get("fresh") is not True
                 or shadow_state.get("internally_coherent") is not True)):
        raise DeployRefused("validation shadow state is not fresh and coherent")
    if validation.get("review") != {
            "status": "UNREVIEWED", "reviewed_bundle_digest": None}:
        raise DeployRefused(
            "validation review field differs from the external-review contract")

    subjects = validation.get("subjects")
    if not isinstance(subjects, list):
        raise DeployRefused("validation subjects are malformed")
    subject_digests = {}
    for subject in subjects:
        if (not isinstance(subject, dict)
                or set(subject) != {"kind", "digest"}
                or re.fullmatch(
                    r"[a-z][a-z0-9_]{0,95}",
                    str(subject.get("kind") or "")) is None
                or _HEX64.fullmatch(
                    str(subject.get("digest") or "")) is None):
            raise DeployRefused("validation subject binding is malformed")
        kind = str(subject["kind"])
        if kind in subject_digests:
            raise DeployRefused("validation subject kind is duplicated")
        subject_digests[kind] = str(subject["digest"])
    shadow_configuration_digest = subject_digests.get("shadow_configuration")
    data_publication_digest = subject_digests.get("data_publication")
    if mode in {"shadow", "dual"} and (
            shadow_configuration_digest is None
            or data_publication_digest is None):
        raise DeployRefused(
            "SHADOW_GO lacks model-configuration or data-publication binding")

    _require_exact_keys(tests, {
        "schema", "candidate_image_digest", "runtime_image_digest",
        "source_identity_sha256", "passed", "failed", "errors", "skipped",
        "xfailed", "xpassed", "exit_code", "suites_completed",
        "auxiliary_image_digests", "non_forward_historical_exclusions",
        "complete",
    }, label="test summary")
    auxiliary = tests.get("auxiliary_image_digests")
    if (tests.get("schema") != VALIDATION_TEST_SCHEMA
            or tests.get("candidate_image_digest") != candidate_digest
            or tests.get("runtime_image_digest") != runtime_digest
            or tests.get("source_identity_sha256") != source_identity
            or tests.get("complete") is not True
            or tests.get("exit_code") != 0
            or not isinstance(tests.get("passed"), int)
            or tests.get("passed") <= 0
            or any(tests.get(field) != 0 for field in (
                "failed", "errors", "skipped", "xfailed", "xpassed"))
            or tests.get("suites_completed") != 3
            or tests.get("non_forward_historical_exclusions")
            != list(NON_FORWARD_HISTORICAL_EXCLUSIONS)
            or not isinstance(auxiliary, list)
            or auxiliary != []):
        raise DeployRefused("validation certified test summary is incomplete")

    return ReviewedValidation(
        mode=mode, path=path, bundle_sha256=bundle_digest,
        git_commit=commit, runtime_image_digest=runtime_digest,
        test_image_digest=candidate_digest,
        source_identity_sha256=source_identity,
        auxiliary_image_digests=tuple(str(item) for item in auxiliary),
        shadow_configuration_sha256=shadow_configuration_digest,
        data_publication_sha256=data_publication_digest,
        validation=validation, test_summary=tests)


def _read_only_command(
        invoke, argv: Sequence[str], *,
        env: Optional[Mapping[str, str]] = None) -> subprocess.CompletedProcess:
    command = [str(item) for item in argv]
    try:
        return invoke(
            command, cwd=str(ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, check=False,
            env=(dict(env) if env is not None else None))
    except OSError as exc:
        raise DeployRefused(
            "required reviewed-bundle verification command is unavailable") from exc


def _current_data_publication_subject(
        reviewed: ReviewedValidation, *, env: Mapping[str, str],
        invoke) -> str:
    explained = _read_only_command(
        invoke, ["bash", "scripts/sentinel-compose.sh", "--explain"],
        env=env)
    if explained.returncode != 0:
        raise DeployRefused("reviewed data publication Compose graph is unavailable")
    try:
        compose_args = shlex.split((explained.stdout or "").strip())
    except ValueError as exc:
        raise DeployRefused(
            "reviewed data publication Compose graph is malformed") from exc
    if not compose_args or "-f" not in compose_args:
        raise DeployRefused("reviewed data publication Compose graph is unavailable")
    run_env = {
        key: value for key, value in env.items()
        if key not in {
            "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
            "SENTINEL_PAPER_ACCOUNT_ID",
        }
    }
    run_env["SENTINEL_RUNTIME_IMAGE_REF"] = reviewed.runtime_image_digest
    completed = _read_only_command(invoke, [
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", "--entrypoint", "python", "sentinel",
        "-c", _DATA_PUBLICATION_CODE,
    ], env=run_env)
    marker = "SENTINEL_DEPLOY_DATA_BINDING="
    payload = None
    if completed.returncode == 0:
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
    if (not isinstance(payload, dict)
            or payload.get("transaction_read_only") is not True):
        raise DeployRefused(
            "current data publication could not be read without mutation")
    return data_publication_subject_value(payload.get("binding"))


def _reviewed_shadow_lineage_preflight(
        reviewed: ReviewedValidation, *, env: Mapping[str, str],
        invoke) -> None:
    explained = _read_only_command(
        invoke, ["bash", "scripts/sentinel-compose.sh", "--explain"],
        env=env)
    if explained.returncode != 0:
        raise DeployRefused("shadow lineage Compose graph is unavailable")
    try:
        compose_args = shlex.split((explained.stdout or "").strip())
    except ValueError as exc:
        raise DeployRefused("shadow lineage Compose graph is malformed") from exc
    if not compose_args or "-f" not in compose_args:
        raise DeployRefused("shadow lineage Compose graph is unavailable")
    run_env = {
        key: value for key, value in env.items()
        if key not in {
            "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
            "SENTINEL_PAPER_ACCOUNT_ID",
        }
    }
    retained_runtime_digest = str(
        env.get("SENTINEL_RUNTIME_IMAGE_DIGEST") or "").strip()
    runtime_artifact_digest = (
        retained_runtime_digest
        if _DIGEST.fullmatch(retained_runtime_digest)
        else reviewed.runtime_image_digest)
    run_env.update({
        "SENTINEL_RUNTIME_IMAGE_REF": reviewed.runtime_image_digest,
        "SENTINEL_SHADOW_OBSERVATION_ENABLED": "1",
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": (
            reviewed.source_identity_sha256),
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": (
            reviewed.shadow_configuration_sha256 or ""),
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": (
            reviewed.data_publication_sha256 or ""),
        "SENTINEL_GIT_COMMIT": reviewed.git_commit,
        # Runtime identity keeps registry/deployment artifacts outside the
        # source hash but inside immutable lineage identity. Before promotion,
        # an existing lineage must therefore see its persisted RepoDigest;
        # after promotion the caller's env contains the intended RepoDigest.
        "SENTINEL_RUNTIME_IMAGE_DIGEST": runtime_artifact_digest,
    })
    forwarded = (
        "SENTINEL_SHADOW_OBSERVATION_ENABLED",
        "SENTINEL_SHADOW_OBSERVATION_ID",
        "SENTINEL_SHADOW_STARTING_CASH",
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
        "SENTINEL_GIT_COMMIT",
        "SENTINEL_RUNTIME_IMAGE_DIGEST",
    )
    env_args = [item for name in forwarded for item in ("-e", name)]
    completed = _read_only_command(invoke, [
        "docker", "compose", *compose_args, "--profile", "cli", "run",
        "--rm", "-T", "--no-deps", *env_args,
        "--entrypoint", "python", "sentinel",
        "-m", "sentinel.shadow_service", "--preflight",
    ], env=run_env)
    if completed.returncode != 0:
        raise DeployRefused(
            "configured shadow lineage is not safely resumable")
    try:
        payload = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise DeployRefused(
            "configured shadow lineage preflight is malformed") from exc
    if (not isinstance(payload, dict)
            or payload.get("schema") != "sentinel.shadow-service-preflight/1"
            or payload.get("mode") != "BROKER_FREE_SHADOW"
            or payload.get("status") not in {
                "NOT_STARTED", "VERIFIED", "RECOVERY_REQUIRED"}
            or payload.get("broker_mutations_authorized") is not False):
        raise DeployRefused(
            "configured shadow lineage preflight did not prove safe state")


def verify_reviewed_shadow_bindings(
        reviewed: ReviewedValidation, *, env: Mapping[str, str], invoke) -> None:
    if reviewed.mode not in {"shadow", "dual"}:
        return
    configured = shadow_configuration_sha256(
        env, source_identity_sha256=reviewed.source_identity_sha256)
    if configured != reviewed.shadow_configuration_sha256:
        raise DeployRefused(
            "local shadow observation id/capital/model/source differs from review")
    current_data = _current_data_publication_subject(
        reviewed, env=env, invoke=invoke)
    if (_validation_subject_digest("data_publication", current_data)
            != reviewed.data_publication_sha256):
        raise DeployRefused(
            "current publication fingerprint/frontier differs from review")
    _reviewed_shadow_lineage_preflight(
        reviewed, env=env, invoke=invoke)


def verify_reviewed_validation_environment(
        reviewed: ReviewedValidation, *, env: Mapping[str, str],
        invoke=subprocess.run) -> None:
    """Bind reviewed bytes to the current checkout and exact local images."""
    def git_output(*args: str) -> str:
        completed = _read_only_command(invoke, ["git", *args])
        if completed.returncode != 0:
            raise DeployRefused("reviewed-bundle Git verification failed")
        return (completed.stdout or "").strip()

    dirty = git_output("status", "--porcelain", "--untracked-files=all")
    branch = git_output("symbolic-ref", "--quiet", "--short", "HEAD")
    head = git_output("rev-parse", "HEAD")
    origin = git_output("rev-parse", "origin/main")
    target = str(env.get("SENTINEL_DEPLOY_GIT_BRANCH", "main") or "main")
    if dirty:
        raise DeployRefused(
            "reviewed deployment requires an exact clean working tree")
    if branch != "main" or target != "main":
        raise DeployRefused("reviewed deployment requires checked-out main")
    if (head != reviewed.git_commit or origin != reviewed.git_commit
            or _HEX40.fullmatch(head) is None):
        raise DeployRefused(
            "reviewed bundle does not match exact local HEAD and origin/main")

    image_ids = (
        reviewed.runtime_image_digest,
        reviewed.test_image_digest,
        *reviewed.auxiliary_image_digests,
    )
    if len(set(image_ids)) != len(image_ids):
        raise DeployRefused("reviewed image identities are not distinct")
    inspected = _read_only_command(
        invoke, ["docker", "image", "inspect", *image_ids])
    if inspected.returncode != 0:
        raise DeployRefused(
            "one or more reviewed local image identities are unavailable")
    try:
        records = _json_value(
            (inspected.stdout or "").encode("utf-8"),
            label="Docker image inspection")
    except UnicodeEncodeError as exc:
        raise DeployRefused("Docker image inspection is not UTF-8") from exc
    if not isinstance(records, list) or len(records) != len(image_ids):
        raise DeployRefused("Docker image inspection is incomplete")
    by_id = {}
    for record in records:
        if not isinstance(record, dict):
            raise DeployRefused("Docker image inspection record is malformed")
        image_id = str(record.get("Id") or "")
        if image_id in by_id or image_id not in image_ids:
            raise DeployRefused("Docker image inspection identity differs")
        labels = ((record.get("Config") or {}).get("Labels")
                  if isinstance(record.get("Config"), dict) else None)
        if (not isinstance(labels, dict)
                or labels.get("org.opencontainers.image.revision")
                != reviewed.git_commit):
            raise DeployRefused(
                "reviewed image revision does not match the reviewed commit")
        rootfs = record.get("RootFS")
        layers = rootfs.get("Layers") if isinstance(rootfs, dict) else None
        if (not isinstance(layers, list) or not layers
                or any(not isinstance(item, str) or not item for item in layers)):
            raise DeployRefused("reviewed image layer identity is malformed")
        by_id[image_id] = list(layers)
    if set(by_id) != set(image_ids):
        raise DeployRefused("Docker image identities are not exact")
    runtime_layers = by_id[reviewed.runtime_image_digest]
    test_layers = by_id[reviewed.test_image_digest]
    if test_layers[:len(runtime_layers)] != runtime_layers:
        raise DeployRefused(
            "reviewed test image is not layered on the reviewed runtime")

    identity = _read_only_command(invoke, [
        "docker", "run", "--rm", "--network", "none",
        "--entrypoint", "python", reviewed.runtime_image_digest,
        "-m", "sentinel", "identity", "--require-environment-compatible",
    ])
    if identity.returncode != 0:
        raise DeployRefused(
            "reviewed runtime could not reproduce its certified identity")
    runtime_identity = _json_value(
        (identity.stdout or "").encode("utf-8"),
        label="reviewed runtime identity")
    if (not isinstance(runtime_identity, dict)
            or runtime_identity.get("identity_hash")
            != reviewed.source_identity_sha256):
        raise DeployRefused(
            "reviewed runtime source identity differs from validation")
    verify_reviewed_shadow_bindings(
        reviewed, env=env, invoke=invoke)


def verify_reviewed_validation_bundle(
        path: Path, *, mode: str, confirmation: str,
        env: Mapping[str, str], now: Optional[datetime] = None,
        invoke=subprocess.run) -> ReviewedValidation:
    reviewed = parse_reviewed_validation_bundle(
        path, mode=mode, confirmation=confirmation, now=now)
    verify_reviewed_validation_environment(
        reviewed, env=env, invoke=invoke)
    return reviewed


def verify_reviewed_account_binding(
        reviewed: ReviewedValidation, account_id: str) -> None:
    """Bind a broker-capable activation to the account observed in review."""
    raw = str(account_id or "").strip()
    if not raw:
        raise DeployRefused("reviewed deployment account binding is empty")
    subjects = {
        str(item["kind"]): str(item["digest"])
        for item in reviewed.validation.get("subjects", [])
    }
    configured = subjects.get("configured_paper_account")
    observed = subjects.get("alpaca_paper_account")
    if configured is not None:
        matches = configured == _validation_subject_digest(
            "configured_paper_account", raw)
    else:
        matches = observed == _validation_subject_digest(
            "alpaca_paper_account", raw)
    if reviewed.mode in {"dual", "paper"} and not matches:
        raise DeployRefused(
            "reviewed PAPER account binding differs from deployment account")
    if configured is not None and not matches:
        raise DeployRefused(
            "reviewed configured account differs from deployment account")


def deployment_request(
        *, mode: Optional[str], validation_bundle: Optional[Path],
        confirmation: Optional[str], env: Mapping[str, str],
        now: Optional[datetime] = None,
        invoke=subprocess.run) -> Optional[ReviewedValidation]:
    supplied = (mode is not None, validation_bundle is not None,
                confirmation is not None)
    if not any(supplied):
        return None
    if not all(supplied):
        raise DeployRefused(
            "--mode, --validation-bundle, and --confirm-reviewed-go are one required set")
    assert mode is not None and validation_bundle is not None
    assert confirmation is not None
    return verify_reviewed_validation_bundle(
        validation_bundle, mode=mode, confirmation=confirmation,
        env=env, now=now, invoke=invoke)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_bool(value: str, *, name: str) -> bool:
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise DeployRefused("%s must be 0/1 or true/false" % name)


def _int(value: str, *, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise DeployRefused("%s must be an integer" % name) from exc
    if parsed < minimum or parsed > maximum:
        raise DeployRefused(
            "%s must be in [%d, %d]" % (name, minimum, maximum))
    return parsed


def load_dotenv(path: Path) -> Dict[str, str]:
    """Read literal KEY=VALUE records without executing shell syntax.

    Process environment wins later.  Unquoted `#` remains part of a value on
    purpose: treating it as a comment can silently truncate a database password.
    """
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise DeployRefused("%s:%d is not KEY=VALUE" % (path, number))
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise DeployRefused("%s:%d has an invalid variable name" % (path, number))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\\"", '"').replace("\\\\", "\\")
        values[key] = value
    return values


def merged_environment(path: Path = ENV_PATH) -> Dict[str, str]:
    env = dict(load_dotenv(path))
    env.update(os.environ)
    return env


def _require(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise DeployRefused("%s is required in .env or the process environment" % name)
    return value


def _resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class Config:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = dict(env)
        self.deployment_id = _require(env, "SENTINEL_DEPLOYMENT_ID")
        self.account_id = _require(env, "SENTINEL_PAPER_ACCOUNT_ID")
        self.runtime_repository = _require(env, "SENTINEL_RUNTIME_IMAGE_REPOSITORY")
        self.test_repository = _require(env, "SENTINEL_TEST_IMAGE_REPOSITORY")
        self.signing_key_id = _require(env, "SENTINEL_DEPLOY_SIGNING_KEY_ID")
        self.signing_key = _resolve_repo_path(
            _require(env, "SENTINEL_DEPLOY_SIGNING_KEY_FILE"))
        self.authority_dir = _resolve_repo_path(
            _require(env, "SENTINEL_AUTHORITY_ARTIFACTS_DIR"))
        self.actor = str(env.get(
            "SENTINEL_DEPLOY_ACTOR", "sentinel-autonomous-deploy")).strip()
        self.reviewer = str(env.get(
            "SENTINEL_DEPLOY_REVIEWER", self.actor)).strip()
        self.ticket_prefix = str(env.get(
            "SENTINEL_DEPLOY_TICKET_PREFIX", "autonomous-deploy")).strip()
        self.max_exposure = str(env.get(
            "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE", "1")).strip()
        self.not_before_margin = _int(
            env.get("SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS", "120"),
            name="SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS",
            minimum=0, maximum=1800)
        self.health_timeout = _int(
            env.get("SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS", "300"),
            name="SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS",
            minimum=30, maximum=1800)
        self.allow_empty_bind = _as_bool(
            env.get("SENTINEL_DEPLOY_ALLOW_EMPTY_BIND", "0"),
            name="SENTINEL_DEPLOY_ALLOW_EMPTY_BIND")
        self.heartbeat_seconds = _int(
            env.get("SENTINEL_AUTOMATION_HEARTBEAT_SECONDS", "10"),
            name="SENTINEL_AUTOMATION_HEARTBEAT_SECONDS",
            minimum=1, maximum=300)

        if str(env.get("ALPACA_BASE_URL", PAPER_URL)).rstrip("/") != PAPER_URL:
            raise DeployRefused(
                "ALPACA_BASE_URL must be exactly %s for autonomous deployment" % PAPER_URL)
        for name in (
                "SENTINEL_POSTGRES_PASSWORD", "SENTINEL_BACKUP_DIR",
                "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SHARADAR_API_KEY"):
            _require(env, name)
        if "@" in self.runtime_repository or "@" in self.test_repository:
            raise DeployRefused("image repositories must be mutable repository names, not digests")
        if not self.actor or not self.reviewer or not self.ticket_prefix:
            raise DeployRefused("deploy actor, reviewer, and ticket prefix must be non-empty")
        try:
            exposure = Decimal(self.max_exposure)
        except InvalidOperation as exc:
            raise DeployRefused("SENTINEL_DEPLOY_MAXIMUM_EXPOSURE is not a decimal") from exc
        if not exposure.is_finite() or exposure < 0 or exposure > 1:
            raise DeployRefused("SENTINEL_DEPLOY_MAXIMUM_EXPOSURE must be finite in [0,1]")
        if not self.signing_key.is_file():
            raise DeployRefused("signing key is not a readable file: %s" % self.signing_key)
        if _under(self.signing_key, ROOT):
            raise DeployRefused("private signing key must live outside the Git checkout")
        self.authority_dir.mkdir(parents=True, exist_ok=True)


class Runner:
    def __init__(self, env: Mapping[str, str], log_path: Path) -> None:
        self.env = dict(env)
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def run(self, argv: Sequence[str], *, check: bool = True,
            capture: bool = False, stream: bool = False,
            cwd: Path = ROOT) -> subprocess.CompletedProcess:
        argv = [str(item) for item in argv]
        stamp = _utc_text(_utcnow())
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write("\n[%s] $ %s\n" % (stamp, " ".join(shlex.quote(x) for x in argv)))
            log.flush()
        try:
            if stream:
                process = subprocess.Popen(
                    argv, cwd=str(cwd), env=self.env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                output: List[str] = []
                assert process.stdout is not None
                for line in process.stdout:
                    output.append(line)
                    print(line, end="", flush=True)
                returncode = process.wait()
                completed = subprocess.CompletedProcess(
                    argv, returncode, stdout="".join(output), stderr="")
            else:
                completed = subprocess.run(
                    argv, cwd=str(cwd), env=self.env,
                    stdout=subprocess.PIPE if capture else None,
                    stderr=subprocess.PIPE if capture else None,
                    text=True, check=False)
        except OSError as exc:
            raise DeployRefused("could not execute %s: %s" % (argv[0], exc)) from exc
        if capture or stream:
            with self.log_path.open("a", encoding="utf-8") as log:
                if completed.stdout:
                    log.write(completed.stdout)
                if completed.stderr:
                    log.write(completed.stderr)
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            tail = " | ".join(detail[-4:])[:1200]
            raise DeployRefused(
                "command failed (%d): %s%s" % (
                    completed.returncode, " ".join(argv),
                    (" — " + tail) if tail else ""))
        return completed


class DeploymentLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DeployRefused("another autonomous deployment holds %s" % self.path) from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write("pid=%d started=%s\n" % (os.getpid(), _utc_text(_utcnow())))
        self.handle.flush()
        return self

    def __exit__(self, *_args):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _json_output(completed: subprocess.CompletedProcess, *, label: str) -> Mapping:
    try:
        value = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise DeployRefused("%s did not return JSON" % label) from exc
    if not isinstance(value, dict):
        raise DeployRefused("%s did not return a JSON object" % label)
    return value


def _repo_digest(value: str, expected_repository: str) -> Tuple[str, str]:
    value = value.strip()
    prefix = expected_repository + "@"
    if not value.startswith(prefix):
        raise DeployRefused("promotion returned a different repository: %s" % value)
    digest = value[len(prefix):]
    if _DIGEST.fullmatch(digest) is None:
        raise DeployRefused("promotion did not return an immutable SHA-256 digest")
    return value, digest


def validate_owned_status(status: Mapping, cfg: Config) -> str:
    state = status.get("ownership")
    if state == "UNKNOWN":
        raise DeployRefused("canonical account ownership is UNKNOWN")
    if state == "OWNED":
        if (status.get("broker") != "alpaca"
                or status.get("broker_account_id") != cfg.account_id
                or status.get("deployment_id") != cfg.deployment_id
                or not isinstance(status.get("takeover_epoch"), int)
                or int(status["takeover_epoch"]) < 1):
            raise DeployRefused(
                "durable OWNED binding does not match configured deployment/account")
        return "OWNED"
    if state == "NOT_OWNED":
        if not cfg.allow_empty_bind:
            raise DeployRefused(
                "account is NOT_OWNED; set SENTINEL_DEPLOY_ALLOW_EMPTY_BIND=1 only for a known empty new paper account")
        return "NOT_OWNED"
    raise DeployRefused("canonical ownership state is malformed: %r" % (state,))


def validate_deployment_integrity_status(status: Mapping, cfg: Config) -> str:
    """Validate durable authority-bearing state without requiring readiness."""
    state = status.get("ownership")
    if state == "OWNED":
        if (status.get("broker") != "alpaca"
                or status.get("broker_account_id") != cfg.account_id
                or status.get("deployment_id") != cfg.deployment_id
                or not isinstance(status.get("takeover_epoch"), int)
                or int(status["takeover_epoch"]) < 1):
            raise DeployRefused(
                "durable OWNED binding contradicts configured deployment/account")
    elif state == "NOT_OWNED":
        # Enrollment is an activation prerequisite, not an install prerequisite.
        pass
    elif state == "UNKNOWN":
        raise DeployRefused("canonical account ownership is UNKNOWN")
    else:
        raise DeployRefused("canonical ownership state is malformed: %r" % (state,))

    for field in ("paper_execution_authority", "administrative_authority"):
        value = status.get(field)
        if not isinstance(value, dict):
            raise DeployRefused("%s status is malformed" % field)
        if value.get("error"):
            raise DeployRefused(
                "%s durable state is unreadable: %s" % (field, value["error"]))
    return str(state)


def classify_paper_account_for_deployment(payload: Mapping, cfg: Config) -> str:
    """Separate broker identity integrity from temporary operational readiness."""
    if not isinstance(payload, dict):
        raise DeployRefused("Alpaca account response is not an object")
    identities = {
        str(payload.get("id") or ""),
        str(payload.get("account_number") or ""),
    }
    if cfg.account_id not in identities:
        raise DeployRefused("Alpaca credentials resolve to a different paper account")
    if str(payload.get("status") or "").upper() != "ACTIVE":
        return "BROKER_NOT_READY"
    for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
        if payload.get(flag) is not False:
            return "BROKER_NOT_READY"
    return "BROKER_READY"


def health_heartbeat_proof(first: Mapping, second: Mapping, *, cfg: Config,
                           certificate_sha256: str) -> None:
    for label, health in (("first", first), ("second", second)):
        if health.get("operational_ready") is not True:
            raise DeployRefused("%s health sample is not operationally ready" % label)
        if health.get("policy_state") != "LEADER_ACTIVE":
            raise DeployRefused("%s health sample has no active leader" % label)
        if (health.get("deployment_id") != cfg.deployment_id
                or health.get("broker_account_id") != cfg.account_id
                or health.get("certificate_sha256") != certificate_sha256
                or health.get("authority_verdict") != "PASS"
                or health.get("authority_lifecycle_current") is not True):
            raise DeployRefused("%s health sample authority identity is not exact" % label)
        if int(health.get("dead_letter_alerts") or 0) != 0:
            raise DeployRefused("%s health sample has dead-letter alerts" % label)
        if health.get("latest_cycle_state") == "BLOCKED" or health.get("latest_failure_code"):
            raise DeployRefused("%s health sample contains a latched automation failure" % label)
    for field in ("control_generation", "leader_holder", "fencing_token"):
        if not first.get(field) or first.get(field) != second.get(field):
            raise DeployRefused("leader proof changed %s between heartbeat samples" % field)
    before = first.get("leader_heartbeat_at")
    after = second.get("leader_heartbeat_at")
    if not before or not after or str(after) <= str(before):
        raise DeployRefused("leader heartbeat did not advance between health samples")


class AutonomousDeploy:
    def __init__(self, cfg: Config, runner: Runner, attempt_dir: Path,
                 reviewed_validation: Optional[ReviewedValidation] = None) -> None:
        self.cfg = cfg
        self.runner = runner
        self.attempt_dir = attempt_dir
        self.env = runner.env
        self.commit = ""
        self.base_compose: List[str] = []
        self.automation_overlay = "docker-compose.sentinel-automation.yml"
        self.runtime_repo_digest = ""
        self.test_repo_digest = ""
        self.runtime_digest = ""
        self.test_digest = ""
        self.transition_started = False
        self.active_certificate = ""
        self.new_certificate = ""
        self.account_equity = Decimal(0)
        self.broker_readiness = "BROKER_NOT_CHECKED"
        self.ownership_state = "UNKNOWN"
        self.reviewed_validation = reviewed_validation

    def phase(self, text: str) -> None:
        print("\n== %s" % text, flush=True)

    def git_preflight(self) -> None:
        self.phase("preflight: exact clean Git checkout")
        dirty = self.runner.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            capture=True).stdout.strip()
        if dirty:
            raise DeployRefused("working tree became dirty after fast-forward")
        branch = self.runner.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture=True).stdout.strip()
        target = self.env.get("SENTINEL_DEPLOY_GIT_BRANCH", "main")
        if branch != target:
            raise DeployRefused("checkout branch %s is not deployment branch %s" % (branch, target))
        self.commit = self.runner.run(
            ["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
        if _HEX40.fullmatch(self.commit) is None:
            raise DeployRefused("Git HEAD is not an exact 40-hex commit")

    def verify_reviewed_preflight(self) -> None:
        """Recheck reviewed bytes/Git/images before any deploy-side change."""
        reviewed = self.reviewed_validation
        if reviewed is None:
            return
        try:
            current_digest = _sha256(reviewed.path.read_bytes())
        except OSError as exc:
            raise DeployRefused(
                "reviewed validation bundle disappeared before deployment") from exc
        if (current_digest != reviewed.bundle_sha256
                or self.commit != reviewed.git_commit):
            raise DeployRefused(
                "reviewed validation identity changed before deployment")

        def invoke(argv, **_kwargs):
            return self.runner.run(argv, capture=True)

        verify_reviewed_validation_environment(
            reviewed, env=self.env, invoke=invoke)
        verify_reviewed_account_binding(reviewed, self.cfg.account_id)

    def verify_reviewed_shadow_bindings_quiesced(self) -> None:
        """Recheck reviewed corpus/lineage after all old writers are stopped."""
        reviewed = self.reviewed_validation
        if reviewed is None or reviewed.mode not in {"shadow", "dual"}:
            return
        self.phase(
            "review: recheck exact publication and lineage under writer fence")

        def invoke(argv, **_kwargs):
            return self.runner.run(argv, capture=True)

        verify_reviewed_shadow_bindings(
            reviewed, env=self.env, invoke=invoke)

    def read_paper_account(self) -> None:
        self.phase("preflight: read-only Alpaca paper account identity")
        request = urllib.request.Request(
            PAPER_URL + "/v2/account",
            headers={
                "APCA-API-KEY-ID": _require(self.env, "ALPACA_API_KEY"),
                "APCA-API-SECRET-KEY": _require(self.env, "ALPACA_SECRET_KEY"),
                "Accept": "application/json",
            }, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise DeployRefused("Alpaca paper account read returned HTTP %d" % exc.code) from exc
        except (OSError, ValueError) as exc:
            raise DeployRefused("Alpaca paper account read failed: %s" % type(exc).__name__) from exc
        if not isinstance(payload, dict):
            raise DeployRefused("Alpaca account response is not an object")
        identities = {str(payload.get("id") or ""), str(payload.get("account_number") or "")}
        if self.cfg.account_id not in identities:
            raise DeployRefused("Alpaca credentials resolve to a different paper account")
        if str(payload.get("status") or "").upper() != "ACTIVE":
            raise DeployRefused("Alpaca paper account is not ACTIVE")
        for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
            if payload.get(flag) is not False:
                raise DeployRefused("Alpaca paper account flag %s is not false" % flag)
        try:
            multiplier = Decimal(str(payload["multiplier"]))
            equity = Decimal(str(payload["equity"]))
            cash = Decimal(str(payload["cash"]))
            buying_power = Decimal(str(payload["buying_power"]))
        except (KeyError, InvalidOperation) as exc:
            raise DeployRefused("Alpaca paper account monetary fields are malformed") from exc
        if not all(x.is_finite() for x in (multiplier, equity, cash, buying_power)):
            raise DeployRefused("Alpaca paper account contains non-finite monetary fields")
        if multiplier != 1 or equity <= 0 or cash < 0 or buying_power < 0:
            raise DeployRefused("Alpaca paper account is not a positive cash-only account")
        if abs(buying_power - cash) > Decimal("1.00"):
            raise DeployRefused("Alpaca paper buying power differs from cash by more than $1")
        self.account_equity = equity

    def check_paper_account_deployment_integrity(self) -> str:
        """Read broker identity if reachable; never require broker readiness."""
        self.phase("preflight: broker identity integrity (readiness may be unavailable)")
        request = urllib.request.Request(
            PAPER_URL + "/v2/account",
            headers={
                "APCA-API-KEY-ID": _require(self.env, "ALPACA_API_KEY"),
                "APCA-API-SECRET-KEY": _require(self.env, "ALPACA_SECRET_KEY"),
                "Accept": "application/json",
            }, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 408, 425, 429} or 500 <= exc.code <= 599:
                self.broker_readiness = "BROKER_NOT_READY"
                return self.broker_readiness
            raise DeployRefused(
                "Alpaca paper account integrity probe returned unexpected HTTP %d"
                % exc.code) from exc
        except OSError:
            self.broker_readiness = "BROKER_NOT_READY"
            return self.broker_readiness
        except ValueError as exc:
            raise DeployRefused("Alpaca paper account response is malformed") from exc
        self.broker_readiness = classify_paper_account_for_deployment(
            payload, self.cfg)
        return self.broker_readiness

    def check_durable_deployment_integrity(self) -> Mapping:
        """Refuse contradictory durable authority while allowing not-ready state."""
        self.phase("integrity: durable ownership/authority state (readiness not required)")
        status = self._status()
        self.ownership_state = validate_deployment_integrity_status(
            status, self.cfg)
        return status

    def resolve_compose(self) -> None:
        explained = self.runner.run(
            ["bash", "scripts/sentinel-compose.sh", "--explain"], capture=True)
        args = shlex.split(explained.stdout.strip())
        if not args or "-f" not in args:
            raise DeployRefused("Sentinel Compose resolver returned no graph")
        self.base_compose = ["docker", "compose"] + args
        if any("nocpu" in part for part in args):
            generated = self.attempt_dir / "docker-compose.sentinel-automation.nocpu.yml"
            self.runner.run([
                self.env.get("SENTINEL_HOST_PYTHON", sys.executable),
                "scripts/sentinel_strip_cpu_limits.py",
                "docker-compose.sentinel-automation.yml", str(generated)])
            self.automation_overlay = str(generated)

    def build_promote(self) -> None:
        reviewed = self.reviewed_validation
        self.phase(
            "promote: exact reviewed runtime and test lens" if reviewed
            else "build: exact Sentinel runtime, authorized runtime, and test lens")
        self.resolve_compose()
        if reviewed is None:
            self.runner.run(self.base_compose + [
                "build", "--build-arg", "SOURCE_GIT_SHA=" + self.commit,
                "sentinel", "sentinel-panel"])
            self.runner.run([
                "docker", "build", "--network", "host",
                "--build-arg", "SENTINEL_RUNTIME_BASE_IMAGE=sentinel:latest",
                "--build-arg", "SOURCE_GIT_SHA=" + self.commit,
                "-t", "sentinel-authorized:latest", "-f",
                "Dockerfile.sentinel-authorized", "."])
            self.runner.run([
                "docker", "build", "--network", "host",
                "--build-arg", "SENTINEL_IMAGE=sentinel-authorized:latest",
                "--build-arg", "SOURCE_GIT_SHA=" + self.commit,
                "-t", "sentinel-test:latest", "-f",
                "Dockerfile.sentinel-test", "."])
        else:
            # The validator already built and tested these exact content IDs.
            # Tagging those IDs avoids rebuilding a different artefact after
            # review while retaining the existing promotion machinery.
            self.runner.run([
                "docker", "tag", reviewed.runtime_image_digest,
                "sentinel-authorized:latest"])
            self.runner.run([
                "docker", "tag", reviewed.test_image_digest,
                "sentinel-test:latest"])

        build_record = self.attempt_dir / "image-build.json"
        self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "capture-build",
            "--git-commit", self.commit,
            "--runtime-ref", "sentinel-authorized:latest",
            "--test-ref", "sentinel-test:latest", "--output", str(build_record)])

        if reviewed is None:
            self.phase("test: complete Sentinel suite in the exact new test image")
            suite = self.runner.run([
                "docker", "run", "--rm", "--network", "none",
                "sentinel-test:latest", "tests/sentinel", "-q", "-ra"], stream=True)
            combined = (suite.stdout or "") + "\n" + (suite.stderr or "")
            if re.search(r"(^|, )\d+ skipped(,| in |$)", combined, re.M):
                raise DeployRefused(
                    "complete Sentinel deployment suite skipped tests")

        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--entrypoint", "python", "sentinel-authorized:latest",
            "-m", "sentinel", "identity", "--require-environment-compatible"])
        self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "verify-build",
            "--record", str(build_record)])

        self.phase("promote: push exact image IDs and freeze immutable RepoDigests")
        runtime_tag = self.cfg.runtime_repository + ":" + self.commit
        test_tag = self.cfg.test_repository + ":" + self.commit
        self.runner.run(["docker", "tag", "sentinel-authorized:latest", runtime_tag])
        self.runner.run(["docker", "tag", "sentinel-test:latest", test_tag])
        self.runner.run(["docker", "push", runtime_tag])
        self.runner.run(["docker", "push", test_tag])
        promotion = self.attempt_dir / "image-promotion.json"
        self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "capture-promotion",
            "--build-record", str(build_record), "--runtime-tag", runtime_tag,
            "--test-tag", test_tag, "--output", str(promotion)])
        runtime = self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "resolve-promotion",
            "--record", str(promotion), "--git-commit", self.commit,
            "--kind", "runtime"], capture=True).stdout.strip()
        test = self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "resolve-promotion",
            "--record", str(promotion), "--git-commit", self.commit,
            "--kind", "test"], capture=True).stdout.strip()
        self.runtime_repo_digest, self.runtime_digest = _repo_digest(
            runtime, self.cfg.runtime_repository)
        self.test_repo_digest, self.test_digest = _repo_digest(
            test, self.cfg.test_repository)
        self.env.update({
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REF": self.runtime_repo_digest,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
            "SENTINEL_FEED_AUTHORIZED": "DEPLOYED_REVIEWED_IMAGE_V1",
            "SENTINEL_FEED_SERVICE_MODE": "DEPLOY",
            "SENTINEL_FEED_GIT_COMMIT": self.commit,
            "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_AUTHORITY_ARTIFACTS_DIR": str(self.cfg.authority_dir),
        })
        self.runner.env.update(self.env)
        if reviewed is None or reviewed.mode in {"dual", "paper"}:
            self._verify_signing_key_is_trusted()

    def _verify_signing_key_is_trusted(self) -> None:
        code = (
            "import sys; from sentinel.authority import load_trust_roots; "
            "r=load_trust_roots().get(sys.argv[1]); "
            "assert r is not None and r.status == 'ACTIVE', "
            "'configured signing key is not an ACTIVE trust root'; print(r.key_id)")
        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--entrypoint", "python", "sentinel-test:latest",
            "-c", code, self.cfg.signing_key_id])

    def _running_automation_containers(self) -> List[str]:
        out = self.runner.run([
            "docker", "ps", "-q",
            "--filter", "label=com.docker.compose.project=sentinel",
            "--filter", "label=com.docker.compose.service=sentinel-automation"],
            capture=True).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _running_shadow_containers(self) -> List[str]:
        out = self.runner.run([
            "docker", "ps", "-q",
            "--filter", "label=com.docker.compose.project=sentinel",
            "--filter", "label=com.docker.compose.service=sentinel-shadow"],
            capture=True).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _direct_stop_automation(self) -> None:
        ids = self._running_automation_containers()
        if ids:
            self.runner.run(["docker", "stop"] + ids)

    def _direct_stop_shadow(self) -> None:
        ids = self._running_shadow_containers()
        if ids:
            self.runner.run(["docker", "stop"] + ids)

    def _try_emergency_kill(self) -> bool:
        result = self.runner.run([
            "bash", "scripts/sentinel-emergency-kill.sh",
            "--actor", self.cfg.actor,
            "--reason", "autonomous deploy fail-closed fence"],
            capture=True, check=False)
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        return result.returncode == 0 or "already engaged" in text.lower()

    def fail_close(self) -> None:
        print("\n!! deployment failed after transition boundary; fencing automation", file=sys.stderr)
        try:
            if not self._try_emergency_kill():
                print("!! durable emergency fence could not be confirmed", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - best-effort emergency path
            print("!! emergency fence error: %s" % exc, file=sys.stderr)
        try:
            self._direct_stop_automation()
            self._direct_stop_shadow()
        except Exception as exc:  # noqa: BLE001
            print("!! automation stop error: %s" % exc, file=sys.stderr)

    @contextlib.contextmanager
    def transition(self):
        self.transition_started = True
        try:
            yield
        except BaseException:
            self.fail_close()
            raise

    def _base_cli(self, args: Sequence[str], *, capture: bool = False,
                  check: bool = True) -> subprocess.CompletedProcess:
        return self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T", "sentinel"]
            + list(args), capture=capture, check=check)

    def _authorized_compose(self) -> List[str]:
        return self.base_compose + ["-f", self.automation_overlay]

    def _authorized_cli(self, args: Sequence[str], *, capture: bool = False,
                        check: bool = True) -> subprocess.CompletedProcess:
        return self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "sentinel-authorized-cli"] + list(args), capture=capture, check=check)

    def _status(self) -> Mapping:
        return _json_output(self._base_cli(["status"], capture=True), label="status")

    def _automation_status(self) -> Mapping:
        return _json_output(
            self._base_cli(["automation-status"], capture=True),
            label="automation-status")

    def quiesce_backup_and_migrate(self) -> None:
        self.phase("transition: fence and stop old automation")
        first_kill = self._try_emergency_kill()
        self._direct_stop_automation()
        self._direct_stop_shadow()
        self.phase("transition: start only behavioral PostgreSQL on preserved volume")
        self.runner.run(self.base_compose + ["up", "-d", "sentinel-postgres"])

        self.phase("durability: fresh pre-migration backup and physical replay")
        self.runner.run(["bash", "scripts/sentinel-base-backup.sh"])
        self.runner.run(["bash", "scripts/sentinel-backup-status.sh"])
        self.runner.run([
            "bash", "scripts/sentinel-restore-drill.sh", "--physical-only"])

        self.phase("schema: explicit migration while automation is stopped")
        code = (
            "import os; from sentinel import schema; from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
            "schema.ensure_schema(c); store.migrate_schema(c); c.close(); "
            "print('schema migration PASS')")
        self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel", "-c", code])
        if not self._try_emergency_kill():
            raise DeployRefused(
                "durable automation kill could not be confirmed after schema migration")
        if not first_kill:
            print("  initial kill was unavailable; automation was stopped and durable kill is now confirmed")
        status = self._automation_status()
        if status.get("enabled"):
            self._base_cli([
                "deactivate-paper-automation", "--actor", self.cfg.actor,
                "--reason", "autonomous deployment configuration transition"])
            status = self._automation_status()
        if status.get("enabled") is not False or status.get("kill_switch_engaged") is not True:
            raise DeployRefused("automation did not reach disabled+killed deployment state")

    def refresh_data(self) -> None:
        self.phase("data: current daily ingest and full readiness contract")
        self._base_cli(["feed-daily"])
        self._base_cli(["check-data"])
        self.runner.run(self.base_compose + ["up", "-d", "sentinel-panel"])

    def _artifact_rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.cfg.authority_dir).as_posix()
        except ValueError as exc:
            raise DeployRefused("authority artifact escaped configured directory") from exc

    def _authorized_artifact(self, path: Path) -> str:
        return "/var/lib/sentinel-authority/" + self._artifact_rel(path)

    def _sign(self, *, tool: str, candidate: Path, output: Path,
              confirmation: str) -> str:
        key_mount = "type=bind,src=%s,dst=/signing-key,readonly" % self.cfg.signing_key
        auth_mount = "type=bind,src=%s,dst=/authority" % self.cfg.authority_dir
        candidate_in = "/authority/" + self._artifact_rel(candidate)
        output_in = "/authority/" + self._artifact_rel(output)
        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--mount", key_mount, "--mount", auth_mount,
            "--entrypoint", "python", "sentinel-test:latest",
            "-m", tool, "issue", "--candidate", candidate_in,
            "--private-key-file", "/signing-key", "--key-id",
            self.cfg.signing_key_id, "--output", output_in, confirmation])
        if not output.is_file():
            raise DeployRefused("offline signer did not create %s" % output)
        return hashlib.sha256(output.read_bytes()).hexdigest()

    def _wait_for(self, instant: str) -> None:
        boundary = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        seconds = (boundary - datetime.now(timezone.utc)).total_seconds()
        if seconds > 0:
            print("  waiting %.0fs for signed not_before boundary" % seconds, flush=True)
            time.sleep(seconds + 1)

    def ensure_ownership(self) -> None:
        self.phase("ownership: verify canonical PostgreSQL account binding")
        status = self._status()
        state = validate_owned_status(status, self.cfg)
        if state == "OWNED":
            return
        self.phase("ownership: one-time strict empty-account enrollment")
        admin = status.get("administrative_authority") or {}
        highest = int(admin.get("highest_issuer_generation") or 0)
        generation = highest + 1
        now = _utcnow()
        not_before = now + timedelta(seconds=self.cfg.not_before_margin)
        candidate = self.attempt_dir / "empty-binding-candidate.json"
        cert = self.attempt_dir / "empty-binding-certificate.json"
        candidate_id = "empty-bind-%s-g%d" % (self.commit[:12], generation)
        result = self._authorized_cli([
            "create-empty-paper-binding-candidate",
            "--certificate-id", candidate_id,
            "--issuer-generation", str(generation),
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--not-before", _utc_text(not_before),
            "--reviewer", self.cfg.reviewer,
            "--ticket", "%s-empty-%d" % (self.cfg.ticket_prefix, generation)],
            capture=True)
        candidate.write_text(result.stdout, encoding="utf-8")
        document = json.loads(result.stdout)
        actual_not_before = document["claims"]["not_before"]
        digest = self._sign(
            tool="tools.sentinel_empty_account_authority",
            candidate=candidate, output=cert,
            confirmation="--confirm-issue-empty-paper-binding")
        self._authorized_cli([
            "install-administrative-certificate", "--certificate",
            self._authorized_artifact(cert), "--confirm-certificate-sha256", digest,
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id, "--takeover-epoch", "1",
            "--reason", "autonomous strict-empty enrollment",
            "--confirm-install-administrative-certificate"])
        self._wait_for(actual_not_before)
        self._authorized_cli([
            "activate-administrative-certificate", "--certificate-sha256", digest,
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id, "--takeover-epoch", "1",
            "--reason", "autonomous strict-empty enrollment",
            "--confirm-activate-administrative-certificate"])
        inspected = _json_output(self._authorized_cli([
            "inspect-empty-paper-account", "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id], capture=True),
            label="empty account inspection")
        if (inspected.get("approval_ready") is not True
                or inspected.get("positions") != []
                or inspected.get("working_open_orders") != []):
            raise DeployRefused(
                "unbound account is not provably empty/stable; inherited books are never auto-migrated")
        self._authorized_cli([
            "bind-empty-paper-account", "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--notes", "autonomous strict-empty enrollment"])
        validate_owned_status(self._status(), self.cfg)

    def _execution_authority_state(self) -> Mapping:
        code = (
            "import json,os; from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
            "cur=c.cursor(); cur.execute(\"SELECT COALESCE((SELECT highest_issuer_generation FROM sentinel_execution_authority_state WHERE id=1),0), (SELECT active_certificate_sha256 FROM sentinel_execution_authority_state WHERE id=1)\"); "
            "r=cur.fetchone(); print(json.dumps({'highest_issuer_generation':int(r[0]),'active_certificate_sha256':r[1]})); c.rollback(); c.close()")
        result = self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel-authorized-cli", "-c", code],
            capture=True)
        return _json_output(result, label="execution authority state")

    def rotate_observation_authority(self) -> Tuple[str, str]:
        self.phase("authority: build and offline-sign renewable paper observation lease")
        state = self._execution_authority_state()
        generation = int(state.get("highest_issuer_generation") or 0) + 1
        predecessor = state.get("active_certificate_sha256")
        if predecessor is not None and re.fullmatch(r"[0-9a-f]{64}", str(predecessor)) is None:
            raise DeployRefused("active execution certificate identity is malformed")
        now = _utcnow()
        not_before = now + timedelta(seconds=self.cfg.not_before_margin)
        candidate = self.attempt_dir / "paper-observation-candidate.json"
        cert = self.attempt_dir / "paper-observation-certificate.json"
        certificate_id = "paper-observation-%s-g%d" % (self.commit[:12], generation)
        result = self._authorized_cli([
            "create-paper-observation-candidate",
            "--certificate-id", certificate_id,
            "--issuer-generation", str(generation),
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--not-before", _utc_text(not_before),
            "--maximum-exposure", self.cfg.max_exposure,
            "--cash", str(self.account_equity),
            "--reviewer", self.cfg.reviewer,
            "--ticket", "%s-observation-%d" % (self.cfg.ticket_prefix, generation)],
            capture=True)
        candidate.write_text(result.stdout, encoding="utf-8")
        document = json.loads(result.stdout)
        claims = document["claims"]
        evidence = document["retained_evidence"]
        decision_session = evidence["warmup"]["decision_session"]
        actual_not_before = claims["not_before"]
        if claims.get("supersedes_certificate_sha256") != predecessor:
            raise DeployRefused("candidate predecessor differs from durable authority")
        digest = self._sign(
            tool="tools.sentinel_observation_authority",
            candidate=candidate, output=cert,
            confirmation="--confirm-issue-paper-observation-only")
        self._authorized_cli([
            "install-system-certificate", "--certificate",
            self._authorized_artifact(cert), "--confirm-certificate-sha256", digest,
            "--reason", "autonomous renewable paper observation deploy",
            "--confirm-install-alpaca-paper-execution-certificate"])
        self._wait_for(actual_not_before)
        if predecessor:
            self._authorized_cli([
                "rotate-system-certificate", "--certificate-sha256", digest,
                "--confirm-supersedes-certificate-sha256", str(predecessor),
                "--confirm-paper-account", self.cfg.account_id,
                "--confirm-deployment-id", self.cfg.deployment_id,
                "--reason", "autonomous renewable paper observation deploy",
                "--confirm-rotate-alpaca-paper-execution-certificate",
                "--confirm-controller-rollout"])
        else:
            self._authorized_cli([
                "activate-system-certificate", "--certificate-sha256", digest,
                "--confirm-paper-account", self.cfg.account_id,
                "--confirm-deployment-id", self.cfg.deployment_id,
                "--reason", "autonomous first paper observation deploy",
                "--confirm-activate-alpaca-paper-execution-certificate",
                "--confirm-controller-rollout"])
        self.active_certificate = str(predecessor or "")
        self.new_certificate = digest
        return digest, decision_session

    def prepare_activate_start(self, certificate_sha256: str,
                               decision_session: str) -> Mapping:
        self.phase("plan: prepare one current durable paper plan")
        prepare_args = [
            "prepare-paper-plan", "--through", decision_session,
            "--warmup-sessions", "252", "--expect-account", self.cfg.account_id]
        if (self.reviewed_validation is not None
                and self.reviewed_validation.mode == "dual"):
            prepare_args.append("--reviewed-informational-dual")
        prepared = _json_output(self._authorized_cli(prepare_args,
            capture=True), label="prepared paper plan")
        current = _json_output(self._base_cli(
            ["current-paper-plan"], capture=True), label="current paper plan")
        plan = prepared.get("plan") or {}
        if plan.get("decision_session") != decision_session:
            raise DeployRefused("prepared plan decision session differs from signed warmup")
        if current.get("database_authorities_match") is False:
            raise DeployRefused("current plan database authorities do not match")
        if (self.reviewed_validation is not None
                and self.reviewed_validation.mode == "dual"):
            self._verify_dual_plan_shadow_reconciliation()

        self.phase("automation: activate behind kill, start pinned service, then release")
        self._authorized_cli([
            "activate-paper-automation",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--confirm-old-writer-fenced", "--actor", self.cfg.actor,
            "--reason", "autonomous deployment",
            "--confirm-enable-unattended-alpaca-paper-automation"])
        self.runner.run(self._authorized_compose() + [
            "--profile", "automation", "up", "-d", "sentinel-automation"])
        killed = self._automation_status()
        if (killed.get("enabled") is not True
                or killed.get("kill_switch_engaged") is not True
                or killed.get("certificate_sha256") != certificate_sha256):
            raise DeployRefused("automation did not start behind the expected kill fence")
        self._authorized_cli([
            "release-paper-automation-kill-switch",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--actor", self.cfg.actor, "--reason", "autonomous deployment verified",
            "--confirm-release-unattended-paper-kill-switch"])
        return current

    def _verify_dual_plan_shadow_reconciliation(self) -> Mapping:
        """Re-earn the exact plan/shadow bridge inside the promoted runtime."""
        self.phase(
            "reconcile: exact certified shadow intent versus PAPER plan")
        code = (
            "import json,os; from decimal import Decimal; "
            "from sentinel import dual_reconciliation; "
            "from sentinel.execution import journal; "
            "from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
            "cur=c.cursor(); cur.execute('BEGIN TRANSACTION READ ONLY'); "
            "p=journal.latest_plan(c); "
            "assert p is not None, 'current PAPER plan is absent'; "
            "r=dual_reconciliation.require_plan_matches_verified_shadow("
            "c,plan=p,observation_id=os.environ.get("
            "'SENTINEL_SHADOW_OBSERVATION_ID','primary'),"
            "starting_cash=Decimal(os.environ.get("
            "'SENTINEL_SHADOW_STARTING_CASH','100000'))); "
            "print('SENTINEL_DUAL_RECONCILIATION='+json.dumps("
            "r,sort_keys=True)); c.rollback(); c.close()")
        completed = self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel-authorized-cli",
            "-c", code], capture=True)
        marker = "SENTINEL_DUAL_RECONCILIATION="
        payload = None
        for line in (completed.stdout or "").splitlines():
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    payload = None
        if (not isinstance(payload, dict)
                or payload.get("schema")
                != "sentinel.dual-plan-shadow-reconciliation/1"
                or payload.get("verdict") != "MATCH"
                or _HEX64.fullmatch(
                    str(payload.get("state_sha256") or "")) is None
                or _HEX64.fullmatch(str(payload.get(
                    "shadow_runtime_authority_sha256") or "")) is None
                or _HEX64.fullmatch(str(payload.get(
                    "sizing_authority_sha256") or "")) is None
                or _HEX64.fullmatch(str(payload.get(
                    "plan_fingerprint") or "")) is None):
            raise DeployRefused(
                "PAPER plan did not exactly match certified shadow intent")
        return payload

    def _wait_for_dual_shadow_session(self, decision_session: str) -> Mapping:
        """Wait only for the already-started broker-free service to attest."""
        self.phase(
            "shadow: wait for current decision-close runtime attestation")
        deadline = time.monotonic() + self.cfg.health_timeout
        last = None
        while time.monotonic() < deadline:
            completed = self.runner.run(self._authorized_compose() + [
                "--profile", "shadow", "exec", "-T", "sentinel-shadow",
                "python", "-m", "sentinel", "shadow-status"],
                capture=True, check=False)
            if completed.returncode == 0:
                try:
                    last = json.loads(completed.stdout or "")
                except json.JSONDecodeError:
                    last = None
                if (isinstance(last, dict)
                        and last.get("session") == decision_session
                        and last.get("shadow_verdict") == "SHADOW_GO"
                        and last.get("verification") == "VERIFIED"):
                    return last
            time.sleep(3)
        raise DeployRefused(
            "certified shadow did not attest the PAPER decision close before "
            "the deployment timeout")

    def _wait_operational(self) -> Mapping:
        deadline = time.monotonic() + self.cfg.health_timeout
        last = None
        while time.monotonic() < deadline:
            last = self._automation_status()
            if (last.get("operational_ready") is True
                    and last.get("policy_state") == "LEADER_ACTIVE"):
                return last
            if last.get("latest_cycle_state") == "BLOCKED" or last.get("latest_failure_code"):
                raise DeployRefused("automation latched a failure while becoming operational")
            time.sleep(3)
        raise DeployRefused(
            "automation did not become operational before timeout; last policy=%r" %
            ((last or {}).get("policy_state"),))

    def verify_operational(self, certificate_sha256: str) -> Mapping:
        self.phase("prove: active leader, exact authority, and advancing heartbeat")
        first = self._wait_operational()
        time.sleep(self.cfg.heartbeat_seconds + 2)
        second = self._automation_status()
        health_heartbeat_proof(
            first, second, cfg=self.cfg,
            certificate_sha256=certificate_sha256)
        status = self._status()
        validate_owned_status(status, self.cfg)
        authority = status.get("paper_execution_authority") or {}
        if (authority.get("authority_mode") != "PAPER_OBSERVATION_ONLY"
                or authority.get("lifecycle_current") is not True):
            raise DeployRefused("final status does not show current PAPER_OBSERVATION_ONLY authority")
        return second

    def start_fenced_runtime(self) -> Mapping:
        """Start the exact promoted runtime while durable trading fences stay on."""
        self.phase("install: start exact promoted runtime in DEPLOYED/FENCED state")
        before = self._automation_status()
        if (before.get("enabled") is not False
                or before.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "fenced runtime install requires disabled+killed automation")
        reviewed_shadow = (
            self.reviewed_validation is not None
            and self.reviewed_validation.mode in {"shadow", "dual"})
        if reviewed_shadow:
            self._direct_stop_automation()
            if self._running_automation_containers():
                raise DeployRefused(
                    "broker-capable automation remains running in shadow mode")
            self.runner.run(self._authorized_compose() + [
                "--profile", "shadow", "up", "-d", "--wait",
                "--wait-timeout", str(self.cfg.health_timeout),
                "sentinel-shadow"])
        else:
            # Fenced/no-args deployments may not inherit a previously reviewed
            # shadow process after its reviewed facts have been cleared.
            self._direct_stop_shadow()
            self.runner.run(self._authorized_compose() + [
                "--profile", "automation", "up", "-d",
                "sentinel-automation"])
        after = self._automation_status()
        if (after.get("enabled") is not False
                or after.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "new runtime did not remain disabled+killed after install")
        return after

    def configure_reviewed_mode_while_fenced(self) -> None:
        """Persist reviewed mode, or force unreviewed installs shadow-off."""
        reviewed = self.reviewed_validation
        status = self._automation_status()
        if (status.get("enabled") is not False
                or status.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "reviewed mode may be persisted only while automation is disabled+killed")
        enabled = (
            "1" if reviewed is not None
            and reviewed.mode in {"shadow", "dual"} else "0")
        updates = {
            "SENTINEL_SHADOW_OBSERVATION_ENABLED": enabled,
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": (
                reviewed.source_identity_sha256 if reviewed is not None else ""),
            "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": (
                reviewed.bundle_sha256 if reviewed is not None else ""),
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE": (
                reviewed.mode if reviewed is not None else ""),
            "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": (
                reviewed.shadow_configuration_sha256
                if reviewed is not None
                and reviewed.mode in {"shadow", "dual"} else ""),
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": (
                reviewed.data_publication_sha256
                if reviewed is not None
                and reviewed.mode in {"shadow", "dual"} else ""),
        }
        self._persist_deploy_facts(updates)
        self.env.update(updates)
        self.runner.env.update(updates)

    def _persist_deploy_facts(self, updates: Mapping[str, str]) -> None:
        update_dotenv(ENV_PATH, updates)

    def _post_deploy_backup(self) -> Optional[str]:
        self.runner.run(["bash", "scripts/sentinel-base-backup.sh"])
        self.runner.run(["bash", "scripts/sentinel-backup-status.sh"])
        self.runner.run(["bash", "scripts/sentinel-restore-drill.sh"])
        return None

    def persist_deployed(self, status: Mapping) -> None:
        """Persist installation success independently of operational readiness."""
        self.phase("finalize: persist immutable DEPLOYED facts while fenced")
        if (status.get("enabled") is not False
                or status.get("kill_switch_engaged") is not True):
            raise DeployRefused(
                "deployment receipt requires disabled+killed automation")
        post_backup = self._post_deploy_backup()
        managed = {
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_REPOSITORY": self.cfg.test_repository,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
        }
        if self.reviewed_validation is not None:
            managed.update({
                "SENTINEL_SHADOW_OBSERVATION_ENABLED": (
                    "1" if self.reviewed_validation.mode in {
                        "shadow", "dual"} else "0"),
                "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": (
                    self.reviewed_validation.source_identity_sha256),
                "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": (
                    self.reviewed_validation.bundle_sha256),
                "SENTINEL_REVIEWED_DEPLOYMENT_MODE": (
                    self.reviewed_validation.mode),
                "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": (
                    self.reviewed_validation.shadow_configuration_sha256 or ""),
                "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": (
                    self.reviewed_validation.data_publication_sha256 or ""),
            })
        self._persist_deploy_facts(managed)
        activation_mode = (
            self.reviewed_validation.mode
            if self.reviewed_validation is not None else "fenced")
        reviewed_shadow_configuration = (
            shadow_configuration_document(
                self.env,
                source_identity_sha256=(
                    self.reviewed_validation.source_identity_sha256))
            if self.reviewed_validation is not None
            and self.reviewed_validation.mode in {"shadow", "dual"} else None)
        receipt = {
            "schema": DEPLOY_SCHEMA,
            "completed_at": _utc_text(_utcnow()),
            "git_commit": self.commit,
            "runtime_image": self.runtime_repo_digest,
            "test_image": self.test_repo_digest,
            "deployment_id": self.cfg.deployment_id,
            "paper_account_id": self.cfg.account_id,
            "deployment_state": "DEPLOYED",
            "operational_state": (
                "SHADOW_OBSERVATION"
                if activation_mode == "shadow" else "FENCED"),
            "activation_mode": activation_mode,
            "reviewed_validation_bundle_sha256": (
                self.reviewed_validation.bundle_sha256
                if self.reviewed_validation is not None else None),
            "validated_source_identity_sha256": (
                self.reviewed_validation.source_identity_sha256
                if self.reviewed_validation is not None else None),
            "validated_shadow_config_sha256": (
                self.reviewed_validation.shadow_configuration_sha256
                if self.reviewed_validation is not None else None),
            "reviewed_shadow_configuration": reviewed_shadow_configuration,
            "validated_data_publication_sha256": (
                self.reviewed_validation.data_publication_sha256
                if self.reviewed_validation is not None else None),
            "shadow_observation_enabled": activation_mode == "shadow",
            "automation_enabled": False,
            "kill_switch_engaged": True,
            "operational_ready": bool(status.get("operational_ready") is True),
            "policy_state": status.get("policy_state"),
            "active_certificate_sha256_at_install": status.get("certificate_sha256"),
            "broker_readiness_at_install": self.broker_readiness,
            "ownership_at_install": self.ownership_state,
            "post_deploy_backup": post_backup,
        }
        path = self.attempt_dir / "deployment-receipt.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        if activation_mode == "shadow":
            print(
                "\nDEPLOYMENT PASS: reviewed broker-free shadow observation is active")
            print("trading automation: disabled and kill switch engaged")
        else:
            print(
                "\nDEPLOYMENT PASS: exact Sentinel runtime is installed and durably fenced")
            print(
                "operational state: FENCED (runtime readiness owns later progression)")
        print("receipt: %s" % path)

    def persist_success(self, health: Mapping) -> None:
        self.phase("finalize: persist immutable deploy facts and post-deploy backup")
        activation_mode = (
            self.reviewed_validation.mode
            if self.reviewed_validation is not None else "paper")
        dual = activation_mode == "dual"
        managed = {
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_REPOSITORY": self.cfg.test_repository,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
        }
        if self.reviewed_validation is not None:
            managed.update({
                "SENTINEL_SHADOW_OBSERVATION_ENABLED": "1" if dual else "0",
                "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": (
                    self.reviewed_validation.source_identity_sha256),
                "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": (
                    self.reviewed_validation.bundle_sha256),
                "SENTINEL_REVIEWED_DEPLOYMENT_MODE": activation_mode,
                "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": (
                    self.reviewed_validation.shadow_configuration_sha256 or ""
                    if dual else ""),
                "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": (
                    self.reviewed_validation.data_publication_sha256 or ""
                    if dual else ""),
            })
        update_dotenv(ENV_PATH, managed)
        self.runner.run(["bash", "scripts/sentinel-base-backup.sh"])
        self.runner.run(["bash", "scripts/sentinel-backup-status.sh"])
        self.runner.run(["bash", "scripts/sentinel-restore-drill.sh"])
        receipt = {
            "schema": DEPLOY_SCHEMA,
            "completed_at": _utc_text(_utcnow()),
            "git_commit": self.commit,
            "runtime_image": self.runtime_repo_digest,
            "test_image": self.test_repo_digest,
            "deployment_id": self.cfg.deployment_id,
            "paper_account_id": self.cfg.account_id,
            "certificate_sha256": self.new_certificate,
            "predecessor_certificate_sha256": self.active_certificate or None,
            "control_generation": health.get("control_generation"),
            "leader_holder": health.get("leader_holder"),
            "fencing_token": health.get("fencing_token"),
            "leader_heartbeat_at": health.get("leader_heartbeat_at"),
            "policy_state": health.get("policy_state"),
            "operational_ready": health.get("operational_ready"),
            "activation_mode": activation_mode,
            "certified_performance_authority": (
                "BROKER_FREE_SHADOW_LEDGER" if dual else "PAPER_TRIAL"),
            "paper_accounting_authoritative": not dual,
            "reviewed_validation_bundle_sha256": (
                self.reviewed_validation.bundle_sha256
                if self.reviewed_validation is not None else None),
        }
        path = self.attempt_dir / "deployment-receipt.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        if dual:
            print(
                "\nDEPLOYMENT PASS: certified shadow plus reconciled Alpaca "
                "PAPER transport is operational")
            print(
                "performance authority: broker-free shadow ledger; PAPER "
                "accounting is display/reconciliation evidence only")
        else:
            print("\nDEPLOYMENT PASS: autonomous Alpaca PAPER trading is authorized and operational")
        print("receipt: %s" % path)

    def run(self) -> None:
        # Deployment establishes software/schema identity and a safe writer fence.
        # Operational readiness (data, broker, ownership, authority, plan, leader)
        # is deliberately not part of this success boundary.
        self.git_preflight()
        self.verify_reviewed_preflight()
        # A reachable broker with a different identity is a deployment-integrity
        # contradiction. Temporary unavailability/blocking is merely readiness.
        self.check_paper_account_deployment_integrity()
        self.build_promote()
        with self.transition():
            self.quiesce_backup_and_migrate()
            self.check_durable_deployment_integrity()
            reviewed = self.reviewed_validation
            # Image promotion and quiescing may take long enough for the old
            # publisher to move the corpus. Recheck the reviewed publication
            # and exact lineage only after writers are stopped, immediately
            # before any reviewed mode fact is persisted or shadow is started.
            self.verify_reviewed_shadow_bindings_quiesced()
            # This is unconditional. A stale `.env` from an earlier reviewed
            # shadow must never let the no-args fenced installer restart shadow.
            self.configure_reviewed_mode_while_fenced()
            if reviewed is not None and reviewed.mode == "dual":
                # The broker-free ledger is brought up and attested first.
                # PAPER remains killed until its immutable plan proves exact
                # equality with that same decision-close state and intent.
                self.start_fenced_runtime()
                self.read_paper_account()
                self.ensure_ownership()
                certificate, decision_session = (
                    self.rotate_observation_authority())
                self._wait_for_dual_shadow_session(decision_session)
                self.prepare_activate_start(certificate, decision_session)
                health = self.verify_operational(certificate)
                self.runner.run(self.base_compose + [
                    "up", "-d", "sentinel-panel"])
                self.persist_success(health)
            elif reviewed is not None and reviewed.mode == "paper":
                # This branch is unreachable for the current two-source bundle,
                # whose PAPER_EXECUTION verdict is NO_GO.  If every paper gate
                # is eventually proved, it reuses the existing signed, killed-
                # first activation transaction rather than inventing a bypass.
                self.read_paper_account()
                self.refresh_data()
                self.ensure_ownership()
                certificate, decision_session = (
                    self.rotate_observation_authority())
                self.prepare_activate_start(certificate, decision_session)
                health = self.verify_operational(certificate)
                self.persist_success(health)
            else:
                status = self.start_fenced_runtime()
                self.persist_deployed(status)


def update_dotenv(path: Path, updates: Mapping[str, str]) -> None:
    """Atomically update only named non-secret deploy facts, preserving .env."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict((str(k), str(v)) for k, v in updates.items())
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        if "=" in candidate:
            key = candidate.split("=", 1)[0].strip()
            if key in remaining:
                out.append("%s=%s" % (key, remaining.pop(key)))
                continue
        out.append(line)
    if remaining:
        if out and out[-1] != "":
            out.append("")
        out.append("# Managed by scripts/sentinel-autonomous-deploy.sh after PASS.")
        for key in sorted(remaining):
            out.append("%s=%s" % (key, remaining[key]))
    temporary = path.with_name(path.name + ".deploy.tmp")
    temporary.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


def _attempt_dir(cfg: Config, commit_hint: str = "pending") -> Path:
    stamp = _utcnow().strftime("%Y%m%dT%H%M%SZ")
    base = cfg.authority_dir / "deployments"
    base.mkdir(parents=True, exist_ok=True)
    path = base / (stamp + "-" + commit_hint[:12])
    counter = 0
    while path.exists():
        counter += 1
        path = base / (stamp + "-" + commit_hint[:12] + "-%d" % counter)
    path.mkdir(mode=0o700)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed Sentinel reviewed-mode deployment")
    parser.add_argument(
        "--explain", action="store_true",
        help="print the enforced deployment phases and exit without deployment")
    parser.add_argument("--mode", choices=("shadow", "dual", "paper"))
    parser.add_argument("--validation-bundle", type=Path)
    parser.add_argument("--confirm-reviewed-go")
    args = parser.parse_args(argv)
    if args.explain:
        print("git ff-only -> broker identity integrity -> build/test/push -> kill/stop -> "
              "backup/restore -> schema -> durable authority integrity -> "
              "start exact runtime disabled+killed -> persist DEPLOYED/FENCED; "
              "runtime later owns data/readiness and activation prerequisites")
        return 0
    try:
        env = merged_environment()
        reviewed = deployment_request(
            mode=args.mode, validation_bundle=args.validation_bundle,
            confirmation=args.confirm_reviewed_go, env=env)
        cfg = Config(env)
        if reviewed is not None:
            verify_reviewed_account_binding(reviewed, cfg.account_id)
        if not (ROOT / ".git").exists():
            raise DeployRefused("autonomous deploy must run from a Git checkout")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=False).stdout.strip()
        attempt = _attempt_dir(cfg, head if _HEX40.fullmatch(head) else "pending")
        runner = Runner(env, attempt / "commands.log")
        with DeploymentLock(cfg.authority_dir / "autonomous-deploy.lock"):
            AutonomousDeploy(
                cfg, runner, attempt,
                reviewed_validation=reviewed).run()
        return 0
    except DeployRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("REFUSED: deployment interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
