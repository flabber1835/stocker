from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SUITE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or SUITE_ROOT)
SCRIPT_ROOT = SUITE_ROOT / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import sentinel_go_ci_runtime as ci  # noqa: E402


COMMIT = "a" * 40
REGISTRY_DIGEST = "sha256:" + "b" * 64
LOCAL_ID = "sha256:" + "c" * 64
SUBJECT = "ghcr.io/flabber1835/stocker/sentinel"
IMMUTABLE_REF = SUBJECT + "@" + REGISTRY_DIGEST
TOKEN = "d" * 64
BOOT = "e" * 64
IDENTITY = "f" * 64


def _image(repo_digests=None, revision=COMMIT, local_id=LOCAL_ID):
    return {
        "Id": local_id,
        "RepoDigests": list(repo_digests if repo_digests is not None else [IMMUTABLE_REF]),
        "Config": {"Labels": {"org.opencontainers.image.revision": revision}},
    }


class FakeRunner:
    def __init__(self, image=None, *, miss_first=False):
        self.image = image or _image()
        self.miss_first = miss_first
        self.inspect_calls = 0
        self.calls = []

    def run(self, argv, *, env=None, cwd=ci.go.ROOT):
        command = [str(item) for item in argv]
        self.calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            self.inspect_calls += 1
            if self.miss_first and self.inspect_calls == 1:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="missing")
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps([self.image]), stderr="")
        if command[:2] == ["docker", "pull"]:
            return subprocess.CompletedProcess(command, 0, stdout="pulled", stderr="")
        if command[:2] == ["docker", "tag"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)


