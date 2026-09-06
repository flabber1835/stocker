from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

import pytest

from scripts import sentinel_ci_certification_verify as verify


COMMIT = "a" * 40
TREE = "b" * 40
DIGEST = "sha256:" + "c" * 64
SUBJECT = verify.EXPECTED_SUBJECT
PUBLICATION = {"id": 9001, "run_attempt": 1}


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _suite(passed):
    return {
        "passed": passed, "failed": 0, "errors": 0,
        "skipped": 0, "xfailed": 0, "xpassed": 0,
    }


def _rehash(manifest):
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = hashlib.sha256(_canonical(manifest)).hexdigest()
    return manifest


def _manifest():
    value = {
        "schema": verify.CERTIFICATION_SCHEMA,
        "certification_version": 1,
        "source": {
            "repository": verify.REPOSITORY,
            "commit": COMMIT,
            "tree": TREE,
        },
        "runtime": {
            "subject_name": SUBJECT,
            "docker_image_digest": DIGEST,
            "immutable_ref": SUBJECT + "@" + DIGEST,
            "ci_local_image_id": "sha256:" + "d" * 64,
            "runtime_capability_sha256": "e" * 64,
            "broker_capable": True,
        },
        "dependencies": {
            "lock_hashes": {
                "sentinel/requirements.lock": "1" * 64,
                "tests/requirements.lock": "2" * 64,
            }
        },
        "tests": {
            "manifest_sha256": "3" * 64,
            "required_counts": {
                "passed": 100, "suites_completed": 3,
                "failed": 0, "errors": 0, "skipped": 0,
                "xfailed": 0, "xpassed": 0,
            },
            "suite_counts": {
                "operator_scripts": _suite(34),
                "sentinel": _suite(33),
                "wealth_core_boundary": _suite(33),
            },
            "required_job_conclusions": {
                name: "success" for name in verify.REQUIRED_JOBS
            },
            "adversarial_evidence": {"status": "PASS", "sha256": "4" * 64},
            "mutation_evidence": {"status": "PASS", "sha256": "5" * 64},
        },
        "ci": {
            "test_workflow_path": verify.SAFETY_WORKFLOW_PATH,
            "test_workflow_run": 7001,
            "test_workflow_attempt": 1,
            "publication_workflow_run": PUBLICATION["id"],
            "publication_workflow_attempt": PUBLICATION["run_attempt"],
        },
        "epochs": {
            "runtime_schema": verify.RUNTIME_SCHEMA_EPOCH,
            "semantic": verify.SEMANTIC_EPOCH,
        },
        "certified_at": "2026-09-06T06:00:00Z",
    }
    return _rehash(value)


def _attestation():
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [{
            "name": SUBJECT,
            "digest": {"sha256": DIGEST.split(":", 1)[1]},
        }],
    }
    return {
        "dsseEnvelope": {
            "payload": base64.b64encode(_canonical(statement)).decode("ascii"),
            "signatures": [{"sig": "fixture"}],
        }
    }


def _archive(manifest=None, provenance_mutator=None, attestation=None):
    manifest = manifest or _manifest()
    certification = _canonical(manifest) + b"\n"
    provenance = {
        "schema": verify.PROVENANCE_SCHEMA,
        "commit": COMMIT,
        "publication_workflow_run": PUBLICATION["id"],
        "test_workflow_run": 7001,
        "subject_name": SUBJECT,
        "tested_image_digest": DIGEST,
        "immutable_runtime": SUBJECT + "@" + DIGEST,
        "certification_manifest_sha256": hashlib.sha256(certification).hexdigest(),
    }
    if provenance_mutator:
        provenance_mutator(provenance)
    files = {
        "certification.json": certification,
        "provenance.json": _canonical(provenance) + b"\n",
        "attestation.sigstore.json": _canonical(attestation or _attestation()) + b"\n",
    }
    sums = "".join(
        "%s  %s\n" % (hashlib.sha256(raw).hexdigest(), name)
        for name, raw in files.items()
    ).encode("ascii")
    files["SHA256SUMS"] = sums
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in files.items():
            bundle.writestr(name, raw)
    return output.getvalue()


def test_valid_bundle_binds_exact_single_runtime_and_workflows():
    result = verify.verify_bundle(_archive(), COMMIT, TREE, PUBLICATION)
    assert result["certified_image"] == SUBJECT + "@" + DIGEST
    assert result["image_digest"] == DIGEST
    assert result["broker_capable"] is True
    assert result["test_workflow_run"] == 7001
    assert result["required_ci_jobs"] == "PASS"


