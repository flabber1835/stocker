#!/usr/bin/env python3
"""Build and validate reusable Sentinel CI software-certification evidence.

The safety workflow creates a source-side input only after the complete exact-head
software suite succeeds. The protected publication workflow combines that input
with GitHub job conclusions and the immutable registry digest. The resulting
manifest is canonical JSON with a self-authenticating SHA-256 over every field
except ``manifest_sha256``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

INPUT_SCHEMA = "sentinel.software-certification-input/1"
MANIFEST_SCHEMA = "sentinel.software-certification/1"
REPOSITORY = "flabber1835/stocker"
TEST_WORKFLOW_PATH = ".github/workflows/sentinel-safety.yml"
REQUIRED_JOBS = (
    "host-python-38-exact-head",
    "sentinel-exact-head",
)
RUNTIME_SCHEMA_EPOCH = "sentinel.behavioral_schema/current"
SEMANTIC_EPOCH = "sentinel.automation_cycle/1"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PYTEST_COUNT = re.compile(
    r"(?P<count>[0-9]+) (?P<kind>passed|failed|skipped|xfailed|xpassed|errors?)"
)
_COUNT_KEYS = ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")


class CertificationManifestRefused(ValueError):
    """Evidence is incomplete, malformed, or cannot support certification."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    def no_duplicates(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CertificationManifestRefused(
                    "%s contains duplicate key %r" % (label, key)
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CertificationManifestRefused("%s is not valid UTF-8 JSON" % label) from exc
    if not isinstance(value, dict):
        raise CertificationManifestRefused("%s is not a JSON object" % label)
    return value


def _require_hex(value: object, *, label: str, git: bool = False) -> str:
    pattern = _HEX40 if git else _HEX64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise CertificationManifestRefused("%s is not a canonical digest" % label)
    return value


def _require_image_digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CertificationManifestRefused("%s is not an immutable sha256 digest" % label)
    return value


