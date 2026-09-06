from __future__ import annotations

from pathlib import Path

import pytest

from tools import sentinel_ci_certification_input_binding as binding
from tools import sentinel_ci_certification_manifest as cert


COMMIT = "a" * 40
TREE = "b" * 40
RUNTIME_ID = "sha256:" + "c" * 64
LOCKS = ("sentinel/requirements.lock", "tests/requirements.lock")
TRACKED_TESTS = ("tests/requirements.lock", "tests/test_fixture.py")


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
    for name in (*LOCKS, "tests/test_fixture.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((name + "\n").encode("ascii"))

    def run(argv, *, cwd):
        assert cwd == root
        if argv == ["git", "rev-parse", "HEAD"]:
            return COMMIT + "\n"
        if argv == ["git", "rev-parse", "HEAD^{tree}"]:
            return TREE + "\n"
        if argv == ["git", "ls-files", "-z", "tests"]:
            return "\x00".join(TRACKED_TESTS) + "\x00"
        raise AssertionError(argv)

    def image_identity(_root, ref):
        assert _root == root
        assert ref == "sentinel:ci"
        return RUNTIME_ID, COMMIT

    monkeypatch.setattr(cert, "_run", run)
    monkeypatch.setattr(cert, "_docker_image_identity", image_identity)
    # Hash independent fixture bytes through the production hash functions.
    # Mutating submitted evidence must leave the observed source unchanged.
    evidence = _evidence()
    evidence["runtime_capability_sha256"] = cert.sha256_file(capability)
    evidence["dependency_lock_hashes"] = cert._dependency_hashes(root)
    evidence["test_manifest_sha256"] = cert._test_manifest_hash(root)
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
        ("runtime_capability_sha256", "f" * 64, "runtime capability"),
    ],
)
def test_binding_refuses_substituted_authority(
        monkeypatch, tmp_path, field, value, match):
    evidence = _patch_observations(monkeypatch, tmp_path)
    evidence[field] = value
    with pytest.raises(binding.InputBindingRefused, match=match):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize("name", LOCKS)
def test_binding_refuses_nested_dependency_hash_substitution(monkeypatch, tmp_path, name):
    evidence = _patch_observations(monkeypatch, tmp_path)
    observed = dict(evidence["dependency_lock_hashes"])
    evidence["dependency_lock_hashes"][name] = "f" * 64
    assert cert._dependency_hashes(tmp_path) == observed
    with pytest.raises(binding.InputBindingRefused, match="dependency lock hashes"):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize("name,match", [
    ("tests/test_fixture.py", "test manifest"),
    ("sentinel/requirements.lock", "dependency lock hashes"),
    ("tests/requirements.lock", "dependency lock hashes"),
    ("deploy/sentinel-authorized-runtime-v1", "runtime capability"),
])
def test_binding_refuses_source_bytes_changed_after_capture(
        monkeypatch, tmp_path, name, match):
    evidence = _patch_observations(monkeypatch, tmp_path)
    (tmp_path / name).write_bytes(b"changed after evidence capture\n")
    with pytest.raises(binding.InputBindingRefused, match=match):
        _verify(tmp_path, evidence)
