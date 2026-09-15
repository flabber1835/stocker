#!/usr/bin/env python3
"""Bind parallel certification evidence to one exact runtime and workflow attempt."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.merge_junit import merge
from tools.sentinel_ci_certification_manifest import (
    _docker_image_identity, _read_json, _run, canonical_bytes, sha256_file,
)

SUITE_LANES = (
    "sentinel-main", "sentinel-warmup", "sentinel-automation", "champion",
    "operator", "wealth-core", "mutations",
)
REPLAY_SHARDS = 4
LANES = (*SUITE_LANES, *(f"replay-{index}" for index in range(REPLAY_SHARDS)))
DEPENDENCIES = {"runtime-build", "parallel-certification", "sharadar-replay"}
REQUIRED_FILES = {
    "sentinel-main": {"sentinel-main.xml", "summary.txt"},
    "sentinel-warmup": {"sentinel-warmup.xml", "summary.txt"},
    "sentinel-automation": {"sentinel-automation.xml", "summary.txt"},
    "champion": {"champion.xml", "summary.txt"},
    "operator": {"scripts.xml", "summary.txt"},
    "wealth-core": {"wealth-core.xml", "summary.txt"},
    "mutations": {"report.json"},
    **{f"replay-{index}": {"collection.json", "junit.xml"}
       for index in range(REPLAY_SHARDS)},
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _inventory(root: Path, *, exclude: set[str] | None = None) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"symlink in evidence: {path}")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if name not in (exclude or set()):
                files[name] = sha256_file(path)
    return files


def _source_identity(root: Path) -> dict:
    run, attempt = (os.environ.get(key, "")
                    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    require(run.isdecimal() and attempt.isdecimal() and int(run) > 0 and int(attempt) > 0,
            "workflow run/attempt is unavailable")
    return {
        "commit": _run(["git", "rev-parse", "HEAD"], cwd=root).strip(),
        "tree": _run(["git", "rev-parse", "HEAD^{tree}"], cwd=root).strip(),
        "workflow_run": int(run), "workflow_attempt": int(attempt),
    }


def _images(root: Path, *, commit: str) -> dict[str, str]:
    images = {}
    for reference in ("sentinel:ci", "sentinel-test:ci"):
        image_id, revision = _docker_image_identity(root, reference)
        require(revision == commit, f"{reference}: image revision differs from source commit")
        images[reference] = image_id
    return images


def build_bundle(root: Path, bundle: Path) -> dict:
    bundle.mkdir(parents=True, exist_ok=False)
    identity = _source_identity(root)
    images = _images(root, commit=identity["commit"])
    subprocess.run(["docker", "save", "--output", str(bundle / "images.tar"),
                    "sentinel:ci", "sentinel-test:ci"], cwd=root, check=True)
    manifest = {"schema": "sentinel.ci-runtime-bundle/1", **identity,
                "images": images, "files": _inventory(bundle)}
    _write_json(bundle / "identity.json", manifest)
    return manifest


def verify_bundle(root: Path, bundle: Path, *, load: bool = False) -> dict:
    manifest = _read_json(bundle / "identity.json", label="runtime bundle")
    require(set(manifest) == {"schema", "commit", "tree", "workflow_run",
                              "workflow_attempt", "images", "files"}
            and manifest["schema"] == "sentinel.ci-runtime-bundle/1",
            "invalid runtime bundle schema")
    for key, value in _source_identity(root).items():
        require(type(manifest[key]) is type(value) and manifest[key] == value,
                f"runtime bundle {key} differs from current workflow source/attempt")
    require(isinstance(manifest["files"], dict)
            and set(manifest["files"]) == {"images.tar"}
            and manifest["files"] == _inventory(bundle, exclude={"identity.json"}),
            "runtime bundle file inventory/hash differs")
    if load:
        subprocess.run(["docker", "load", "--input", str(bundle / "images.tar")],
                       cwd=root, check=True)
    require(manifest["images"] == _images(root, commit=manifest["commit"]),
            "loaded image IDs differ from built runtime/test lens")
    return manifest


def complete_lane(root: Path, bundle: Path, evidence: Path, lane: str) -> dict:
    manifest = verify_bundle(root, bundle)
    require(lane in LANES, "undeclared certification lane")
    require(not (evidence / "receipt.json").exists(), "duplicate lane receipt")
    files = _inventory(evidence)
    require(REQUIRED_FILES[lane].issubset(files), f"{lane}: missing required evidence files")
    receipt = {"schema": "sentinel.ci-lane-receipt/1", "lane": lane,
               "bundle_sha256": sha256_file(bundle / "identity.json"),
               "identity": manifest, "files": files}
    _write_json(evidence / "receipt.json", receipt)
    return receipt


def require_dependencies(needs: dict) -> None:
    require(isinstance(needs, dict) and set(needs) == DEPENDENCIES,
            "mandatory certification dependency inventory differs")
    for name, result in needs.items():
        require(isinstance(result, dict) and result.get("result") == "success",
                f"mandatory dependency {name} did not succeed")


def verify_lanes(root: Path, bundle: Path, workers: Path, needs: dict) -> dict[str, Path]:
    require_dependencies(needs)
    manifest = verify_bundle(root, bundle)
    bundle_hash = sha256_file(bundle / "identity.json")
    lanes = {}
    directories = list(workers.iterdir())
    require(len(directories) == len(LANES), "missing or extra certification lane artifacts")
    for directory in directories:
        require(directory.is_dir() and not directory.is_symlink(), "invalid lane artifact")
        receipt = _read_json(directory / "receipt.json", label="lane receipt")
        lane = receipt.get("lane")
        require(isinstance(lane, str) and lane in LANES and lane not in lanes,
                "undeclared or duplicate certification lane")
        require(set(receipt) == {"schema", "lane", "bundle_sha256", "identity", "files"}
                and receipt["schema"] == "sentinel.ci-lane-receipt/1"
                and canonical_bytes(receipt["identity"]) == canonical_bytes(manifest)
                and receipt["bundle_sha256"] == bundle_hash,
                f"{lane}: receipt runtime/source/workflow identity differs")
        files = _inventory(directory, exclude={"receipt.json"})
        require(isinstance(receipt["files"], dict) and receipt["files"] == files
                and REQUIRED_FILES[lane].issubset(files), f"{lane}: evidence inventory/hash differs")
        lanes[lane] = directory
    require(set(lanes) == set(LANES), "incomplete certification lane union")
    return lanes


def assemble(root: Path, bundle: Path, workers: Path, needs: dict, output: Path) -> dict:
    lanes = verify_lanes(root, bundle, workers, needs)
    system = output / "sentinel-system-evidence"
    replay = output / "sharadar-required-evidence"
    mutation = output / "sentinel-mutation-evidence"
    for directory in (system, replay, mutation):
        directory.mkdir(parents=True, exist_ok=False)
    for lane, filename in (("champion", "champion.xml"), ("operator", "scripts.xml"),
                           ("wealth-core", "wealth-core.xml"),
                           ("sentinel-automation", "sentinel-automation.xml")):
        shutil.copyfile(lanes[lane] / filename, system / filename)
    merge([lanes["sentinel-main"] / "sentinel-main.xml",
           lanes["sentinel-warmup"] / "sentinel-warmup.xml"], system / "sentinel-main.xml")
    total = merge([system / "sentinel-main.xml", system / "sentinel-automation.xml"],
                  system / "sentinel.xml")
    cases = list(ET.parse(system / "sentinel.xml").getroot().iter("testcase"))
    require(all(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
                for case in cases), "Sentinel partition contains non-passing tests")
    logs = "\n".join((lanes[lane] / "summary.txt").read_text(encoding="utf-8")
                     for lane in SUITE_LANES[:3])
    (output / "sentinel-complete.txt").write_text(
        logs + f"\n{total} passed (complete disjoint Sentinel JUnit union)\n", encoding="utf-8")
    for lane, filename in (("operator", "sentinel-scripts.txt"),
                           ("wealth-core", "wealth-core-prospective.txt")):
        shutil.copyfile(lanes[lane] / "summary.txt", output / filename)
    shutil.copyfile(lanes["mutations"] / "report.json", mutation / "report.json")
    for index in range(REPLAY_SHARDS):
        shutil.copytree(lanes[f"replay-{index}"], replay / str(index))
    result = {"verdict": "PASS", "lanes": list(LANES), "sentinel_tests": total,
              "bundle_sha256": sha256_file(bundle / "identity.json")}
    _write_json(system / "parallel-evidence.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build-bundle", "load-bundle", "complete-lane", "assemble",
                                             "verify-needs"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--lane", choices=LANES)
    parser.add_argument("--workers", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "verify-needs":
        require_dependencies(json.loads(os.environ.get("CI_NEEDS", "null")))
        print("PASS: every mandatory build, suite lane and replay shard succeeded")
        return 0
    require(args.bundle is not None, "runtime bundle is required")
    if args.command == "build-bundle":
        result = build_bundle(args.root, args.bundle)
    elif args.command == "load-bundle":
        result = verify_bundle(args.root, args.bundle, load=True)
    elif args.command == "complete-lane":
        require(args.evidence is not None and args.lane is not None, "lane/evidence is required")
        receipt = complete_lane(args.root, args.bundle, args.evidence, args.lane)
        result = {"verdict": "PASS", "lane": args.lane, "files": len(receipt["files"]),
                  "bundle_sha256": receipt["bundle_sha256"],
                  "source_commit": receipt["identity"]["commit"],
                  "workflow_run": receipt["identity"]["workflow_run"],
                  "workflow_attempt": receipt["identity"]["workflow_attempt"],
                  "images": receipt["identity"]["images"]}
    else:
        require(args.workers is not None and args.output is not None, "workers/output is required")
        result = assemble(args.root, args.bundle, args.workers,
                          json.loads(os.environ.get("CI_NEEDS", "null")), args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
