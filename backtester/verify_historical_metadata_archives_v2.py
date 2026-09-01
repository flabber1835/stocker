#!/usr/bin/env python3
"""Verify every retained SEC Form 3/4/5 archive against committed SHA-256 evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.archive-verification/1"


def verify_archives(sec_dir: Path, coverage_path: Path, source_lock: Path) -> dict:
    lock = json.loads(source_lock.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    expected_names = base.expected_archive_names(
        int(lock["sec_bulk"]["first_year"]),
        int(lock["sec_bulk"]["through_year"]),
        int(lock["sec_bulk"]["through_quarter"]),
    )
    rows = coverage.get("archives")
    if not isinstance(rows, list):
        raise base.ReconstructionError("committed SEC coverage has no archive manifest")
    by_name = {str(row.get("archive") or ""): row for row in rows}
    if set(by_name) != set(expected_names) or len(by_name) != len(expected_names):
        raise base.ReconstructionError("committed SEC coverage archive inventory does not match source lock")
    if int(coverage.get("archive_count", -1)) != len(expected_names):
        raise base.ReconstructionError("committed SEC coverage archive_count mismatch")

    verified = []
    for index, name in enumerate(expected_names, 1):
        path = sec_dir / name
        row = by_name[name]
        expected_sha = str(row.get("sha256") or "")
        expected_size = int(row.get("size_bytes") or -1)
        if len(expected_sha) != 64:
            raise base.ReconstructionError(f"invalid committed SHA-256 for {name}")
        if not path.is_file():
            raise base.ReconstructionError(f"missing retained SEC archive: {path}")
        actual_size = path.stat().st_size
        actual_sha = base.sha256_file(path)
        if actual_size != expected_size:
            raise base.ReconstructionError(f"size mismatch for {name}: {actual_size} != {expected_size}")
        if actual_sha != expected_sha:
            raise base.ReconstructionError(f"SHA-256 mismatch for {name}: {actual_sha} != {expected_sha}")
        verified.append({"archive": name, "sha256": actual_sha, "size_bytes": actual_size})
        print(f"[ARCHIVE VERIFY] {index}/{len(expected_names)} {name} {actual_sha}", flush=True)

    return {
        "schema": SCHEMA,
        "status": "PASS",
        "archive_count": len(verified),
        "coverage_sha256": base.sha256_file(coverage_path),
        "source_lock_sha256": base.sha256_file(source_lock),
        "first_archive": verified[0]["archive"] if verified else "",
        "last_archive": verified[-1]["archive"] if verified else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-dir", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    args = parser.parse_args()
    result = verify_archives(args.sec_dir, args.coverage, args.source_lock)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
