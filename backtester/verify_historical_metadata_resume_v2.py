#!/usr/bin/env python3
"""Verify a v2 web checkpoint before any resumed SEC acquisition."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.resume-verification/1"


def _rows(root: Path, name: str):
    path = root / name
    return base.read_gzip_csv(path) if path.exists() else []


def verify_resume(
    plan_path: Path,
    web_dir: Path,
    source_sha: str,
    canonical_hash: str,
    candidates_sha: str,
    parser_sha: str,
) -> dict:
    checkpoint_path = web_dir / "checkpoint.json"
    if not checkpoint_path.exists():
        return {"schema": SCHEMA, "status": "NO_CHECKPOINT"}
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    expected_identity = base.checkpoint_identity(
        source_sha, canonical_hash, candidates_sha, base.sha256_file(plan_path), parser_sha
    )
    if checkpoint.get("identity") != expected_identity:
        raise base.ReconstructionError("resume checkpoint identity mismatch")

    expected_cache = str(checkpoint.get("cache_manifest_sha256") or "")
    actual_cache = base.directory_content_hash(web_dir / ".http-cache")
    if expected_cache != actual_cache:
        raise base.ReconstructionError(
            f"resume cache hash mismatch: {actual_cache} != {expected_cache}"
        )

    identity_rows = _rows(web_dir, "web_identity_sources.csv.gz")
    type_rows = _rows(web_dir, "web_security_type_sources.csv.gz")
    sic_rows = _rows(web_dir, "web_sic_sources.csv.gz")
    actual_evidence = base.normalized_web_evidence_hash(identity_rows, type_rows, sic_rows)
    expected_evidence = str(checkpoint.get("normalized_evidence_sha256") or "")
    if actual_evidence != expected_evidence:
        raise base.ReconstructionError(
            f"resume normalized evidence hash mismatch: {actual_evidence} != {expected_evidence}"
        )

    plan_ciks = {
        base.validate_cik(row.get("cik"))
        for row in base.read_gzip_csv(plan_path)
        if base.validate_cik(row.get("cik"))
    }
    completed = {base.validate_cik(value) for value in checkpoint.get("completed_ciks", [])}
    completed.discard("")
    if not completed.issubset(plan_ciks):
        raise base.ReconstructionError("resume checkpoint contains CIKs absent from current plan")

    return {
        "schema": SCHEMA,
        "status": "PASS",
        "completed_ciks": len(completed),
        "planned_ciks": len(plan_ciks),
        "cache_manifest_sha256": actual_cache,
        "normalized_evidence_sha256": actual_evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--canonical-hash", required=True)
    parser.add_argument("--candidates-sha", required=True)
    parser.add_argument("--parser-sha", required=True)
    args = parser.parse_args()
    result = verify_resume(
        args.plan, args.web_dir, args.source_sha, args.canonical_hash,
        args.candidates_sha, args.parser_sha,
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
