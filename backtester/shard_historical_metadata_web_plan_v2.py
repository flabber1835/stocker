#!/usr/bin/env python3
"""Partition the bounded V2 SEC fallback plan by stable validated CIK hash."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.web-shards/1"
FIELDS = [
    "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type", "need_sic",
    "discovery_only_cik_hint", "first_session", "last_session", "first_need_session",
    "first_unknown_type_session", "first_missing_sector_session", "episode_first_session",
    "episode_last_session", "source_selection_rule",
]


def shard_for_cik(cik: str, shards: int) -> int:
    valid = base.validate_cik(cik)
    if not valid:
        raise base.ReconstructionError(f"invalid CIK in web plan: {cik!r}")
    return int(hashlib.sha256(valid.encode("ascii")).hexdigest()[:16], 16) % shards


def shard_plan(plan_dir: Path, output: Path, shards: int = 32) -> dict:
    if shards < 1 or shards > 256:
        raise base.ReconstructionError(f"unsupported shard count: {shards}")
    plan_path = plan_dir / "web_plan.csv.gz"
    rows = base.read_gzip_csv(plan_path)
    buckets: list[list[dict[str, str]]] = [[] for _ in range(shards)]
    ciks_by_shard: list[set[str]] = [set() for _ in range(shards)]
    all_ciks: set[str] = set()
    for row in rows:
        if base.norm_ticker(row.get("alias_symbol")):
            raise base.ReconstructionError("CIK sharding refuses inferred ticker aliases")
        cik = base.validate_cik(row.get("cik"))
        if not cik:
            raise base.ReconstructionError(f"web plan contains invalid/empty CIK: {row}")
        item = dict(row)
        item["cik"] = cik
        shard = shard_for_cik(cik, shards)
        buckets[shard].append(item)
        ciks_by_shard[shard].add(cik)
        all_ciks.add(cik)

    output.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for shard in range(shards):
        path = output / f"web_plan_shard_{shard:02d}.csv.gz"
        ordered = sorted(
            buckets[shard],
            key=lambda row: (
                row.get("cik", ""), row.get("security_id", ""), row.get("first_need_session", ""), row.get("ticker", "")
            ),
        )
        base.write_gzip_csv(path, FIELDS, ordered)
        manifest_rows.append({
            "shard": f"{shard:02d}",
            "rows": len(ordered),
            "unique_ciks": len(ciks_by_shard[shard]),
            "plan_sha256": base.sha256_file(path),
        })
    base.write_gzip_csv(
        output / "web_shard_manifest.csv.gz",
        ["shard", "rows", "unique_ciks", "plan_sha256"],
        manifest_rows,
    )
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "shards": shards,
        "plan_rows": len(rows),
        "unique_valid_ciks": len(all_ciks),
        "partition_rule": "sha256(canonical_10_digit_cik)[0:16] modulo shard_count",
        "max_parallel_sec_clients": 1,
        "shards_with_work": sum(bool(bucket) for bucket in buckets),
    }
    (output / "web_shard_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=32)
    args = parser.parse_args()
    result = shard_plan(args.plan_dir, args.output, args.shards)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
