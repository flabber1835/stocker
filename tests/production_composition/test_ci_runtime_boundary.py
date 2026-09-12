from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_ci_runtime as ci  # noqa: E402

COMMIT = "a" * 40
TREE = "b" * 40
REGISTRY = "sha256:" + "c" * 64
LOCAL = "sha256:" + "d" * 64
IMMUTABLE = "ghcr.io/flabber1835/stocker/sentinel@" + REGISTRY
NOW = "2026-09-11T04:00:00Z"


class NullRunner:
    def run(self, argv, *, env=None, cwd=ROOT):
        raise AssertionError(f"unexpected runner call: {argv}")


def _git():
    return ci.go.GitIdentity(
        commit=COMMIT, branch_is_main=True, clean=True, origin_main=COMMIT)


def _prepare_identity(monkeypatch):
    monkeypatch.setattr(ci.go_lock, "current_run_token", lambda: "1" * 64)
    monkeypatch.setattr(ci, "_boot_hash", lambda: "2" * 64)


@pytest.mark.parametrize(("sentinel", "github", "expected"), [
    ("sentinel-token", "github-token", "sentinel-token"),
    (None, "github-token", "github-token"),
    (None, None, None),
])
def test_ci_verifier_credential_precedence_is_exact(
        monkeypatch, sentinel, github, expected):
    _prepare_identity(monkeypatch)
    captured = {}

    class Client:
        def __init__(self, token=None, opener=None):
            captured["token"] = token

    monkeypatch.setattr(ci.verifier, "GitHubReadClient", Client)
    monkeypatch.setattr(
        ci.verifier, "verify_current",
        lambda **_kwargs: (_ for _ in ()).throw(
            ci.verifier.CertificationVerificationRefused(
                "CERT_GITHUB_UNAVAILABLE", "fixture refusal")))
    if sentinel is None:
        monkeypatch.delenv("SENTINEL_GITHUB_READ_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SENTINEL_GITHUB_READ_TOKEN", sentinel)
    if github is None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_TOKEN", github)

    summary, gate = ci.certify_from_ci(
        NullRunner(), git=_git(), now_text=NOW, run_suite=True)

    assert captured["token"] == expected
    assert summary.complete is False
    assert gate.status == ci.go.FAIL


@pytest.mark.parametrize("reason", [
    "CERT_GITHUB_UNAVAILABLE",
    "CERT_NO_PUBLICATION",
    "CERT_ARTIFACT_MISSING",
    "CERT_ARTIFACT_DIGEST_INVALID",
    "CERT_ARTIFACT_DIGEST_MISMATCH",
    "CERT_SOURCE_SHA_MISMATCH",
])
def test_ci_certificate_refusal_reason_survives_to_go_gate(monkeypatch, reason):
    _prepare_identity(monkeypatch)

    class Client:
        def __init__(self, token=None, opener=None):
            self.token = token

    monkeypatch.setattr(ci.verifier, "GitHubReadClient", Client)
    monkeypatch.setattr(
        ci.verifier, "verify_current",
        lambda **_kwargs: (_ for _ in ()).throw(
            ci.verifier.CertificationVerificationRefused(reason, "fixture")))
    monkeypatch.setenv("SENTINEL_GITHUB_READ_TOKEN", "fixture-token")

    _summary, gate = ci.certify_from_ci(
        NullRunner(), git=_git(), now_text=NOW, run_suite=True)

    expected = ci.go.make_gate(
        "certified_suite_no_skips", ci.go.FAIL, NOW, {"reason": reason})
    assert gate.status == ci.go.FAIL
    assert gate.evidence_sha256 == expected.evidence_sha256


class ImageRunner:
    def __init__(self, *, pull_rc=0, revision=COMMIT, repo_digest=True):
        self.pull_rc = pull_rc
        self.revision = revision
        self.repo_digest = repo_digest
        self.present = False
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        command = [str(item) for item in argv]
        self.calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            if not self.present:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="missing")
            payload = [{
                "Id": LOCAL,
                "RepoDigests": [IMMUTABLE] if self.repo_digest else [],
                "Config": {"Labels": {
                    "org.opencontainers.image.revision": self.revision,
                }},
            }]
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(payload), stderr="")
        if command[:2] == ["docker", "pull"]:
            if self.pull_rc == 0:
                self.present = True
            return subprocess.CompletedProcess(
                command, self.pull_rc, stdout="", stderr="")
        if command[:2] == ["docker", "tag"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)


def test_missing_certified_image_is_pulled_then_bound_to_exact_revision(monkeypatch):
    runner = ImageRunner()
    monkeypatch.setattr(ci.go, "_inspect_image_id", lambda _runner, _ref: LOCAL)
    result = ci._ensure_exact_image(
        runner, immutable_ref=IMMUTABLE,
        registry_digest=REGISTRY, commit=COMMIT)
    assert result == LOCAL
    assert ["docker", "pull", IMMUTABLE] in runner.calls
    assert any(call[:2] == ["docker", "tag"] for call in runner.calls)


@pytest.mark.parametrize(("kind", "fragment"), [
    ("pull", "could not be pulled"),
    ("revision", "source revision differs"),
    ("digest", "not bound to the certified registry digest"),
    ("tag", "tag does not resolve"),
])
def test_registry_to_local_binding_fails_closed_on_adversarial_image_state(
        monkeypatch, kind, fragment):
    runner = ImageRunner(
        pull_rc=1 if kind == "pull" else 0,
        revision="f" * 40 if kind == "revision" else COMMIT,
        repo_digest=kind != "digest",
    )
    tagged = "sha256:" + "e" * 64 if kind == "tag" else LOCAL
    monkeypatch.setattr(ci.go, "_inspect_image_id", lambda _runner, _ref: tagged)
    with pytest.raises(ci.CIRuntimeRefused, match=fragment):
        ci._ensure_exact_image(
            runner, immutable_ref=IMMUTABLE,
            registry_digest=REGISTRY, commit=COMMIT)


def test_registry_digest_mismatch_is_refused_before_any_docker_call():
    runner = ImageRunner()
    wrong = "sha256:" + "e" * 64
    with pytest.raises(ci.CIRuntimeRefused, match="reference/digest disagree"):
        ci._ensure_exact_image(
            runner, immutable_ref=IMMUTABLE,
            registry_digest=wrong, commit=COMMIT)
    assert runner.calls == []
