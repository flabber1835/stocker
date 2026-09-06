#!/usr/bin/env python3
"""Read-only verifier for reusable Sentinel CI software certification."""
from __future__ import annotations

import argparse
import base64
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
REQUIRED_JOBS = ("host-python-38-exact-head", "sentinel-exact-head")
API_ROOT = "https://api.github.com"

_GIT = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class CertificationVerificationRefused(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _refuse(code: str, detail: str) -> None:
    raise CertificationVerificationRefused(code, detail)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(raw: bytes, *, code: str, label: str) -> Mapping[str, Any]:
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


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        _refuse("CERT_GIT_IDENTITY_UNAVAILABLE", "git identity command failed")
    return (completed.stdout or "").strip()


def current_identity(root: Path = ROOT) -> Mapping[str, str]:
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if _GIT.fullmatch(head) is None or _GIT.fullmatch(tree) is None:
        _refuse("CERT_GIT_IDENTITY_UNAVAILABLE", "Git identity is malformed")
    return {"commit": head, "tree": tree}


class GitHubReadClient:
    """Minimal GET-only GitHub client. It has no mutation methods."""

    def __init__(self, token: Optional[str] = None,
                 opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.token = token
        self.opener = opener

    def _request(self, url: str) -> bytes:
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

    def json(self, path: str) -> Mapping[str, Any]:
        return _json_bytes(
            self._request(API_ROOT + path),
            code="CERT_GITHUB_RESPONSE_INVALID", label="GitHub response")

    def bytes(self, url: str) -> bytes:
        return self._request(url)


def _run_path(run: Mapping[str, Any]) -> str:
    value = str(run.get("path") or "")
    return value.split("@", 1)[0]


def _publication_run(client: GitHubReadClient, commit: str) -> Mapping[str, Any]:
    payload = client.json(
        "/repos/%s/actions/runs?head_sha=%s&per_page=100" % (REPOSITORY, commit))
    rows = payload.get("workflow_runs")
    if not isinstance(rows, list):
        _refuse("CERT_GITHUB_RESPONSE_INVALID", "workflow run list is malformed")
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if (row.get("workflow_id") == PUBLICATION_WORKFLOW_ID
                and _run_path(row) == PUBLICATION_WORKFLOW_PATH
                and row.get("head_sha") == commit
                and row.get("head_branch") == "main"
                and row.get("event") == "workflow_run"
                and row.get("status") == "completed"
                and row.get("conclusion") == "success"):
            candidates.append(row)
    if not candidates:
        _refuse("CERT_NO_PUBLICATION", "no successful exact-SHA publication run exists")
    candidates.sort(key=lambda row: (int(row.get("run_attempt") or 0), int(row.get("id") or 0)))
    return candidates[-1]


def _publication_artifact(client: GitHubReadClient, run: Mapping[str, Any],
                          commit: str) -> Mapping[str, Any]:
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
    if _DIGEST.fullmatch(digest) is None:
        _refuse("CERT_ARTIFACT_DIGEST_INVALID", "artifact has no sha256 digest")
    workflow = artifact.get("workflow_run")
    if not isinstance(workflow, dict) or workflow.get("id") != run_id \
            or workflow.get("head_sha") != commit:
        _refuse("CERT_ARTIFACT_BINDING_INVALID", "artifact workflow binding is invalid")
    return artifact


def _download_artifact(client: GitHubReadClient,
                       artifact: Mapping[str, Any]) -> bytes:
    url = str(artifact.get("archive_download_url") or "")
    if not url.startswith(API_ROOT + "/"):
        _refuse("CERT_ARTIFACT_BINDING_INVALID", "artifact download URL is invalid")
    raw = client.bytes(url)
    expected = str(artifact["digest"]).split(":", 1)[1]
    if _sha256(raw) != expected:
        _refuse("CERT_ARTIFACT_DIGEST_MISMATCH", "downloaded artifact digest differs")
    return raw


def _bundle_members(archive: bytes) -> Mapping[str, bytes]:
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


def _verify_sums(members: Mapping[str, bytes]) -> None:
    try:
        lines = members["SHA256SUMS"].decode("ascii").splitlines()
    except UnicodeError as exc:
        _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "checksum manifest is not ASCII")
        raise AssertionError from exc
    expected_names = {
        "certification.json", "provenance.json", "attestation.sigstore.json"}
    found = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None:
            _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "checksum row is malformed")
        digest, name = match.groups()
        if name in found or name not in expected_names or _sha256(members[name]) != digest:
            _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "bundle checksum mismatch")
        found.add(name)
    if found != expected_names:
        _refuse("CERT_BUNDLE_INTEGRITY_INVALID", "bundle checksum set is incomplete")


