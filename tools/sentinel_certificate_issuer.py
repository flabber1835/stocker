"""Offline Ed25519 issuer for Sentinel paper-execution certificates.

This tool never generates keys and never contacts a network or broker.  It
accepts one operator-mounted PKCS#8 Ed25519 private key, validates that every
evidence file named by the canonical claims has the exact signed digest and an
internally passing schema, then publishes one no-clobber certificate file.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Mapping, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel.authority import (
    AuthorityRefused,
    canonical_json_bytes,
    canonical_sha256,
    key_id_for_public_key,
    signed_envelope_bytes,
    unsigned_envelope_bytes,
    validate_certificate_claims,
)
from sentinel.execution.authority_gate import (
    publication_policy_implementation_sha256,
)


EVIDENCE_INDEX_SCHEMA = "sentinel.certificate_evidence_index/1"
RESOURCE_MEASUREMENT_PRODUCER = "scripts/sentinel-measure.sh"
REQUIRED_EVIDENCE = frozenset({
    "certification_manifest", "wealth_core", "controller", "forward_chain",
    "resource_envelope", "publication_policy", "reference_artifact",
    "reference_checksums", "base_manifest", "pre_suite_manifest",
    "test_run", "test_summary", "expected_hashes", "baseline_run",
    "forward_chain_run", "resource_policy", "resource_measurements",
    "resource_policy_candidate",
    "publication_row", "automation_config",
})


class IssuanceRefused(RuntimeError):
    """The evidence set cannot support a signed paper-execution decision."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json(payload: bytes, *, label: str,
                 allow_floating_point: bool = False) -> Mapping:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise IssuanceRefused(f"{label} repeats JSON key {key!r}")
            value[key] = item
        return value

    def nonfinite(value):
        raise IssuanceRefused(f"{label} contains non-finite number {value}")

    try:
        options = {"object_pairs_hook": unique, "parse_constant": nonfinite}
        if not allow_floating_point:
            options["parse_float"] = lambda _value: (_ for _ in ()).throw(
                IssuanceRefused(f"{label} contains a floating-point number"))
        value = json.loads(payload.decode("utf-8"), **options)
    except IssuanceRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise IssuanceRefused(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise IssuanceRefused(f"{label} must be a JSON object")
    return value


def _exact(value: Mapping, fields: set[str], *, label: str) -> None:
    if set(value) != fields:
        raise IssuanceRefused(
            f"{label} fields differ: expected {sorted(fields)}, got {sorted(value)}")


def _load_evidence(index_path: Path) -> tuple[Mapping, dict[str, tuple[Path, bytes, Mapping | None]]]:
    index_path = Path(index_path).resolve()
    try:
        index_bytes = index_path.read_bytes()
    except OSError as exc:
        raise IssuanceRefused(f"evidence index is unreadable: {index_path}") from exc
    index = _strict_json(index_bytes, label="evidence index")
    _exact(index, {"schema", "artifacts"}, label="evidence index")
    if index["schema"] != EVIDENCE_INDEX_SCHEMA:
        raise IssuanceRefused("evidence index schema is unknown")
    artifacts = index["artifacts"]
    if not isinstance(artifacts, Mapping) or set(artifacts) != REQUIRED_EVIDENCE:
        raise IssuanceRefused(
            "evidence index must name exactly: " + ", ".join(sorted(REQUIRED_EVIDENCE)))
    loaded = {}
    for name, record in artifacts.items():
        if not isinstance(record, Mapping):
            raise IssuanceRefused(f"evidence record {name} must be an object")
        _exact(record, {"path", "sha256", "format"}, label=f"evidence record {name}")
        if not isinstance(record["path"], str) or not record["path"]:
            raise IssuanceRefused(f"evidence record {name} path is invalid")
        path = (index_path.parent / record["path"]).resolve()
        try:
            path.relative_to(index_path.parent)
        except ValueError as exc:
            raise IssuanceRefused(
                f"evidence record {name} escapes the evidence directory") from exc
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise IssuanceRefused(f"evidence record {name} is unreadable") from exc
        actual = _sha256(payload)
        if record["sha256"] != actual:
            raise IssuanceRefused(
                f"evidence record {name} digest mismatch: actual {actual}")
        if record["format"] == "json":
            parsed = _strict_json(
                payload, label=f"evidence record {name}",
                allow_floating_point=(name in {
                    "expected_hashes", "baseline_run"}))
        elif record["format"] == "bytes":
            parsed = None
        else:
            raise IssuanceRefused(f"evidence record {name} format is unknown")
        loaded[name] = (path, payload, parsed)
    return index, loaded


def _require_zero(value: Mapping, field: str, *, label: str) -> None:
    if type(value.get(field)) is not int or value[field] != 0:
        raise IssuanceRefused(f"{label} requires exactly zero {field}")


def _unique_image_digest(image: object, *, label: str) -> str:
    if not isinstance(image, Mapping) or not isinstance(
            image.get("repo_digests"), list):
        raise IssuanceRefused(f"{label} image identity is absent")
    values = {
        "sha256:" + item.split("@sha256:", 1)[1]
        for item in image["repo_digests"]
        if isinstance(item, str) and "@sha256:" in item
    }
    if (len(values) != 1 or re.fullmatch(
            r"sha256:[0-9a-f]{64}", next(iter(values), "")) is None):
        raise IssuanceRefused(f"{label} image digest is not unique/immutable")
    return next(iter(values))


def _require_reference_checksum(index: Mapping, loaded: Mapping) -> None:
    """Prove the retained checksum manifest actually names the reference."""
    artifact = index["artifacts"]["reference_artifact"]
    digest = _sha256(loaded["reference_artifact"][1])
    name = Path(artifact["path"]).name
    try:
        lines = loaded["reference_checksums"][1].decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise IssuanceRefused(
            "reference checksum manifest is not UTF-8") from exc
    accepted = {f"{digest}  {name}", f"{digest} *{name}"}
    if sum(line in accepted for line in lines) != 1:
        raise IssuanceRefused(
            "reference checksum manifest does not contain exactly one exact "
            "entry for the retained reference artifact")


def _validate_formal_test_evidence(loaded: Mapping) -> None:
    base = loaded["base_manifest"][2]
    pre = loaded["pre_suite_manifest"][2]
    run = loaded["test_run"][2]
    summary = loaded["test_summary"][2]
    if (not isinstance(base, Mapping)
            or base.get("schema") != "sentinel.certification_manifest/2"
            or base.get("lifecycle") != "FINALIZED"
            or not isinstance(pre, Mapping)
            or pre.get("schema") != "sentinel.certification_manifest/2"
            or pre.get("lifecycle") != "FROZEN"
            or not isinstance(run, Mapping)
            or run.get("schema") != "sentinel.certification-test-run/1"
            or set(run) != {
                "schema", "status", "producer_sha256", "base_manifest",
                "command", "inventory", "inventory_log_base64",
                "pytest_log_base64", "pytest_log_sha256", "exit_code",
                "passed", "failed", "skipped", "xfailed", "xpassed",
                "errors"}
            or run.get("status") != "PASS"
            or not isinstance(summary, Mapping)
            or summary.get("schema")
            != "sentinel.certification-test-summary/1"):
        raise IssuanceRefused("formal certification test evidence is not canonical")
    binding = run.get("base_manifest")
    command = run.get("command")
    inventory = run.get("inventory")
    from scripts import sentinel_test_run as formal_runner
    if run.get("producer_sha256") != _sha256(
            Path(formal_runner.__file__).resolve().read_bytes()):
        raise IssuanceRefused("formal test-run producer source differs")
    try:
        inventory_log = base64.b64decode(
            run.get("inventory_log_base64"), validate=True)
        pytest_log = base64.b64decode(
            run.get("pytest_log_base64"), validate=True)
    except (ValueError, TypeError) as exc:
        raise IssuanceRefused(
            "formal test-run retained logs are not canonical base64") from exc
    if (base64.b64encode(inventory_log).decode("ascii")
            != run.get("inventory_log_base64")
            or base64.b64encode(pytest_log).decode("ascii")
            != run.get("pytest_log_base64")):
        raise IssuanceRefused("formal test-run log base64 is not canonical")
    try:
        parsed_inventory = formal_runner.inventory_from_log(inventory_log)
        parsed_counts = formal_runner.counts_from_log(
            pytest_log, exit_code=run.get("exit_code"))
    except formal_runner.TestRunRefused as exc:
        raise IssuanceRefused(
            f"formal test-run retained logs do not prove PASS: {exc}") from exc
    expected_binding_fields = {
        "path", "sha256", "lifecycle", "identity_hash", "git_commit",
        "certification_input_sha256", "runtime_image_digest",
        "test_image_digest",
    }
    expected_command_fields = {"argv", "sha256"}
    expected_inventory_fields = {"nodeids", "sha256", "count"}
    if (set(binding or {}) != expected_binding_fields
            or binding.get("sha256") != _sha256(
                loaded["pre_suite_manifest"][1])
            or binding.get("lifecycle") != "FROZEN"
            or binding.get("git_commit") != base.get("git_commit")
            or binding.get("git_commit") != pre.get("git_commit")
            or binding.get("identity_hash") != base.get("identity_hash")
            or binding.get("identity_hash") != pre.get("identity_hash")
            or binding.get("certification_input_sha256") != (
                (base.get("image_source_hashes") or {}).get(
                    "certification_inputs"))
            or binding.get("certification_input_sha256") != (
                (pre.get("image_source_hashes") or {}).get(
                    "certification_inputs"))
            or binding.get("runtime_image_digest") != _unique_image_digest(
                base.get("sentinel_runtime_image"), label="runtime")
            or binding.get("runtime_image_digest") != _unique_image_digest(
                pre.get("sentinel_runtime_image"), label="pre-suite runtime")
            or binding.get("test_image_digest") != _unique_image_digest(
                base.get("sentinel_test_image"), label="test")
            or binding.get("test_image_digest") != _unique_image_digest(
                pre.get("sentinel_test_image"), label="pre-suite test")
            or base.get("verdict") != "PASS"
            or run.get("exit_code") != 0
            or not isinstance(command, Mapping)
            or set(command) != expected_command_fields
            or not isinstance(command.get("argv"), list)
            or not command.get("argv")
            or any(not isinstance(arg, str) or not arg
                   for arg in command.get("argv", []))
            or command.get("sha256") != canonical_sha256(command["argv"])
            or not isinstance(inventory, Mapping)
            or set(inventory) != expected_inventory_fields
            or inventory.get("nodeids") != sorted(set(
                inventory.get("nodeids") or []))
            or not inventory.get("nodeids")
            or inventory.get("count") != len(inventory.get("nodeids") or [])
            or inventory != parsed_inventory
            or run.get("pytest_log_sha256") != _sha256(pytest_log)
            or any(run.get(field) != value
                   for field, value in parsed_counts.items())):
        raise IssuanceRefused("formal test-run provenance or inventory differs")
    try:
        formal_runner.validate_canonical_command(
            command["argv"],
            expected_test_image_digest=binding["test_image_digest"],
        )
    except formal_runner.TestRunRefused as exc:
        raise IssuanceRefused(
            f"formal test command is not the complete certified suite: {exc}"
        ) from exc
    for field in ("failed", "skipped", "xpassed", "errors"):
        _require_zero(run, field, label="formal certification test run")
    if (type(run.get("passed")) is not int or run["passed"] < 1
            or type(run.get("xfailed")) is not int or run["xfailed"] < 0
            or run["passed"] + run["xfailed"] != inventory["count"]):
        raise IssuanceRefused("formal test-run outcomes do not cover inventory")
    expected_summary = {
        "schema": "sentinel.certification-test-summary/1",
        "test_run_sha256": _sha256(loaded["test_run"][1]),
        "pre_suite_manifest_sha256": _sha256(
            loaded["pre_suite_manifest"][1]),
        "base_manifest_sha256": _sha256(loaded["base_manifest"][1]),
        "pytest_log_sha256": run.get("pytest_log_sha256"),
        "command_sha256": command["sha256"],
        "inventory_sha256": inventory["sha256"],
        "inventory_count": inventory["count"],
        **{field: run[field] for field in (
            "passed", "failed", "skipped", "xfailed", "xpassed", "errors")},
    }
    if summary != expected_summary:
        raise IssuanceRefused("test summary is not derived from the formal run")


def _decision_input_bindings(loaded: Mapping) -> Mapping:
    return {
        "base_manifest_sha256": _sha256(loaded["base_manifest"][1]),
        "test_summary_sha256": _sha256(loaded["test_summary"][1]),
        "expected_hashes_sha256": _sha256(loaded["expected_hashes"][1]),
        "baseline_run_sha256": _sha256(loaded["baseline_run"][1]),
        "forward_chain_run_sha256": _sha256(
            loaded["forward_chain_run"][1]),
        "forward_chain_sha256": _sha256(loaded["forward_chain"][1]),
        "reference_sha256": _sha256(loaded["reference_artifact"][1]),
    }


def _validate_decision_producer(loaded: Mapping, decision: Mapping,
                                *, label: str) -> None:
    producer = decision.get("producer")
    bindings = _decision_input_bindings(loaded)
    if (not isinstance(producer, Mapping)
            or set(producer) != {"schema", *bindings, "review"}
            or producer.get("schema") != "sentinel.certification-decision/1"
            or any(producer.get(field) != value
                   for field, value in bindings.items())):
        raise IssuanceRefused(f"{label} was not emitted from indexed inputs")
    review = producer.get("review")
    if (not isinstance(review, Mapping)
            or review.get("schema")
            != "sentinel.certification-decision-review/1"
            or review.get("source_sha256") != canonical_sha256(bindings)
            or review.get("authority_effect") != "NONE"
            or not review.get("reviewer") or not review.get("ticket")):
        raise IssuanceRefused(f"{label} has no exact reviewed input binding")


def _validate_formal_baseline(loaded: Mapping) -> Mapping:
    from tools import wealth_core_baseline_run as formal_baseline
    record = loaded["baseline_run"][2]
    if not isinstance(record, Mapping):
        raise IssuanceRefused("formal baseline-run record is absent")
    try:
        if (formal_baseline.canonical_bytes(record)
                != loaded["baseline_run"][1]):
            raise formal_baseline.BaselineRunRefused(
                "record bytes are not canonical")
        formal_baseline.validate_record(record)
        expected = base64.b64decode(
            record["expected_hashes"]["bytes_base64"], validate=True)
        manifest = base64.b64decode(
            record["certification_manifest"]["bytes_base64"], validate=True)
    except (formal_baseline.BaselineRunRefused, KeyError, TypeError,
            ValueError) as exc:
        raise IssuanceRefused(
            f"formal baseline-run producer evidence is invalid: {exc}") from exc
    if (expected != loaded["expected_hashes"][1]
            or manifest != loaded["base_manifest"][1]):
        raise IssuanceRefused(
            "formal baseline-run retained inputs differ from indexed bytes")
    return record["terminal_run"]["row"]


def _validate_formal_forward(loaded: Mapping) -> tuple[Mapping, Mapping]:
    from scripts import sentinel_forward_run as formal_forward
    record = loaded["forward_chain_run"][2]
    if not isinstance(record, Mapping):
        raise IssuanceRefused("formal forward-chain record is absent")
    try:
        if (formal_forward.canonical_bytes(record)
                != loaded["forward_chain_run"][1]):
            raise formal_forward.ForwardRunRefused(
                "record bytes are not canonical")
        raw = formal_forward.validate_record(record)
    except (formal_forward.ForwardRunRefused, KeyError, TypeError,
            ValueError) as exc:
        raise IssuanceRefused(
            f"formal forward-chain producer evidence is invalid: {exc}") from exc
    if record.get("base_manifest", {}).get("sha256") != _sha256(
            loaded["base_manifest"][1]):
        raise IssuanceRefused(
            "formal forward-chain manifest differs from indexed bytes")
    return raw, record


def _validate_resource_measurements(loaded: Mapping, resource: Mapping,
                                    policy: Mapping,
                                    measurement_index: Mapping) -> None:
    target = policy.get("artifact_target")
    review = policy.get("review")
    required = policy.get("required_phases")
    measurements = measurement_index.get("measurements")
    retained = measurement_index.get("retained_measurements")
    commands = policy.get("phase_commands")
    elapsed_limits = policy.get("max_elapsed_seconds")
    minimum = policy.get("min_headroom_percent")
    if (not isinstance(target, Mapping)
            or set(target) != {"git_commit", "runtime_image_digest",
                               "test_image_digest", "automation_config_sha256"}
            or not isinstance(review, Mapping)
            or review.get("schema")
            != "sentinel.resource-envelope-policy-review/1"
            or review.get("authority_effect") != "NONE"
            or not isinstance(required, list)
            or required != sorted(set(required)) or not required
            or not isinstance(commands, Mapping)
            or set(commands) != set(required)
            or not isinstance(elapsed_limits, Mapping)
            or set(elapsed_limits) != set(required)
            or type(minimum) is not int or not 0 <= minimum <= 100
            or type(policy.get("require_cpu_enforced")) is not bool
            or type(policy.get("allow_host_memory_observed")) is not bool
            or not isinstance(measurements, Mapping)
            or set(measurements) != set(required)
            or not isinstance(retained, Mapping)
            or set(retained) != set(required)
            or resource.get("retained_measurements") != retained):
        raise IssuanceRefused("resource policy/retained measurement index differs")
    for phase in required:
        record = retained[phase]
        if not isinstance(record, Mapping) or set(record) != {
                "report_sha256", "report", "samples_sha256", "samples_base64"}:
            raise IssuanceRefused(f"resource phase {phase} retention is malformed")
        report = record["report"]
        producer = report.get("producer") if isinstance(report, Mapping) else None
        producer_path = (Path(__file__).resolve().parents[1]
                         / RESOURCE_MEASUREMENT_PRODUCER)
        if (not isinstance(report, Mapping)
                or report.get("schema") != "sentinel.resource-measurement/1"
                or report.get("phase") != phase
                or record["report_sha256"] != canonical_sha256(report)
                or measurements[phase] != record["report_sha256"]
                or not isinstance(producer, Mapping)
                or set(producer) != {"path", "sha256"}
                or producer.get("path") != RESOURCE_MEASUREMENT_PRODUCER
                or producer.get("sha256")
                != _sha256(producer_path.read_bytes())):
            raise IssuanceRefused(f"resource phase {phase} report identity differs")
        try:
            samples = base64.b64decode(
                record["samples_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise IssuanceRefused(
                f"resource phase {phase} samples are not canonical base64") from exc
        identity = report.get("identity")
        runtime = report.get("reviewed_runtime_image")
        test_image = report.get("reviewed_test_image")
        phase_container = report.get("phase_container")
        if (record["samples_sha256"] != _sha256(samples)
                or not isinstance(identity, Mapping)
                or identity.get("samples_sha256") != record["samples_sha256"]
                or identity.get("resource_policy_sha256")
                != _sha256(loaded["resource_policy"][1])
                or any(identity.get(field) != target.get(field) for field in (
                    "git_commit", "runtime_image_digest", "test_image_digest",
                    "automation_config_sha256"))
                or report.get("command_argv") != commands[phase]
                or identity.get("phase_command_sha256")
                != canonical_sha256(commands[phase])
                or not isinstance(report.get("host_evidence"), Mapping)
                or report["host_evidence"].get("probed") is not True
                or identity.get("host_capabilities_sha256")
                != canonical_sha256(report["host_evidence"])
                or not isinstance(runtime, Mapping)
                or runtime.get("ref") != (
                    f"{report.get('runtime_image_repository')}@"
                    f"{target['runtime_image_digest']}")
                or not isinstance(phase_container, Mapping)
                or runtime.get("id") != identity.get("runtime_image_id")
                or phase_container.get("image_id")
                != identity.get("runtime_image_id")
                or phase_container.get("configured_image") != runtime.get("ref")
                or not isinstance(test_image, Mapping)
                or test_image.get("ref") != (
                    f"{report.get('test_image_repository')}@"
                    f"{target['test_image_digest']}")
                or test_image.get("id") != identity.get("test_image_id")
                or runtime.get("source_revision") != target["git_commit"]
                or test_image.get("source_revision") != target["git_commit"]):
            raise IssuanceRefused(
                f"resource phase {phase} artifact/image provenance differs")
        if (report.get("exit_code") != 0
                or type(report.get("samples")) is not int
                or report["samples"] < 1
                or report.get("memory_verdict") != "PASS"
                or report.get("headroom_verdict") != "PASS"
                or type(report.get("elapsed_seconds")) is not int
                or report["elapsed_seconds"] > elapsed_limits[phase]
                or phase_container.get("oom_killed") is not False
                or any(item.get("oom_killed")
                       or int(item.get("restarts") or 0)
                       for item in report.get("oom_and_restarts") or [])
                or any(type(item.get("headroom_basis_points")) is not int
                       or item["headroom_basis_points"] < minimum * 100
                       for item in (report.get("containers") or {}).values())
                or (policy["require_cpu_enforced"]
                    and report.get("cpu_limit_enforcement") != "ENFORCED")
                or (report.get("host_memory_verdict") != "PASS"
                    and not (policy["allow_host_memory_observed"]
                             and report.get("host_memory_verdict")
                             == "OBSERVED"))):
            raise IssuanceRefused(
                f"resource phase {phase} does not independently pass policy")


def validate_evidence(claims: Mapping, index_path: Path) -> None:
    """Require full evidence bytes, internal PASS/GO, and cross-identities."""
    try:
        validate_certificate_claims(claims)
    except AuthorityRefused as exc:
        raise IssuanceRefused(str(exc)) from exc
    index, loaded = _load_evidence(index_path)
    bindings = claims["bindings"]

    expected = {
        "certification_manifest": bindings["certification_manifest_sha256"],
        "wealth_core": bindings["wealth_core"]["evidence_sha256"],
        "controller": bindings["controller"]["evidence_sha256"],
        "forward_chain": bindings["forward_chain"]["evidence_sha256"],
        "resource_envelope": bindings["resource_envelope"]["evidence_sha256"],
        "publication_policy": bindings["publication_policy"]["evidence_sha256"],
        "reference_artifact": bindings["reference"]["artifact_sha256"],
        "reference_checksums": bindings["reference"]["checksums_sha256"],
    }
    for name, digest in expected.items():
        actual = _sha256(loaded[name][1])
        if digest != actual:
            raise IssuanceRefused(
                f"claims bind {name} {digest}, evidence index supplies {actual}")
    _require_reference_checksum(index, loaded)

    manifest = loaded["certification_manifest"][2]
    if (manifest is None
            or manifest.get("schema") != "sentinel.certification_manifest/3"
            or manifest.get("lifecycle") != "FINALIZED"
            or manifest.get("verdict") != "PASS"
            or manifest.get("failures") != []):
        raise IssuanceRefused(
            "certification manifest must be exact FINALIZED/PASS schema /3")
    producer = manifest.get("producer")
    if not isinstance(producer, Mapping) or set(producer) != {
            "schema", "base_manifest_sha256", "pre_suite_manifest_sha256",
            "test_run_sha256", "test_summary_sha256",
            "expected_hashes_sha256", "baseline_run_sha256",
            "forward_chain_run_sha256", "resource_policy_sha256",
            "resource_policy_candidate_sha256",
            "resource_measurements_sha256", "publication_row_sha256",
            "automation_config_sha256"}:
        raise IssuanceRefused(
            "certification manifest was not emitted by the authority-evidence producer")
    if producer["schema"] != "sentinel.authority-evidence-bundle/1":
        raise IssuanceRefused("authority-evidence producer schema is unknown")
    producer_artifacts = {
        "base_manifest_sha256": "base_manifest",
        "pre_suite_manifest_sha256": "pre_suite_manifest",
        "test_run_sha256": "test_run",
        "test_summary_sha256": "test_summary",
        "expected_hashes_sha256": "expected_hashes",
        "baseline_run_sha256": "baseline_run",
        "forward_chain_run_sha256": "forward_chain_run",
        "resource_policy_candidate_sha256": "resource_policy_candidate",
        "resource_policy_sha256": "resource_policy",
        "resource_measurements_sha256": "resource_measurements",
        "publication_row_sha256": "publication_row",
        "automation_config_sha256": "automation_config",
    }
    for field, artifact in producer_artifacts.items():
        if producer[field] != _sha256(loaded[artifact][1]):
            raise IssuanceRefused(
                f"producer {field} does not bind indexed {artifact} bytes")
    _validate_formal_test_evidence(loaded)
    for field in ("strict_xfails", "strict_skips", "strict_xpasses",
                  "failed_tests"):
        _require_zero(manifest, field, label="certification manifest")
    if type(manifest.get("passed_tests")) is not int or manifest["passed_tests"] < 1:
        raise IssuanceRefused("certification manifest has no passing tests")
    for field, expected_value in claims["certification"].items():
        if manifest.get(field) != expected_value:
            raise IssuanceRefused(
                f"certification manifest {field} differs from signed summary")
    if manifest.get("git_commit") != bindings["git_commit"]:
        raise IssuanceRefused("manifest and certificate git commits differ")
    if manifest.get("identity_hash") != bindings["runtime_identity_sha256"]:
        raise IssuanceRefused("manifest and certificate runtime identities differ")
    if manifest.get("final_corpus_hash") != bindings[
            "certification_corpus"]["corpus_sha256"]:
        raise IssuanceRefused("manifest and certificate corpus identities differ")
    manifest_matches = {
        "sentinel_source_hash": bindings["sentinel_source_sha256"],
        "wealth_core_source_hash": bindings["wealth_core_source_sha256"],
        "requirements_lock_sha256": bindings["requirements_lock_sha256"],
        "runtime_image_digest": bindings["runtime_image_digest"],
        "test_image_digest": bindings["test_image_digest"],
        "strategy_identity_sha256": bindings["strategy_identity_sha256"],
        "execution_config_sha256": bindings["execution_config_sha256"],
        "automation_config_sha256": bindings["automation_config_sha256"],
        "publication_policy_sha256": bindings["publication_policy"][
            "evidence_sha256"],
        "wealth_core_evidence_sha256": bindings["wealth_core"][
            "evidence_sha256"],
        "controller_evidence_sha256": bindings["controller"][
            "evidence_sha256"],
        "forward_chain_evidence_sha256": bindings["forward_chain"][
            "evidence_sha256"],
        "resource_envelope_evidence_sha256": bindings["resource_envelope"][
            "evidence_sha256"],
    }
    for field, expected_value in manifest_matches.items():
        if manifest.get(field) != expected_value:
            raise IssuanceRefused(
                f"certification manifest {field} does not match signed evidence")

    wealth = loaded["wealth_core"][2]
    if (wealth is None or wealth.get("schema") != "wealth-core.certification/1"
            or wealth.get("verdict") != "GO"):
        raise IssuanceRefused("Wealth Core evidence is not GO")
    for field in ("strict_xfails", "strict_skips", "strict_xpasses",
                  "failed_tests"):
        _require_zero(wealth, field, label="Wealth Core evidence")
    wealth_matches = {
        "source_sha256": bindings["wealth_core_source_sha256"],
        "config_sha256": bindings["wealth_core"]["config_sha256"],
        "eligibility_sha256": bindings["wealth_core"]["eligibility_sha256"],
        "expected_hashes_sha256": bindings["wealth_core"][
            "expected_hashes_sha256"],
        "corpus_sha256": bindings["certification_corpus"]["corpus_sha256"],
        "data_version": bindings["certification_corpus"]["data_version"],
    }
    for field, expected_value in wealth_matches.items():
        if wealth.get(field) != expected_value:
            raise IssuanceRefused(
                f"Wealth Core evidence {field} does not match signed identity")
    _validate_decision_producer(loaded, wealth, label="Wealth Core evidence")
    expected_hashes = loaded["expected_hashes"][2]
    baseline = _validate_formal_baseline(loaded)
    expected_provenance = (expected_hashes or {}).get("provenance") or {}
    expected_corpus = (expected_hashes or {}).get("corpus") or {}
    expected_values = (expected_hashes or {}).get("hashes")
    from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
    producer_path = Path(__file__).resolve().with_name(
        "wealth_core_expected_hashes.py")
    loader_path = Path(__file__).resolve().parents[1] / (
        "services/backtester/app/wealth_core_replay.py")
    population_fields = (
        "distinct_securities", "first_session_securities",
        "last_session_securities", "maximum_session_securities")
    if (not isinstance(expected_hashes, Mapping)
            or expected_hashes.get("schema") != "wealth_core_expected_hashes.v1"
            or expected_hashes.get("status") != "ready"
            or not isinstance(expected_values, Mapping)
            or set(expected_values) != set(HASH_ORDER)
            or any(re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
                   for value in expected_values.values())
            or any(not isinstance(expected_corpus.get(field), int)
                   or expected_corpus[field] <= 0
                   for field in population_fields)
            or any(expected_corpus[field]
                   > expected_corpus["distinct_securities"]
                   for field in population_fields[1:])
            or expected_provenance.get("producer")
            != "tools/wealth_core_expected_hashes.py"
            or expected_provenance.get("producer_sha256")
            != _sha256(producer_path.read_bytes())
            or expected_provenance.get("canonical_loader")
            != "services/backtester/app/wealth_core_replay.py"
            or expected_provenance.get("canonical_loader_sha256")
            != _sha256(loader_path.read_bytes())
            or not isinstance(baseline, Mapping)
            or baseline.get("mode") != "baseline_replay"
            or baseline.get("status") != "success"
            or (baseline.get("spec") or {}).get("expected_hashes")
            != expected_values
            or str((baseline.get("spec") or {}).get("expected_data_version"))
            != str(expected_corpus.get("version"))
            or baseline.get("parity_hashes") != expected_values
            or ((baseline.get("summary") or {}).get("divergence") or {}).get(
                "identical") is not True):
        raise IssuanceRefused(
            "Wealth Core decision is not backed by repository producer/replay")
    controller = loaded["controller"][2]
    controller_required = "CONTROLLER" in claims["allowed_rollout_modes"]
    if controller_required and (
            controller is None
            or controller.get("schema") != "sentinel.controller-certification/1"
            or controller.get("verdict") != "PASS"):
        raise IssuanceRefused("controller evidence is not PASS")
    if controller_required:
        _validate_decision_producer(
            loaded, controller, label="controller evidence")
        controller_matches = {
            "rule_sha256": bindings["controller"]["rule_sha256"],
            "config_sha256": bindings["controller"]["config_sha256"],
            "reference_sha256": bindings["reference"]["artifact_sha256"],
            "corpus_sha256": bindings["certification_corpus"]["corpus_sha256"],
        }
        for field, expected_value in controller_matches.items():
            if controller.get(field) != expected_value:
                raise IssuanceRefused(
                    f"controller evidence {field} does not match signed identity")
    raw_forward, forward_record = _validate_formal_forward(loaded)
    forward = loaded["forward_chain"][2]
    review = forward.get("review") if isinstance(forward, Mapping) else None
    expected_forward = dict(raw_forward)
    expected_forward["manual_review_required"] = False
    expected_forward["review"] = review
    if (forward is None
            or forward.get("schema") != "sentinel.production-forward-chain/1"
            or forward.get("differential_verdict") != "PASS"
            or forward.get("authority_effect") != "NONE"
            or forward.get("runtime_authority_changed") is not False
            or forward.get("manual_review_required") is not False
            or forward != expected_forward):
        raise IssuanceRefused(
            "forward-chain evidence is not derived from the formal PASS run")
    if (not isinstance(review, Mapping)
            or set(review) != {
                "schema", "formal_run_sha256", "raw_report_sha256",
                "reviewer", "ticket", "reviewed_at",
                "confirmed_authority_effect"}
            or review.get("schema") != "sentinel.forward-chain-review/1"
            or review.get("formal_run_sha256")
            != _sha256(loaded["forward_chain_run"][1])
            or review.get("raw_report_sha256")
            != forward_record.get("stdout_sha256")
            or review.get("confirmed_authority_effect") != "NONE"
            or not review.get("reviewer") or not review.get("ticket")
            or not review.get("reviewed_at")):
        raise IssuanceRefused(
            "forward-chain review does not bind the indexed formal run")
    if forward.get("corpus_identity", {}).get("corpus_hash") != bindings[
            "certification_corpus"]["corpus_sha256"]:
        raise IssuanceRefused("forward-chain corpus does not match certification")
    if forward.get("reference", {}).get("sha256") != bindings[
            "reference"]["artifact_sha256"]:
        raise IssuanceRefused("forward-chain reference does not match certification")
    source = forward.get("source_identity")
    if not isinstance(source, Mapping):
        raise IssuanceRefused("forward-chain source identity is missing")
    if source.get("controller_rule_sha256") != bindings[
            "controller"]["rule_sha256"]:
        raise IssuanceRefused("forward-chain controller rule identity differs")
    formal_summary = forward_record.get("report") or {}
    if formal_summary.get("runtime_identity_sha256") != bindings[
            "runtime_identity_sha256"]:
        raise IssuanceRefused("forward-chain runtime environment identity differs")
    try:
        strategy_sha = hashlib.sha256(canonical_json_bytes(
            source.get("strategy_identity"))).hexdigest()
    except AuthorityRefused as exc:
        raise IssuanceRefused("forward-chain strategy identity is malformed") from exc
    if (strategy_sha != bindings["strategy_identity_sha256"]
            or formal_summary.get("strategy_identity_sha256") != strategy_sha):
        raise IssuanceRefused("forward-chain strategy identity differs")
    environment = source.get("environment")
    if (not isinstance(environment, Mapping)
            or environment.get("sentinel_source", {}).get("hash")
            != bindings["sentinel_source_sha256"]
            or environment.get("wealth_core_source", {}).get("hash")
            != bindings["wealth_core_source_sha256"]):
        raise IssuanceRefused("forward-chain source hashes differ")
    comparison = forward.get("comparison")
    if (not isinstance(comparison, Mapping)
            or comparison.get("first_divergence") is not None
            or comparison.get("reference_sessions_compared")
            != comparison.get("expected_reference_sessions")
            or comparison.get("field_comparisons")
            != comparison.get("expected_full_pass_field_comparisons")):
        raise IssuanceRefused("forward-chain comparison is incomplete")
    resource = loaded["resource_envelope"][2]
    if (resource is None or resource.get("schema") != "sentinel.resource-envelope/1"
            or resource.get("verdict") != "PASS"
            or resource.get("policy_sha256")
            != bindings["resource_envelope"]["policy_sha256"]):
        raise IssuanceRefused("resource-envelope evidence is not PASS /1")
    resource_policy = loaded["resource_policy"][2]
    resource_measurements = loaded["resource_measurements"][2]
    if (resource_policy is None
            or resource_policy.get("schema")
            != "sentinel.resource-envelope-policy/1"
            or resource.get("policy_sha256")
            != _sha256(loaded["resource_policy"][1])
            or resource_measurements is None
            or resource_measurements.get("schema")
            != "sentinel.resource-measurement-index/1"
            or resource.get("measurements")
            != resource_measurements.get("measurements")
            or resource.get("failures") != []):
        raise IssuanceRefused(
            "resource-envelope evidence is not derived from indexed policy/measurements")
    policy_candidate = loaded["resource_policy_candidate"][2]
    policy_review = resource_policy.get("review")
    if (not isinstance(policy_candidate, Mapping)
            or policy_candidate.get("schema")
            != "sentinel.resource-envelope-policy-candidate/1"
            or not isinstance(policy_review, Mapping)
            or policy_review.get("source_sha256")
            != _sha256(loaded["resource_policy_candidate"][1])):
        raise IssuanceRefused(
            "reviewed resource policy does not bind its indexed candidate")
    _validate_resource_measurements(
        loaded, resource, resource_policy, resource_measurements)
    policy = loaded["publication_policy"][2]
    expected_policy_fields = {
        "schema", "verdict", "implementation_sha256",
        "chain_root_sha256", "publication_row_sha256",
        "base_manifest_sha256", "certification_data_version",
    }
    if (policy is None or set(policy) != expected_policy_fields
            or policy.get("schema") != "sentinel.publication-policy/1"
            or policy.get("verdict") != "PASS"
            or policy.get("implementation_sha256")
            != publication_policy_implementation_sha256()
            or policy.get("implementation_sha256")
            != bindings["publication_policy"]["implementation_sha256"]
            or policy.get("chain_root_sha256")
            != bindings["publication_policy"]["chain_root_sha256"]):
        raise IssuanceRefused("publication-policy evidence is not PASS /1")
    publication_row = loaded["publication_row"][2]
    certification_version = bindings["certification_corpus"]["data_version"]
    base_generation = ((loaded["base_manifest"][2].get(
        "parity_generations") or {}).get("sentinel_data_version"))
    if (publication_row is None
            or publication_row.get("schema")
            != "sentinel.corpus-publication-row/1"
            or canonical_json_bytes(publication_row)
            != loaded["publication_row"][1]
            or policy.get("publication_row_sha256")
            != _sha256(loaded["publication_row"][1])
            or policy.get("chain_root_sha256")
            != canonical_sha256(publication_row)
            or policy.get("base_manifest_sha256")
            != _sha256(loaded["base_manifest"][1])
            or policy.get("certification_data_version")
            != certification_version
            or publication_row.get("version") != certification_version
            or base_generation != certification_version):
        raise IssuanceRefused(
            "publication-policy evidence does not bind the certified corpus "
            "generation and indexed publication row")


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    path = Path(path)
    if os.name == "posix":
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            raise IssuanceRefused("issuer private-key file is unreadable") from exc
        if mode & 0o077:
            raise IssuanceRefused(
                "issuer private-key file must not be group/world accessible")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IssuanceRefused("issuer private-key file is unreadable") from exc
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except (TypeError, ValueError) as exc:
        raise IssuanceRefused(
            "issuer key must be an unencrypted PKCS#8 PEM Ed25519 private key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise IssuanceRefused("issuer private key is not Ed25519")
    return key


def issue(*, claims_path: Path | None = None, claims_payload: bytes | None = None,
          evidence_index: Path, private_key_path: Path,
          key_id: str, output: Path) -> str:
    if (claims_path is None) == (claims_payload is None):
        raise IssuanceRefused(
            "supply exactly one claims path or pre-read claims payload")
    claims_bytes = (bytes(claims_payload) if claims_payload is not None
                    else Path(claims_path).read_bytes())
    claims = _strict_json(claims_bytes, label="certificate claims")
    if canonical_json_bytes(claims) != claims_bytes:
        raise IssuanceRefused("certificate claims bytes are not canonical JSON")
    validate_evidence(claims, evidence_index)
    key = _load_private_key(private_key_path)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    actual_key_id = key_id_for_public_key(public)
    if key_id != actual_key_id:
        raise IssuanceRefused(
            f"confirmed key_id does not identify mounted key: actual {actual_key_id}")
    unsigned = unsigned_envelope_bytes(key_id=key_id, claims=claims)
    payload = signed_envelope_bytes(
        key_id=key_id, claims=claims, signature=key.sign(unsigned))
    _atomic_no_clobber(Path(output), payload)
    return _sha256(payload)


def _atomic_no_clobber(output: Path, payload: bytes) -> None:
    output = output.resolve()
    if not output.parent.is_dir():
        raise IssuanceRefused("certificate output directory does not exist")
    temporary = output.with_name(f".{output.name}.tmp.{os.getpid()}")
    linked = False
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise IssuanceRefused(
                f"certificate output already exists; refusing overwrite: {output}") from exc
        linked = True
        _issuer_unlink_retry(temporary)
        _issuer_fsync_directory(output.parent)
    except BaseException as exc:
        if linked:
            _issuer_rollback(output, exc)
        raise
    finally:
        try:
            _issuer_unlink_retry(temporary)
        except OSError:
            pass


def _issuer_unlink_retry(path: Path, *, attempts: int = 4) -> None:
    failure = None
    for _ in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            failure = exc
    assert failure is not None
    raise failure


def _issuer_fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    failure = None
    try:
        os.fsync(descriptor)
    except BaseException as exc:
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


def _issuer_rollback(path: Path, original: BaseException) -> None:
    try:
        _issuer_unlink_retry(path)
    except OSError as cleanup:
        quarantine = path.with_name(f".{path.name}.rollback.{os.getpid()}")
        try:
            os.replace(path, quarantine)
            try:
                _issuer_unlink_retry(quarantine)
            except OSError as residual:
                if hasattr(original, "add_note"):
                    original.add_note(
                        f"rollback quarantine remains at {quarantine}: "
                        f"{residual!r}")
        except OSError as rename_error:
            if hasattr(original, "add_note"):
                original.add_note(
                    f"could not remove issued certificate: {cleanup!r}; "
                    f"rename fallback failed: {rename_error!r}")
    try:
        _issuer_fsync_directory(path.parent)
    except BaseException as cleanup_fsync:
        if hasattr(original, "add_note"):
            original.add_note(
                f"certificate rollback fsync also failed: {cleanup_fsync!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline no-network Ed25519 Sentinel certificate issuer")
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-issue-alpaca-paper-execution-certificate",
        action="store_true")
    parser.add_argument(
        "--confirm-issue-alpaca-paper-administrative-certificate",
        action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        claims_payload = Path(args.claims).read_bytes()
        claims = _strict_json(claims_payload, label="certificate claims")
        if canonical_json_bytes(claims) != claims_payload:
            raise IssuanceRefused(
                "certificate claims bytes are not canonical JSON")
        administrative = any(
            operation in {"ADMIN_INSPECT", "ADMIN_MIGRATE", "ADMIN_ADOPT"}
            for operation in claims.get("permitted_operations", []))
        if administrative:
            if (not args.confirm_issue_alpaca_paper_administrative_certificate
                    or args.confirm_issue_alpaca_paper_execution_certificate):
                raise IssuanceRefused(
                    "administrative issuance requires only the explicit "
                    "administrative-certificate confirmation")
        elif (not args.confirm_issue_alpaca_paper_execution_certificate
              or args.confirm_issue_alpaca_paper_administrative_certificate):
            raise IssuanceRefused(
                "execution issuance requires only the explicit "
                "execution-certificate confirmation")
        digest = issue(
            claims_payload=claims_payload, evidence_index=args.evidence_index,
            private_key_path=args.private_key_file, key_id=args.key_id,
            output=args.output)
    except (AuthorityRefused, IssuanceRefused, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "issued": True,
        "scope": "ALPACA_PAPER",
        "certificate_sha256": digest,
        "output": str(args.output),
        "broker_contacted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
