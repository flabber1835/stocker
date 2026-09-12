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
            "expected_xfails": {},
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


def _quarantined_input():
    evidence = _input()
    counts = evidence["test_counts"]
    counts["expected_xfails"] = {"wealth_core_boundary": {
        "nodeids": sorted(cert.WEALTH_EXPECTED_XFAILS), "junit_sha256": "7" * 64,
    }}
    counts["total"]["xfailed"] = 3
    counts["suite_counts"]["wealth_core_boundary"]["xfailed"] = 3
    return evidence


def _summary_paths(tmp_path, *, wealth="30 passed, 3 xfailed in 1.23s"):
    paths = {}
    for name, summary in (
        ("sentinel", "10 passed in 1.23s"),
        ("operator_scripts", "20 passed in 1.23s"),
        ("wealth_core_boundary", wealth),
    ):
        path = tmp_path / (name + ".txt")
        path.write_text(summary + "\n", encoding="utf-8")
        paths[name] = path
    return paths


def _execution():
    return {
        "schema": "stocker.test-owner-execution/3", "verdict": "PASS",
        "owner": "wealth-core.prospective", "complete_collection": True,
        "expected_xfails": sorted(cert.WEALTH_EXPECTED_XFAILS),
        "collected_nodes": 33, "executed_nodes": 33, "passing_nodes": 30,
    }


def test_certification_preserves_exact_quarantine_through_nas_verification():
    from scripts import sentinel_ci_certification_verify as host

    manifest = _finalize(_quarantined_input())
    cert.verify_manifest(manifest)
    host._verify_manifest(manifest, COMMIT, TREE, {"id": 5678, "run_attempt": 1})
    assert manifest["certification_version"] == 2
    assert manifest["tests"]["required_counts"]["passed"] == 123
    assert manifest["tests"]["required_counts"]["xfailed"] == 3
    assert manifest["tests"]["expected_xfails"] == _quarantined_input()["test_counts"]["expected_xfails"]


def test_legacy_certificate_keeps_its_all_pass_contract():
    from scripts import sentinel_ci_certification_verify as host

    evidence = _input()
    evidence["schema"] = cert.LEGACY_INPUT_SCHEMA
    del evidence["test_counts"]["expected_xfails"]
    manifest = _finalize(evidence)
    cert.verify_manifest(manifest)
    host._verify_manifest(manifest, COMMIT, TREE, {"id": 5678, "run_attempt": 1})
    assert manifest["schema"] == cert.LEGACY_MANIFEST_SCHEMA
    assert "expected_xfails" not in manifest["tests"]


def test_xfail_summary_requires_fresh_owner_execution(tmp_path):
    paths = _summary_paths(tmp_path)
    with pytest.raises(cert.CertificationManifestRefused, match="non-passes"):
        cert.collect_test_counts(paths)
    junit = tmp_path / "wealth.xml"
    junit.write_text("current JUnit bytes", encoding="utf-8")
    counts = cert.collect_test_counts(paths, wealth_execution=_execution(), wealth_junit=junit)
    assert counts["total"]["passed"] == 60
    assert counts["total"]["xfailed"] == 3
    assert counts["expected_xfails"]["wealth_core_boundary"]["junit_sha256"] == cert.sha256_file(junit)


@pytest.mark.parametrize("key,value", [
    ("schema", "stocker.test-owner-execution/2"), ("owner", "sentinel.complete"),
    ("verdict", "FAIL"), ("complete_collection", False), ("expected_xfails", []),
    ("collected_nodes", 34), ("executed_nodes", 32), ("passing_nodes", 29),
])
def test_xfail_summary_rejects_invalid_execution_evidence(tmp_path, key, value):
    junit = tmp_path / "wealth.xml"
    junit.write_text("current JUnit bytes", encoding="utf-8")
    evidence = _execution()
    evidence[key] = value
    with pytest.raises(cert.CertificationManifestRefused):
        cert.collect_test_counts(_summary_paths(tmp_path), wealth_execution=evidence, wealth_junit=junit)


@pytest.mark.parametrize("kind", ["failed", "errors", "skipped", "xpassed", "deselected"])
def test_authorized_xfails_do_not_mask_other_outcomes(tmp_path, kind):
    junit = tmp_path / "wealth.xml"
    junit.write_text("current JUnit bytes", encoding="utf-8")
    paths = _summary_paths(tmp_path, wealth=f"30 passed, 3 xfailed, 1 {kind} in 1.23s")
    with pytest.raises(cert.CertificationManifestRefused):
        cert.collect_test_counts(paths, wealth_execution=_execution(), wealth_junit=junit)


def test_assembly_reexecutes_owner_verifier_against_current_junit(tmp_path):
    import json

    script = tmp_path / "tools" / "verify_test_owner_execution.py"
    script.parent.mkdir()
    junit = tmp_path / "wealth.xml"
    junit.write_text("current JUnit bytes", encoding="utf-8")
    script.write_text(
        "import json, sys\n"
        f"assert sys.argv[1:] == ['--owner', 'wealth-core.prospective', '--junit', {str(junit)!r}]\n"
        f"print({json.dumps(_execution())!r})\n", encoding="utf-8")
    assert cert._wealth_execution(tmp_path, junit) == _execution()
    script.write_text("raise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(cert.CertificationManifestRefused, match="command failed"):
        cert._wealth_execution(tmp_path, junit)


@pytest.mark.parametrize("mutation", [
    "wrong-node", "missing-node", "duplicate-node", "missing-hash", "wrong-suite",
    "missing-outcome", "extra-outcome", "unreported-outcome", "downgrade", "bool-count",
])
def test_rehashed_manifest_cannot_widen_or_lose_expected_failure_authority(mutation):
    from scripts import sentinel_ci_certification_verify as host

    manifest = _finalize(_quarantined_input())
    tests = manifest["tests"]
    quarantine = tests["expected_xfails"]["wealth_core_boundary"]
    if mutation == "wrong-node":
        quarantine["nodeids"][0] += "_unreviewed"
    elif mutation == "missing-node":
        quarantine["nodeids"].pop()
    elif mutation == "duplicate-node":
        quarantine["nodeids"].append(quarantine["nodeids"][0])
    elif mutation == "missing-hash":
        del quarantine["junit_sha256"]
    elif mutation == "wrong-suite":
        tests["expected_xfails"] = {"sentinel": quarantine}
    elif mutation == "missing-outcome":
        tests["suite_counts"]["wealth_core_boundary"]["xfailed"] = 2
    elif mutation == "extra-outcome":
        tests["suite_counts"]["sentinel"]["xfailed"] = 1
    elif mutation == "unreported-outcome":
        tests["required_counts"]["xfailed"] = 0
    elif mutation == "downgrade":
        manifest["schema"] = cert.LEGACY_MANIFEST_SCHEMA
        manifest["certification_version"] = 1
    elif mutation == "bool-count":
        tests["suite_counts"]["sentinel"]["skipped"] = False
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = cert.sha256_bytes(cert.canonical_bytes(manifest))
    with pytest.raises(cert.CertificationManifestRefused):
        cert.verify_manifest(manifest)
    with pytest.raises(host.CertificationVerificationRefused):
        host._verify_manifest(manifest, COMMIT, TREE, {"id": 5678, "run_attempt": 1})
