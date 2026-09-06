from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tools import sentinel_ci_certification_manifest as cert


COMMIT = "a" * 40
TREE = "b" * 40
RUNTIME_DIGEST = "sha256:" + "c" * 64
RUNTIME_ID = "sha256:" + "d" * 64
RUNTIME_SUBJECT = cert.RUNTIME_SUBJECT


def _suite(passed=41):
    row = {key: 0 for key in cert._COUNT_KEYS}
    row["passed"] = passed
    return row


def _input():
    return {
        "schema": cert.INPUT_SCHEMA,
        "repository": cert.REPOSITORY,
        "source_commit": COMMIT,
        "source_tree": TREE,
        "test_workflow_path": cert.TEST_WORKFLOW_PATH,
        "test_workflow_run": 1234,
        "test_workflow_attempt": 1,
        "runtime_image_id": RUNTIME_ID,
        "runtime_capability_sha256": "1" * 64,
        "dependency_lock_hashes": {
            "sentinel/requirements.lock": "2" * 64,
            "tests/requirements.lock": "3" * 64,
        },
        "test_manifest_sha256": "4" * 64,
        "test_counts": {
            "suites_completed": 3,
            "suite_counts": {
                "operator_scripts": _suite(),
                "sentinel": _suite(),
                "wealth_core_boundary": _suite(),
            },
            "total": _suite(123),
        },
        "adversarial_evidence": {"status": "PASS", "sha256": "5" * 64},
        "mutation_evidence": {"status": "PASS", "sha256": "6" * 64},
        "runtime_schema_epoch": cert.RUNTIME_SCHEMA_EPOCH,
        "semantic_epoch": cert.SEMANTIC_EPOCH,
    }


def _jobs(**overrides):
    conclusions = {name: "success" for name in cert.REQUIRED_JOBS}
    conclusions.update(overrides)
    return {"jobs": [
        {"name": name, "conclusion": conclusions[name]}
        for name in cert.REQUIRED_JOBS
    ]}


def _finalize(evidence=None, jobs=None, subject=RUNTIME_SUBJECT):
    return cert.finalize_manifest(
        input_evidence=evidence or _input(),
        jobs_payload=jobs or _jobs(),
        subject_name=subject,
        image_digest=RUNTIME_DIGEST,
        publication_run=5678,
        publication_attempt=1,
        certified_at="2026-09-06T06:00:00Z",
    )


def test_final_manifest_binds_one_broker_capable_runtime_source_ci_and_hash():
    manifest = _finalize()
    cert.verify_manifest(manifest)
    assert manifest["source"] == {
        "repository": cert.REPOSITORY,
        "commit": COMMIT,
        "tree": TREE,
    }
    runtime = manifest["runtime"]
    assert runtime["subject_name"] == RUNTIME_SUBJECT
    assert runtime["docker_image_digest"] == RUNTIME_DIGEST
    assert runtime["immutable_ref"] == RUNTIME_SUBJECT + "@" + RUNTIME_DIGEST
    assert runtime["ci_local_image_id"] == RUNTIME_ID
    assert runtime["runtime_capability_sha256"] == "1" * 64
    assert runtime["broker_capable"] is True
    assert manifest["tests"]["required_counts"]["passed"] == 123
    assert len(manifest["manifest_sha256"]) == 64


def test_tampered_manifest_refuses():
    manifest = _finalize()
    manifest["source"]["commit"] = "f" * 40
    with pytest.raises(cert.CertificationManifestRefused, match="integrity"):
        cert.verify_manifest(manifest)


def test_wrong_runtime_subject_refuses():
    with pytest.raises(cert.CertificationManifestRefused, match="subject"):
        _finalize(subject="ghcr.io/flabber1835/stocker/sentinel-authorized")


def test_manifest_cannot_claim_runtime_is_not_broker_capable():
    manifest = _finalize()
    manifest["runtime"]["broker_capable"] = False
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = cert.sha256_bytes(cert.canonical_bytes(manifest))
    with pytest.raises(cert.CertificationManifestRefused, match="runtime authority"):
        cert.verify_manifest(manifest)


def test_missing_required_ci_job_refuses():
    jobs = _jobs()
    jobs["jobs"].pop()
    with pytest.raises(cert.CertificationManifestRefused, match="missing"):
        _finalize(jobs=jobs)


def test_failed_required_ci_job_refuses():
    with pytest.raises(cert.CertificationManifestRefused, match="did not succeed"):
        _finalize(jobs=_jobs(**{"sentinel-exact-head": "failure"}))


def test_nonpass_test_count_refuses():
    evidence = _input()
    evidence["test_counts"]["total"]["skipped"] = 1
    with pytest.raises(cert.CertificationManifestRefused, match="non-passes"):
        _finalize(evidence=evidence)


def test_pytest_summary_counts_three_required_suites(tmp_path: Path):
    paths = {}
    for name, count in (
        ("sentinel", 10),
        ("operator_scripts", 20),
        ("wealth_core_boundary", 30),
    ):
        path = tmp_path / (name + ".txt")
        path.write_text("progress\n%d passed in 1.23s\n" % count, encoding="utf-8")
        paths[name] = path
    counts = cert.collect_test_counts(paths)
    assert counts["suites_completed"] == 3
    assert counts["total"] == _suite(60)


def test_duplicate_required_job_refuses():
    jobs = _jobs()
    jobs["jobs"].append(deepcopy(jobs["jobs"][0]))
    with pytest.raises(cert.CertificationManifestRefused, match="duplicated"):
        _finalize(jobs=jobs)
