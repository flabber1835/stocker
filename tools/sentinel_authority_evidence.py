"""Deterministic, no-clobber producer for signed-authority evidence.

This module never owns a key and never contacts a broker.  It promotes an exact
raw forward-chain report after human review, scores retained resource reports,
binds a canonical publication row to the installed policy implementation, and
assembles the only evidence-index/manifest shape accepted by the offline issuer.
Blocked evidence is retained honestly; only a complete bundle says PASS.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from sentinel.authority import canonical_json_bytes, canonical_sha256
from sentinel.execution.authority_gate import (
    publication_policy_implementation_sha256,
)


BUNDLE_SCHEMA = "sentinel.authority-evidence-bundle/1"
MANIFEST_SCHEMA = "sentinel.certification_manifest/3"
INDEX_SCHEMA = "sentinel.certificate_evidence_index/1"
TEST_SUMMARY_SCHEMA = "sentinel.certification-test-summary/1"
RESOURCE_POLICY_SCHEMA = "sentinel.resource-envelope-policy/1"
RESOURCE_POLICY_CANDIDATE_SCHEMA = "sentinel.resource-envelope-policy-candidate/1"
RESOURCE_MEASUREMENT_SCHEMA = "sentinel.resource-measurement/1"
TEST_RUN_SCHEMA = "sentinel.certification-test-run/1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
RESOURCE_MEASUREMENT_PRODUCER = "scripts/sentinel-measure.sh"
_CANONICAL_LOADER_BUNDLE_SCHEMA = "wealth_core.canonical-loader-bundle/1"
APPROVED_CERTIFICATION_REVISION = (
    "7f12174273dfa071a25614d2c4a1be8ebfdfbc3a")
_EXPECTED_HASH_PRODUCER = "tools/wealth_core_expected_hashes.py"
_APPROVED_EXPECTED_HASH_PRODUCER_SHA256 = (
    "8ea492a9f53d1f3cb6ba28ca3c6f5d50d1471942772b5fa04832fdd7d215c2b4")
_APPROVED_CANONICAL_LOADER_SOURCES = {
    "services/backtester/app/wealth_core_replay.py":
        "03c966510fe47b6572c6f2c629797e3a898a6ed3ec14114e7d094b92d558142a",
    "services/backtester/app/wealth_core_replay_impl.py":
        "2ebce6ca026f944b812ab2b0bf290db5eaa4df7b42a12710b6f3bb41613c2f7d",
    "shared/stock_strategy_shared/split_reconciliation.py":
        "a32f6698763bfd110b309fc42d9bb39b1c2e0272bd81e5ff659a5f7a5017dfd7",
}
_APPROVED_CANONICAL_LOADER_BUNDLE_SHA256 = (
    "7d10f4b00e41b78764e81cadbaad7c3a0564b6db6678c983d78fc7cbfe11c669")
COMPLETED_CHECK_IDS = (
    "base_manifest_finalized",
    "formal_test_run",
    "wealth_core_decision",
    "controller_decision",
    "decision_input_bindings",
    "forward_chain_review",
    "resource_envelope",
    "publication_policy",
    "immutable_images",
    "strategy_identity",
    "automation_config",
    "reference_artifacts",
)


class EvidenceRefused(RuntimeError):
    """Input evidence cannot support a final authority decision."""


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_external_loader_bundle(value: object) -> bool:
    """Match the loader bytes approved at ``APPROVED_CERTIFICATION_REVISION``."""
    if not isinstance(value, Mapping):
        return False
    expected = {
        "schema": _CANONICAL_LOADER_BUNDLE_SCHEMA,
        "sources": _APPROVED_CANONICAL_LOADER_SOURCES,
        "sha256": _APPROVED_CANONICAL_LOADER_BUNDLE_SHA256,
    }
    return dict(value) == expected


def _validate_external_certification_source(value: object) -> bool:
    """Bind an expected-hash artifact to the preserved reviewed source bytes."""
    return (isinstance(value, Mapping)
            and value.get("producer") == _EXPECTED_HASH_PRODUCER
            and value.get("producer_sha256")
            == _APPROVED_EXPECTED_HASH_PRODUCER_SHA256
            and _validate_external_loader_bundle(
                value.get("canonical_loader_bundle")))


def _source_config_sha256(value: Mapping) -> str:
    """Hash source-owned numeric configuration without putting floats in claims."""
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")
    return sha(payload)


def _load(path: Path, *, label: str) -> tuple[bytes, Mapping]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceRefused(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    def nonfinite(value):
        raise EvidenceRefused(f"{label} contains non-finite number {value}")

    try:
        payload = Path(path).read_bytes()
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=nonfinite)
    except EvidenceRefused:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceRefused(f"{label} is not readable JSON") from exc
    if not isinstance(value, Mapping):
        raise EvidenceRefused(f"{label} must be a JSON object")
    return payload, value


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    failure = None
    try:
        os.fsync(descriptor)
    except BaseException as exc:  # preserve fsync over a later close error
        failure = exc
    try:
        os.close(descriptor)
    except BaseException as exc:
        if failure is None:
            failure = exc
        elif hasattr(failure, "add_note"):
            failure.add_note(f"directory close also failed: {exc!r}")
    if failure is not None:
        raise failure


def _unlink_retry(path: Path, *, attempts: int = 3) -> None:
    failure = None
    for _attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            failure = exc
    assert failure is not None
    raise failure


def _rmtree_retry(path: Path, *, attempts: int = 3) -> None:
    failure = None
    for _attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            failure = exc
    assert failure is not None
    raise failure


def _rollback_file(path: Path, parent: Path, original: BaseException) -> None:
    try:
        _unlink_retry(path)
    except OSError as cleanup:
        # Removing the authoritative name matters more than removing bytes.
        # A same-directory rename is the fallback when unlink is transiently
        # unavailable (notably antivirus/indexer interference on Windows).
        quarantine = parent / f".{path.name}.rollback.{os.getpid()}"
        try:
            os.replace(path, quarantine)
            try:
                _unlink_retry(quarantine)
            except OSError as residual:
                if hasattr(original, "add_note"):
                    original.add_note(
                        f"rollback quarantine remains at {quarantine}: {residual!r}")
        except OSError as rename_error:
            if hasattr(original, "add_note"):
                original.add_note(
                    f"could not remove published path: {cleanup!r}; "
                    f"rename fallback failed: {rename_error!r}")
    try:
        _fsync_directory(parent)
    except BaseException as cleanup_fsync:
        if hasattr(original, "add_note"):
            original.add_note(
                f"rollback parent fsync also failed: {cleanup_fsync!r}")


def _rollback_directory(path: Path, parent: Path,
                        original: BaseException) -> None:
    try:
        _rmtree_retry(path)
    except OSError as cleanup:
        quarantine = parent / f".{path.name}.rollback.{os.getpid()}"
        try:
            os.replace(path, quarantine)
            try:
                _rmtree_retry(quarantine)
            except OSError as residual:
                if hasattr(original, "add_note"):
                    original.add_note(
                        f"rollback quarantine remains at {quarantine}: {residual!r}")
        except OSError as rename_error:
            if hasattr(original, "add_note"):
                original.add_note(
                    f"could not remove published bundle: {cleanup!r}; "
                    f"rename fallback failed: {rename_error!r}")
    try:
        _fsync_directory(parent)
    except BaseException as cleanup_fsync:
        if hasattr(original, "add_note"):
            original.add_note(
                f"rollback parent fsync also failed: {cleanup_fsync!r}")


def _write_no_clobber(path: Path, payload: bytes) -> None:
    path = Path(path).resolve()
    if not path.parent.is_dir():
        raise EvidenceRefused(f"output parent does not exist: {path.parent}")
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    linked = False
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise EvidenceRefused(f"output exists; refusing overwrite: {path}") from exc
        linked = True
        _unlink_retry(temporary)
        _fsync_directory(path.parent)
    except BaseException as exc:
        if linked:
            _rollback_file(path, path.parent, exc)
        raise
    finally:
        try:
            _unlink_retry(temporary)
        except OSError:
            pass


def _unique_image_digest(image: object, *, label: str) -> str:
    if not isinstance(image, Mapping):
        raise EvidenceRefused(f"{label} image identity is absent")
    values = image.get("repo_digests")
    if not isinstance(values, list):
        raise EvidenceRefused(f"{label} RepoDigests are absent")
    resolved = {"sha256:" + value.split("@sha256:", 1)[1]
                for value in values if isinstance(value, str)
                and "@sha256:" in value}
    if (len(resolved) != 1 or re.fullmatch(
            r"sha256:[0-9a-f]{64}", next(iter(resolved), "")) is None):
        raise EvidenceRefused(f"{label} has no unique immutable RepoDigest")
    return next(iter(resolved))


def summarize_test_run(test_run: Path, pre_suite_manifest: Path,
                       base_manifest: Path,
                       output: Path) -> Mapping:
    run_bytes, run = _load(test_run, label="formal certification test run")
    pre_bytes, pre = _load(pre_suite_manifest, label="pre-suite base manifest")
    base_bytes, base = _load(base_manifest, label="finalized base manifest")
    formal_canonical = json.dumps(
        run, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")
    if formal_canonical != run_bytes:
        raise EvidenceRefused("formal certification test run is not canonical JSON")
    required = {
        "schema", "status", "producer_sha256", "base_manifest", "command",
        "inventory", "inventory_log_base64", "pytest_log_base64",
        "pytest_log_sha256", "exit_code", "passed", "failed", "skipped",
        "xfailed", "xpassed", "errors",
    }
    if set(run) != required or run.get("schema") != TEST_RUN_SCHEMA:
        raise EvidenceRefused("formal certification test-run schema/fields differ")
    manifest = run.get("base_manifest")
    if not isinstance(manifest, Mapping) or set(manifest) != {
            "path", "sha256", "lifecycle", "identity_hash", "git_commit",
            "certification_input_sha256", "runtime_image_digest",
            "test_image_digest"}:
        raise EvidenceRefused("test-run base-manifest binding fields differ")
    if (run.get("status") != "PASS" or run.get("exit_code") != 0
            or base.get("schema") != "sentinel.certification_manifest/2"
            or base.get("lifecycle") != "FINALIZED"
            or base.get("verdict") != "PASS"):
        raise EvidenceRefused("formal test run/base manifest is not PASS/finalized")
    counts = {}
    for field in ("passed", "failed", "skipped", "xfailed", "xpassed", "errors"):
        if type(run.get(field)) is not int or run[field] < 0:
            raise EvidenceRefused(f"formal test-run {field} is invalid")
        counts[field] = run[field]
    if (counts["passed"] < 1 or counts["failed"] or counts["skipped"]
            or counts["xpassed"] or counts["errors"]):
        raise EvidenceRefused("formal test-run outcomes are not certification-clean")
    command = run.get("command")
    inventory = run.get("inventory")
    from scripts import sentinel_test_run as formal_runner
    producer_path = Path(formal_runner.__file__).resolve()
    if run.get("producer_sha256") != sha(producer_path.read_bytes()):
        raise EvidenceRefused("formal test-run producer source differs")
    try:
        inventory_log = base64.b64decode(
            run["inventory_log_base64"], validate=True)
        pytest_log = base64.b64decode(
            run["pytest_log_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise EvidenceRefused("formal test-run logs are not canonical base64") from exc
    if (base64.b64encode(inventory_log).decode("ascii")
            != run["inventory_log_base64"]
            or base64.b64encode(pytest_log).decode("ascii")
            != run["pytest_log_base64"]):
        raise EvidenceRefused("formal test-run log base64 is not canonical")
    try:
        parsed_inventory = formal_runner.inventory_from_log(inventory_log)
        parsed_counts = formal_runner.counts_from_log(
            pytest_log, exit_code=run.get("exit_code"))
    except formal_runner.TestRunRefused as exc:
        raise EvidenceRefused(
            f"formal test-run retained logs do not prove PASS: {exc}") from exc
    if (not isinstance(command, Mapping) or set(command) != {"argv", "sha256"}
            or not isinstance(command.get("argv"), list)
            or not command["argv"]
            or any(not isinstance(item, str) or not item for item in command["argv"])
            or command.get("sha256") != canonical_sha256(command["argv"])
            or not isinstance(inventory, Mapping)
            or set(inventory) != {"nodeids", "sha256", "count"}
            or not isinstance(inventory.get("nodeids"), list)
            or inventory["nodeids"] != sorted(set(inventory["nodeids"]))
            or not inventory["nodeids"]
            or inventory.get("count") != len(inventory["nodeids"])
            or inventory.get("sha256") != parsed_inventory["sha256"]
            or counts["passed"] + counts["xfailed"] != inventory["count"]):
        raise EvidenceRefused("formal test command/inventory identity is invalid")
    try:
        formal_runner.validate_canonical_command(
            command["argv"],
            expected_test_image_digest=manifest["test_image_digest"],
        )
    except formal_runner.TestRunRefused as exc:
        raise EvidenceRefused(
            f"formal test command is not the complete certified suite: {exc}"
        ) from exc
    if (inventory != parsed_inventory
            or any(run[field] != value for field, value in parsed_counts.items())
            or run["pytest_log_sha256"] != sha(pytest_log)):
        raise EvidenceRefused(
            "formal test-run claims differ from retained runner logs")
    expected_input = ((base.get("image_source_hashes") or {}).get(
        "certification_inputs"))
    if (manifest["git_commit"] != base.get("git_commit")
            or manifest["identity_hash"] != base.get("identity_hash")
            or manifest["certification_input_sha256"] != expected_input
            or manifest["runtime_image_digest"] != _unique_image_digest(
                base.get("sentinel_runtime_image"), label="runtime")
            or manifest["test_image_digest"] != _unique_image_digest(
                base.get("sentinel_test_image"), label="test")
            or manifest["sha256"] != sha(pre_bytes)
            or manifest["lifecycle"] != pre.get("lifecycle")
            or manifest["git_commit"] != pre.get("git_commit")
            or manifest["identity_hash"] != pre.get("identity_hash")
            or manifest["certification_input_sha256"] != (
                (pre.get("image_source_hashes") or {}).get(
                    "certification_inputs"))
            or manifest["runtime_image_digest"] != _unique_image_digest(
                pre.get("sentinel_runtime_image"), label="pre-suite runtime")
            or manifest["test_image_digest"] != _unique_image_digest(
                pre.get("sentinel_test_image"), label="pre-suite test")
            or sha(pre_bytes) == sha(base_bytes)):
        raise EvidenceRefused("formal test run differs from finalized manifest identity")
    if (HEX.fullmatch(str(run["pytest_log_sha256"])) is None
            or manifest["lifecycle"] != "FROZEN"):
        raise EvidenceRefused("formal test run log/lifecycle identity is invalid")
    value = {
        "schema": TEST_SUMMARY_SCHEMA,
        "test_run_sha256": sha(run_bytes),
        "pre_suite_manifest_sha256": sha(pre_bytes),
        "base_manifest_sha256": sha(base_bytes),
        "pytest_log_sha256": run["pytest_log_sha256"],
        "command_sha256": command["sha256"],
        "inventory_sha256": inventory["sha256"],
        "inventory_count": inventory["count"],
        **counts,
    }
    _write_no_clobber(output, canonical_json_bytes(value))
    return value


def promote_forward_chain(*, formal_run_path: Path, output: Path,
                          confirm_sha256: str, reviewer: str, ticket: str,
                          reviewed_at: str) -> Mapping:
    from scripts import sentinel_forward_run as formal_forward
    record_bytes, record = _load(
        formal_run_path, label="formal production forward-chain run")
    if formal_forward.canonical_bytes(record) != record_bytes:
        raise EvidenceRefused("formal forward-chain record is not canonical JSON")
    try:
        raw = formal_forward.validate_record(record)
        raw_bytes = base64.b64decode(record["stdout_base64"], validate=True)
    except (formal_forward.ForwardRunRefused, KeyError, TypeError,
            ValueError) as exc:
        raise EvidenceRefused(
            f"formal forward-chain producer evidence is invalid: {exc}") from exc
    actual = sha(record_bytes)
    if confirm_sha256 != actual:
        raise EvidenceRefused(
            f"formal forward-chain SHA-256 mismatch: actual {actual}")
    if (raw.get("schema") != "sentinel.production-forward-chain/2"
            or raw.get("differential_verdict") != "PASS"
            or raw.get("authority_effect") != "NONE"
            or raw.get("runtime_authority_changed") is not False
            or raw.get("manual_review_required") is not True):
        raise EvidenceRefused("raw forward-chain report is not reviewable PASS evidence")
    comparison = raw.get("comparison") or {}
    if (comparison.get("first_divergence") is not None
            or comparison.get("reference_sessions_compared")
            != comparison.get("expected_reference_sessions")
            or comparison.get("field_comparisons")
            != comparison.get("expected_full_pass_field_comparisons")):
        raise EvidenceRefused("raw forward-chain differential is incomplete")
    try:
        when = datetime.strptime(reviewed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError as exc:
        raise EvidenceRefused("reviewed_at must be an exact UTC second") from exc
    if not reviewer.strip() or not ticket.strip() or when.utcoffset().total_seconds() != 0:
        raise EvidenceRefused("forward-chain review identity/ticket is required")
    promoted = dict(raw)
    promoted["manual_review_required"] = False
    promoted["review"] = {
        "schema": "sentinel.forward-chain-review/1",
        "formal_run_sha256": actual,
        "raw_report_sha256": sha(raw_bytes),
        "reviewer": reviewer.strip(),
        "ticket": ticket.strip(),
        "reviewed_at": reviewed_at,
        "confirmed_authority_effect": "NONE",
    }
    _write_no_clobber(output, canonical_json_bytes(promoted))
    return promoted


def _review(*, source_sha256: str, reviewer: str, ticket: str,
            reviewed_at: str, schema: str) -> Mapping:
    try:
        when = datetime.strptime(reviewed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError as exc:
        raise EvidenceRefused("reviewed_at must be an exact UTC second") from exc
    if (not reviewer.strip() or not ticket.strip()
            or when.utcoffset().total_seconds() != 0):
        raise EvidenceRefused("review identity/ticket is required")
    return {
        "schema": schema,
        "source_sha256": source_sha256,
        "reviewer": reviewer.strip(),
        "ticket": ticket.strip(),
        "reviewed_at": reviewed_at,
        "authority_effect": "NONE",
    }


def _artifact_target(value: object, *, label: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != {
            "git_commit", "runtime_image_digest", "test_image_digest",
            "automation_config_sha256"}:
        raise EvidenceRefused(f"{label} artifact target fields are invalid")
    git_commit = str(value["git_commit"])
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", git_commit) is None:
        raise EvidenceRefused(f"{label} Git commit is invalid")
    for field in ("runtime_image_digest", "test_image_digest"):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(value[field])) is None:
            raise EvidenceRefused(f"{label} {field} is invalid")
    if HEX.fullmatch(str(value["automation_config_sha256"])) is None:
        raise EvidenceRefused(f"{label} automation config digest is invalid")
    return value


def _validate_formal_baseline(*, record: Mapping, payload: bytes,
                              expected_bytes: bytes,
                              base_bytes: bytes) -> Mapping:
    from tools import wealth_core_baseline_run as formal_baseline
    if formal_baseline.canonical_bytes(record) != payload:
        raise EvidenceRefused("formal baseline-run record is not canonical JSON")
    try:
        formal_baseline.validate_record(record)
        expected_bound = base64.b64decode(
            record["expected_hashes"]["bytes_base64"], validate=True)
        manifest_bound = base64.b64decode(
            record["certification_manifest"]["bytes_base64"], validate=True)
    except (formal_baseline.BaselineRunRefused, KeyError, TypeError,
            ValueError) as exc:
        raise EvidenceRefused(
            f"formal baseline-run producer evidence is invalid: {exc}") from exc
    if expected_bound != expected_bytes or manifest_bound != base_bytes:
        raise EvidenceRefused(
            "formal baseline-run inputs differ from retained expected/manifest bytes")
    return record["terminal_run"]["row"]


def _validate_formal_forward(*, record: Mapping, payload: bytes,
                             base_bytes: bytes) -> Mapping:
    from scripts import sentinel_forward_run as formal_forward
    if formal_forward.canonical_bytes(record) != payload:
        raise EvidenceRefused("formal forward-chain record is not canonical JSON")
    try:
        raw = formal_forward.validate_record(record)
    except (formal_forward.ForwardRunRefused, KeyError, TypeError,
            ValueError) as exc:
        raise EvidenceRefused(
            f"formal forward-chain producer evidence is invalid: {exc}") from exc
    base = record.get("base_manifest") or {}
    if base.get("sha256") != sha(base_bytes):
        raise EvidenceRefused(
            "formal forward-chain run names a different finalized manifest")
    return raw


def promote_resource_policy(*, candidate_path: Path, output: Path,
                            confirm_sha256: str, reviewer: str, ticket: str,
                            reviewed_at: str) -> Mapping:
    candidate_bytes, candidate = _load(
        candidate_path, label="resource policy candidate")
    actual = sha(candidate_bytes)
    if confirm_sha256 != actual:
        raise EvidenceRefused(f"resource policy SHA-256 mismatch: actual {actual}")
    if candidate.get("schema") != RESOURCE_POLICY_CANDIDATE_SCHEMA:
        raise EvidenceRefused("resource policy candidate schema is unknown")
    target = _artifact_target(candidate.get("artifact_target"), label="policy")
    required = candidate.get("required_phases")
    commands = candidate.get("phase_commands")
    elapsed = candidate.get("max_elapsed_seconds")
    minimum = candidate.get("min_headroom_percent")
    if (not isinstance(required, list) or not required
            or required != sorted(set(required))
            or not isinstance(commands, Mapping) or set(commands) != set(required)
            or any(not isinstance(commands[phase], list)
                   or not commands[phase]
                   or any(not isinstance(arg, str) or not arg
                          for arg in commands[phase]) for phase in required)
            or not isinstance(elapsed, Mapping) or set(elapsed) != set(required)
            or any(type(elapsed[phase]) is not int or elapsed[phase] < 1
                   for phase in required)
            or type(minimum) is not int or not 0 <= minimum <= 100
            or type(candidate.get("require_cpu_enforced")) is not bool
            or type(candidate.get("allow_host_memory_observed")) is not bool):
        raise EvidenceRefused("resource policy candidate fields are invalid")
    promoted = {
        "schema": RESOURCE_POLICY_SCHEMA,
        "artifact_target": dict(target),
        "required_phases": required,
        "phase_commands": {phase: commands[phase] for phase in required},
        "max_elapsed_seconds": {phase: elapsed[phase] for phase in required},
        "min_headroom_percent": minimum,
        "require_cpu_enforced": candidate["require_cpu_enforced"],
        "allow_host_memory_observed": candidate["allow_host_memory_observed"],
        "review": _review(
            source_sha256=actual, reviewer=reviewer, ticket=ticket,
            reviewed_at=reviewed_at,
            schema="sentinel.resource-envelope-policy-review/1"),
    }
    _write_no_clobber(output, canonical_json_bytes(promoted))
    return promoted


def score_resources(*, policy_path: Path, measurement_paths: Sequence[Path],
                    output: Path) -> Mapping:
    policy_bytes, policy = _load(policy_path, label="resource policy")
    if (policy.get("schema") != RESOURCE_POLICY_SCHEMA
            or canonical_json_bytes(policy) != policy_bytes):
        raise EvidenceRefused("resource policy schema is unknown")
    target = _artifact_target(policy.get("artifact_target"), label="policy")
    review = policy.get("review")
    if (not isinstance(review, Mapping)
            or review.get("schema")
            != "sentinel.resource-envelope-policy-review/1"
            or review.get("authority_effect") != "NONE"
            or HEX.fullmatch(str(review.get("source_sha256") or "")) is None):
        raise EvidenceRefused("resource policy has no reviewed source binding")
    required = policy.get("required_phases")
    commands = policy.get("phase_commands")
    elapsed_limits = policy.get("max_elapsed_seconds")
    minimum = policy.get("min_headroom_percent")
    if (not isinstance(required, list) or not required
            or required != sorted(set(required))
            or not isinstance(commands, Mapping)
            or set(commands) != set(required)
            or not isinstance(elapsed_limits, Mapping)
            or set(elapsed_limits) != set(required)
            or type(minimum) is not int or not 0 <= minimum <= 100
            or type(policy.get("require_cpu_enforced")) is not bool
            or type(policy.get("allow_host_memory_observed")) is not bool):
        raise EvidenceRefused("resource policy fields are invalid")
    measurements, retained, failures = {}, {}, []
    for path in measurement_paths:
        payload, report = _load(path, label=f"resource report {path}")
        try:
            report_canonical = canonical_json_bytes(report)
        except Exception as exc:
            raise EvidenceRefused(
                "resource report contains non-canonical JSON values") from exc
        if (report.get("schema") != RESOURCE_MEASUREMENT_SCHEMA
                or report_canonical != payload):
            raise EvidenceRefused(
                "resource report must be canonical sentinel.resource-measurement/1")
        producer = report.get("producer")
        producer_path = (Path(__file__).resolve().parents[1]
                         / RESOURCE_MEASUREMENT_PRODUCER)
        if (not isinstance(producer, Mapping)
                or set(producer) != {"path", "sha256"}
                or producer.get("path") != RESOURCE_MEASUREMENT_PRODUCER
                or producer.get("sha256") != sha(producer_path.read_bytes())):
            raise EvidenceRefused(
                "resource report does not bind the repository measurement producer")
        phase = report.get("phase")
        if phase not in required or phase in measurements:
            raise EvidenceRefused("resource reports contain an unknown/duplicate phase")
        identity = report.get("identity")
        if not isinstance(identity, Mapping) or set(identity) != {
                "git_commit", "runtime_image_digest", "runtime_image_id",
                "runtime_image_source_revision", "test_image_digest",
                "test_image_id", "test_image_source_revision",
                "automation_config_sha256", "resource_policy_sha256",
                "phase_command_sha256", "host_capabilities_sha256",
                "samples_sha256"}:
            raise EvidenceRefused("resource measurement identity fields are invalid")
        for field in ("git_commit", "runtime_image_digest", "test_image_digest",
                      "automation_config_sha256"):
            if identity[field] != target[field]:
                raise EvidenceRefused(
                    f"resource measurement {phase} {field} differs from policy")
        if (identity["resource_policy_sha256"] != sha(policy_bytes)
                or identity["runtime_image_source_revision"] != target["git_commit"]
                or identity["test_image_source_revision"] != target["git_commit"]
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(
                    identity["runtime_image_id"])) is None
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(
                    identity["test_image_id"])) is None):
            raise EvidenceRefused(
                f"resource measurement {phase} image/policy provenance is invalid")
        command_argv = report.get("command_argv")
        if (command_argv != commands[phase]
                or identity["phase_command_sha256"]
                != canonical_sha256(command_argv)):
            raise EvidenceRefused(
                f"resource measurement {phase} command differs from policy")
        host_evidence = report.get("host_evidence")
        if (not isinstance(host_evidence, Mapping)
                or host_evidence.get("probed") is not True
                or not isinstance(host_evidence.get("host"), Mapping)
                or identity["host_capabilities_sha256"]
                != canonical_sha256(host_evidence)):
            raise EvidenceRefused(
                f"resource measurement {phase} host identity is invalid")
        sample_name = report.get("samples_file")
        if (not isinstance(sample_name, str) or not sample_name
                or Path(sample_name).name != sample_name):
            raise EvidenceRefused(
                f"resource measurement {phase} samples path is invalid")
        try:
            sample_bytes = (Path(path).parent / sample_name).read_bytes()
        except OSError as exc:
            raise EvidenceRefused(
                f"resource measurement {phase} samples are unreadable") from exc
        if (HEX.fullmatch(str(identity["samples_sha256"])) is None
                or sha(sample_bytes) != identity["samples_sha256"]):
            raise EvidenceRefused(
                f"resource measurement {phase} samples digest differs")
        phase_container = report.get("phase_container")
        runtime_image = report.get("reviewed_runtime_image")
        test_image = report.get("reviewed_test_image")
        if (not isinstance(phase_container, Mapping)
                or phase_container.get("image_id") != identity["runtime_image_id"]
                or phase_container.get("configured_image") != (
                    f"{report.get('runtime_image_repository')}@"
                    f"{target['runtime_image_digest']}")
                or not isinstance(runtime_image, Mapping)
                or runtime_image != {
                    "ref": (f"{report.get('runtime_image_repository')}@"
                            f"{target['runtime_image_digest']}"),
                    "id": identity["runtime_image_id"],
                    "source_revision": target["git_commit"],
                }
                or not isinstance(test_image, Mapping)
                or test_image != {
                    "ref": (f"{report.get('test_image_repository')}@"
                            f"{target['test_image_digest']}"),
                    "id": identity["test_image_id"],
                    "source_revision": target["git_commit"],
                }):
            raise EvidenceRefused(
                f"resource measurement {phase} did not run the reviewed image")
        measurements[phase] = sha(payload)
        retained[phase] = {
            "report_sha256": sha(payload),
            "report": report,
            "samples_sha256": sha(sample_bytes),
            "samples_base64": base64.b64encode(sample_bytes).decode("ascii"),
        }
        if report.get("exit_code") != 0 or int(report.get("samples") or 0) < 1:
            failures.append(f"{phase}: failed or unmeasured")
        if report.get("memory_verdict") != "PASS" or report.get(
                "headroom_verdict") != "PASS":
            failures.append(f"{phase}: memory/headroom is not PASS")
        if int(report.get("elapsed_seconds") or 0) > int(elapsed_limits[phase]):
            failures.append(f"{phase}: elapsed limit exceeded")
        if report.get("phase_container", {}).get("oom_killed"):
            failures.append(f"{phase}: measured container OOM-killed")
        if any(item.get("oom_killed") or int(item.get("restarts") or 0)
               for item in report.get("oom_and_restarts") or []):
            failures.append(f"{phase}: OOM/restart evidence present")
        for container in (report.get("containers") or {}).values():
            if (container.get("headroom_basis_points") is None
                    or type(container["headroom_basis_points"]) is not int
                    or container["headroom_basis_points"] < minimum * 100):
                failures.append(f"{phase}: measured headroom below policy")
        if (policy["require_cpu_enforced"]
                and report.get("cpu_limit_enforcement") != "ENFORCED"):
            failures.append(f"{phase}: CPU limit is not enforced")
        host = str(report.get("host_memory_verdict") or "")
        if host != "PASS" and not (
                policy["allow_host_memory_observed"] and host == "OBSERVED"):
            failures.append(f"{phase}: host memory disposition is not accepted")
    for phase in required:
        if phase not in measurements:
            failures.append(f"{phase}: measurement missing")
    evidence = {
        "schema": "sentinel.resource-envelope/1",
        "verdict": "PASS" if not failures else "BLOCKED",
        "policy_sha256": sha(policy_bytes),
        "measurements": dict(sorted(measurements.items())),
        "retained_measurements": dict(sorted(retained.items())),
        "failures": sorted(set(failures)),
    }
    _write_no_clobber(output, canonical_json_bytes(evidence))
    return evidence


def produce_publication_policy(*, publication_row_path: Path,
                               base_manifest_path: Path,
                               output: Path) -> Mapping:
    row_bytes, row = _load(publication_row_path, label="publication row")
    base_bytes, base = _load(
        base_manifest_path, label="finalized base manifest")
    if row.get("schema") != "sentinel.corpus-publication-row/1":
        raise EvidenceRefused("publication row is not canonical schema /1")
    if canonical_json_bytes(row) != row_bytes:
        raise EvidenceRefused("publication row bytes are not canonical JSON")
    certification_version = (base.get("parity_generations") or {}).get(
        "sentinel_data_version")
    if (base.get("schema") != "sentinel.certification_manifest/2"
            or base.get("lifecycle") != "FINALIZED"
            or base.get("verdict") != "PASS"
            or type(certification_version) is not int
            or certification_version < 1):
        raise EvidenceRefused(
            "publication policy requires a finalized base certification generation")
    if row.get("version") != certification_version:
        raise EvidenceRefused(
            "publication-chain root version differs from the certified corpus "
            "generation")
    evidence = {
        "schema": "sentinel.publication-policy/1",
        "verdict": "PASS",
        "implementation_sha256": publication_policy_implementation_sha256(),
        "chain_root_sha256": canonical_sha256(row),
        "publication_row_sha256": sha(row_bytes),
        "base_manifest_sha256": sha(base_bytes),
        "certification_data_version": certification_version,
    }
    _write_no_clobber(output, canonical_json_bytes(evidence))
    return evidence


def produce_certification_decisions(
        *, output: Path, base_manifest: Path, test_summary: Path,
        expected_hashes: Path, baseline_run: Path, forward_run: Path,
        forward_reviewed: Path,
        reference_artifact: Path, confirm_inputs_sha256: str,
        reviewer: str, ticket: str,
        reviewed_at: str) -> tuple[Mapping, Mapping]:
    """Derive Wealth Core/controller verdicts from actual producer outputs."""
    base_bytes, base = _load(base_manifest, label="finalized base manifest")
    tests_bytes, tests = _load(test_summary, label="test summary")
    expected_bytes, expected = _load(
        expected_hashes, label="Wealth Core expected hashes")
    baseline_bytes, baseline = _load(
        baseline_run, label="Wealth Core baseline replay")
    forward_bytes, forward = _load(
        forward_reviewed, label="reviewed production forward chain")
    forward_run_bytes, forward_run_record = _load(
        forward_run, label="formal production forward-chain run")
    reference_bytes = Path(reference_artifact).read_bytes()
    decision_inputs = {
        "base_manifest_sha256": sha(base_bytes),
        "test_summary_sha256": sha(tests_bytes),
        "expected_hashes_sha256": sha(expected_bytes),
        "baseline_run_sha256": sha(baseline_bytes),
        "forward_chain_run_sha256": sha(forward_run_bytes),
        "forward_chain_sha256": sha(forward_bytes),
        "reference_sha256": sha(reference_bytes),
    }
    decision_inputs_sha256 = canonical_sha256(decision_inputs)
    if confirm_inputs_sha256 != decision_inputs_sha256:
        raise EvidenceRefused(
            "certification decision input SHA-256 mismatch: actual "
            f"{decision_inputs_sha256}")
    if base.get("schema") != "sentinel.certification_manifest/2":
        raise EvidenceRefused("decision base manifest schema is unknown")
    if tests.get("schema") != TEST_SUMMARY_SCHEMA:
        raise EvidenceRefused("decision test-summary schema is unknown")
    if (set(expected) != {"schema", "status", "window", "hashes", "corpus",
                          "run", "provenance"}
            or expected.get("schema") != "wealth_core_expected_hashes.v1"):
        raise EvidenceRefused("expected-hash producer schema is unknown")
    expected_corpus = expected.get("corpus") or {}
    population_fields = (
        "distinct_securities", "first_session_securities",
        "last_session_securities", "maximum_session_securities")
    if (any(not isinstance(expected_corpus.get(field), int)
            or expected_corpus[field] <= 0 for field in population_fields)
            or any(expected_corpus[field]
                   > expected_corpus["distinct_securities"]
                   for field in population_fields[1:])):
        raise EvidenceRefused(
            "expected-hash artifact has no nonzero causal metadata population")
    if forward.get("schema") != "sentinel.production-forward-chain/2":
        raise EvidenceRefused("controller forward-chain schema is unknown")
    raw_forward = _validate_formal_forward(
        record=forward_run_record, payload=forward_run_bytes,
        base_bytes=base_bytes)
    review = forward.get("review") or {}
    expected_forward = dict(raw_forward)
    expected_forward["manual_review_required"] = False
    expected_forward["review"] = review
    if (forward != expected_forward
            or review.get("schema") != "sentinel.forward-chain-review/1"
            or review.get("formal_run_sha256") != sha(forward_run_bytes)
            or review.get("raw_report_sha256")
            != sha(base64.b64decode(
                forward_run_record["stdout_base64"], validate=True))):
        raise EvidenceRefused(
            "reviewed forward chain is not derived from the formal run")
    baseline_row = _validate_formal_baseline(
        record=baseline, payload=baseline_bytes,
        expected_bytes=expected_bytes, base_bytes=base_bytes)
    expected_provenance = expected.get("provenance") or {}
    expected_corpus = expected.get("corpus") or {}
    expected_run = expected.get("run") or {}
    hashes = expected.get("hashes")
    from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
    if (not isinstance(hashes, Mapping)
            or set(hashes) != set(HASH_ORDER)
            or any(HEX.fullmatch(str(value)) is None for value in hashes.values())
            or expected.get("status") != "ready"):
        raise EvidenceRefused("expected-hash producer output is incomplete")
    runtime_environment = expected_provenance.get("runtime_environment")
    if (not _validate_external_certification_source(expected_provenance)
            or not isinstance(runtime_environment, Mapping)
            or runtime_environment.get("compatible") is not True
            or runtime_environment.get("pins_match") is not True
            or runtime_environment.get("sources_known") is not True
            or runtime_environment.get("pin_drift") != {}
            or runtime_environment.get("lock_present") is not True
            or HEX.fullmatch(str(runtime_environment.get(
                "image_lock_sha256") or "")) is None):
        raise EvidenceRefused(
            "expected hashes do not bind the external producer/runtime")
    strict = {name: tests.get(name) for name in (
        "failed", "skipped", "xfailed", "xpassed")}
    if any(type(value) is not int or value < 0 for value in strict.values()):
        raise EvidenceRefused("test-summary strict outcomes are invalid")
    base_generation = (base.get("parity_generations") or {}).get(
        "canonical_data_version")
    baseline_spec = baseline_row.get("spec") or {}
    baseline_summary = baseline_row.get("summary") or {}
    baseline_provenance = baseline_summary.get("provenance") or {}
    wealth_failures = []
    if base.get("lifecycle") != "FINALIZED" or base.get("verdict") != "PASS":
        wealth_failures.append("base rehearsal manifest is not FINALIZED/PASS")
    for field, value in strict.items():
        if value:
            wealth_failures.append(f"formal certification has {value} {field}")
    if expected_provenance.get("wealth_core_source_hash") != base.get(
            "wealth_core_source_hash"):
        wealth_failures.append("expected hashes use different Wealth Core source")
    if expected_provenance.get("runtime_identity_hash") != base.get(
            "identity_hash"):
        wealth_failures.append("expected hashes use different runtime identity")
    if (str(expected_corpus.get("version")) != str(base_generation)
            or str(baseline_provenance.get("bt_data_version"))
            != str(expected_corpus.get("version"))):
        wealth_failures.append("expected/baseline corpus generation differs")
    if (baseline_row.get("mode") != "baseline_replay"
            or baseline_row.get("status") != "success"
            or baseline_spec.get("expected_hashes") != hashes
            or str(baseline_spec.get("expected_data_version"))
            != str(expected_corpus.get("version"))
            or baseline_row.get("parity_hashes") != hashes
            or (baseline_summary.get("divergence") or {}).get("identical")
            is not True):
        wealth_failures.append("baseline replay did not reproduce expected hashes")
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    eligibility_identity = dataclasses.asdict(EligibilityConfig())
    config_identity = {
        "strategy_id": expected_run.get("strategy_id"),
        "strategy_version": expected_run.get("strategy_version"),
        "engine_config_hash": expected_run.get("config_hash"),
    }
    corpus_sha = str(base.get("final_corpus_hash") or "")
    if HEX.fullmatch(corpus_sha) is None:
        wealth_failures.append("final certification corpus hash is absent")
        corpus_sha = "0" * 64
    sentinel_generation = (base.get("parity_generations") or {}).get(
        "sentinel_data_version")
    if (type(sentinel_generation) is not int or sentinel_generation < 1):
        wealth_failures.append(
            "final Sentinel publication data version is not a positive integer")
        sentinel_generation = 0
    decision_review = _review(
        source_sha256=decision_inputs_sha256, reviewer=reviewer, ticket=ticket,
        reviewed_at=reviewed_at,
        schema="sentinel.certification-decision-review/1")
    wealth = {
        "schema": "wealth-core.certification/1",
        "verdict": "GO" if not wealth_failures else "NO-GO",
        "failures": sorted(set(wealth_failures)),
        "strict_xfails": strict["xfailed"],
        "strict_skips": strict["skipped"],
        "strict_xpasses": strict["xpassed"],
        "failed_tests": strict["failed"],
        "source_sha256": str(base.get("wealth_core_source_hash") or ""),
        "config_sha256": canonical_sha256(config_identity),
        "eligibility_sha256": _source_config_sha256(eligibility_identity),
        "expected_hashes_sha256": sha(expected_bytes),
        "corpus_sha256": corpus_sha,
        "data_version": sentinel_generation,
        "producer": {
            "schema": "sentinel.certification-decision/1",
            **decision_inputs,
            "review": decision_review,
        },
    }
    source = forward.get("source_identity") or {}
    comparison = forward.get("comparison") or {}
    controller_failures = []
    if (forward.get("differential_verdict") != "PASS"
            or forward.get("manual_review_required") is not False
            or comparison.get("first_divergence") is not None
            or comparison.get("reference_sessions_compared")
            != comparison.get("expected_reference_sessions")
            or comparison.get("field_comparisons")
            != comparison.get("expected_full_pass_field_comparisons")):
        controller_failures.append("reviewed controller differential is incomplete")
    reference_sha = sha(reference_bytes)
    if ((forward.get("reference") or {}).get("sha256") != reference_sha
            or source.get("reference_sha256") != reference_sha):
        controller_failures.append("controller reference identity differs")
    forward_corpus = (forward.get("corpus_identity") or {}).get("corpus_hash")
    if forward_corpus != corpus_sha:
        controller_failures.append("controller corpus differs from certification")
    from sentinel.controller.frozen_rule import load as load_controller
    controller_config = load_controller()
    if source.get("controller_rule_sha256") != controller_config.digest:
        controller_failures.append("forward chain used a different controller rule")
    controller = {
        "schema": "sentinel.controller-certification/1",
        "verdict": "PASS" if not controller_failures else "FAIL",
        "failures": sorted(set(controller_failures)),
        "rule_sha256": str(controller_config.digest),
        "config_sha256": canonical_sha256(controller_config.to_dict()),
        "reference_sha256": reference_sha,
        "corpus_sha256": corpus_sha,
        "producer": {
            "schema": "sentinel.certification-decision/1",
            **decision_inputs,
            "review": _review(
                source_sha256=decision_inputs_sha256, reviewer=reviewer,
                ticket=ticket, reviewed_at=reviewed_at,
                schema="sentinel.certification-decision-review/1"),
        },
    }
    output = Path(output).resolve()
    if output.exists() or not output.parent.is_dir():
        raise EvidenceRefused("decision output exists or parent is absent")
    temporary = output.parent / f".{output.name}.tmp.{os.getpid()}"
    temporary.mkdir()
    published = False
    try:
        _write_no_clobber(
            temporary / "wealth_core.json", canonical_json_bytes(wealth))
        _write_no_clobber(
            temporary / "controller.json", canonical_json_bytes(controller))
        os.rename(temporary, output)
        published = True
        _fsync_directory(output.parent)
    except BaseException as exc:
        if published:
            _rollback_directory(output, output.parent, exc)
        try:
            _rmtree_retry(temporary)
        except OSError as cleanup:
            if hasattr(exc, "add_note"):
                exc.add_note(f"decision cleanup also failed: {cleanup!r}")
        raise
    return wealth, controller


def _copy(source: Path, destination: Path) -> tuple[bytes, Mapping | None]:
    payload = Path(source).read_bytes()
    _write_no_clobber(destination, payload)
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    return payload, parsed


def finalize_bundle(*, output: Path, base_manifest: Path,
                    pre_suite_manifest: Path, test_run: Path,
                    test_summary: Path,
                    expected_hashes: Path, baseline_run: Path,
                    wealth_core: Path, controller: Path, forward_run: Path,
                    forward_reviewed: Path, resource_policy: Path,
                    resource_policy_candidate: Path,
                    resource_evidence: Path,
                    publication_row: Path, publication_evidence: Path,
                    reference_artifact: Path, reference_checksums: Path,
                    automation_config: Path, execution_config_sha256: str,
                    completed_checks: int) -> Mapping:
    if (type(completed_checks) is not int
            or completed_checks != len(COMPLETED_CHECK_IDS)):
        raise EvidenceRefused(
            "completed-check confirmation differs from the producer gate set: "
            f"expected {len(COMPLETED_CHECK_IDS)}")
    output = Path(output).resolve()
    if output.exists():
        raise EvidenceRefused(f"bundle exists; refusing overwrite: {output}")
    parent = output.parent
    if not parent.is_dir():
        raise EvidenceRefused("bundle parent does not exist")
    temporary = parent / f".{output.name}.tmp.{os.getpid()}"
    temporary.mkdir()
    published = False
    try:
        sources = {
            "base_manifest": base_manifest,
            "pre_suite_manifest": pre_suite_manifest,
            "test_run": test_run,
            "test_summary": test_summary,
            "expected_hashes": expected_hashes,
            "baseline_run": baseline_run,
            "wealth_core": wealth_core,
            "controller": controller,
            "forward_chain_run": forward_run,
            "forward_chain": forward_reviewed,
            "resource_policy_candidate": resource_policy_candidate,
            "resource_policy": resource_policy,
            "resource_envelope": resource_evidence,
            "publication_row": publication_row,
            "publication_policy": publication_evidence,
            "reference_artifact": reference_artifact,
            "reference_checksums": reference_checksums,
            "automation_config": automation_config,
        }
        loaded = {}
        artifacts = {}
        for name, source in sources.items():
            if name in {"reference_artifact", "reference_checksums"}:
                destination = temporary / Path(source).name
            else:
                suffix = Path(source).suffix or ".bin"
                destination = temporary / f"{name}{suffix}"
            payload, parsed = _copy(source, destination)
            loaded[name] = (payload, parsed)
            artifacts[name] = {
                "path": destination.name,
                "sha256": sha(payload),
                "format": "json" if parsed is not None else "bytes",
            }
        resource_document = loaded["resource_envelope"][1] or {}
        measurement_index = {
            "schema": "sentinel.resource-measurement-index/1",
            "measurements": resource_document.get("measurements"),
            "retained_measurements": resource_document.get(
                "retained_measurements"),
        }
        measurement_payload = canonical_json_bytes(measurement_index)
        measurement_name = "resource_measurements.json"
        _write_no_clobber(temporary / measurement_name, measurement_payload)
        loaded["resource_measurements"] = (
            measurement_payload, measurement_index)
        artifacts["resource_measurements"] = {
            "path": measurement_name, "sha256": sha(measurement_payload),
            "format": "json",
        }
        base = loaded["base_manifest"][1] or {}
        tests = loaded["test_summary"][1] or {}
        wealth = loaded["wealth_core"][1] or {}
        controller_doc = loaded["controller"][1] or {}
        forward = loaded["forward_chain"][1] or {}
        resource = loaded["resource_envelope"][1] or {}
        policy = loaded["publication_policy"][1] or {}
        publication_row_doc = loaded["publication_row"][1] or {}
        automation = loaded["automation_config"][1]
        blockers = []
        if base.get("schema") != "sentinel.certification_manifest/2" or \
                base.get("lifecycle") != "FINALIZED" or base.get("verdict") != "PASS":
            blockers.append("base rehearsal manifest is not FINALIZED/PASS /2")
        for name in ("failed", "skipped", "xfailed", "xpassed"):
            if type(tests.get(name)) is not int or tests.get(name) != 0:
                blockers.append(f"test summary {name} is not zero")
        if (tests.get("test_run_sha256")
                != artifacts["test_run"]["sha256"]
                or tests.get("pre_suite_manifest_sha256")
                != artifacts["pre_suite_manifest"]["sha256"]
                or tests.get("base_manifest_sha256")
                != artifacts["base_manifest"]["sha256"]):
            blockers.append("test summary producer bindings differ")
        if wealth.get("verdict") != "GO":
            blockers.append("Wealth Core is not GO")
        if controller_doc.get("verdict") != "PASS":
            blockers.append("controller is not PASS")
        decision_fields = {
            "schema", "base_manifest_sha256", "test_summary_sha256",
            "expected_hashes_sha256", "baseline_run_sha256",
            "forward_chain_run_sha256", "forward_chain_sha256",
            "reference_sha256", "review",
        }
        expected_decision_bindings = {
            "base_manifest_sha256": artifacts["base_manifest"]["sha256"],
            "test_summary_sha256": artifacts["test_summary"]["sha256"],
            "expected_hashes_sha256": artifacts["expected_hashes"]["sha256"],
            "baseline_run_sha256": artifacts["baseline_run"]["sha256"],
            "forward_chain_run_sha256": artifacts[
                "forward_chain_run"]["sha256"],
            "forward_chain_sha256": artifacts["forward_chain"]["sha256"],
            "reference_sha256": artifacts["reference_artifact"]["sha256"],
        }
        for label, decision in (("Wealth Core", wealth),
                                ("controller", controller_doc)):
            producer = decision.get("producer")
            if (not isinstance(producer, Mapping)
                    or set(producer) != decision_fields
                    or producer.get("schema")
                    != "sentinel.certification-decision/1"
                    or any(producer.get(field) != value for field, value in
                           expected_decision_bindings.items())
                    or not isinstance(producer.get("review"), Mapping)
                    or producer["review"].get("source_sha256")
                    != canonical_sha256(expected_decision_bindings)):
                blockers.append(
                    f"{label} decision does not bind actual producer inputs")
        if forward.get("manual_review_required") is not False:
            blockers.append("forward chain has not been reviewed")
        if resource.get("verdict") != "PASS":
            blockers.append("resource envelope is not PASS")
        certification_version = (base.get("parity_generations") or {}).get(
            "sentinel_data_version")
        expected_policy_fields = {
            "schema", "verdict", "implementation_sha256",
            "chain_root_sha256", "publication_row_sha256",
            "base_manifest_sha256", "certification_data_version",
        }
        if (set(policy) != expected_policy_fields
                or policy.get("verdict") != "PASS"
                or policy.get("implementation_sha256")
                != publication_policy_implementation_sha256()
                or policy.get("base_manifest_sha256")
                != artifacts["base_manifest"]["sha256"]
                or policy.get("certification_data_version")
                != certification_version
                or policy.get("publication_row_sha256")
                != artifacts["publication_row"]["sha256"]
                or policy.get("chain_root_sha256")
                != canonical_sha256(publication_row_doc)):
            blockers.append("publication policy producer bindings differ")
        if publication_row_doc.get("version") != certification_version:
            blockers.append(
                "publication-chain root is not the certification corpus generation")
        runtime_image = ((base.get("sentinel_runtime_image") or {}).get(
            "repo_digests") or [])
        test_image = ((base.get("sentinel_test_image") or {}).get(
            "repo_digests") or [])
        def digest(values):
            resolved = {"sha256:" + value.split("@sha256:", 1)[1]
                        for value in values
                        if isinstance(value, str) and "@sha256:" in value}
            if (len(resolved) != 1
                    or any(re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                           for value in resolved)):
                blockers.append("image has no unique immutable repository digest")
                return "sha256:" + "0" * 64
            return next(iter(resolved))
        runtime_digest, test_digest = digest(runtime_image), digest(test_image)
        strategy = (forward.get("source_identity") or {}).get("strategy_identity")
        strategy_sha = canonical_sha256(strategy) if isinstance(strategy, Mapping) \
            else "0" * 64
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "lifecycle": "FINALIZED",
            "verdict": "PASS" if not blockers else "BLOCKED",
            "failures": sorted(set(blockers)),
            "strict_xfails": int(tests.get("xfailed") or 0),
            "strict_skips": int(tests.get("skipped") or 0),
            "strict_xpasses": int(tests.get("xpassed") or 0),
            "failed_tests": int(tests.get("failed") or 0),
            "passed_tests": int(tests.get("passed") or 0),
            "completed_checks": len(COMPLETED_CHECK_IDS),
            "git_commit": base.get("git_commit"),
            "identity_hash": base.get("identity_hash"),
            "final_corpus_hash": base.get("final_corpus_hash"),
            "sentinel_source_hash": base.get("sentinel_source_hash"),
            "wealth_core_source_hash": base.get("wealth_core_source_hash"),
            "requirements_lock_sha256": base.get("requirements_lock_sha256"),
            "runtime_image_digest": runtime_digest,
            "test_image_digest": test_digest,
            "strategy_identity_sha256": strategy_sha,
            "execution_config_sha256": execution_config_sha256,
            "automation_config_sha256": canonical_sha256(automation),
            "publication_policy_sha256": artifacts["publication_policy"]["sha256"],
            "wealth_core_evidence_sha256": artifacts["wealth_core"]["sha256"],
            "controller_evidence_sha256": artifacts["controller"]["sha256"],
            "forward_chain_evidence_sha256": artifacts["forward_chain"]["sha256"],
            "resource_envelope_evidence_sha256": artifacts["resource_envelope"]["sha256"],
            "producer": {
                "schema": BUNDLE_SCHEMA,
                "base_manifest_sha256": artifacts["base_manifest"]["sha256"],
                "pre_suite_manifest_sha256": artifacts["pre_suite_manifest"]["sha256"],
                "test_run_sha256": artifacts["test_run"]["sha256"],
                "test_summary_sha256": artifacts["test_summary"]["sha256"],
                "expected_hashes_sha256": artifacts["expected_hashes"]["sha256"],
                "baseline_run_sha256": artifacts["baseline_run"]["sha256"],
                "forward_chain_run_sha256": artifacts[
                    "forward_chain_run"]["sha256"],
                "resource_policy_candidate_sha256": artifacts[
                    "resource_policy_candidate"]["sha256"],
                "resource_policy_sha256": artifacts["resource_policy"]["sha256"],
                "resource_measurements_sha256": artifacts["resource_measurements"]["sha256"],
                "publication_row_sha256": artifacts["publication_row"]["sha256"],
                "automation_config_sha256": artifacts["automation_config"]["sha256"],
            },
        }
        manifest_payload = canonical_json_bytes(manifest)
        _write_no_clobber(temporary / "certification_manifest.json", manifest_payload)
        artifacts["certification_manifest"] = {
            "path": "certification_manifest.json", "sha256": sha(manifest_payload),
            "format": "json",
        }
        index = {"schema": INDEX_SCHEMA, "artifacts": dict(sorted(artifacts.items()))}
        _write_no_clobber(temporary / "evidence_index.json", canonical_json_bytes(index))
        os.rename(temporary, output)
        published = True
        _fsync_directory(parent)
        return manifest
    except BaseException as exc:
        if published:
            _rollback_directory(output, parent, exc)
        try:
            _rmtree_retry(temporary)
        except OSError as cleanup:
            if hasattr(exc, "add_note"):
                exc.add_note(f"temporary bundle cleanup also failed: {cleanup!r}")
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summarize-tests")
    summary.add_argument("--test-run", type=Path, required=True)
    summary.add_argument("--pre-suite-manifest", type=Path, required=True)
    summary.add_argument("--base-manifest", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    forward = commands.add_parser("promote-forward-chain")
    forward.add_argument("--formal-run", type=Path, required=True)
    forward.add_argument("--output", type=Path, required=True)
    forward.add_argument("--confirm-sha256", required=True)
    forward.add_argument("--reviewer", required=True)
    forward.add_argument("--ticket", required=True)
    forward.add_argument("--reviewed-at", required=True)
    resource_review = commands.add_parser("promote-resource-policy")
    resource_review.add_argument("--candidate", type=Path, required=True)
    resource_review.add_argument("--output", type=Path, required=True)
    resource_review.add_argument("--confirm-sha256", required=True)
    resource_review.add_argument("--reviewer", required=True)
    resource_review.add_argument("--ticket", required=True)
    resource_review.add_argument("--reviewed-at", required=True)
    resource = commands.add_parser("score-resources")
    resource.add_argument("--policy", type=Path, required=True)
    resource.add_argument("--measurement", type=Path, action="append", required=True)
    resource.add_argument("--output", type=Path, required=True)
    publication = commands.add_parser("publication-policy")
    publication.add_argument("--publication-row", type=Path, required=True)
    publication.add_argument("--base-manifest", type=Path, required=True)
    publication.add_argument("--output", type=Path, required=True)
    decide = commands.add_parser("decide-certification")
    for option in ("base-manifest", "test-summary", "expected-hashes",
                   "baseline-run", "forward-run", "forward-reviewed",
                   "reference-artifact"):
        decide.add_argument(f"--{option}", type=Path, required=True)
    decide.add_argument("--confirm-inputs-sha256", required=True)
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--ticket", required=True)
    decide.add_argument("--reviewed-at", required=True)
    decide.add_argument("--output", type=Path, required=True)
    finalize = commands.add_parser("finalize-bundle")
    for option in (
            "base-manifest", "pre-suite-manifest", "test-run", "test-summary",
            "expected-hashes", "baseline-run",
            "wealth-core", "controller",
            "forward-run", "forward-reviewed", "resource-policy",
            "resource-policy-candidate",
            "resource-evidence", "publication-row",
            "publication-evidence", "reference-artifact",
            "reference-checksums", "automation-config"):
        finalize.add_argument(f"--{option}", type=Path, required=True)
    finalize.add_argument("--execution-config-sha256", required=True)
    finalize.add_argument("--completed-checks", type=int, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "summarize-tests":
            summarize_test_run(
                args.test_run, args.pre_suite_manifest,
                args.base_manifest, args.output)
        elif args.command == "promote-forward-chain":
            promote_forward_chain(
                formal_run_path=args.formal_run, output=args.output,
                confirm_sha256=args.confirm_sha256, reviewer=args.reviewer,
                ticket=args.ticket, reviewed_at=args.reviewed_at)
        elif args.command == "promote-resource-policy":
            promote_resource_policy(
                candidate_path=args.candidate, output=args.output,
                confirm_sha256=args.confirm_sha256, reviewer=args.reviewer,
                ticket=args.ticket, reviewed_at=args.reviewed_at)
        elif args.command == "score-resources":
            score_resources(policy_path=args.policy,
                            measurement_paths=args.measurement, output=args.output)
        elif args.command == "publication-policy":
            produce_publication_policy(
                publication_row_path=args.publication_row,
                base_manifest_path=args.base_manifest,
                output=args.output)
        elif args.command == "decide-certification":
            produce_certification_decisions(
                output=args.output, base_manifest=args.base_manifest,
                test_summary=args.test_summary,
                expected_hashes=args.expected_hashes,
                baseline_run=args.baseline_run,
                forward_run=args.forward_run,
                forward_reviewed=args.forward_reviewed,
                reference_artifact=args.reference_artifact,
                confirm_inputs_sha256=args.confirm_inputs_sha256,
                reviewer=args.reviewer, ticket=args.ticket,
                reviewed_at=args.reviewed_at)
        elif args.command == "finalize-bundle":
            finalize_bundle(
                output=args.output, base_manifest=args.base_manifest,
                pre_suite_manifest=args.pre_suite_manifest,
                test_run=args.test_run, test_summary=args.test_summary,
                expected_hashes=args.expected_hashes,
                baseline_run=args.baseline_run,
                wealth_core=args.wealth_core,
                controller=args.controller, forward_run=args.forward_run,
                forward_reviewed=args.forward_reviewed,
                resource_policy_candidate=args.resource_policy_candidate,
                resource_policy=args.resource_policy,
                resource_evidence=args.resource_evidence,
                publication_row=args.publication_row,
                publication_evidence=args.publication_evidence,
                reference_artifact=args.reference_artifact,
                reference_checksums=args.reference_checksums,
                automation_config=args.automation_config,
                execution_config_sha256=args.execution_config_sha256,
                completed_checks=args.completed_checks)
    except EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
