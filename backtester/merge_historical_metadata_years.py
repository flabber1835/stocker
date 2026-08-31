#!/usr/bin/env python3
"""Deterministically merge per-year historical metadata evidence artifacts."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
from pathlib import Path


def read_gz_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_gz_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            import io
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)


def dedup_exact(rows: list[dict[str, str]], keys: tuple[str, ...]) -> list[dict[str, str]]:
    chosen: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(str(row.get(k, "")) for k in keys)
        chosen.setdefault(key, row)
    return [chosen[k] for k in sorted(chosen)]


def assert_no_conflicts(rows: list[dict[str, str]], identity_keys: tuple[str, ...], value_key: str, label: str) -> None:
    seen: dict[tuple[str, ...], str] = {}
    conflicts: list[tuple[tuple[str, ...], str, str]] = []
    for row in rows:
        key = tuple(str(row.get(k, "")) for k in identity_keys)
        value = str(row.get(value_key, ""))
        prior = seen.setdefault(key, value)
        if prior != value:
            conflicts.append((key, prior, value))
    if conflicts:
        sample = conflicts[:10]
        raise RuntimeError(f"{label} conflicts detected: {sample}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--from-year", type=int, default=2007)
    p.add_argument("--through-year", type=int, default=2026)
    args = p.parse_args()

    coverages: dict[int, dict] = {}
    for path in sorted(args.input.rglob("coverage.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "backtester.historical-metadata-year-evidence/1":
            continue
        year = int(payload["target_year"])
        if year in coverages:
            raise RuntimeError(f"duplicate coverage artifact for year {year}")
        coverages[year] = payload

    expected = set(range(args.from_year, args.through_year + 1))
    present = set(coverages)
    if present != expected:
        raise RuntimeError(f"year artifact set mismatch: missing={sorted(expected-present)} extra={sorted(present-expected)}")

    def gather(name: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for path in sorted(args.input.rglob(name)):
            rows.extend(read_gz_csv(path))
        return rows

    identity = gather("identity_events.csv.gz")
    types = gather("security_type_events.csv.gz")
    sics = gather("sic_events.csv.gz")
    sources = gather("source_manifest.csv.gz")
    unresolved = gather("unresolved.csv.gz")

    assert_no_conflicts(
        types,
        ("filed", "ticker", "cik", "accession", "source_sha256"),
        "classification",
        "security type",
    )
    assert_no_conflicts(
        sics,
        ("filed", "ticker", "cik", "accession", "source_sha256"),
        "sic",
        "SIC",
    )

    identity = dedup_exact(identity, ("filed", "ticker", "cik", "accession", "source_sha256"))
    types = dedup_exact(types, ("filed", "ticker", "cik", "classification", "accession", "source_sha256"))
    sics = dedup_exact(sics, ("filed", "ticker", "cik", "sic", "accession", "source_sha256"))
    sources = dedup_exact(sources, ("filed", "cik", "accession", "sha256"))
    unresolved = dedup_exact(unresolved, ("target_year", "security_id", "ticker", "reason", "candidate_ciks"))

    args.output.mkdir(parents=True, exist_ok=True)
    filings_out = args.output / "primary-sec-filings"
    filings_out.mkdir(exist_ok=True)
    copied = 0
    for source in sorted(args.input.rglob("primary-sec-filings/*.txt.gz")):
        target = filings_out / source.name
        if target.exists():
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
                raise RuntimeError(f"primary filing filename collision with different bytes: {source.name}")
            continue
        shutil.copy2(source, target)
        copied += 1

    write_gz_csv(args.output / "identity_events.csv.gz", [
        "filed", "usable_after", "ticker", "cik", "form", "accession", "source_url",
        "source_sha256", "evidence", "discovery_only_cik_hint",
    ], identity)
    write_gz_csv(args.output / "security_type_events.csv.gz", [
        "filed", "usable_after", "ticker", "cik", "classification", "security_title_evidence",
        "form", "accession", "source_url", "source_sha256", "authority",
    ], types)
    write_gz_csv(args.output / "sic_events.csv.gz", [
        "filed", "usable_after", "ticker", "cik", "sic", "form", "accession",
        "source_url", "source_sha256", "authority",
    ], sics)
    write_gz_csv(args.output / "source_manifest.csv.gz", [
        "filed", "cik", "form", "accession", "url", "sha256", "bytes", "artifact_member",
    ], sources)
    write_gz_csv(args.output / "unresolved.csv.gz", [
        "target_year", "security_id", "ticker", "reason", "candidate_ciks", "observations",
        "unknown_type_observations", "missing_sector_observations",
    ], unresolved)

    years = {str(year): coverages[year] for year in sorted(coverages)}
    total_requests = sum(int(coverages[y]["network"]["requests"]) for y in coverages)
    total_failures = sum(len(coverages[y]["network"]["failures"]) for y in coverages)
    summary = {
        "schema": "backtester.historical-metadata-2007-2026-merged-evidence/1",
        "status": "EVIDENCE_HARVEST_COMPLETE",
        "causal_rule": "filed < decision_session",
        "from_year": args.from_year,
        "through_year": args.through_year,
        "years": years,
        "merged": {
            "identity_events": len(identity),
            "security_type_events": len(types),
            "sic_events": len(sics),
            "source_manifest_rows": len(sources),
            "unresolved_episode_records": len(unresolved),
            "primary_sec_filing_files": len(list(filings_out.glob("*.txt.gz"))),
            "new_primary_files_copied_during_merge": copied,
            "type_conflicts": 0,
            "sic_conflicts": 0,
            "network_requests": total_requests,
            "network_failures": total_failures,
        },
    }
    (args.output / "coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files_out = sorted(p for p in args.output.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(args.output).as_posix()}" for p in files_out]
    (args.output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

    print(
        f"[MERGE] years={args.from_year}-{args.through_year} identity={len(identity)} "
        f"type={len(types)} sic={len(sics)} unresolved={len(unresolved)} "
        f"filings={summary['merged']['primary_sec_filing_files']} failures={total_failures}",
        flush=True,
    )
    print(json.dumps(summary["merged"], indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
