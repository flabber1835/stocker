#!/usr/bin/env python3
"""Merge all V2 SEC CIK shard artifacts into one authenticated web corpus."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.web-merge/2"
ATTEMPT_RE = re.compile(r"attempt-(\d+)")


def _dedup(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
    chosen: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        key = tuple(str(row.get(k, "")) for k in keys)
        candidate = dict(row)
        prior = chosen.get(key)
        if prior is not None and prior != candidate:
            if json.dumps(prior, sort_keys=True) != json.dumps(candidate, sort_keys=True):
                raise base.ReconstructionError(f"conflicting duplicate web evidence for {key}")
        else:
            chosen[key] = candidate
    return [chosen[key] for key in sorted(chosen)]


def _copy_sources(shard_dir: Path, output: Path) -> int:
    copied = 0
    root = shard_dir / "sources"
    if not root.exists():
        return 0
    for source in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = source.relative_to(shard_dir)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if base.sha256_file(target) != base.sha256_file(source):
                raise base.ReconstructionError(f"content-addressed source collision: {relative}")
        else:
            shutil.copyfile(source, target)
            copied += 1
    return copied


def _attempt(path: Path) -> int:
    matches = [int(value) for value in ATTEMPT_RE.findall(path.as_posix())]
    return max(matches) if matches else 0


def merge(root: Path, output: Path, expected_shards: int = 32) -> dict:
    coverage_paths = sorted(root.rglob("shard_runner_coverage.json"))
    candidates_by_shard: dict[str, list[tuple[int, Path]]] = {}
    for coverage_path in coverage_paths:
        payload = json.loads(coverage_path.read_text(encoding="utf-8"))
        shard = str(payload.get("shard") or "")
        if not shard or payload.get("status") != "PASS":
            continue
        candidates_by_shard.setdefault(shard, []).append((_attempt(coverage_path), coverage_path.parent))

    by_shard: dict[str, Path] = {}
    selected_attempts: dict[str, int] = {}
    for shard, choices in candidates_by_shard.items():
        choices.sort(key=lambda item: item[0])
        highest = choices[-1][0]
        winners = [path for attempt, path in choices if attempt == highest]
        if len(winners) != 1:
            raise base.ReconstructionError(f"duplicate latest PASS artifact for shard {shard} attempt {highest}")
        selected_attempts[shard] = highest
        by_shard[shard] = winners[0]

    expected = {f"{index:02d}" for index in range(expected_shards)}
    actual = set(by_shard)
    if actual != expected:
        raise base.ReconstructionError(
            f"web shard inventory mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}"
        )

    output.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, str]] = []
    identity_rows: list[dict[str, str]] = []
    type_rows: list[dict[str, str]] = []
    rejected_rows: list[dict[str, str]] = []
    sic_rows: list[dict[str, str]] = []
    transport = Counter()
    terminal_absences = 0
    planned_ciks = 0
    completed_ciks = 0
    copied_sources = 0

    for index in range(expected_shards):
        shard = f"{index:02d}"
        shard_dir = by_shard[shard]
        base.verify_checksums(shard_dir)
        web = json.loads((shard_dir / "web_coverage.json").read_text(encoding="utf-8"))
        if web.get("status") != "PASS" or not web.get("complete"):
            raise base.ReconstructionError(f"web shard {shard} not transport-complete")
        planned_ciks += int(web.get("planned_unique_ciks") or 0)
        completed_ciks += int(web.get("completed_unique_ciks") or 0)
        for key, value in (web.get("transport") or {}).items():
            try:
                transport[str(key)] += int(value)
            except (TypeError, ValueError):
                pass
        terminal_absences += int(web.get("terminal_source_absences") or (web.get("transport") or {}).get("terminal_absences") or 0)

        def load(name: str) -> list[dict[str, str]]:
            path = shard_dir / name
            return base.read_gzip_csv(path) if path.exists() else []

        source_rows.extend(load("web_source_manifest.csv.gz"))
        identity_rows.extend(load("web_identity_sources.csv.gz"))
        type_rows.extend(load("web_security_type_sources.csv.gz"))
        rejected_rows.extend(load("web_security_type_rejected.csv.gz"))
        sic_rows.extend(load("web_sic_sources.csv.gz"))
        copied_sources += _copy_sources(shard_dir, output)
        print(
            f"[MERGE PROGRESS] shard={index+1}/{expected_shards} pct={(index+1)*100.0/expected_shards:.1f}% "
            f"attempt={selected_attempts[shard]} planned_ciks={planned_ciks} completed_ciks={completed_ciks} "
            f"sources_copied={copied_sources}",
            flush=True,
        )

    source_rows = _dedup(source_rows, ("url", "status", "sha256", "artifact_member"))
    identity_rows = _dedup(identity_rows, ("security_id_hint", "filed", "cik", "accession", "sec_symbol", "source_sha256"))
    type_rows = _dedup(type_rows, ("security_id_hint", "filed", "cik", "accession", "classification", "source_sha256"))
    rejected_rows = _dedup(rejected_rows, ("security_id_hint", "filed", "cik", "accession", "classification", "source_sha256", "reason"))
    sic_rows = _dedup(sic_rows, ("filed", "cik", "sic", "accession", "source_sha256"))

    for row in source_rows:
        member = str(row.get("artifact_member") or "")
        digest = str(row.get("sha256") or "")
        terminal = str(row.get("terminal_absence") or "").lower() in {"true", "1"}
        if not member:
            if terminal:
                continue
            if str(row.get("status") or "") == "200" and int(row.get("bytes") or 0) > 0:
                raise base.ReconstructionError(f"source manifest row lacks artifact member: {row.get('url')}")
            continue
        path = output / member
        if not path.is_file():
            raise base.ReconstructionError(f"merged source object missing: {member}")
        if digest and base.sha256_file(path) != digest:
            raise base.ReconstructionError(f"merged source object hash mismatch: {member}")

    base.write_gzip_csv(output / "web_source_manifest.csv.gz", [
        "url", "status", "path", "sha256", "bytes", "attempts", "terminal_absence", "retrieved_at", "artifact_member",
    ], source_rows)
    base.write_gzip_csv(output / "web_identity_sources.csv.gz", [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind", "source_url", "source_sha256",
    ], identity_rows)
    base.write_gzip_csv(output / "web_security_type_sources.csv.gz", [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "security_title_evidence", "authority", "source_url", "source_sha256",
    ], type_rows)
    base.write_gzip_csv(output / "web_security_type_rejected.csv.gz", [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "reason", "source_url", "source_sha256",
    ], rejected_rows)
    base.write_gzip_csv(output / "web_sic_sources.csv.gz", [
        "filed", "cik", "sic", "source_kind", "accession", "source_url", "source_sha256",
    ], sic_rows)

    normalized_hash = base.normalized_web_evidence_hash(identity_rows, type_rows, sic_rows)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "complete": completed_ciks == planned_ciks,
        "expected_shards": expected_shards,
        "merged_shards": len(by_shard),
        "selected_attempts": selected_attempts,
        "planned_unique_ciks": planned_ciks,
        "completed_unique_ciks": completed_ciks,
        "terminal_source_absences": terminal_absences,
        "transport": dict(transport),
        "source_manifest_rows": len(source_rows),
        "identity_sources": len(identity_rows),
        "admitted_security_type_sources": len(type_rows),
        "rejected_security_type_sources": len(rejected_rows),
        "sic_sources": len(sic_rows),
        "normalized_evidence_sha256": normalized_hash,
        "partitioning": "stable validated CIK hash shards; SEC-facing max-parallel=1",
    }
    if not summary["complete"]:
        raise base.ReconstructionError("merged web corpus is missing completed CIKs")
    (output / "web_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output)
    base.verify_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, default=32)
    args = parser.parse_args()
    result = merge(args.root, args.output, args.expected_shards)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
