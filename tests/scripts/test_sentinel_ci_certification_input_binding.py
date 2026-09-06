from __future__ import annotations

from pathlib import Path

import pytest

from tools import sentinel_ci_certification_input_binding as binding
from tools import sentinel_ci_certification_manifest as cert


COMMIT = "a" * 40
TREE = "b" * 40
RUNTIME_ID = "sha256:" + "c" * 64


def _suite(passed=1):
    row = {key: 0 for key in cert._COUNT_KEYS}
    row["passed"] = passed
    return row


def _evidence():
    return {
        "schema": cert.INPUT_SCHEMA,
        "repository": cert.REPOSITORY,
        "source_commit": COMMIT,
        "source_tree": TREE,
        "test_workflow_path": cert.TEST_WORKFLOW_PATH,
        "test_workflow_run": 101,
        "test_workflow_attempt": 2,
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
            "total": _suite(3),
        },
        "adversarial_evidence": {"status": "PASS", "sha256": "5" * 64},
        "mutation_evidence": {"status": "PASS", "sha256": "6" * 64},
        "runtime_schema_epoch": cert.RUNTIME_SCHEMA_EPOCH,
        "semantic_epoch": cert.SEMANTIC_EPOCH,
    }


def _patch_observations(monkeypatch, root: Path):
    capability = root / "deploy" / "sentinel-authorized-runtime-v1"
    capability.parent.mkdir(parents=True)
    capability.write_bytes(b"capability")
    evidence = _evidence()
    evidence["runtime_capability_sha256"] = cert.sha256_file(capability)

    def run(argv, *, cwd):
        assert cwd == root
        if argv[-1] == "HEAD":
            return COMMIT + "\n"
        if argv[-1] == "HEAD^{tree}":
            return TREE + "\n"
        raise AssertionError(argv)

    def image_identity(_root, ref):
        assert ref == "sentinel:ci"
        return RUNTIME_ID, COMMIT

    monkeypatch.setattr(cert, "_run", run)
    monkeypatch.setattr(cert, "_docker_image_identity", image_identity)
    monkeypatch.setattr(
        cert, "_dependency_hashes", lambda _root: evidence["dependency_lock_hashes"])
    monkeypatch.setattr(
        cert, "_test_manifest_hash", lambda _root: evidence["test_manifest_sha256"])
    return evidence


def _verify(root, evidence):
    binding.verify_binding(
        root=root,
        evidence=evidence,
        expected_commit=COMMIT,
        expected_workflow_run=101,
        expected_workflow_attempt=2,
        image_ref="sentinel:ci",
    )


def test_binding_reobserves_exact_trigger_checkout_and_runtime(monkeypatch, tmp_path):
    evidence = _patch_observations(monkeypatch, tmp_path)
    _verify(tmp_path, evidence)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("source_commit", "f" * 40, "source commit"),
        ("source_tree", "f" * 40, "source tree"),
        ("test_workflow_run", 999, "workflow run"),
        ("test_workflow_attempt", 999, "workflow attempt"),
        ("runtime_image_id", "sha256:" + "e" * 64, "runtime image ID"),
        ("test_manifest_sha256", "f" * 64, "test manifest"),
    ],
)
def test_binding_refuses_substituted_authority(
        monkeypatch, tmp_path, field, value, match):
    evidence = _patch_observations(monkeypatch, tmp_path)
    evidence[field] = value
    with pytest.raises(binding.InputBindingRefused, match=match):
        _verify(tmp_path, evidence)
