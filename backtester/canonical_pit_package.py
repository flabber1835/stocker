#!/usr/bin/env python3
"""Publish and verify the branch-owned pointer to a canonical PIT package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.canonical_pit_dataset import CanonicalPITDataset


POINTER_SCHEMA = "backtester.canonical-pit-package-pointer/1"
PACKAGE_RE = re.compile(
    r"^ghcr\.io/flabber1835/stocker-canonical-pit@sha256:[0-9a-f]{64}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pointer(path: Path) -> dict:
    pointer = json.loads(Path(path).read_text(encoding="utf-8"))
    if pointer.get("schema") != POINTER_SCHEMA:
        raise RuntimeError("unexpected canonical PIT package pointer schema")
    if pointer.get("status") != "PASS":
        raise RuntimeError("canonical PIT package pointer is not admitted")
    if not PACKAGE_RE.fullmatch(str(pointer.get("package") or "")):
        raise RuntimeError("canonical PIT package is not pinned by GHCR digest")
    for key in ("dataset_hash", "manifest_sha256"):
        if not SHA256_RE.fullmatch(str(pointer.get(key) or "")):
            raise RuntimeError(f"invalid canonical PIT pointer {key}")
    if not GIT_SHA_RE.fullmatch(str(pointer.get("reconstruction_code_sha") or "")):
        raise RuntimeError("invalid canonical PIT pointer reconstruction_code_sha")
    window = pointer.get("window") or {}
    if not all(window.get(key) for key in ("warmup_start", "measurement_start", "end")):
        raise RuntimeError("canonical PIT pointer window is incomplete")
    if not str(pointer.get("source_run_url") or "").startswith(
        "https://github.com/flabber1835/stocker/actions/runs/"
    ):
        raise RuntimeError("canonical PIT pointer source run is invalid")
    return pointer


def verify_pointer_dataset(pointer_path: Path, dataset_path: Path) -> dict:
    pointer = load_pointer(pointer_path)
    window = pointer["window"]
    dataset = CanonicalPITDataset(
        dataset_path,
        expected_start=window["warmup_start"],
        expected_end=window["end"],
    )
    if dataset.dataset_hash != pointer["dataset_hash"]:
        raise RuntimeError("canonical PIT package dataset hash differs from pointer")
    manifest_hash = _sha256(dataset.manifest_path)
    if manifest_hash != pointer["manifest_sha256"]:
        raise RuntimeError("canonical PIT package manifest hash differs from pointer")
    if dataset.manifest.get("reconstruction_code_sha") != pointer["reconstruction_code_sha"]:
        raise RuntimeError("canonical PIT reconstruction SHA differs from pointer")
    return pointer


def write_pointer(
    *, dataset_path: Path, output: Path, package: str,
    source_run_id: str, source_run_url: str,
) -> dict:
    dataset = CanonicalPITDataset(dataset_path)
    if not PACKAGE_RE.fullmatch(package):
        raise RuntimeError("published package must be pinned by GHCR digest")
    manifest = dataset.manifest
    pointer = {
        "schema": POINTER_SCHEMA,
        "status": "PASS",
        "dataset_id": manifest["dataset_id"],
        "dataset_hash": dataset.dataset_hash,
        "manifest_sha256": _sha256(dataset.manifest_path),
        "reconstruction_code_sha": manifest["reconstruction_code_sha"],
        "package": package,
        "source_run_id": str(source_run_id),
        "source_run_url": source_run_url,
        "window": manifest["window"],
        "counts": manifest["counts"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pointer


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("--dataset", type=Path, required=True)
    write.add_argument("--output", type=Path, required=True)
    write.add_argument("--package", required=True)
    write.add_argument("--source-run-id", required=True)
    write.add_argument("--source-run-url", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--pointer", type=Path, required=True)
    verify.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "write":
        result = write_pointer(
            dataset_path=args.dataset,
            output=args.output,
            package=args.package,
            source_run_id=args.source_run_id,
            source_run_url=args.source_run_url,
        )
    else:
        result = verify_pointer_dataset(args.pointer, args.dataset)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
