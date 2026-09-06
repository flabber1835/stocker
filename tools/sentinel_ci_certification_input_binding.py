#!/usr/bin/env python3
"""Re-observe exact publication inputs before a software certificate is issued."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Mapping, Sequence

from tools import sentinel_ci_certification_manifest as cert


class InputBindingRefused(ValueError):
    pass


def verify_binding(*, root: Path, evidence: Mapping[str, object],
                   expected_commit: str, expected_workflow_run: int,
                   expected_workflow_attempt: int, ordinary_image_ref: str,
                   authorized_image_ref: str) -> None:
    cert._validate_input(evidence)
    if evidence.get("source_commit") != expected_commit:
        raise InputBindingRefused("source commit differs from publication trigger")
    if evidence.get("test_workflow_run") != expected_workflow_run:
        raise InputBindingRefused("test workflow run differs from publication trigger")
    if evidence.get("test_workflow_attempt") != expected_workflow_attempt:
        raise InputBindingRefused("test workflow attempt differs from publication trigger")

    head = cert._run(["git", "rev-parse", "HEAD"], cwd=root).strip()
    tree = cert._run(["git", "rev-parse", "HEAD^{tree}"], cwd=root).strip()
    if head != expected_commit:
        raise InputBindingRefused("publication checkout differs from trigger commit")
    if evidence.get("source_tree") != tree:
        raise InputBindingRefused("source tree differs from publication checkout")

    ordinary_id, ordinary_revision = cert._docker_image_identity(
        root, ordinary_image_ref)
    authorized_id, authorized_revision = cert._docker_image_identity(
        root, authorized_image_ref)
    if ordinary_revision != expected_commit or authorized_revision != expected_commit:
        raise InputBindingRefused("loaded runtime revision differs from trigger commit")
    if evidence.get("ordinary_image_id") != ordinary_id:
        raise InputBindingRefused("loaded ordinary image ID differs from tested image ID")
    if evidence.get("authorized_image_id") != authorized_id:
        raise InputBindingRefused("loaded authorized image ID differs from tested image ID")
    if ordinary_id == authorized_id:
        raise InputBindingRefused("ordinary and authorized runtime images are not distinct")

    capability = root / "deploy" / "sentinel-authorized-runtime-v1"
    if evidence.get("authorized_runtime_capability_sha256") != cert.sha256_file(capability):
        raise InputBindingRefused("authorized runtime capability hash differs")
    if evidence.get("dependency_lock_hashes") != cert._dependency_hashes(root):
        raise InputBindingRefused("dependency lock hashes differ from checkout")
    if evidence.get("test_manifest_sha256") != cert._test_manifest_hash(root):
        raise InputBindingRefused("test manifest hash differs from checkout")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-workflow-run", type=int, required=True)
    parser.add_argument("--expected-workflow-attempt", type=int, required=True)
    parser.add_argument("--ordinary-image-ref", required=True)
    parser.add_argument("--authorized-image-ref", required=True)
    args = parser.parse_args(argv)
    try:
        evidence = cert._read_json(args.input, label="software certification input")
        verify_binding(
            root=args.root.resolve(), evidence=evidence,
            expected_commit=args.expected_commit,
            expected_workflow_run=args.expected_workflow_run,
            expected_workflow_attempt=args.expected_workflow_attempt,
            ordinary_image_ref=args.ordinary_image_ref,
            authorized_image_ref=args.authorized_image_ref,
        )
    except (cert.CertificationManifestRefused, InputBindingRefused) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