def test_cached_exact_registry_digest_is_reused_without_pull(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(ci.go, "_inspect_image_id", lambda _runner, _ref: LOCAL_ID)

    result = ci._ensure_exact_image(
        runner, immutable_ref=IMMUTABLE_REF,
        registry_digest=REGISTRY_DIGEST, commit=COMMIT)

    assert result == LOCAL_ID
    assert not any(call[:2] == ["docker", "pull"] for call in runner.calls)
    assert ["docker", "tag", IMMUTABLE_REF, "sentinel-go-runtime:" + COMMIT] \
        in runner.calls


def test_missing_exact_registry_digest_is_pulled_then_bound(monkeypatch):
    runner = FakeRunner(miss_first=True)
    monkeypatch.setattr(ci.go, "_inspect_image_id", lambda _runner, _ref: LOCAL_ID)

    result = ci._ensure_exact_image(
        runner, immutable_ref=IMMUTABLE_REF,
        registry_digest=REGISTRY_DIGEST, commit=COMMIT)

    assert result == LOCAL_ID
    assert ["docker", "pull", IMMUTABLE_REF] in runner.calls
    assert runner.inspect_calls == 2


def test_wrong_cached_repo_digest_refuses(monkeypatch):
    wrong = SUBJECT + "@sha256:" + "9" * 64
    runner = FakeRunner(_image(repo_digests=[wrong]))
    monkeypatch.setattr(ci.go, "_inspect_image_id", lambda _runner, _ref: LOCAL_ID)

    with pytest.raises(ci.CIRuntimeRefused, match="certified registry digest"):
        ci._ensure_exact_image(
            runner, immutable_ref=IMMUTABLE_REF,
            registry_digest=REGISTRY_DIGEST, commit=COMMIT)


def test_wrong_certificate_reference_digest_refuses_before_docker():
    runner = FakeRunner()
    with pytest.raises(ci.CIRuntimeRefused, match="reference/digest disagree"):
        ci._ensure_exact_image(
            runner, immutable_ref=IMMUTABLE_REF,
            registry_digest="sha256:" + "8" * 64, commit=COMMIT)
    assert runner.calls == []


def test_current_run_binding_cannot_be_reused_by_another_go_invocation(
        monkeypatch, tmp_path):
    path = tmp_path / "binding.json"
    monkeypatch.setattr(ci, "BINDING_PATH", path)
    monkeypatch.setattr(ci, "_boot_hash", lambda: BOOT)
    monkeypatch.setattr(ci.go_lock, "current_run_token", lambda: TOKEN)
    result = {
        "certified_image": IMMUTABLE_REF,
        "image_digest": REGISTRY_DIGEST,
        "test_workflow_run": 101,
        "publication_workflow_run": 202,
    }
    ci._write_binding(
        commit=COMMIT, result=result, local_id=LOCAL_ID,
        source_identity=IDENTITY, passed_tests=3612,
        token=TOKEN, boot_hash=BOOT)

    loaded = ci.load_binding(commit=COMMIT)
    assert loaded["certified_image"] == IMMUTABLE_REF
    assert loaded["local_image_id"] == LOCAL_ID

    monkeypatch.setattr(ci.go_lock, "current_run_token", lambda: "1" * 64)
    with pytest.raises(ci.CIRuntimeRefused, match="another GO invocation"):
        ci.load_binding(commit=COMMIT)


def test_verifier_refusal_fails_software_certification_gate(monkeypatch):
    monkeypatch.setattr(ci.go_lock, "current_run_token", lambda: TOKEN)
    monkeypatch.setattr(ci, "_boot_hash", lambda: BOOT)

    def refuse(*_args, **_kwargs):
        raise ci.verifier.CertificationVerificationRefused(
            "CERT_NO_PUBLICATION", "fixture")

    monkeypatch.setattr(ci.verifier, "verify_current", refuse)
    git = ci.go.GitIdentity(
        commit=COMMIT, branch_is_main=True, clean=True, origin_main=COMMIT)

    summary, gate = ci.certify_from_ci(
        FakeRunner(), git=git, now_text="2026-09-06T15:00:00Z",
        run_suite=True)

    assert not summary.complete
    assert gate.status == ci.go.FAIL


def test_local_full_build_graph_has_one_runtime_and_one_test_lens_only():
    source = (REPO_ROOT / "scripts" / "sentinel_go_local_full_runtime.py").read_text()
    assert 'runtime_ref = "sentinel-go-runtime:%s" % commit' in source
    assert 'test_ref = "sentinel-go-test:%s" % commit' in source
    assert "sentinel-go-authorized" not in source
    assert "Dockerfile.sentinel-authorized" not in source
    assert '"SENTINEL_IMAGE=" + runtime_ref' in source


def test_default_launcher_uses_ci_and_local_full_is_explicit():
    launcher = (REPO_ROOT / "scripts" / "sentinel-go-validate.sh").read_text()
    entry = (REPO_ROOT / "scripts" / "sentinel_go_verified_entry.py").read_text()
    assert "--local-full-certification" in launcher
    assert '[ "$LOCAL_FULL" -eq 1 ]' in launcher
    assert "sentinel_go_readonly_data_preflight.py" in launcher
    assert "CI_CERTIFIED_RUNTIME" in entry
    assert "LOCAL_FULL" in entry
    assert "ci_runtime.certify_from_ci" in entry
    assert "local_full_runtime.certify_local_full" in entry


def test_ci_promotion_selects_registry_digest_only_after_target_proof():
    source = (REPO_ROOT / "scripts" / "sentinel_go_promote.py").read_text()
    assert "_current_run_target_pass(head)" in source
    assert "ci_runtime.load_binding" in source
    assert "verifier.verify_current" in source
    assert "runtime._write_pointer(certified_image)" in source
    assert source.index("_current_run_target_pass(head)") < source.index(
        "_promote_ci(head=head, runner=runner)")


def test_compose_pointer_accepts_registry_digest_and_rejects_mutable_tag():
    source = (REPO_ROOT / "scripts" / "sentinel-compose.sh").read_text()
    assert "ghcr\\.io/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}" in source
    assert "local_id is None and registry_ref is None" in source
    assert "ghcr.io/flabber1835/stocker/sentinel:latest" not in source