def test_tampered_manifest_refuses_with_stable_code():
    manifest = _manifest()
    manifest["source"]["commit"] = "f" * 40
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(manifest=manifest), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_MANIFEST_TAMPERED"


def test_wrong_source_tree_refuses():
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(), COMMIT, "f" * 40, PUBLICATION)
    assert caught.value.code == "CERT_SOURCE_TREE_MISMATCH"


def test_unknown_manifest_schema_refuses_after_valid_integrity_hash():
    manifest = _manifest()
    manifest["schema"] = "sentinel.software-certification/999"
    _rehash(manifest)
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(manifest=manifest), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_MANIFEST_SCHEMA_UNKNOWN"


def test_wrong_runtime_subject_refuses():
    manifest = _manifest()
    manifest["runtime"]["subject_name"] = "ghcr.io/flabber1835/stocker/other"
    manifest["runtime"]["immutable_ref"] = (
        manifest["runtime"]["subject_name"] + "@" + DIGEST)
    _rehash(manifest)
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(manifest=manifest), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_RUNTIME_SUBJECT_INVALID"


def test_runtime_must_be_broker_capable():
    manifest = _manifest()
    manifest["runtime"]["broker_capable"] = False
    _rehash(manifest)
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(manifest=manifest), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_RUNTIME_CAPABILITY_INVALID"


def test_unknown_epoch_refuses():
    manifest = _manifest()
    manifest["epochs"]["semantic"] = "sentinel.automation_cycle/999"
    _rehash(manifest)
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(manifest=manifest), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_EPOCH_UNSUPPORTED"


def test_nonpass_suite_count_refuses():
    manifest = _manifest()
    manifest["tests"]["suite_counts"]["sentinel"]["skipped"] = 1
    _rehash(manifest)
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(_archive(manifest=manifest), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_TEST_COUNTS_INVALID"


def test_provenance_digest_substitution_refuses():
    def mutate(value):
        value["tested_image_digest"] = "sha256:" + "8" * 64
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(
            _archive(provenance_mutator=mutate), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_PROVENANCE_BINDING_INVALID"


def test_attestation_subject_substitution_refuses():
    attestation = _attestation()
    payload = json.loads(base64.b64decode(attestation["dsseEnvelope"]["payload"]))
    payload["subject"][0]["digest"]["sha256"] = "7" * 64
    attestation["dsseEnvelope"]["payload"] = base64.b64encode(
        _canonical(payload)).decode("ascii")
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify.verify_bundle(
            _archive(attestation=attestation), COMMIT, TREE, PUBLICATION)
    assert caught.value.code == "CERT_ATTESTATION_BINDING_INVALID"


class _SafetyClient:
    def __init__(self, jobs):
        self.jobs = jobs

    def json(self, path):
        if path.endswith("/jobs?per_page=100"):
            return {"jobs": self.jobs}
        repository = {"id": verify.REPOSITORY_ID, "full_name": verify.REPOSITORY}
        return {
            "workflow_id": verify.SAFETY_WORKFLOW_ID,
            "path": verify.SAFETY_WORKFLOW_PATH,
            "head_sha": COMMIT,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "repository": repository,
            "head_repository": dict(repository),
        }


def _result():
    return {
        "test_workflow_run": 7001,
        "test_workflow_attempt": 1,
        "source_commit": COMMIT,
    }


def test_required_safety_jobs_are_reobserved():
    jobs = [{"name": name, "conclusion": "success"}
            for name in verify.REQUIRED_JOBS]
    verify._verify_safety_run(_SafetyClient(jobs), _result())


def test_missing_required_safety_job_refuses():
    jobs = [{"name": verify.REQUIRED_JOBS[0], "conclusion": "success"}]
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify._verify_safety_run(_SafetyClient(jobs), _result())
    assert caught.value.code == "CERT_REQUIRED_JOB_MISSING"


def test_failed_required_safety_job_refuses():
    jobs = [
        {"name": verify.REQUIRED_JOBS[0], "conclusion": "success"},
        {"name": verify.REQUIRED_JOBS[1], "conclusion": "failure"},
    ]
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        verify._verify_safety_run(_SafetyClient(jobs), _result())
    assert caught.value.code == "CERT_REQUIRED_JOB_FAILED"
