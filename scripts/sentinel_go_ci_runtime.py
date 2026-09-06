#!/usr/bin/env python3
"""Acquire one exact CI-certified Sentinel runtime for production GO.

This module has Docker-image authority only. It does not touch PostgreSQL,
Sharadar, Alpaca, broker state, or deployment verdicts. Normal GO uses it to
replace the expensive local software-certification build/test phase with exact
GitHub CI evidence for the current clean main commit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Optional

import sentinel_ci_certification_verify as verifier
import sentinel_go_lock as go_lock
import sentinel_go_validate as go

BINDING_SCHEMA = "sentinel.nas-go-ci-runtime-binding/1"
BINDING_PATH = (
    go.ROOT / "artifacts" / "sentinel" / "go-validation" /
    "ci-certified-runtime.json"
)
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
_IMMUTABLE_REF = re.compile(
    r"^ghcr\.io/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")


class CIRuntimeRefused(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _boot_hash() -> Optional[str]:
    try:
        value = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return hashlib.sha256(value.encode("ascii")).hexdigest() if value else None


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".ci-runtime-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _inspect(runner: go.CommandRunner, reference: str) -> Mapping[str, Any]:
    completed = runner.run(["docker", "image", "inspect", reference])
    if completed.returncode != 0:
        raise CIRuntimeRefused("certified runtime is not locally inspectable")
    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise CIRuntimeRefused("Docker image inspection is invalid JSON") from exc
    if (not isinstance(payload, list) or len(payload) != 1
            or not isinstance(payload[0], dict)):
        raise CIRuntimeRefused("Docker image inspection is not one exact image")
    return payload[0]


def _ensure_exact_image(runner: go.CommandRunner, *, immutable_ref: str,
                        registry_digest: str, commit: str) -> str:
    if _IMMUTABLE_REF.fullmatch(immutable_ref) is None:
        raise CIRuntimeRefused("CI certificate has no supported immutable GHCR reference")
    if go._IMAGE_DIGEST.fullmatch(registry_digest) is None:
        raise CIRuntimeRefused("CI certificate has no immutable registry digest")
    if not immutable_ref.endswith("@" + registry_digest):
        raise CIRuntimeRefused("CI certificate registry reference/digest disagree")
    try:
        image = _inspect(runner, immutable_ref)
    except CIRuntimeRefused:
        pulled = runner.run(["docker", "pull", immutable_ref])
        if pulled.returncode != 0:
            raise CIRuntimeRefused("exact CI-certified runtime could not be pulled")
        image = _inspect(runner, immutable_ref)

    local_id = str(image.get("Id") or "")
    if go._IMAGE_DIGEST.fullmatch(local_id) is None:
        raise CIRuntimeRefused("pulled runtime has no immutable local image ID")
    repo_digests = image.get("RepoDigests")
    if not isinstance(repo_digests, list) or immutable_ref not in repo_digests:
        raise CIRuntimeRefused("local runtime is not bound to the certified registry digest")
    config = image.get("Config") if isinstance(image.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    revision = str(labels.get("org.opencontainers.image.revision") or "")
    if revision != commit:
        raise CIRuntimeRefused("certified runtime source revision differs from current commit")

    tag = "sentinel-go-runtime:%s" % commit
    tagged = runner.run(["docker", "tag", immutable_ref, tag])
    if tagged.returncode != 0:
        raise CIRuntimeRefused("exact CI-certified runtime could not be tagged locally")
    tagged_id = go._inspect_image_id(runner, tag)
    if tagged_id != local_id:
        raise CIRuntimeRefused("local runtime tag does not resolve to certified bytes")
    return local_id


_IDENTITY_CODE = r'''
import json
from sentinel.identity import rehearsal_identity
from tools import sentinel_forward_chain as chain
record = rehearsal_identity()
print(json.dumps({
    'identity_hash': record.get('identity_hash'),
    'environment_compatible': bool(
        (record.get('environment') or {}).get('compatible')),
    'parity_helper_present': bool(
        getattr(chain, 'REPORT_SCHEMA', None)
        == 'sentinel.production-forward-chain/2'),
    'reference_tape_present': bool(chain.REFERENCE_PATH.is_file()),
    'reference_checksum_present': bool(chain.REFERENCE_CHECKSUMS_PATH.is_file()),
}, sort_keys=True))
'''.strip()


def _runtime_identity(runner: go.CommandRunner, local_id: str) -> str:
    completed = runner.run([
        "docker", "run", "--rm", "--network", "none",
        "--entrypoint", "python", local_id, "-c", _IDENTITY_CODE,
    ])
    if completed.returncode != 0:
        raise CIRuntimeRefused("certified runtime identity probe failed")
    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise CIRuntimeRefused("certified runtime identity probe was malformed") from exc
    identity = str(payload.get("identity_hash") or "") if isinstance(payload, dict) else ""
    if (go._HEX64.fullmatch(identity) is None
            or payload.get("environment_compatible") is not True
            or payload.get("parity_helper_present") is not True
            or payload.get("reference_tape_present") is not True
            or payload.get("reference_checksum_present") is not True):
        raise CIRuntimeRefused(
            "certified runtime lacks compatible identity/parity evidence")
    return identity


def _certified_pass_count(client: verifier.GitHubReadClient, *,
                          result: Mapping[str, Any]) -> int:
    """Read the count only from the exact publication already verified above."""
    try:
        commit = str(result["source_commit"])
        tree = str(result["source_tree"])
        publication = {
            "id": int(result["publication_workflow_run"]),
            "run_attempt": int(result["publication_workflow_attempt"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CIRuntimeRefused("verified CI result has incomplete publication identity") from exc

    artifact = verifier._publication_artifact(client, publication, commit)
    archive = verifier._download_artifact(client, artifact)
    members = verifier._bundle_members(archive)
    verifier._verify_sums(members)
    manifest = verifier._json_bytes(
        members["certification.json"], "CERT_MANIFEST_SCHEMA_UNKNOWN",
        "certification manifest")
    binding = verifier._verify_manifest(manifest, commit, tree, publication)
    ci = binding.get("ci") if isinstance(binding, dict) else None
    if (binding.get("digest") != result.get("image_digest")
            or not isinstance(ci, dict)
            or ci.get("test_workflow_run") != result.get("test_workflow_run")
            or ci.get("test_workflow_attempt") != result.get("test_workflow_attempt")):
        raise CIRuntimeRefused(
            "test-count artifact differs from the verified CI certification")
    tests = manifest.get("tests") if isinstance(manifest, dict) else None
    counts = tests.get("required_counts") if isinstance(tests, dict) else None
    value = counts.get("passed") if isinstance(counts, dict) else None
    if type(value) is not int or value <= 0:
        raise CIRuntimeRefused("verified CI certificate has no positive test count")
    return value


def _write_binding(*, commit: str, result: Mapping[str, Any], local_id: str,
                   source_identity: str, passed_tests: int,
                   token: str, boot_hash: str) -> Mapping[str, Any]:
    evidence = {
        "schema": BINDING_SCHEMA,
        "git_commit": commit,
        "certified_image": str(result["certified_image"]),
        "registry_digest": str(result["image_digest"]),
        "local_image_id": local_id,
        "source_identity_sha256": source_identity,
        "certified_test_passes": int(passed_tests),
        "test_workflow_run": int(result["test_workflow_run"]),
        "publication_workflow_run": int(result["publication_workflow_run"]),
        "run_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
        "host_boot_id_sha256": boot_hash,
        "verified_at": _utc_now(),
    }
    payload = dict(evidence)
    payload["evidence_sha256"] = _sha(evidence)
    _atomic_json(BINDING_PATH, payload)
    return payload


def certify_from_ci(runner: go.CommandRunner, *, git: go.GitIdentity,
                    now_text: str, run_suite: bool):
    if not run_suite:
        summary = go.TestSummary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.NOT_PROVEN, now_text,
            {"reason": "CI_CERTIFICATION_NOT_REQUESTED"})
    if not (git.commit and git.branch_is_main and git.clean and git.matches_origin_main):
        summary = go.TestSummary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.NOT_PROVEN, now_text,
            {"reason": "GIT_IDENTITY_NOT_PASS_NO_CI_CERTIFICATION"})

    token = go_lock.current_run_token()
    boot_hash = _boot_hash()
    if token is None or boot_hash is None:
        summary = go.TestSummary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.NOT_PROVEN, now_text,
            {"reason": "CURRENT_LIFECYCLE_IDENTITY_UNAVAILABLE"})

    client = verifier.GitHubReadClient(
        token=os.environ.get("SENTINEL_GITHUB_READ_TOKEN")
        or os.environ.get("GITHUB_TOKEN"))
    try:
        result = verifier.verify_current(
            root=go.ROOT, commit=git.commit, client=client)
        passed_tests = _certified_pass_count(client, result=result)
        immutable_ref = str(result.get("certified_image") or "")
        registry_digest = str(result.get("image_digest") or "")
        local_id = _ensure_exact_image(
            runner, immutable_ref=immutable_ref,
            registry_digest=registry_digest, commit=git.commit)
        source_identity = _runtime_identity(runner, local_id)
        _write_binding(
            commit=git.commit, result=result, local_id=local_id,
            source_identity=source_identity, passed_tests=passed_tests,
            token=token, boot_hash=boot_hash)
    except verifier.CertificationVerificationRefused as exc:
        summary = go.TestSummary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.FAIL, now_text,
            {"reason": exc.code})
    except (CIRuntimeRefused, KeyError, TypeError, ValueError):
        summary = go.TestSummary(None, None, None)
        return summary, go.make_gate(
            "certified_suite_no_skips", go.FAIL, now_text,
            {"reason": "CI_CERTIFIED_RUNTIME_BINDING_FAILED"})

    summary = go.TestSummary(
        candidate_image_digest=local_id,
        runtime_image_digest=local_id,
        source_identity_sha256=source_identity,
        passed=passed_tests,
        failed=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        exit_code=0,
        suites_completed=3,
        auxiliary_image_digests=(),
        non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS,
    )
    return summary, go.make_gate(
        "certified_suite_no_skips", go.PASS, now_text,
        {"ci_software_certification_verified": True,
         "git_commit": git.commit,
         "certified_test_passes": passed_tests,
         "registry_digest_sha256": hashlib.sha256(
             registry_digest.encode("ascii")).hexdigest(),
         "local_image_id_sha256": hashlib.sha256(
             local_id.encode("ascii")).hexdigest()})


def load_binding(*, commit: str, runner: Optional[go.CommandRunner] = None,
                 require_current_run: bool = True) -> Mapping[str, Any]:
    try:
        payload = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise CIRuntimeRefused("CI-certified runtime binding is unavailable") from exc
    expected = {
        "schema", "git_commit", "certified_image", "registry_digest",
        "local_image_id", "source_identity_sha256", "certified_test_passes",
        "test_workflow_run", "publication_workflow_run", "run_token_sha256",
        "host_boot_id_sha256", "verified_at", "evidence_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise CIRuntimeRefused("CI-certified runtime binding schema is invalid")
    supplied = str(payload.get("evidence_sha256") or "")
    evidence = {key: value for key, value in payload.items()
                if key != "evidence_sha256"}
    if supplied != _sha(evidence) or payload.get("schema") != BINDING_SCHEMA:
        raise CIRuntimeRefused("CI-certified runtime binding integrity is invalid")
    if payload.get("git_commit") != commit:
        raise CIRuntimeRefused("CI-certified runtime binding is for another commit")
    boot_hash = _boot_hash()
    if boot_hash is None or payload.get("host_boot_id_sha256") != boot_hash:
        raise CIRuntimeRefused("CI-certified runtime binding is from another host boot")
    if require_current_run:
        token = go_lock.current_run_token()
        if token is None or payload.get("run_token_sha256") != hashlib.sha256(
                token.encode("ascii")).hexdigest():
            raise CIRuntimeRefused("CI-certified runtime binding is from another GO invocation")
    immutable_ref = str(payload.get("certified_image") or "")
    registry_digest = str(payload.get("registry_digest") or "")
    local_id = str(payload.get("local_image_id") or "")
    if (_IMMUTABLE_REF.fullmatch(immutable_ref) is None
            or go._IMAGE_DIGEST.fullmatch(registry_digest) is None
            or go._IMAGE_DIGEST.fullmatch(local_id) is None
            or not immutable_ref.endswith("@" + registry_digest)
            or go._HEX64.fullmatch(str(payload.get("source_identity_sha256") or "")) is None
            or not isinstance(payload.get("certified_test_passes"), int)
            or payload["certified_test_passes"] <= 0):
        raise CIRuntimeRefused("CI-certified runtime binding fields are malformed")
    if runner is not None:
        image = _inspect(runner, immutable_ref)
        if str(image.get("Id") or "") != local_id:
            raise CIRuntimeRefused("local CI-certified runtime bytes changed")
        repo_digests = image.get("RepoDigests")
        if not isinstance(repo_digests, list) or immutable_ref not in repo_digests:
            raise CIRuntimeRefused("local runtime lost its certified registry binding")
    return payload