def _verify_manifest(manifest: Mapping[str, Any], *, commit: str,
                     tree: str, publication_run: Mapping[str, Any]) -> Mapping[str, Any]:
    if manifest.get("schema") != CERTIFICATION_SCHEMA:
        _refuse("CERT_MANIFEST_SCHEMA_UNKNOWN", "certification schema is unsupported")
    supplied = manifest.get("manifest_sha256")
    if not isinstance(supplied, str) or _HEX64.fullmatch(supplied) is None:
        _refuse("CERT_MANIFEST_TAMPERED", "manifest hash is malformed")
    unsigned = {key: value for key, value in manifest.items()
                if key != "manifest_sha256"}
    if _sha256(_canonical(unsigned)) != supplied:
        _refuse("CERT_MANIFEST_TAMPERED", "manifest hash check failed")
    source = manifest.get("source")
    runtime = manifest.get("runtime")
    tests = manifest.get("tests")
    ci = manifest.get("ci")
    if not all(isinstance(value, dict) for value in (source, runtime, tests, ci)):
        _refuse("CERT_MANIFEST_SCHEMA_UNKNOWN", "manifest binding sections are missing")
    if source.get("repository") != REPOSITORY or source.get("commit") != commit:
        _refuse("CERT_SOURCE_SHA_MISMATCH", "manifest source commit differs")
    if source.get("tree") != tree:
        _refuse("CERT_SOURCE_TREE_MISMATCH", "manifest source tree differs")
    digest = str(runtime.get("docker_image_digest") or "")
    if _DIGEST.fullmatch(digest) is None:
        _refuse("CERT_IMAGE_DIGEST_MISSING", "runtime digest is missing")
    if runtime.get("authorized_runtime_digest") != digest:
        _refuse("CERT_AUTHORIZED_RUNTIME_MISMATCH", "authorized runtime digest differs")
    subject = str(runtime.get("subject_name") or "")
    if runtime.get("immutable_ref") != "%s@%s" % (subject, digest):
        _refuse("CERT_IMAGE_BINDING_INVALID", "immutable runtime reference differs")
    required_jobs = tests.get("required_job_conclusions")
    if required_jobs != {name: "success" for name in REQUIRED_JOBS}:
        _refuse("CERT_REQUIRED_JOB_FAILED", "manifest required-job conclusions differ")
    counts = tests.get("required_counts")
    if not isinstance(counts, dict) or int(counts.get("passed") or 0) <= 0 \
            or int(counts.get("suites_completed") or 0) != 3:
        _refuse("CERT_TEST_COUNTS_INVALID", "required test counts are incomplete")
    for name in ("failed", "errors", "skipped", "xfailed", "xpassed"):
        if counts.get(name) != 0:
            _refuse("CERT_TEST_COUNTS_INVALID", "required test counts contain non-passes")
    if int(ci.get("publication_workflow_run") or 0) != int(publication_run.get("id") or 0):
        _refuse("CERT_PUBLICATION_BINDING_INVALID", "publication run differs")
    if int(ci.get("publication_workflow_attempt") or 0) != int(publication_run.get("run_attempt") or 0):
        _refuse("CERT_PUBLICATION_BINDING_INVALID", "publication attempt differs")
    return {"digest": digest, "subject": subject, "ci": ci}


def _verify_provenance(provenance: Mapping[str, Any], members: Mapping[str, bytes],
                       *, commit: str, publication_run_id: int,
                       digest: str, subject: str, test_run_id: int) -> None:
    if provenance.get("schema") != PROVENANCE_SCHEMA:
        _refuse("CERT_PROVENANCE_SCHEMA_INVALID", "provenance schema is unsupported")
    if provenance.get("commit") != commit or \
            int(provenance.get("publication_workflow_run") or 0) != publication_run_id or \
            int(provenance.get("test_workflow_run") or 0) != test_run_id:
        _refuse("CERT_PROVENANCE_BINDING_INVALID", "provenance workflow binding differs")
    if provenance.get("tested_image_digest") != digest or \
            provenance.get("immutable_authorized_image") != "%s@%s" % (subject, digest):
        _refuse("CERT_PROVENANCE_BINDING_INVALID", "provenance runtime binding differs")
    if provenance.get("certification_manifest_sha256") != _sha256(members["certification.json"]):
        _refuse("CERT_PROVENANCE_BINDING_INVALID", "provenance manifest hash differs")


def _verify_attestation(bundle: Mapping[str, Any], *, subject: str, digest: str) -> None:
    envelope = bundle.get("dsseEnvelope")
    if not isinstance(envelope, dict) or not envelope.get("signatures"):
        _refuse("CERT_ATTESTATION_BINDING_INVALID", "attestation envelope is incomplete")
    try:
        statement = json.loads(base64.b64decode(envelope["payload"], validate=True))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _refuse("CERT_ATTESTATION_BINDING_INVALID", "attestation payload is malformed")
        raise AssertionError from exc
    algorithm, separator, value = digest.partition(":")
    expected = [{"name": subject, "digest": {algorithm: value}}]
    if separator != ":" or algorithm != "sha256" or \
            statement.get("_type") != "https://in-toto.io/Statement/v1" or \
            statement.get("predicateType") != "https://slsa.dev/provenance/v1" or \
            statement.get("subject") != expected:
        _refuse("CERT_ATTESTATION_BINDING_INVALID", "attestation subject differs")


