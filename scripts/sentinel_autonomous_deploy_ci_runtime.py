"""Read-only admission of the one signed runtime for reviewed installation."""
from __future__ import annotations

import json
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
from typing import Mapping

import sentinel_ci_certification_verify as verifier


class CertifiedInstallRefused(RuntimeError):
    pass


def _verification_context(root: Path, commit: str):
    """Cheap local facts, never a substitute for the initial signed verification."""
    identity = verifier.current_identity(root)
    if identity['commit'] != commit or verifier._git(
            root, 'status', '--porcelain', '--untracked-files=all'):
        raise CertifiedInstallRefused('software proof requires its exact clean checkout')
    policy = verifier._promotion_policy()
    modules = (verifier, policy)
    sources = tuple((str(Path(module.__file__).resolve()),
                     hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
                    for module in modules)
    # These globals select trusted repositories, workflows, schemas and subjects.
    # Bind their loaded values as well as the files from which they were imported.
    trust = tuple((module.__name__, tuple(sorted(
        (key, repr(value)) for key, value in vars(module).items()
        if key.isupper()))) for module in modules)
    return (os.getpid(), str(Path(root).resolve()), identity, sources, trust)


class SoftwareVerification:
    """One deployment owner; never persist or inherit its authenticated result."""
    def __init__(self):
        self._context = None
        self._result = None

    def verify(self, *, root: Path, commit: str, env: Mapping[str, str]):
        try:
            context = _verification_context(root, commit)
            if self._context is not None:
                if context != self._context:
                    raise CertifiedInstallRefused('software verification context changed')
                return deepcopy(self._result)
            result = verifier.verify_current(
                root=root, commit=commit,
                client=verifier.GitHubReadClient(
                    token=env.get('SENTINEL_GITHUB_READ_TOKEN')
                    or env.get('GITHUB_TOKEN') or env.get('GH_TOKEN')))
            if (result.get('source_commit') != context[2]['commit']
                    or result.get('source_tree') != context[2]['tree']
                    or _verification_context(root, commit) != context):
                raise CertifiedInstallRefused('software identity changed during verification')
            self._context, self._result = context, deepcopy(result)
            return deepcopy(result)
        except verifier.CertificationVerificationRefused as exc:
            raise CertifiedInstallRefused('%s: %s' % (exc.code, exc.detail)) from None
        except OSError as exc:
            raise CertifiedInstallRefused('software verification context is unavailable') from exc


def verify_reviewed_runtime(reviewed, *, env: Mapping[str, str], invoke,
                            root: Path, software_verification=None) -> Mapping:
    """Bind signed GitHub evidence to the exact reviewed local image bytes."""
    try:
        result = (software_verification.verify(
            root=root, commit=reviewed.git_commit, env=env)
            if software_verification is not None else verifier.verify_current(
                root=root, commit=reviewed.git_commit,
                client=verifier.GitHubReadClient(
                    token=env.get("SENTINEL_GITHUB_READ_TOKEN")
                    or env.get("GITHUB_TOKEN") or env.get("GH_TOKEN"))))
    except verifier.CertificationVerificationRefused as exc:
        raise CertifiedInstallRefused("%s: %s" % (exc.code, exc.detail)) from None
    reference = str(result.get("certified_image") or "")
    digest = str(result.get("image_digest") or "")
    if (result.get("source_commit") != reviewed.git_commit
            or result.get("software_certification") != "VERIFIED"
            or result.get("required_ci_jobs") != "PASS"
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            or re.fullmatch(
                r"ghcr\.io/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}", reference) is None
            or not reference.endswith("@" + digest)):
        raise CertifiedInstallRefused("signed runtime certification binding is malformed")
    inspected = invoke(["docker", "image", "inspect", reference],
                       cwd=str(root), stdout=-1, stderr=-1, text=True,
                       check=False, timeout=300)
    try:
        records = json.loads(inspected.stdout or "")
    except (ValueError, TypeError):
        records = None
    if (inspected.returncode != 0 or not isinstance(records, list)
            or len(records) != 1 or not isinstance(records[0], dict)):
        raise CertifiedInstallRefused("signed runtime is not exactly locally inspectable")
    image = records[0]
    config = image.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if (image.get("Id") != reviewed.runtime_image_digest
            or reviewed.test_image_digest != reviewed.runtime_image_digest
            or not isinstance(image.get("RepoDigests"), list)
            or reference not in image["RepoDigests"]
            or not isinstance(labels, dict)
            or labels.get("org.opencontainers.image.revision") != reviewed.git_commit):
        raise CertifiedInstallRefused("signed registry runtime differs from reviewed image")
    return result
