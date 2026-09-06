#!/usr/bin/env python3
"""Build and validate reusable Sentinel CI software-certification evidence."""
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
REQUIRED_JOBS = ("host-python-38-exact-head", "sentinel-exact-head")
RUNTIME_SUBJECT = "ghcr.io/flabber1835/stocker/sentinel"
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
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
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
                    "%s contains duplicate key %r" % (label, key))
            result[key] = value
        return result
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CertificationManifestRefused(
            "%s is not valid UTF-8 JSON" % label) from exc
    if not isinstance(value, dict):
        raise CertificationManifestRefused("%s is not a JSON object" % label)
    return value


def _require_hex64(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise CertificationManifestRefused("%s is not a canonical sha256" % label)
    return value


def _require_git_object(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise CertificationManifestRefused("%s is not a canonical Git object id" % label)
    return value


def _require_image_digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CertificationManifestRefused(
            "%s is not an immutable sha256 digest" % label)
    return value


def _run(argv: Sequence[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        [str(item) for item in argv], cwd=str(cwd), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise CertificationManifestRefused(
            "command failed: %s" % " ".join(argv))
    return completed.stdout or ""


def _summary_counts(path: Path) -> dict[str, int]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise CertificationManifestRefused("test summary is unreadable") from exc
    for line in reversed(lines):
        matches = list(_PYTEST_COUNT.finditer(line))
        if not matches or not any(m.group("kind") == "passed" for m in matches):
            continue
        result = {key: 0 for key in _COUNT_KEYS}
        for match in matches:
            kind = match.group("kind")
            if kind == "error":
                kind = "errors"
            result[kind] += int(match.group("count"))
        if result["passed"] > 0:
            return result
    raise CertificationManifestRefused("test summary has no pytest result line")


def collect_test_counts(suites: Mapping[str, Path]) -> dict[str, Any]:
    required = {"sentinel", "operator_scripts", "wealth_core_boundary"}
    if set(suites) != required:
        raise CertificationManifestRefused("test suite set is not the certification contract")
    rows = {name: _summary_counts(path) for name, path in sorted(suites.items())}
    total = {key: sum(row[key] for row in rows.values()) for key in _COUNT_KEYS}
    if total["passed"] <= 0 or any(total[key] for key in _COUNT_KEYS if key != "passed"):
        raise CertificationManifestRefused("software suite contains a non-pass result")
    return {"suites_completed": 3, "suite_counts": rows, "total": total}


def _test_manifest_hash(root: Path) -> str:
    raw = _run(["git", "ls-files", "-z", "tests"], cwd=root)
    names = sorted(item for item in raw.split("\x00") if item)
    if not names:
        raise CertificationManifestRefused("tracked test manifest is empty")
    digest = hashlib.sha256()
    for name in names:
        digest.update(("%s  %s\n" % (sha256_file(root / name), name)).encode("utf-8"))
    return digest.hexdigest()


def _dependency_hashes(root: Path) -> dict[str, str]:
    names = ("sentinel/requirements.lock", "tests/requirements.lock")
    if any(not (root / name).is_file() for name in names):
        raise CertificationManifestRefused("required dependency locks are missing")
    return {name: sha256_file(root / name) for name in names}


def _docker_image_identity(root: Path, reference: str) -> tuple[str, str]:
    try:
        payload = json.loads(_run(["docker", "image", "inspect", reference], cwd=root))
        image = payload[0]
        image_id = str(image["Id"])
        revision = str((image.get("Config") or {}).get("Labels", {}).get(
            "org.opencontainers.image.revision", ""))
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CertificationManifestRefused("Docker image identity is malformed") from exc
    _require_image_digest(image_id, label="runtime image id")
    _require_git_object(revision, label="runtime source revision")
    return image_id, revision


def build_input(*, root: Path, commit: str, workflow_run: int,
                workflow_attempt: int, image_ref: str,
                suites: Mapping[str, Path], adversarial_report: Path,
                mutation_report: Path) -> dict[str, Any]:
    commit = _require_git_object(commit, label="source commit")
    if workflow_run <= 0 or workflow_attempt <= 0:
        raise CertificationManifestRefused("workflow identity is invalid")
    if _run(["git", "rev-parse", "HEAD"], cwd=root).strip() != commit:
        raise CertificationManifestRefused("checked-out HEAD differs from source commit")
    tree = _run(["git", "rev-parse", "HEAD^{tree}"], cwd=root).strip()
    _require_git_object(tree, label="source tree")
    image_id, revision = _docker_image_identity(root, image_ref)
    if revision != commit:
        raise CertificationManifestRefused("runtime image revision differs from source commit")
    capability = root / "deploy" / "sentinel-authorized-runtime-v1"
    if not capability.is_file():
        raise CertificationManifestRefused("runtime capability marker is missing")
    return {
        "schema": INPUT_SCHEMA,
        "repository": REPOSITORY,
        "source_commit": commit,
        "source_tree": tree,
        "test_workflow_path": TEST_WORKFLOW_PATH,
        "test_workflow_run": workflow_run,
        "test_workflow_attempt": workflow_attempt,
        "runtime_image_id": image_id,
        "runtime_capability_sha256": sha256_file(capability),
        "dependency_lock_hashes": _dependency_hashes(root),
        "test_manifest_sha256": _test_manifest_hash(root),
        "test_counts": collect_test_counts(suites),
        "adversarial_evidence": {"status": "PASS", "sha256": sha256_file(adversarial_report)},
        "mutation_evidence": {"status": "PASS", "sha256": sha256_file(mutation_report)},
        "runtime_schema_epoch": RUNTIME_SCHEMA_EPOCH,
        "semantic_epoch": SEMANTIC_EPOCH,
    }


def _validate_input(value: Mapping[str, Any]) -> None:
    fields = {
        "schema", "repository", "source_commit", "source_tree",
        "test_workflow_path", "test_workflow_run", "test_workflow_attempt",
        "runtime_image_id", "runtime_capability_sha256", "dependency_lock_hashes",
        "test_manifest_sha256", "test_counts", "adversarial_evidence",
        "mutation_evidence", "runtime_schema_epoch", "semantic_epoch",
    }
    if set(value) != fields or value.get("schema") != INPUT_SCHEMA:
        raise CertificationManifestRefused("software certification input schema is invalid")
    if value.get("repository") != REPOSITORY or value.get("test_workflow_path") != TEST_WORKFLOW_PATH:
        raise CertificationManifestRefused("software certification input authority is invalid")
    _require_git_object(value.get("source_commit"), label="source commit")
    _require_git_object(value.get("source_tree"), label="source tree")
    _require_image_digest(value.get("runtime_image_id"), label="runtime image id")
    _require_hex64(value.get("runtime_capability_sha256"), label="runtime capability hash")
    _require_hex64(value.get("test_manifest_sha256"), label="test manifest hash")
    locks = value.get("dependency_lock_hashes")
    if not isinstance(locks, dict) or set(locks) != {
            "sentinel/requirements.lock", "tests/requirements.lock"}:
        raise CertificationManifestRefused("dependency lock hashes are invalid")
    for digest in locks.values():
        _require_hex64(digest, label="dependency lock hash")
    counts = value.get("test_counts")
    if not isinstance(counts, dict) or counts.get("suites_completed") != 3:
        raise CertificationManifestRefused("required software test count is invalid")
    total = counts.get("total")
    suite_counts = counts.get("suite_counts")
    if not isinstance(total, dict) or set(total) != set(_COUNT_KEYS):
        raise CertificationManifestRefused("software test totals are invalid")
    if not isinstance(suite_counts, dict) or set(suite_counts) != {
            "sentinel", "operator_scripts", "wealth_core_boundary"}:
        raise CertificationManifestRefused("software suite counts are invalid")
    if total.get("passed", 0) <= 0 or any(total.get(key) for key in _COUNT_KEYS if key != "passed"):
        raise CertificationManifestRefused("software test totals contain non-passes")
    for row in suite_counts.values():
        if not isinstance(row, dict) or set(row) != set(_COUNT_KEYS) \
                or row.get("passed", 0) <= 0 or any(
                    row.get(key) for key in _COUNT_KEYS if key != "passed"):
            raise CertificationManifestRefused("software suite contains non-passes")
    if sum(row["passed"] for row in suite_counts.values()) != total["passed"]:
        raise CertificationManifestRefused("software suite totals do not add up")
    for name in ("adversarial_evidence", "mutation_evidence"):
        row = value.get(name)
        if not isinstance(row, dict) or set(row) != {"status", "sha256"} or row.get("status") != "PASS":
            raise CertificationManifestRefused("%s status is not PASS" % name)
        _require_hex64(row.get("sha256"), label=name + " hash")
    if value.get("runtime_schema_epoch") != RUNTIME_SCHEMA_EPOCH or \
            value.get("semantic_epoch") != SEMANTIC_EPOCH:
        raise CertificationManifestRefused("software certification epoch is unsupported")


def _required_jobs(payload: Mapping[str, Any]) -> dict[str, str]:
    rows = payload.get("jobs")
    if not isinstance(rows, list):
        raise CertificationManifestRefused("GitHub jobs response has no jobs array")
    found = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("name") not in REQUIRED_JOBS:
            continue
        name = str(row["name"])
        if name in found:
            raise CertificationManifestRefused("required CI job is duplicated: %s" % name)
        found[name] = str(row.get("conclusion") or "")
    if set(found) != set(REQUIRED_JOBS):
        raise CertificationManifestRefused("required CI jobs are missing")
    if any(found[name] != "success" for name in REQUIRED_JOBS):
        raise CertificationManifestRefused("a required CI job did not succeed")
    return {name: found[name] for name in REQUIRED_JOBS}


def finalize_manifest(*, input_evidence: Mapping[str, Any],
                      jobs_payload: Mapping[str, Any], subject_name: str,
                      image_digest: str, publication_run: int,
                      publication_attempt: int, certified_at: str) -> dict[str, Any]:
    _validate_input(input_evidence)
    if subject_name != RUNTIME_SUBJECT:
        raise CertificationManifestRefused("runtime registry subject is invalid")
    image_digest = _require_image_digest(image_digest, label="registry image digest")
    if publication_run <= 0 or publication_attempt <= 0:
        raise CertificationManifestRefused("publication workflow identity is invalid")
    try:
        parsed = datetime.fromisoformat(certified_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CertificationManifestRefused("certification timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise CertificationManifestRefused("certification timestamp has no timezone")
    counts = input_evidence["test_counts"]
    manifest = {
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
            "immutable_ref": "%s@%s" % (subject_name, image_digest),
            "ci_local_image_id": input_evidence["runtime_image_id"],
            "runtime_capability_sha256": input_evidence["runtime_capability_sha256"],
            "broker_capable": True,
        },
        "dependencies": {"lock_hashes": input_evidence["dependency_lock_hashes"]},
        "tests": {
            "manifest_sha256": input_evidence["test_manifest_sha256"],
            "required_counts": {
                "passed": counts["total"]["passed"],
                "suites_completed": counts["suites_completed"],
                "failed": 0, "errors": 0, "skipped": 0,
                "xfailed": 0, "xpassed": 0,
            },
            "suite_counts": counts["suite_counts"],
            "required_job_conclusions": _required_jobs(jobs_payload),
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
        "certified_at": parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    manifest["manifest_sha256"] = sha256_bytes(canonical_bytes(manifest))
    return manifest


def verify_manifest(value: Mapping[str, Any]) -> None:
    expected_top = {
        "schema", "certification_version", "source", "runtime", "dependencies",
        "tests", "ci", "epochs", "certified_at", "manifest_sha256",
    }
    if set(value) != expected_top or value.get("schema") != MANIFEST_SCHEMA \
            or value.get("certification_version") != 1:
        raise CertificationManifestRefused("certification manifest schema is unsupported")
    supplied = value.get("manifest_sha256")
    _require_hex64(supplied, label="certification manifest hash")
    unsigned = {k: v for k, v in value.items() if k != "manifest_sha256"}
    if supplied != sha256_bytes(canonical_bytes(unsigned)):
        raise CertificationManifestRefused("certification manifest integrity check failed")
    source = value.get("source")
    runtime = value.get("runtime")
    tests = value.get("tests")
    ci = value.get("ci")
    epochs = value.get("epochs")
    dependencies = value.get("dependencies")
    if not all(isinstance(item, dict) for item in (source, runtime, tests, ci, epochs, dependencies)):
        raise CertificationManifestRefused("certification binding is incomplete")
    if source.get("repository") != REPOSITORY:
        raise CertificationManifestRefused("manifest repository authority is invalid")
    _require_git_object(source.get("commit"), label="manifest source commit")
    _require_git_object(source.get("tree"), label="manifest source tree")
    if set(runtime) != {
            "subject_name", "docker_image_digest", "immutable_ref",
            "ci_local_image_id", "runtime_capability_sha256", "broker_capable"}:
        raise CertificationManifestRefused("runtime certification shape is invalid")
    if runtime.get("subject_name") != RUNTIME_SUBJECT or runtime.get("broker_capable") is not True:
        raise CertificationManifestRefused("runtime authority is invalid")
    digest = _require_image_digest(runtime.get("docker_image_digest"), label="runtime digest")
    if runtime.get("immutable_ref") != "%s@%s" % (RUNTIME_SUBJECT, digest):
        raise CertificationManifestRefused("runtime immutable reference is inconsistent")
    _require_image_digest(runtime.get("ci_local_image_id"), label="runtime local image id")
    _require_hex64(runtime.get("runtime_capability_sha256"), label="runtime capability hash")
    locks = dependencies.get("lock_hashes")
    if not isinstance(locks, dict) or set(locks) != {
            "sentinel/requirements.lock", "tests/requirements.lock"}:
        raise CertificationManifestRefused("manifest dependency locks are invalid")
    for item in locks.values():
        _require_hex64(item, label="manifest dependency hash")
    if tests.get("required_job_conclusions") != {name: "success" for name in REQUIRED_JOBS}:
        raise CertificationManifestRefused("required CI job conclusions are invalid")
    required = tests.get("required_counts")
    if not isinstance(required, dict) or required.get("passed", 0) <= 0 or \
            required.get("suites_completed") != 3 or any(
                required.get(key) for key in ("failed", "errors", "skipped", "xfailed", "xpassed")):
        raise CertificationManifestRefused("required test counts are invalid")
    _require_hex64(tests.get("manifest_sha256"), label="manifest test hash")
    for name in ("adversarial_evidence", "mutation_evidence"):
        row = tests.get(name)
        if not isinstance(row, dict) or row.get("status") != "PASS":
            raise CertificationManifestRefused("manifest evidence status is invalid")
        _require_hex64(row.get("sha256"), label="manifest evidence hash")
    if ci.get("test_workflow_path") != TEST_WORKFLOW_PATH:
        raise CertificationManifestRefused("certification workflow binding is invalid")
    if epochs != {"runtime_schema": RUNTIME_SCHEMA_EPOCH, "semantic": SEMANTIC_EPOCH}:
        raise CertificationManifestRefused("certification epoch is unsupported")


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-input")
    build.add_argument("--root", type=Path, default=Path("."))
    build.add_argument("--commit", required=True)
    build.add_argument("--workflow-run", type=int, required=True)
    build.add_argument("--workflow-attempt", type=int, required=True)
    build.add_argument("--image-ref", required=True)
    build.add_argument("--sentinel-summary", type=Path, required=True)
    build.add_argument("--operator-summary", type=Path, required=True)
    build.add_argument("--wealth-summary", type=Path, required=True)
    build.add_argument("--adversarial-report", type=Path, required=True)
    build.add_argument("--mutation-report", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--input", type=Path, required=True)
    final.add_argument("--jobs", type=Path, required=True)
    final.add_argument("--subject-name", required=True)
    final.add_argument("--image-digest", required=True)
    final.add_argument("--publication-run", type=int, required=True)
    final.add_argument("--publication-attempt", type=int, required=True)
    final.add_argument("--certified-at", required=True)
    final.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-input":
            value = build_input(
                root=args.root.resolve(), commit=args.commit,
                workflow_run=args.workflow_run, workflow_attempt=args.workflow_attempt,
                image_ref=args.image_ref,
                suites={
                    "sentinel": args.sentinel_summary,
                    "operator_scripts": args.operator_summary,
                    "wealth_core_boundary": args.wealth_summary,
                },
                adversarial_report=args.adversarial_report,
                mutation_report=args.mutation_report,
            )
            _write(args.output, value)
        elif args.command == "finalize":
            value = finalize_manifest(
                input_evidence=_read_json(args.input, label="software certification input"),
                jobs_payload=_read_json(args.jobs, label="GitHub jobs response"),
                subject_name=args.subject_name, image_digest=args.image_digest,
                publication_run=args.publication_run,
                publication_attempt=args.publication_attempt,
                certified_at=args.certified_at,
            )
            verify_manifest(value)
            _write(args.output, value)
        else:
            verify_manifest(_read_json(args.manifest, label="certification manifest"))
    except CertificationManifestRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