def verify_bundle(archive: bytes, *, commit: str, tree: str,
                  publication_run: Mapping[str, Any]) -> Mapping[str, Any]:
    members = _bundle_members(archive)
    _verify_sums(members)
    manifest = _json_bytes(
        members["certification.json"], code="CERT_MANIFEST_SCHEMA_UNKNOWN",
        label="certification manifest")
    binding = _verify_manifest(
        manifest, commit=commit, tree=tree, publication_run=publication_run)
    ci = binding["ci"]
    test_run_id = int(ci.get("test_workflow_run") or 0)
    if test_run_id <= 0:
        _refuse("CERT_SAFETY_BINDING_INVALID", "safety run is missing")
    provenance = _json_bytes(
        members["provenance.json"], code="CERT_PROVENANCE_SCHEMA_INVALID",
        label="provenance")
    _verify_provenance(
        provenance, members, commit=commit,
        publication_run_id=int(publication_run["id"]),
        digest=str(binding["digest"]), subject=str(binding["subject"]),
        test_run_id=test_run_id)
    attestation = _json_bytes(
        members["attestation.sigstore.json"],
        code="CERT_ATTESTATION_BINDING_INVALID", label="attestation")
    _verify_attestation(
        attestation, subject=str(binding["subject"]), digest=str(binding["digest"]))
    return {
        "schema": CERTIFICATION_SCHEMA,
        "source_commit": commit,
        "source_tree": tree,
        "certified_image": "%s@%s" % (binding["subject"], binding["digest"]),
        "image_digest": binding["digest"],
        "test_workflow_run": test_run_id,
        "test_workflow_attempt": int(ci.get("test_workflow_attempt") or 0),
        "publication_workflow_run": int(publication_run["id"]),
        "publication_workflow_attempt": int(publication_run.get("run_attempt") or 0),
        "required_ci_jobs": "PASS",
        "software_certification": "VERIFIED",
    }


def _verify_safety_run(client: GitHubReadClient, result: Mapping[str, Any]) -> None:
    run_id = int(result["test_workflow_run"])
    run = client.json("/repos/%s/actions/runs/%d" % (REPOSITORY, run_id))
    if (run.get("workflow_id") != SAFETY_WORKFLOW_ID
            or _run_path(run) != SAFETY_WORKFLOW_PATH
            or run.get("head_sha") != result["source_commit"]
            or run.get("head_branch") != "main"
            or run.get("event") != "push"
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or int(run.get("run_attempt") or 0) != int(result["test_workflow_attempt"])):
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


def verify_current(*, root: Path = ROOT, commit: Optional[str] = None,
                   client: Optional[GitHubReadClient] = None) -> Mapping[str, Any]:
    identity = current_identity(root)
    expected = commit or identity["commit"]
    if _GIT.fullmatch(expected) is None or expected != identity["commit"]:
        _refuse("CERT_SOURCE_SHA_MISMATCH", "requested commit differs from current HEAD")
    client = client or GitHubReadClient(
        token=os.environ.get("SENTINEL_GITHUB_READ_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    publication = _publication_run(client, expected)
    artifact = _publication_artifact(client, publication, expected)
    archive = _download_artifact(client, artifact)
    result = dict(verify_bundle(
        archive, commit=expected, tree=identity["tree"],
        publication_run=publication))
    _verify_safety_run(client, result)
    final_identity = current_identity(root)
    if final_identity != identity:
        _refuse("CERT_CURRENT_HEAD_CHANGED", "current Git identity changed during verification")
    result["artifact_digest"] = artifact["digest"]
    result["publication_url"] = publication.get("html_url")
    return result


def _write_output(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_current(commit=args.commit)
    except CertificationVerificationRefused as exc:
        detail_hash = _sha256(exc.detail.encode("utf-8"))
        print("REFUSED: %s [detail_sha256=%s]" % (exc.code, detail_hash), file=sys.stderr)
        return 2
    if args.output:
        _write_output(args.output, result)
    print("=== CERTIFIED SOFTWARE RUNTIME ===")
    print("source commit: %s" % result["source_commit"])
    print("certification schema: %s" % result["schema"])
    print("CI run: %s" % result["test_workflow_run"])
    print("required CI jobs: PASS")
    print("certified image: %s" % result["certified_image"])
    print("software certification: VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