def _run(argv: Sequence[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        [str(item) for item in argv],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise CertificationManifestRefused("command failed: %s" % " ".join(argv))
    return (completed.stdout or "").strip()


def _summary_counts(path: Path) -> dict[str, int]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise CertificationManifestRefused("test summary is unreadable") from exc
    for line in reversed(lines):
        matches = list(_PYTEST_COUNT.finditer(line))
        if not matches or not any(match.group("kind") == "passed" for match in matches):
            continue
        result = {key: 0 for key in _COUNT_KEYS}
        for match in matches:
            kind = match.group("kind")
            if kind == "error":
                kind = "errors"
            result[kind] += int(match.group("count"))
        if result["passed"] <= 0:
            continue
        return result
    raise CertificationManifestRefused("test summary has no pytest result line")


def collect_test_counts(suites: Mapping[str, Path]) -> dict[str, Any]:
    if set(suites) != {"sentinel", "operator_scripts", "wealth_core_boundary"}:
        raise CertificationManifestRefused("test suite set is not the certification contract")
    suite_counts = {name: _summary_counts(path) for name, path in sorted(suites.items())}
    totals = {key: sum(row[key] for row in suite_counts.values()) for key in _COUNT_KEYS}
    if totals["passed"] <= 0 or any(totals[key] for key in _COUNT_KEYS if key != "passed"):
        raise CertificationManifestRefused("software suite contains a non-pass result")
    return {
        "suites_completed": len(suite_counts),
        "suite_counts": suite_counts,
        "total": totals,
    }


def _test_manifest_hash(root: Path) -> str:
    listed = _run(["git", "ls-files", "-z", "tests"], cwd=root).encode("utf-8")
    names = [item for item in listed.decode("utf-8").split("\x00") if item]
    if not names:
        raise CertificationManifestRefused("tracked test manifest is empty")
    digest = hashlib.sha256()
    for name in sorted(names):
        path = root / name
        file_hash = sha256_file(path)
        digest.update(("%s  %s\n" % (file_hash, name)).encode("utf-8"))
    return digest.hexdigest()


def _dependency_hashes(root: Path) -> dict[str, str]:
    lock_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.lock")
        if ".git" not in path.parts
    )
    required = {"sentinel/requirements.lock", "tests/requirements.lock"}
    if not required.issubset(set(lock_paths)):
        raise CertificationManifestRefused("required dependency locks are missing")
    return {name: sha256_file(root / name) for name in lock_paths}


def _docker_image_identity(root: Path, reference: str) -> tuple[str, str]:
    raw = _run(["docker", "image", "inspect", reference], cwd=root)
    try:
        payload = json.loads(raw)
        image = payload[0]
        image_id = str(image["Id"])
        revision = str((image.get("Config") or {}).get("Labels", {}).get(
            "org.opencontainers.image.revision", ""))
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CertificationManifestRefused("Docker image identity is malformed") from exc
    _require_image_digest(image_id, label="authorized image id")
    _require_hex(revision, label="authorized image source revision", git=True)
    return image_id, revision


def build_input(
    *,
    root: Path,
    commit: str,
    workflow_run: int,
    workflow_attempt: int,
    image_ref: str,
    suites: Mapping[str, Path],
    adversarial_report: Path,
    mutation_report: Path,
) -> dict[str, Any]:
    commit = _require_hex(commit, label="source commit", git=True)
    if workflow_run <= 0 or workflow_attempt <= 0:
        raise CertificationManifestRefused("workflow identity is invalid")
    head = _run(["git", "rev-parse", "HEAD"], cwd=root)
    if head != commit:
        raise CertificationManifestRefused("checked-out HEAD differs from source commit")
    tree = _run(["git", "rev-parse", "HEAD^{tree}"], cwd=root)
    _require_hex(tree, label="source tree")
    image_id, revision = _docker_image_identity(root, image_ref)
    if revision != commit:
        raise CertificationManifestRefused("authorized image revision differs from source commit")
    capability = root / "deploy" / "sentinel-authorized-runtime-v1"
    if not capability.is_file():
        raise CertificationManifestRefused("authorized runtime capability marker is missing")
    counts = collect_test_counts(suites)
    evidence = {
        "schema": INPUT_SCHEMA,
        "repository": REPOSITORY,
        "source_commit": commit,
        "source_tree": tree,
        "test_workflow_path": TEST_WORKFLOW_PATH,
        "test_workflow_run": workflow_run,
        "test_workflow_attempt": workflow_attempt,
        "authorized_image_id": image_id,
        "authorized_runtime_capability_sha256": sha256_file(capability),
        "dependency_lock_hashes": _dependency_hashes(root),
        "test_manifest_sha256": _test_manifest_hash(root),
        "test_counts": counts,
        "adversarial_evidence": {
            "status": "PASS",
            "sha256": sha256_file(adversarial_report),
        },
        "mutation_evidence": {
            "status": "PASS",
            "sha256": sha256_file(mutation_report),
        },
        "runtime_schema_epoch": RUNTIME_SCHEMA_EPOCH,
        "semantic_epoch": SEMANTIC_EPOCH,
    }
    return evidence


def _required_job_conclusions(jobs_payload: Mapping[str, Any]) -> dict[str, str]:
    rows = jobs_payload.get("jobs")
    if not isinstance(rows, list):
        raise CertificationManifestRefused("GitHub jobs response has no jobs array")
    found: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if name not in REQUIRED_JOBS:
            continue
        if name in found:
            raise CertificationManifestRefused("required CI job is duplicated: %s" % name)
        found[str(name)] = str(row.get("conclusion") or "")
    if set(found) != set(REQUIRED_JOBS):
        missing = sorted(set(REQUIRED_JOBS) - set(found))
        raise CertificationManifestRefused(
            "required CI jobs are missing: %s" % ", ".join(missing)
        )
    if any(value != "success" for value in found.values()):
        raise CertificationManifestRefused("a required CI job did not succeed")
    return {name: found[name] for name in REQUIRED_JOBS}


def _validate_input(value: Mapping[str, Any]) -> None:
    exact_fields = {
        "schema", "repository", "source_commit", "source_tree",
        "test_workflow_path", "test_workflow_run", "test_workflow_attempt",
        "authorized_image_id", "authorized_runtime_capability_sha256",
        "dependency_lock_hashes", "test_manifest_sha256", "test_counts",
        "adversarial_evidence", "mutation_evidence", "runtime_schema_epoch",
        "semantic_epoch",
    }
    if set(value) != exact_fields or value.get("schema") != INPUT_SCHEMA:
        raise CertificationManifestRefused("software certification input schema is invalid")
    if value.get("repository") != REPOSITORY or value.get("test_workflow_path") != TEST_WORKFLOW_PATH:
        raise CertificationManifestRefused("software certification input authority is invalid")
    _require_hex(value.get("source_commit"), label="source commit", git=True)
    _require_hex(value.get("source_tree"), label="source tree")
    _require_image_digest(value.get("authorized_image_id"), label="authorized image id")
    _require_hex(value.get("authorized_runtime_capability_sha256"), label="capability hash")
    _require_hex(value.get("test_manifest_sha256"), label="test manifest hash")
    locks = value.get("dependency_lock_hashes")
    if not isinstance(locks, dict) or not locks:
        raise CertificationManifestRefused("dependency lock hashes are missing")
    for name, digest in locks.items():
        if not isinstance(name, str) or not name.endswith(".lock"):
            raise CertificationManifestRefused("dependency lock name is invalid")
        _require_hex(digest, label="dependency lock hash")
    counts = value.get("test_counts")
    if not isinstance(counts, dict) or counts.get("suites_completed") != 3:
        raise CertificationManifestRefused("required software test count is invalid")
    total = counts.get("total")
    if not isinstance(total, dict) or set(total) != set(_COUNT_KEYS):
        raise CertificationManifestRefused("software test totals are invalid")
    if total.get("passed", 0) <= 0 or any(total.get(key) for key in _COUNT_KEYS if key != "passed"):
        raise CertificationManifestRefused("software test totals contain non-passes")
    for name in ("adversarial_evidence", "mutation_evidence"):
        row = value.get(name)
        if not isinstance(row, dict) or row.get("status") != "PASS":
            raise CertificationManifestRefused("%s status is not PASS" % name)
        _require_hex(row.get("sha256"), label=name + " hash")
    if value.get("runtime_schema_epoch") != RUNTIME_SCHEMA_EPOCH:
        raise CertificationManifestRefused("runtime schema epoch is unsupported")
    if value.get("semantic_epoch") != SEMANTIC_EPOCH:
        raise CertificationManifestRefused("semantic epoch is unsupported")


def finalize_manifest(
    *,
    input_evidence: Mapping[str, Any],
    jobs_payload: Mapping[str, Any],
    subject_name: str,
    image_digest: str,
    publication_run: int,
    publication_attempt: int,
    certified_at: str,
) -> dict[str, Any]:
    _validate_input(input_evidence)
    image_digest = _require_image_digest(image_digest, label="registry image digest")
    if not subject_name.startswith("ghcr.io/") or "@" in subject_name or ":" in subject_name.split("/", 1)[-1]:
        raise CertificationManifestRefused("registry subject name is invalid")
    if publication_run <= 0 or publication_attempt <= 0:
        raise CertificationManifestRefused("publication workflow identity is invalid")
    try:
        parsed_time = datetime.fromisoformat(certified_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CertificationManifestRefused("certification timestamp is invalid") from exc
    if parsed_time.tzinfo is None:
        raise CertificationManifestRefused("certification timestamp has no timezone")
    jobs = _required_job_conclusions(jobs_payload)
    immutable_ref = "%s@%s" % (subject_name, image_digest)
    counts = input_evidence["test_counts"]
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "certification_version": 1,
        "source": {
            "repository": input_evidence["repository"],
            "commit": input_evidence["source_commit"],
            "tree": input_evidence["source_tree"],
        },
        "runtime": {
            "subject_name": subject_name,
            "docker_image_digest": image_digest,
            "authorized_runtime_digest": image_digest,
            "immutable_ref": immutable_ref,
            "ci_local_image_id": input_evidence["authorized_image_id"],
            "authorized_runtime_capability_sha256": input_evidence[
                "authorized_runtime_capability_sha256"
            ],
        },
        "dependencies": {
            "lock_hashes": input_evidence["dependency_lock_hashes"],
        },
        "tests": {
            "manifest_sha256": input_evidence["test_manifest_sha256"],
            "required_counts": {
                "passed": counts["total"]["passed"],
                "suites_completed": counts["suites_completed"],
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "xfailed": 0,
                "xpassed": 0,
            },
            "suite_counts": counts["suite_counts"],
            "required_job_conclusions": jobs,
            "adversarial_evidence": input_evidence["adversarial_evidence"],
            "mutation_evidence": input_evidence["mutation_evidence"],
        },
        "ci": {
            "test_workflow_path": input_evidence["test_workflow_path"],
            "test_workflow_run": input_evidence["test_workflow_run"],
            "test_workflow_attempt": input_evidence["test_workflow_attempt"],
            "publication_workflow_run": publication_run,
            "publication_workflow_attempt": publication_attempt,
        },
        "epochs": {
            "runtime_schema": input_evidence["runtime_schema_epoch"],
            "semantic": input_evidence["semantic_epoch"],
        },
        "certified_at": parsed_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    manifest["manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
    return manifest


def verify_manifest(value: Mapping[str, Any]) -> None:
    if value.get("schema") != MANIFEST_SCHEMA:
        raise CertificationManifestRefused("certification manifest schema is unsupported")
    supplied = value.get("manifest_sha256")
    _require_hex(supplied, label="certification manifest hash")
    unsigned = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if supplied != sha256_bytes(canonical_bytes(unsigned)):
        raise CertificationManifestRefused("certification manifest integrity check failed")
    source = value.get("source")
    runtime = value.get("runtime")
    if not isinstance(source, dict) or not isinstance(runtime, dict):
        raise CertificationManifestRefused("certification source/runtime binding is missing")
    commit = _require_hex(source.get("commit"), label="manifest source commit", git=True)
    _require_hex(source.get("tree"), label="manifest source tree")
    digest = _require_image_digest(runtime.get("docker_image_digest"), label="manifest image digest")
    if runtime.get("authorized_runtime_digest") != digest:
        raise CertificationManifestRefused("authorized runtime digest differs from image digest")
    if runtime.get("immutable_ref") != "%s@%s" % (runtime.get("subject_name"), digest):
        raise CertificationManifestRefused("immutable runtime reference is inconsistent")
    ci = value.get("ci")
    if not isinstance(ci, dict) or ci.get("test_workflow_path") != TEST_WORKFLOW_PATH:
        raise CertificationManifestRefused("certification workflow binding is invalid")
    tests = value.get("tests")
    if not isinstance(tests, dict):
        raise CertificationManifestRefused("certification test evidence is missing")
    jobs = tests.get("required_job_conclusions")
    if jobs != {name: "success" for name in REQUIRED_JOBS}:
        raise CertificationManifestRefused("required CI job conclusions are invalid")
    required_counts = tests.get("required_counts")
    if not isinstance(required_counts, dict) or required_counts.get("passed", 0) <= 0:
        raise CertificationManifestRefused("required test counts are invalid")
    if any(required_counts.get(key) for key in ("failed", "errors", "skipped", "xfailed", "xpassed")):
        raise CertificationManifestRefused("required test counts contain non-passes")
    if source.get("repository") != REPOSITORY or not commit:
        raise CertificationManifestRefused("manifest repository authority is invalid")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(canonical_bytes(value) + b"\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("build-input")
    create.add_argument("--root", type=Path, default=Path("."))
    create.add_argument("--commit", required=True)
    create.add_argument("--workflow-run", required=True, type=int)
    create.add_argument("--workflow-attempt", required=True, type=int)
    create.add_argument("--image-ref", required=True)
    create.add_argument("--sentinel-summary", type=Path, required=True)
    create.add_argument("--operator-summary", type=Path, required=True)
    create.add_argument("--wealth-summary", type=Path, required=True)
    create.add_argument("--adversarial-report", type=Path, required=True)
    create.add_argument("--mutation-report", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)

    final = sub.add_parser("finalize")
    final.add_argument("--input", type=Path, required=True)
    final.add_argument("--jobs", type=Path, required=True)
    final.add_argument("--subject-name", required=True)
    final.add_argument("--image-digest", required=True)
    final.add_argument("--publication-run", required=True, type=int)
    final.add_argument("--publication-attempt", required=True, type=int)
    final.add_argument("--certified-at", required=True)
    final.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "build-input":
            value = build_input(
                root=args.root.resolve(),
                commit=args.commit,
                workflow_run=args.workflow_run,
                workflow_attempt=args.workflow_attempt,
                image_ref=args.image_ref,
                suites={
                    "sentinel": args.sentinel_summary,
                    "operator_scripts": args.operator_summary,
                    "wealth_core_boundary": args.wealth_summary,
                },
                adversarial_report=args.adversarial_report,
                mutation_report=args.mutation_report,
            )
            _write_json(args.output, value)
        elif args.command == "finalize":
            value = finalize_manifest(
                input_evidence=_read_json(args.input, label="software certification input"),
                jobs_payload=_read_json(args.jobs, label="GitHub jobs response"),
                subject_name=args.subject_name,
                image_digest=args.image_digest,
                publication_run=args.publication_run,
                publication_attempt=args.publication_attempt,
                certified_at=args.certified_at,
            )
            verify_manifest(value)
            _write_json(args.output, value)
        else:
            verify_manifest(_read_json(args.path, label="software certification manifest"))
    except CertificationManifestRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
