"""Bind the replay to the checked-out production source without rewriting it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_manifest(runtime: Path) -> dict[str, str]:
    return {
        str(path.relative_to(runtime)).replace("\\", "/"): sha(path)
        for folder in ("sentinel", "shared")
        for path in sorted((runtime / folder).rglob("*.py"))
    }


def harness_manifest() -> dict[str, str]:
    return {
        path.name: sha(path)
        for path in sorted(HERE.glob("*.py"))
    }


def git_revision(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        text=True, stdout=subprocess.PIPE).stdout.strip()


def build_manifest(repo: Path) -> dict:
    from sentinel.strategy import production_strategy

    controller, identity = production_strategy()
    files = source_manifest(repo)
    record = {
        "schema": "full-system-production-runtime/2",
        "revision": git_revision(repo),
        "strategy": identity,
        "controller": controller.to_dict(),
        "files": files,
        "tree_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest(),
        "harness_files": harness_manifest(),
        "runtime_rewritten": False,
    }
    return record


def write_manifest(repo: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("runtime manifest already exists")
    record = build_manifest(repo)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(write_manifest(
        args.repo.resolve(), args.output.resolve()), sort_keys=True))
