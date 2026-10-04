"""Read-only admission of the one signed runtime for reviewed installation."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Mapping

import sentinel_ci_certification_verify as verifier


class CertifiedInstallRefused(RuntimeError):
    pass


def verify_reviewed_runtime(reviewed, *, env: Mapping[str, str], invoke,
                            root: Path) -> Mapping:
    """Bind signed GitHub evidence to the exact reviewed local image bytes."""
    try:
        result = verifier.verify_current(
            root=root, commit=reviewed.git_commit,
            client=verifier.GitHubReadClient(
                token=env.get("SENTINEL_GITHUB_READ_TOKEN")
                or env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")))
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
