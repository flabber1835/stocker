#!/usr/bin/env python3
"""Verify reusable CI certification for the exact current Sentinel runtime."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Mapping, Optional, Sequence
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "flabber1835/stocker"
REPOSITORY_ID = 1233957439
SAFETY_WORKFLOW_ID = 333697638
SAFETY_WORKFLOW_PATH = ".github/workflows/sentinel-safety.yml"
PUBLICATION_WORKFLOW_ID = 346316730
PUBLICATION_WORKFLOW_PATH = ".github/workflows/sentinel-publish.yml"
CERTIFICATION_SCHEMA = "sentinel.software-certification/1"
PROVENANCE_SCHEMA = "sentinel.exact-sha-provenance/4"
RUNTIME_SCHEMA_EPOCH = "sentinel.behavioral_schema/current"
SEMANTIC_EPOCH = "sentinel.automation_cycle/1"
EXPECTED_SUBJECT = "ghcr.io/flabber1835/stocker/sentinel"
REQUIRED_JOBS = ("host-python-38-exact-head", "sentinel-exact-head")
REQUIRED_LOCKS = ("sentinel/requirements.lock", "tests/requirements.lock")
REQUIRED_SUITES = ("operator_scripts", "sentinel", "wealth_core_boundary")
COUNT_KEYS = ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")
API_ROOT = "https://api.github.com"

_GIT = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class CertificationVerificationRefused(RuntimeError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _refuse(code, detail):
    raise CertificationVerificationRefused(code, detail)


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _json_bytes(raw, code, label):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _refuse(code, "%s contains duplicate key" % label)
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _refuse(code, "%s is not valid UTF-8 JSON" % label)
        raise AssertionError from exc
    if not isinstance(value, dict):
        _refuse(code, "%s is not a JSON object" % label)
    return value


def _git(root, *args):
    completed = subprocess.run(
        ["git"] + list(args), cwd=str(root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        _refuse("CERT_GIT_IDENTITY_UNAVAILABLE", "git identity command failed")
    return (completed.stdout or "").strip()


def current_identity(root=ROOT):
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if _GIT.fullmatch(head) is None or _GIT.fullmatch(tree) is None:
        _refuse("CERT_GIT_IDENTITY_UNAVAILABLE", "Git identity is malformed")
    return {"commit": head, "tree": tree}


class _AuthorizationStrippingRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source = urllib.parse.urlsplit(req.full_url)
        destination = urllib.parse.urlsplit(newurl)
        if (source.scheme.lower(), source.hostname, source.port) != (
                destination.scheme.lower(), destination.hostname, destination.port):
            redirected.remove_header("Authorization")
        return redirected


def _safe_urlopen(request, timeout=30):
    opener = urllib.request.build_opener(_AuthorizationStrippingRedirect())
    return opener.open(request, timeout=timeout)


class GitHubReadClient:
    """GET-only GitHub client. This class exposes no mutation method."""

    def __init__(self, token=None, opener=_safe_urlopen):
        self.token = token
        self.opener = opener

    def _request(self, url):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "stocker-sentinel-certification-verifier/1",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            response = self.opener(request, timeout=30)
            return response.read()
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            _refuse("CERT_GITHUB_UNAVAILABLE", "GitHub read failed")
            raise AssertionError from exc

    def json(self, path):
        return _json_bytes(
            self._request(API_ROOT + path),
            "CERT_GITHUB_RESPONSE_INVALID", "GitHub response")

    def bytes(self, url):
        return self._request(url)


def _run_path(run):
    return str(run.get("path") or "").split("@", 1)[0]


def _same_repo(run):
    repository = run.get("repository")
    head_repository = run.get("head_repository")
    return bool(
        isinstance(repository, dict)
        and repository.get("id") == REPOSITORY_ID
        and repository.get("full_name") == REPOSITORY
        and isinstance(head_repository, dict)
        and head_repository.get("id") == REPOSITORY_ID
        and head_repository.get("full_name") == REPOSITORY)


def _publication_run(client, commit):
    payload = client.json(
        "/repos/%s/actions/runs?head_sha=%s&per_page=100" % (REPOSITORY, commit))
    rows = payload.get("workflow_runs")
    if not isinstance(rows, list):
        _refuse("CERT_GITHUB_RESPONSE_INVALID", "workflow run list is malformed")
    candidates = [row for row in rows if isinstance(row, dict)
                  and row.get("workflow_id") == PUBLICATION_WORKFLOW_ID
                  and _run_path(row) == PUBLICATION_WORKFLOW_PATH
                  and row.get("head_sha") == commit
                  and row.get("head_branch") == "main"
                  and row.get("event") == "workflow_run"
                  and row.get("status") == "completed"
                  and row.get("conclusion") == "success"
                  and _same_repo(row)]
    if not candidates:
        _refuse("CERT_NO_PUBLICATION", "no successful exact-SHA publication run exists")
    candidates.sort(key=lambda row: (
        int(row.get("run_attempt") or 0), int(row.get("id") or 0)))
    return candidates[-1]


def _publication_artifact(client, run, commit):
    run_id = int(run.get("id") or 0)
    payload = client.json(
        "/repos/%s/actions/runs/%d/artifacts?per_page=100" % (REPOSITORY, run_id))
    rows = payload.get("artifacts")
    if not isinstance(rows, list):
        _refuse("CERT_GITHUB_RESPONSE_INVALID", "artifact list is malformed")
    name = "sentinel-provenance-%s" % commit
    candidates = [row for row in rows if isinstance(row, dict)
                  and row.get("name") == name and row.get("expired") is False]
    if len(candidates) != 1:
        _refuse("CERT_ARTIFACT_MISSING", "exact certification artifact is unavailable")
    artifact = candidates[0]
    digest = str(artifact.get("digest") or "")
    workflow = artifact.get("workflow_run")
    if _DIGEST.fullmatch(digest) is None:
        _refuse("CERT_ARTIFACT_DIGEST_INVALID", "artifact has no SHA-256 digest")
    if not isinstance(workflow, dict) or workflow.get("id") != run_id \
            or workflow.get("repository_id") != REPOSITORY_ID \
            or workflow.get("head_repository_id") != REPOSITORY_ID \
            or workflow.get("head_branch") != "main" \
            or workflow.get("head_sha") != commit:
        _refuse("CERT_ARTIFACT_BINDING_INVALID", "artifact workflow binding is invalid")
    return artifact


def _download_artifact(client, artifact):
    url = str(artifact.get("archive_download_url") or "")
    if not url.startswith(API_ROOT + "/"):
        _refuse("CERT_ARTIFACT_BINDING_INVALID", "artifact download URL is invalid")
    raw = client.bytes(url)
    if _sha256(raw) != str(artifact["digest"]).split(":", 1)[1]:
        _refuse("CERT_ARTIFACT_DIGEST_MISMATCH", "downloaded artifact digest differs")
    return raw


def _bundle_members(archive):
    expected = {
        "certification.json", "provenance.json",
        "attestation.sigstore.json", "SHA256SUMS",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(archive), "r") as bundle:
            names = bundle.namelist()
            if len(names) != len(expected) or set(names) != expected:
                _refuse("CERT_BUNDLE_SCHEMA_INVALID", "bundle members are not exact")
            return {name: bundle.read(name) for name in names}
    except zipfile.BadZipFile as exc:
        _refuse("CERT_BUNDLE_SCHEMA_INVALID", "certification artifact is not a ZIP")
        raise AssertionError from exc


def _verify_sums(members):
    try:
        lines = members["SHA256SUMS"].decode("ascii").splitlines()
    except UnicodeError as exc:
        _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "checksum manifest is not ASCII")
        raise AssertionError from exc
    expected = {"certification.json", "provenance.json", "attestation.sigstore.json"}
    found = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None:
            _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "checksum row is malformed")
        digest, name = match.groups()
        if name in found or name not in expected or _sha256(members[name]) != digest:
            _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "bundle checksum mismatch")
        found.add(name)
    if found != expected:
        _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "bundle checksum set is incomplete")


def _require_hex64(value, code, label):
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        _refuse(code, "%s is not a canonical SHA-256" % label)
    return value


def _verify_counts(tests):
    required = tests.get("required_counts")
    suites = tests.get("suite_counts")
    if not isinstance(required, dict) or set(required) != {
            "passed", "suites_completed", "failed", "errors", "skipped",
            "xfailed", "xpassed"}:
        _refuse("CERT_TEST_COUNTS_INVALID", "required test counts are malformed")
    if required.get("suites_completed") != 3 or type(required.get("passed")) is not int \
            or required["passed"] <= 0 or any(
                required.get(key) != 0 for key in COUNT_KEYS if key != "passed"):
        _refuse("CERT_TEST_COUNTS_INVALID", "required test counts contain non-passes")
    if not isinstance(suites, dict) or set(suites) != set(REQUIRED_SUITES):
        _refuse("CERT_TEST_COUNTS_INVALID", "suite count set is invalid")
    passed = 0
    for name in REQUIRED_SUITES:
        row = suites[name]
        if not isinstance(row, dict) or set(row) != set(COUNT_KEYS) \
                or type(row.get("passed")) is not int or row["passed"] <= 0 \
                or any(row.get(key) != 0 for key in COUNT_KEYS if key != "passed"):
            _refuse("CERT_TEST_COUNTS_INVALID", "suite count row is invalid")
        passed += row["passed"]
    if passed != required["passed"]:
        _refuse("CERT_TEST_COUNTS_INVALID", "suite totals differ from required total")


def _verify_manifest(manifest, commit, tree, publication_run):
    expected_top = {
        "schema", "certification_version", "source", "runtime", "dependencies",
        "tests", "ci", "epochs", "certified_at", "manifest_sha256",
    }
    if set(manifest) != expected_top or manifest.get("schema") != CERTIFICATION_SCHEMA \
            or manifest.get("certification_version") != 1:
        _refuse("CERT_MANIFEST_SCHEMA_UNKNOWN", "certification schema is unsupported")
    supplied = manifest.get("manifest_sha256")
    _require_hex64(supplied, "CERT_MANIFEST_TAMPERED", "manifest hash")
    unsigned = {key: value for key, value in manifest.items()
                if key != "manifest_sha256"}
    if _sha256(_canonical(unsigned)) != supplied:
        _refuse("CERT_MANIFEST_TAMPERED", "manifest hash check failed")

    source = manifest.get("source")
    runtime = manifest.get("runtime")
    dependencies = manifest.get("dependencies")
    tests = manifest.get("tests")
    ci = manifest.get("ci")
    epochs = manifest.get("epochs")
    if not all(isinstance(value, dict) for value in (
            source, runtime, dependencies, tests, ci, epochs)):
        _refuse("CERT_MANIFEST_SCHEMA_UNKNOWN", "manifest binding sections are missing")
    if set(source) != {"repository", "commit", "tree"} \
            or source.get("repository") != REPOSITORY or source.get("commit") != commit:
        _refuse("CERT_SOURCE_SHA_MISMATCH", "manifest source commit differs")
    if source.get("tree") != tree:
        _refuse("CERT_SOURCE_TREE_MISMATCH", "manifest source tree differs")

    expected_runtime = {
        "subject_name", "docker_image_digest", "immutable_ref",
        "ci_local_image_id", "runtime_capability_sha256", "broker_capable",
    }
    if set(runtime) != expected_runtime or runtime.get("subject_name") != EXPECTED_SUBJECT:
        _refuse("CERT_RUNTIME_SUBJECT_INVALID", "runtime subject is unsupported")
    if runtime.get("broker_capable") is not True:
        _refuse("CERT_RUNTIME_CAPABILITY_INVALID", "certified runtime is not broker-capable")
    digest = str(runtime.get("docker_image_digest") or "")
    if _DIGEST.fullmatch(digest) is None:
        _refuse("CERT_IMAGE_DIGEST_MISSING", "runtime digest is missing")
    if runtime.get("immutable_ref") != "%s@%s" % (EXPECTED_SUBJECT, digest):
        _refuse("CERT_IMAGE_BINDING_INVALID", "immutable runtime reference differs")
    if _DIGEST.fullmatch(str(runtime.get("ci_local_image_id") or "")) is None:
        _refuse("CERT_IMAGE_BINDING_INVALID", "CI image ID is malformed")
    _require_hex64(runtime.get("runtime_capability_sha256"),
                   "CERT_RUNTIME_CAPABILITY_INVALID", "runtime capability hash")

    if set(dependencies) != {"lock_hashes"} or not isinstance(
            dependencies.get("lock_hashes"), dict):
        _refuse("CERT_DEPENDENCY_HASHES_INVALID", "dependency lock hashes are malformed")
    locks = dependencies["lock_hashes"]
    if set(locks) != set(REQUIRED_LOCKS):
        _refuse("CERT_DEPENDENCY_HASHES_INVALID", "dependency lock set is invalid")
    for name in REQUIRED_LOCKS:
        _require_hex64(locks[name], "CERT_DEPENDENCY_HASHES_INVALID", "dependency hash")

    expected_tests = {
        "manifest_sha256", "required_counts", "suite_counts",
        "required_job_conclusions", "adversarial_evidence", "mutation_evidence",
    }
    if set(tests) != expected_tests:
        _refuse("CERT_MANIFEST_SCHEMA_UNKNOWN", "test evidence schema is malformed")
    _require_hex64(tests.get("manifest_sha256"),
                   "CERT_TEST_MANIFEST_INVALID", "test manifest hash")
    if tests.get("required_job_conclusions") != {
            name: "success" for name in REQUIRED_JOBS}:
        _refuse("CERT_REQUIRED_JOB_FAILED", "manifest required-job conclusions differ")
    _verify_counts(tests)
    for name in ("adversarial_evidence", "mutation_evidence"):
        evidence = tests.get(name)
        if not isinstance(evidence, dict) or set(evidence) != {"status", "sha256"} \
                or evidence.get("status") != "PASS":
            _refuse("CERT_EVIDENCE_INVALID", "%s status is invalid" % name)
        _require_hex64(evidence.get("sha256"), "CERT_EVIDENCE_INVALID", name + " hash")

    expected_ci = {
        "test_workflow_path", "test_workflow_run", "test_workflow_attempt",
        "publication_workflow_run", "publication_workflow_attempt",
    }
    if set(ci) != expected_ci or ci.get("test_workflow_path") != SAFETY_WORKFLOW_PATH:
        _refuse("CERT_SAFETY_BINDING_INVALID", "certification workflow binding is invalid")
    for field in (
            "test_workflow_run", "test_workflow_attempt",
            "publication_workflow_run", "publication_workflow_attempt"):
        if type(ci.get(field)) is not int or ci[field] <= 0:
            _refuse("CERT_SAFETY_BINDING_INVALID", "workflow identity is invalid")
    if ci["publication_workflow_run"] != int(publication_run.get("id") or 0) \
            or ci["publication_workflow_attempt"] != int(publication_run.get("run_attempt") or 0):
        _refuse("CERT_PUBLICATION_BINDING_INVALID", "publication workflow identity differs")

    if epochs != {"runtime_schema": RUNTIME_SCHEMA_EPOCH, "semantic": SEMANTIC_EPOCH}:
        _refuse("CERT_EPOCH_UNSUPPORTED", "certification epoch is unsupported")
    certified_at = manifest.get("certified_at")
    if not isinstance(certified_at, str) or not certified_at.endswith("Z"):
        _refuse("CERT_CERTIFIED_AT_INVALID", "certification timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(certified_at[:-1] + "+00:00")
    except ValueError as exc:
        _refuse("CERT_CERTIFIED_AT_INVALID", "certification timestamp is malformed")
        raise AssertionError from exc
    if parsed.utcoffset() is None:
        _refuse("CERT_CERTIFIED_AT_INVALID", "certification timestamp has no timezone")
    return {"digest": digest, "ci": ci}


def _verify_provenance(provenance, members, commit, publication_run_id,
                       digest, test_run_id):
    if provenance.get("schema") != PROVENANCE_SCHEMA:
        _refuse("CERT_PROVENANCE_SCHEMA_INVALID", "provenance schema is unsupported")
    if provenance.get("commit") != commit \
            or int(provenance.get("publication_workflow_run") or 0) != publication_run_id \
            or int(provenance.get("test_workflow_run") or 0) != test_run_id:
        _refuse("CERT_PROVENANCE_BINDING_INVALID", "provenance workflow binding differs")
    if provenance.get("subject_name") != EXPECTED_SUBJECT \
            or provenance.get("tested_image_digest") != digest \
            or provenance.get("immutable_runtime") != "%s@%s" % (EXPECTED_SUBJECT, digest):
        _refuse("CERT_PROVENANCE_BINDING_INVALID", "provenance runtime binding differs")
    if provenance.get("certification_manifest_sha256") != _sha256(members["certification.json"]):
        _refuse("CERT_PROVENANCE_BINDING_INVALID", "provenance manifest hash differs")


def _verify_attestation(bundle, digest):
    envelope = bundle.get("dsseEnvelope")
    if not isinstance(envelope, dict) or not envelope.get("signatures"):
        _refuse("CERT_ATTESTATION_BINDING_INVALID", "attestation envelope is incomplete")
    try:
        statement = json.loads(base64.b64decode(envelope["payload"], validate=True))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _refuse("CERT_ATTESTATION_BINDING_INVALID", "attestation payload is malformed")
        raise AssertionError from exc
    algorithm, separator, value = digest.partition(":")
    expected = [{"name": EXPECTED_SUBJECT, "digest": {algorithm: value}}]
    if separator != ":" or algorithm != "sha256" \
            or statement.get("_type") != "https://in-toto.io/Statement/v1" \
            or statement.get("predicateType") != "https://slsa.dev/provenance/v1" \
            or statement.get("subject") != expected:
        _refuse("CERT_ATTESTATION_BINDING_INVALID", "attestation subject differs")


def verify_bundle(archive, commit, tree, publication_run):
    members = _bundle_members(archive)
    _verify_sums(members)
    manifest = _json_bytes(
        members["certification.json"], "CERT_MANIFEST_SCHEMA_UNKNOWN",
        "certification manifest")
    binding = _verify_manifest(manifest, commit, tree, publication_run)
    test_run_id = int(binding["ci"]["test_workflow_run"])
    provenance = _json_bytes(
        members["provenance.json"], "CERT_PROVENANCE_SCHEMA_INVALID", "provenance")
    _verify_provenance(
        provenance, members, commit, int(publication_run["id"]),
        str(binding["digest"]), test_run_id)
    attestation = _json_bytes(
        members["attestation.sigstore.json"],
        "CERT_ATTESTATION_BINDING_INVALID", "attestation")
    _verify_attestation(attestation, str(binding["digest"]))
    ci = binding["ci"]
    return {
        "schema": CERTIFICATION_SCHEMA,
        "source_commit": commit,
        "source_tree": tree,
        "certified_image": "%s@%s" % (EXPECTED_SUBJECT, binding["digest"]),
        "image_digest": binding["digest"],
        "broker_capable": True,
        "test_workflow_run": test_run_id,
        "test_workflow_attempt": int(ci["test_workflow_attempt"]),
        "publication_workflow_run": int(publication_run["id"]),
        "publication_workflow_attempt": int(publication_run.get("run_attempt") or 0),
        "required_ci_jobs": "PASS",
        "software_certification": "VERIFIED",
    }


def _verify_safety_run(client, result):
    run_id = int(result["test_workflow_run"])
    run = client.json("/repos/%s/actions/runs/%d" % (REPOSITORY, run_id))
    if run.get("workflow_id") != SAFETY_WORKFLOW_ID \
            or _run_path(run) != SAFETY_WORKFLOW_PATH \
            or run.get("head_sha") != result["source_commit"] \
            or run.get("head_branch") != "main" \
            or run.get("event") != "push" \
            or run.get("status") != "completed" \
            or run.get("conclusion") != "success" \
            or int(run.get("run_attempt") or 0) != int(result["test_workflow_attempt"]) \
            or not _same_repo(run):
        _refuse("CERT_SAFETY_BINDING_INVALID", "safety workflow binding is invalid")
    jobs = client.json(
        "/repos/%s/actions/runs/%d/jobs?per_page=100" % (REPOSITORY, run_id))
    rows = jobs.get("jobs")
    if not isinstance(rows, list):
        _refuse("CERT_GITHUB_RESPONSE_INVALID", "safety jobs response is malformed")
    found = {}
    for row in rows:
        if isinstance(row, dict) and row.get("name") in REQUIRED_JOBS:
            name = str(row["name"])
            if name in found:
                _refuse("CERT_REQUIRED_JOB_DUPLICATE", "required CI job is duplicated")
            found[name] = str(row.get("conclusion") or "")
    if set(found) != set(REQUIRED_JOBS):
        _refuse("CERT_REQUIRED_JOB_MISSING", "required CI job is missing")
    if any(found[name] != "success" for name in REQUIRED_JOBS):
        _refuse("CERT_REQUIRED_JOB_FAILED", "required CI job did not succeed")


def verify_current(root=ROOT, commit=None, client=None):
    identity = current_identity(root)
    expected = commit or identity["commit"]
    if _GIT.fullmatch(expected) is None or expected != identity["commit"]:
        _refuse("CERT_SOURCE_SHA_MISMATCH", "requested commit differs from current HEAD")
    client = client or GitHubReadClient(
        token=os.environ.get("SENTINEL_GITHUB_READ_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    publication = _publication_run(client, expected)
    artifact = _publication_artifact(client, publication, expected)
    result = verify_bundle(
        _download_artifact(client, artifact), expected, identity["tree"], publication)
    _verify_safety_run(client, result)
    final_identity = current_identity(root)
    if final_identity != identity:
        _refuse("CERT_CURRENT_HEAD_CHANGED", "Git identity changed during verification")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_current(commit=args.commit)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(_canonical(result) + b"\n")
        print("software certification: VERIFIED %s" % result["certified_image"])
        return 0
    except CertificationVerificationRefused as exc:
        detail_hash = hashlib.sha256(exc.detail.encode("utf-8")).hexdigest()
        print("REFUSED: %s [detail_sha256=%s]" % (exc.code, detail_hash), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
