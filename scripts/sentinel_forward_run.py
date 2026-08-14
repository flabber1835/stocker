"""Emit formal evidence from the actual production forward-chain invocation.

The public CLI has no input for a pre-existing report.  It resolves the exact
test-image RepoDigest from a finalized certification manifest, invokes the
broker-free production runner itself, validates the captured bytes, and only
then atomically publishes a canonical record.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

from sentinel.core import production as production_module


SCHEMA = "sentinel.production-forward-chain-run/1"
REPORT_SCHEMA = "sentinel.production-forward-chain/1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNNER = ROOT / "tools" / "sentinel_forward_chain.py"
DEFAULT_PRODUCTION = Path(production_module.__file__).resolve()
DEFAULT_RULE = (
    ROOT / "docs" / "sentinel-handoff" / "00_README"
    / "FROZEN_SENTINEL_1P1_RULE.json"
)
DEFAULT_REFERENCE = (
    ROOT / "docs" / "sentinel-reference-implementation"
    / "sentinel_1p1_daily.csv"
)
DEFAULT_REFERENCE_SUMS = DEFAULT_REFERENCE.with_name("SHA256SUMS.txt")

CHAIN_START = "1998-01-02"
REFERENCE_START = "2006-07-31"
REFERENCE_END = "2026-07-31"
CHAIN_SESSIONS = 7_188
WARM_SESSIONS = 40
ADVANCED_SESSIONS = CHAIN_SESSIONS - WARM_SESSIONS
REFERENCE_SESSIONS = 5_032
FIELD_COMPARISONS = 55_351
FROZEN_REFERENCE_SHA256 = (
    "9bf46bfa229888d997072dd4fa3f60f772b208b1e2c55480c8cf65dd7b1c62f7"
)
REFERENCE_FIELDS = [
    "date", "nav", "allocation", "parent_allocation", "shadow_equity",
    "open_shadow_equity", "shadow_dd", "damaged", "green", "r20",
    "r40", "stops20", "stress_duration",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_NETWORK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_TOP_FIELDS = {
    "schema", "status", "producer_sha256", "runner_sha256",
    "base_manifest", "command", "stdout_base64", "stdout_sha256",
    "stderr_base64", "stderr_sha256", "exit_code", "report",
}
_BASE_FIELDS = {
    "path", "sha256", "lifecycle", "verdict", "git_commit",
    "identity_hash", "certification_input_sha256", "runtime_image_digest",
    "test_image_digest", "sentinel_source_sha256",
    "wealth_core_source_sha256", "certification_corpus_sha256",
    "publication_data_version",
}
_REPORT_FIELDS = {
    "schema", "raw_sha256", "authority_effect",
    "runtime_authority_changed", "manual_review_required",
    "differential_verdict", "transaction", "publication_coherence_sha256",
    "corpus_identity_sha256", "source_identity_sha256", "reference_sha256",
    "controller_rule_sha256", "environment_identity_sha256",
    "runtime_identity_sha256", "strategy_identity_sha256",
    "production_module_sha256", "runner_sha256", "chain_sessions_warmed",
    "chain_sessions_advanced", "reference_sessions_compared",
    "expected_reference_sessions", "field_comparisons",
    "expected_full_pass_field_comparisons", "first_divergence",
    "final_state_fingerprint",
}
_RAW_REPORT_FIELDS = {
    "schema", "differential_verdict", "authority_effect",
    "runtime_authority_changed", "manual_review_required", "reference",
    "alignment", "comparison", "transaction", "publication_coherence",
    "corpus_identity", "source_identity",
}
_SOURCE_FIELDS = {
    "environment", "environment_identity_sha256", "strategy_identity",
    "controller_rule_sha256", "production_module",
    "production_module_sha256", "runner", "runner_sha256",
    "reference_sha256",
}
_CORPUS_FIELDS = {
    "window", "data_version", "publication", "postgres_server_version",
    "postgres_certified", "first_session", "last_session", "sessions",
    "securities", "normalised_bars", "vendor_actions", "vendor_universe",
    "spy_total_return", "applied_repairs", "refusals", "anomalies",
    "refusal_truncation", "corpus_hash",
}
_COHERENCE_FIELDS = {
    "coherent", "version", "unpublished_rows", "unpublished_bars",
    "unpublished_actions", "unpublished_spy", "unpublished_universe",
    "unpublished_repairs", "unpublished_anomalies", "unpublished_runs",
    "enumeration",
}
_COMPARISON_FIELDS = {
    "differential_verdict", "chain_sessions_warmed",
    "chain_sessions_advanced", "reference_sessions_compared",
    "field_comparisons", "first_divergence",
    "final_close_decision_boundary", "final_state_fingerprint",
    "expected_reference_sessions", "expected_full_pass_field_comparisons",
    "reference_only_fields",
}


class ForwardRunRefused(ValueError):
    """The invocation bytes do not prove a complete production differential."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    """Return the one canonical JSON representation used by this schema."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return _sha256(canonical_bytes(value))


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ForwardRunRefused(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ForwardRunRefused(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ForwardRunRefused(f"{label} is not a JSON object")
    return value


def _mapping(value: object, *, label: str,
             fields: set[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ForwardRunRefused(f"{label} is not an object")
    if fields is not None and set(value) != fields:
        raise ForwardRunRefused(f"{label} fields are not the exact schema")
    return value


def _sha(value: object, *, label: str, git: bool = False) -> str:
    pattern = _GIT_SHA if git else _SHA256
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ForwardRunRefused(f"{label} is not a canonical digest")
    return value


def _integer(value: object, *, label: str, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ForwardRunRefused(f"{label} is not a canonical integer")
    return value


def _decode_base64(value: object, *, label: str) -> bytes:
    if not isinstance(value, str):
        raise ForwardRunRefused(f"{label} is not Base64 text")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ForwardRunRefused(f"{label} is not canonical Base64") from exc
    if base64.b64encode(raw).decode("ascii") != value:
        raise ForwardRunRefused(f"{label} is not canonical padded Base64")
    return raw


def _unique_repo_identity(image: object, *, label: str) -> tuple[str, str]:
    image = _mapping(image, label=label)
    refs = image.get("repo_digests")
    if not isinstance(refs, list) or not refs:
        raise ForwardRunRefused(f"{label} has no immutable RepoDigest")
    digests: set[str] = set()
    for ref in refs:
        if not isinstance(ref, str) or "@sha256:" not in ref:
            raise ForwardRunRefused(f"{label} has a malformed RepoDigest")
        digest = "sha256:" + ref.rsplit("@sha256:", 1)[1]
        _sha(digest.removeprefix("sha256:"), label=f"{label} digest")
        digests.add(digest)
    if len(digests) != 1:
        raise ForwardRunRefused(f"{label} has ambiguous content digests")
    return next(iter(digests)), sorted(refs)[0]


def manifest_binding(path: Path) -> tuple[dict[str, Any], str]:
    """Validate and bind the exact finalized manifest bytes."""
    raw = path.read_bytes()
    manifest = _json_object(raw, label="finalized manifest")
    if (manifest.get("schema") != "sentinel.certification_manifest/2"
            or manifest.get("lifecycle") != "FINALIZED"
            or manifest.get("verdict") != "PASS"
            or manifest.get("failures") != []
            or manifest.get("git_tree_clean") is not True):
        raise ForwardRunRefused(
            "base manifest is not clean FINALIZED/PASS certification evidence")
    commit = _sha(manifest.get("git_commit"), label="git_commit", git=True)
    runtime = _mapping(
        manifest.get("sentinel_runtime_image"), label="runtime image")
    test = _mapping(manifest.get("sentinel_test_image"), label="test image")
    if (runtime.get("source_revision") != commit
            or test.get("source_revision") != commit):
        raise ForwardRunRefused("manifest images do not carry its Git revision")
    runtime_digest, _ = _unique_repo_identity(runtime, label="runtime image")
    test_digest, test_ref = _unique_repo_identity(test, label="test image")
    if runtime_digest == test_digest:
        raise ForwardRunRefused("runtime and test image digests are identical")
    inputs = _mapping(
        manifest.get("image_source_hashes"), label="image source hashes")
    generations = _mapping(
        manifest.get("parity_generations"), label="parity generations")
    identity_hash = _sha(manifest.get("identity_hash"), label="identity_hash")
    corpus_hash = _sha(
        manifest.get("final_corpus_hash"), label="final_corpus_hash")
    if (manifest.get("final_identity_hash") != identity_hash
            or manifest.get("corpus_hash") != corpus_hash):
        raise ForwardRunRefused("manifest completion differs from frozen identity")
    binding = {
        "path": path.as_posix(),
        "sha256": _sha256(raw),
        "lifecycle": "FINALIZED",
        "verdict": "PASS",
        "git_commit": commit,
        "identity_hash": identity_hash,
        "certification_input_sha256": _sha(
            inputs.get("certification_inputs"),
            label="image_source_hashes.certification_inputs"),
        "runtime_image_digest": runtime_digest,
        "test_image_digest": test_digest,
        "sentinel_source_sha256": _sha(
            manifest.get("sentinel_source_hash"), label="sentinel source"),
        "wealth_core_source_sha256": _sha(
            manifest.get("wealth_core_source_hash"), label="Wealth Core source"),
        "certification_corpus_sha256": corpus_hash,
        "publication_data_version": _integer(
            generations.get("sentinel_data_version"),
            label="parity publication version", positive=True),
    }
    return binding, test_ref


def _validate_base_binding(base: object) -> Mapping[str, Any]:
    base = _mapping(base, label="base_manifest", fields=_BASE_FIELDS)
    if base.get("lifecycle") != "FINALIZED" or base.get("verdict") != "PASS":
        raise ForwardRunRefused("base_manifest lifecycle/verdict is not final PASS")
    if not isinstance(base.get("path"), str) or not base["path"]:
        raise ForwardRunRefused("base_manifest.path is empty")
    for field in (
            "sha256", "identity_hash", "certification_input_sha256",
            "sentinel_source_sha256", "wealth_core_source_sha256",
            "certification_corpus_sha256"):
        _sha(base.get(field), label=f"base_manifest.{field}")
    _sha(base.get("git_commit"), label="base_manifest.git_commit", git=True)
    for field in ("runtime_image_digest", "test_image_digest"):
        digest = base.get(field)
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ForwardRunRefused(f"base_manifest.{field} is malformed")
        _sha(digest.removeprefix("sha256:"), label=f"base_manifest.{field}")
    if base["runtime_image_digest"] == base["test_image_digest"]:
        raise ForwardRunRefused("base manifest image digests are identical")
    _integer(base.get("publication_data_version"),
             label="base_manifest.publication_data_version", positive=True)
    return base


def _runtime_identity_sha256(environment: Mapping[str, Any]) -> str:
    # This deliberately matches sentinel.identity.rehearsal_identity rather
    # than the compact envelope encoding.
    return _sha256(json.dumps(environment, sort_keys=True).encode())


def _report_binding(raw: Mapping[str, Any], *, raw_sha256: str,
                    base: Mapping[str, Any], runner_path: Path) -> dict[str, Any]:
    _mapping(raw, label="raw forward report", fields=_RAW_REPORT_FIELDS)
    if (raw.get("schema") != REPORT_SCHEMA
            or raw.get("differential_verdict") != "PASS"
            or raw.get("authority_effect") != "NONE"
            or raw.get("runtime_authority_changed") is not False
            or raw.get("manual_review_required") is not True):
        raise ForwardRunRefused("raw forward report is not a review-pending PASS")

    transaction = _mapping(
        raw.get("transaction"), label="report.transaction",
        fields={"isolation", "read_only"})
    if transaction != {"isolation": "repeatable read", "read_only": "on"}:
        raise ForwardRunRefused("forward run did not use a read-only snapshot")

    coherence = _mapping(
        raw.get("publication_coherence"), label="publication coherence",
        fields=_COHERENCE_FIELDS)
    version = base["publication_data_version"]
    if (coherence.get("coherent") is not True
            or coherence.get("version") != version
            or any(coherence.get(field) != 0 for field in (
                "unpublished_rows", "unpublished_bars", "unpublished_actions",
                "unpublished_spy", "unpublished_universe",
                "unpublished_repairs", "unpublished_anomalies"))
            or coherence.get("unpublished_runs") != []
            or coherence.get("enumeration") != "exhaustive"):
        raise ForwardRunRefused("publication coherence is incomplete")

    corpus = _mapping(
        raw.get("corpus_identity"), label="corpus identity",
        fields=_CORPUS_FIELDS)
    publication = _mapping(
        corpus.get("publication"), label="corpus publication",
        fields={"version", "previous_version", "run_id", "window", "evidence"})
    if (corpus.get("data_version") != version
            or publication.get("version") != version
            or corpus.get("corpus_hash") != base["certification_corpus_sha256"]
            or corpus.get("window") != {"start": CHAIN_START,
                                        "end": REFERENCE_END}
            or corpus.get("first_session") != CHAIN_START
            or corpus.get("last_session") != REFERENCE_END
            or corpus.get("sessions") != CHAIN_SESSIONS
            or corpus.get("postgres_certified") is not True):
        raise ForwardRunRefused("forward corpus differs from finalized certification")

    reference = _mapping(raw.get("reference"), label="reference identity", fields={
        "artifact", "sha256", "expected_sha256", "checksum_verified",
        "checksum_manifest", "checksum_manifest_sha256", "columns", "sessions",
        "first_session", "last_session",
    })
    reference_sha = _sha(reference.get("sha256"), label="reference.sha256")
    if (reference_sha != FROZEN_REFERENCE_SHA256
            or reference.get("expected_sha256") != reference_sha
            or reference.get("checksum_verified") is not True
            or reference.get("checksum_manifest_sha256")
            != _sha256(DEFAULT_REFERENCE_SUMS.read_bytes())
            or reference_sha != _sha256(DEFAULT_REFERENCE.read_bytes())
            or reference.get("columns") != REFERENCE_FIELDS
            or reference.get("sessions") != REFERENCE_SESSIONS
            or reference.get("first_session") != REFERENCE_START
            or reference.get("last_session") != REFERENCE_END):
        raise ForwardRunRefused("reference identity is not the frozen full tape")

    source = _mapping(
        raw.get("source_identity"), label="source identity", fields=_SOURCE_FIELDS)
    environment = _mapping(source.get("environment"), label="runtime environment")
    environment_sha = _canonical_sha256(environment)
    runtime_identity_sha = _runtime_identity_sha256(environment)
    if (source.get("environment_identity_sha256") != environment_sha
            or runtime_identity_sha != base["identity_hash"]
            or environment.get("certified") is not True
            or environment.get("pins_match") is not True
            or environment.get("sources_known") is not True
            or environment.get("lock_present") is not True
            or environment.get("pin_drift") != {}
            or (environment.get("sentinel_source") or {}).get("hash")
            != base["sentinel_source_sha256"]
            or (environment.get("wealth_core_source") or {}).get("hash")
            != base["wealth_core_source_sha256"]):
        raise ForwardRunRefused("forward runtime environment differs from manifest")
    expected_runner = _sha256(runner_path.read_bytes())
    expected_production = _sha256(DEFAULT_PRODUCTION.read_bytes())
    expected_controller = _sha256(DEFAULT_RULE.read_bytes())
    if (source.get("runner_sha256") != expected_runner
            or source.get("production_module_sha256") != expected_production
            or source.get("controller_rule_sha256") != expected_controller
            or source.get("reference_sha256") != reference_sha):
        raise ForwardRunRefused("forward runner/production source identity differs")
    strategy = _mapping(source.get("strategy_identity"), label="strategy identity")
    if not strategy:
        raise ForwardRunRefused("strategy identity is empty")

    alignment = _mapping(raw.get("alignment"), label="alignment", fields={
        "reference_allocation", "production_target_core_exposure",
        "reference_parent_allocation", "full_pass_allocation_coverage",
    })
    coverage = _mapping(
        alignment.get("full_pass_allocation_coverage"), label="alignment coverage")
    if coverage != {
        "effective_allocations": REFERENCE_SESSIONS,
        "effective_decision_window": ["2006-07-28", "2026-07-30"],
        "close_decisions_compared_to_next_row": REFERENCE_SESSIONS - 1,
        "close_decision_window": [REFERENCE_START, "2026-07-30"],
        "uncompared_close_decision": REFERENCE_END,
    }:
        raise ForwardRunRefused("forward alignment coverage is incomplete")

    comparison = _mapping(
        raw.get("comparison"), label="comparison", fields=_COMPARISON_FIELDS)
    final_boundary = _mapping(
        comparison.get("final_close_decision_boundary"),
        label="final close decision boundary", fields={
            "production_session", "production_field", "actual",
            "reference_session", "status", "excluded_from_verdict"})
    if (comparison.get("differential_verdict") != "PASS"
            or comparison.get("chain_sessions_warmed") != WARM_SESSIONS
            or comparison.get("chain_sessions_advanced") != ADVANCED_SESSIONS
            or comparison.get("reference_sessions_compared")
            != REFERENCE_SESSIONS
            or comparison.get("expected_reference_sessions")
            != REFERENCE_SESSIONS
            or comparison.get("field_comparisons") != FIELD_COMPARISONS
            or comparison.get("expected_full_pass_field_comparisons")
            != FIELD_COMPARISONS
            or comparison.get("reference_only_fields")
            != ["nav", "open_shadow_equity"]
            or comparison.get("first_divergence") is not None
            or final_boundary.get("production_session") != REFERENCE_END
            or final_boundary.get("production_field") != "target_core_exposure"
            or final_boundary.get("reference_session") is not None
            or final_boundary.get("status")
            != "NOT_COMPARABLE_NO_NEXT_REFERENCE_SESSION"
            or final_boundary.get("excluded_from_verdict") is not True):
        raise ForwardRunRefused("forward differential completion is incomplete")
    state_fingerprint = _sha(
        comparison.get("final_state_fingerprint"),
        label="final_state_fingerprint")

    return {
        "schema": REPORT_SCHEMA,
        "raw_sha256": raw_sha256,
        "authority_effect": "NONE",
        "runtime_authority_changed": False,
        "manual_review_required": True,
        "differential_verdict": "PASS",
        "transaction": dict(transaction),
        "publication_coherence_sha256": _canonical_sha256(coherence),
        "corpus_identity_sha256": _canonical_sha256(corpus),
        "source_identity_sha256": _canonical_sha256(source),
        "reference_sha256": reference_sha,
        "controller_rule_sha256": source["controller_rule_sha256"],
        "environment_identity_sha256": environment_sha,
        "runtime_identity_sha256": runtime_identity_sha,
        "strategy_identity_sha256": _canonical_sha256(strategy),
        "production_module_sha256": source["production_module_sha256"],
        "runner_sha256": expected_runner,
        "chain_sessions_warmed": WARM_SESSIONS,
        "chain_sessions_advanced": ADVANCED_SESSIONS,
        "reference_sessions_compared": REFERENCE_SESSIONS,
        "expected_reference_sessions": REFERENCE_SESSIONS,
        "field_comparisons": FIELD_COMPARISONS,
        "expected_full_pass_field_comparisons": FIELD_COMPARISONS,
        "first_divergence": None,
        "final_state_fingerprint": state_fingerprint,
    }


def _validate_command(command: object, base: Mapping[str, Any]) -> list[str]:
    if (not isinstance(command, list)
            or any(not isinstance(part, str) or not part for part in command)):
        raise ForwardRunRefused("command argv is malformed")
    expected_prefix = [
        "docker", "run", "--rm", "--network",
    ]
    expected_tail = [
        "--entrypoint", "python", "-e", "SENTINEL_DATABASE_URL",
        "-m", "tools.sentinel_forward_chain", "--quiet",
    ]
    if (len(command) != 13 or command[:4] != expected_prefix
            or command[5:9] != expected_tail[:4]
            or command[10:] != expected_tail[4:]
            or _NETWORK.fullmatch(command[4]) is None
            or "@" not in command[9]
            or command[9].rsplit("@", 1)[1] != base["test_image_digest"]):
        raise ForwardRunRefused("command is not the canonical forward-run argv")
    return command


def build_record(*, manifest_path: Path, command: Sequence[str], stdout: bytes,
                 stderr: bytes, exit_code: int,
                 producer_path: Path | None = None,
                 runner_path: Path | None = None) -> dict[str, Any]:
    """Build deterministic evidence from one in-memory invocation result.

    This API exists for falsifiers and integration fixtures.  The production
    CLI obtains these bytes only from its own ``subprocess.run`` call.
    """
    producer_path = Path(producer_path or __file__).resolve()
    runner_path = Path(runner_path or DEFAULT_RUNNER).resolve()
    base, _ = manifest_binding(Path(manifest_path))
    argv = _validate_command(list(command), base)
    if type(exit_code) is not int or exit_code != 0:
        raise ForwardRunRefused("production forward runner did not exit zero")
    if stderr != b"":
        raise ForwardRunRefused("production forward runner emitted stderr")
    if not stdout:
        raise ForwardRunRefused("production forward runner emitted no report")
    raw = _json_object(stdout, label="forward-run stdout")
    stdout_sha = _sha256(stdout)
    report = _report_binding(
        raw, raw_sha256=stdout_sha, base=base, runner_path=runner_path)
    record = {
        "schema": SCHEMA,
        "status": "PASS",
        "producer_sha256": _sha256(producer_path.read_bytes()),
        "runner_sha256": _sha256(runner_path.read_bytes()),
        "base_manifest": base,
        "command": {"argv": argv, "sha256": _canonical_sha256(argv)},
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        "stdout_sha256": stdout_sha,
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stderr_sha256": _sha256(stderr),
        "exit_code": exit_code,
        "report": report,
    }
    validate_record(
        record, producer_path=producer_path, runner_path=runner_path)
    return record


def validate_record(record: Mapping[str, Any], *,
                    producer_path: Path | None = None,
                    runner_path: Path | None = None) -> Mapping[str, Any]:
    """Strictly validate one record and return its decoded raw report."""
    producer_path = Path(producer_path or __file__).resolve()
    runner_path = Path(runner_path or DEFAULT_RUNNER).resolve()
    record = _mapping(record, label="formal forward run", fields=_TOP_FIELDS)
    if record.get("schema") != SCHEMA or record.get("status") != "PASS":
        raise ForwardRunRefused("formal forward run schema/status is not PASS")
    if record.get("producer_sha256") != _sha256(producer_path.read_bytes()):
        raise ForwardRunRefused("formal forward producer source differs")
    expected_runner = _sha256(runner_path.read_bytes())
    if record.get("runner_sha256") != expected_runner:
        raise ForwardRunRefused("formal production runner source differs")
    base = _validate_base_binding(record.get("base_manifest"))
    command = _mapping(
        record.get("command"), label="command", fields={"argv", "sha256"})
    argv = _validate_command(command.get("argv"), base)
    if command.get("sha256") != _canonical_sha256(argv):
        raise ForwardRunRefused("formal forward command digest differs")
    stdout = _decode_base64(record.get("stdout_base64"), label="stdout_base64")
    stderr = _decode_base64(record.get("stderr_base64"), label="stderr_base64")
    if (record.get("stdout_sha256") != _sha256(stdout)
            or record.get("stderr_sha256") != _sha256(stderr)
            or stderr != b"" or record.get("exit_code") != 0):
        raise ForwardRunRefused("formal forward invocation bytes/status differ")
    raw = _json_object(stdout, label="formal forward stdout")
    expected_report = _report_binding(
        raw, raw_sha256=_sha256(stdout), base=base, runner_path=runner_path)
    report = _mapping(record.get("report"), label="report", fields=_REPORT_FIELDS)
    if report != expected_report:
        raise ForwardRunRefused("formal forward report summary is not re-derived")
    return raw


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink_retry(path: Path) -> None:
    last: OSError | None = None
    for _ in range(4):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last = exc
    assert last is not None
    raise last


def _rollback(path: Path, original: BaseException) -> None:
    try:
        _unlink_retry(path)
    except OSError as cleanup:
        quarantine = path.with_name(f".{path.name}.rollback.{os.getpid()}")
        try:
            os.replace(path, quarantine)
            _unlink_retry(quarantine)
        except OSError as rename_error:
            if hasattr(original, "add_note"):
                original.add_note(
                    f"publication rollback failed: {cleanup!r}; "
                    f"quarantine failed: {rename_error!r}")
    try:
        _fsync_directory(path.parent)
    except BaseException as exc:  # noqa: BLE001 - preserve original failure
        if hasattr(original, "add_note"):
            original.add_note(f"rollback directory fsync failed: {exc!r}")


def write_record_atomic(record: Mapping[str, Any], output: Path) -> None:
    """Publish canonical bytes with same-volume no-clobber and rollback."""
    validate_record(record)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp")
    temporary = Path(name)
    published = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_bytes(record))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
        published = True
        _fsync_directory(output.parent)
        _unlink_retry(temporary)
        _fsync_directory(output.parent)
    except BaseException as exc:
        if published:
            _rollback(output, exc)
        raise
    finally:
        try:
            _unlink_retry(temporary)
        except OSError:
            pass


def run_formal(*, manifest_path: Path, output: Path, network: str,
               invoke: Callable[..., subprocess.CompletedProcess] = subprocess.run
               ) -> Mapping[str, Any]:
    """Own one actual Docker invocation and publish its formal evidence."""
    if _NETWORK.fullmatch(network) is None:
        raise ForwardRunRefused("Docker network name is malformed")
    if not os.environ.get("SENTINEL_DATABASE_URL", "").strip():
        raise ForwardRunRefused("SENTINEL_DATABASE_URL is unset")
    _, test_ref = manifest_binding(Path(manifest_path))
    command = [
        "docker", "run", "--rm", "--network", network,
        "--entrypoint", "python", "-e", "SENTINEL_DATABASE_URL", test_ref,
        "-m", "tools.sentinel_forward_chain", "--quiet",
    ]
    try:
        completed = invoke(command, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise ForwardRunRefused("Docker could not invoke the forward runner") from exc
    record = build_record(
        manifest_path=Path(manifest_path), command=command,
        stdout=bytes(completed.stdout), stderr=bytes(completed.stderr),
        exit_code=int(completed.returncode))
    write_record_atomic(record, Path(output))
    return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and retain the formal broker-free forward differential")
    operations = parser.add_subparsers(dest="operation", required=True)
    run = operations.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--network", default="sentinel_default")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_formal(
            manifest_path=args.manifest, output=args.output,
            network=args.network)
    except (OSError, ForwardRunRefused) as exc:
        print(f"FORMAL FORWARD RUN REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
