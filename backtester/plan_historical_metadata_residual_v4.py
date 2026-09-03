#!/usr/bin/env python3
"""Build a bounded V4 recovery inventory for definitive corrected PIT metadata gaps.

This stage performs no external requests and admits no new metadata. It projects
already-frozen V2/V3 evidence and the retained SEC raw-source index onto the
corrected security topology so later recovery is bounded to the exact unresolved
canonical episodes.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA = "backtester.historical-metadata-reconstruction-v4.residual-plan/1"
CIK_SUBMISSION_RE = re.compile(r"/submissions/CIK(\d{10})\.json(?:$|\?)", re.I)
CIK_ARCHIVE_RE = re.compile(r"/Archives/edgar/data/(\d+)(?:/|$)", re.I)
IDENTITY_QUALITIES = {
    "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML",
    "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksums(root: Path) -> int:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError(f"missing checksum manifest: {manifest}")
    verified = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        path = root / relative.strip()
        if not path.is_file():
            raise RuntimeError(f"checksum member missing: {relative}")
        if sha256_file(path) != digest:
            raise RuntimeError(f"checksum mismatch: {relative}")
        verified += 1
    return verified


def iter_gzip_csv(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    return list(iter_gzip_csv(path))


def write_gzip_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def valid_cik(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits or len(digits) > 10:
        return ""
    return digits.zfill(10)


def split_ciks(value: object) -> set[str]:
    return {c for c in (valid_cik(part) for part in str(value or "").split(";")) if c}


def cik_from_url(url: str) -> str:
    match = CIK_SUBMISSION_RE.search(url)
    if match:
        return match.group(1)
    match = CIK_ARCHIVE_RE.search(url)
    return match.group(1).zfill(10) if match else ""


def mapped_sid(raw_sid: object, old_to_corrected: Mapping[str, str], corrected_sids: set[str]) -> str:
    sid = str(raw_sid or "").strip()
    if sid in corrected_sids:
        return sid
    return old_to_corrected.get(sid, "")


def build(*, audit_root: Path, v2_root: Path, v3_root: Path, corrected_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    verified = {
        "audit": verify_checksums(audit_root),
        "v2": verify_checksums(v2_root),
        "corrected": verify_checksums(corrected_root),
    }
    audit_summary = json.loads((audit_root / "summary.json").read_text(encoding="utf-8"))
    v3_summary = json.loads((v3_root / "summary.json").read_text(encoding="utf-8"))
    corrected_summary = json.loads((corrected_root / "summary.json").read_text(encoding="utf-8"))
    if audit_summary.get("status") != "PASS" or audit_summary.get("admission_status") != "REVIEW_REQUIRED":
        raise RuntimeError("definitive corrected observation audit is not the expected REVIEW_REQUIRED PASS")
    unresolved_expected = int(audit_summary.get("unresolved_after_corrected_overlay", {}).get("episodes", -1))
    if unresolved_expected < 0:
        raise RuntimeError("audit summary lacks definitive unresolved episode count")
    if v3_summary.get("status") != "PASS" or v3_summary.get("candidate_only") is not True:
        raise RuntimeError("V3 candidate package is not an immutable candidate-only PASS")
    if corrected_summary.get("status") != "PASS":
        raise RuntimeError("corrected topology is not PASS")
    for key in ("blocking_identity_conflicts", "candidate_mapping_anomalies", "security_type_conflict_episodes"):
        if int(corrected_summary.get(key, -1)) != 0:
            raise RuntimeError(f"corrected topology blocker: {key}={corrected_summary.get(key)}")

    unresolved = read_gzip_csv(audit_root / "definitive_unresolved_episodes.csv.gz")
    if len(unresolved) != unresolved_expected:
        raise RuntimeError(f"definitive unresolved count mismatch: {len(unresolved)} != {unresolved_expected}")
    corrected_sids = {row["security_id"] for row in unresolved}

    mapping_rows = read_gzip_csv(corrected_root / "old_to_corrected_episode_mapping.csv.gz")
    old_to_corrected: dict[str, str] = {}
    old_observed: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        if row.get("disposition") != "CONTAINED":
            raise RuntimeError(f"non-contained old episode mapping encountered: {row}")
        old = str(row.get("old_security_id") or "")
        new = str(row.get("corrected_security_id") or "")
        if not old or not new:
            raise RuntimeError(f"invalid old/corrected mapping row: {row}")
        prior = old_to_corrected.get(old)
        if prior and prior != new:
            raise RuntimeError(f"old security maps to multiple corrected episodes: {old}")
        old_to_corrected[old] = new
        if new in corrected_sids:
            old_observed[new].update(split_ciks(row.get("old_observed_ciks")))

    v2_identity: dict[str, set[str]] = defaultdict(set)
    for row in iter_gzip_csv(v2_root / "timeline" / "identity_events.csv.gz"):
        sid = mapped_sid(row.get("security_id"), old_to_corrected, corrected_sids)
        cik = valid_cik(row.get("cik"))
        if sid in corrected_sids and cik:
            v2_identity[sid].add(cik)

    v3_identity: dict[str, set[str]] = defaultdict(set)
    v3_discovery_hints: dict[str, set[str]] = defaultdict(set)
    v3_existing_counts: dict[str, Counter] = defaultdict(Counter)
    for row in iter_gzip_csv(v3_root / "candidate_evidence.csv.gz"):
        sid = mapped_sid(row.get("security_id"), old_to_corrected, corrected_sids)
        if sid not in corrected_sids:
            continue
        kind = str(row.get("candidate_kind") or "")
        v3_existing_counts[sid][kind] += 1
        cik = valid_cik(row.get("candidate_cik"))
        if not cik:
            continue
        if kind == "IDENTITY_EXACT_TICKER" and str(row.get("candidate_quality") or "") in IDENTITY_QUALITIES:
            v3_identity[sid].add(cik)
        elif str(row.get("cik_authority") or "") == "DISCOVERY_ONLY_HINT":
            v3_discovery_hints[sid].add(cik)

    web_plan_causal: dict[str, set[str]] = defaultdict(set)
    web_plan_hints: dict[str, set[str]] = defaultdict(set)
    for row in iter_gzip_csv(v2_root / "web-plan" / "web_plan.csv.gz"):
        sid = mapped_sid(row.get("security_id"), old_to_corrected, corrected_sids)
        cik = valid_cik(row.get("cik"))
        if sid not in corrected_sids or not cik:
            continue
        if str(row.get("discovery_only_cik_hint") or "").lower() == "true":
            web_plan_hints[sid].add(cik)
        else:
            web_plan_causal[sid].add(cik)

    retained_ciks: set[str] = set()
    retained_sources_by_cik = Counter()
    for row in iter_gzip_csv(v2_root / "web" / "web_source_manifest.csv.gz"):
        if str(row.get("status") or "") != "200":
            continue
        cik = cik_from_url(str(row.get("url") or ""))
        if cik:
            retained_ciks.add(cik)
            retained_sources_by_cik[cik] += 1

    rows: list[dict[str, object]] = []
    route_counts = Counter()
    bucket_route_counts = Counter()
    raw_target_ciks: set[str] = set()
    causal_episode_count = 0
    for row in unresolved:
        sid = row["security_id"]
        causal = set(old_observed[sid]) | set(v2_identity[sid]) | set(v3_identity[sid]) | set(web_plan_causal[sid])
        hints = (set(web_plan_hints[sid]) | set(v3_discovery_hints[sid])) - causal
        causal_retained = causal & retained_ciks
        hint_retained = hints & retained_ciks
        if causal_retained:
            route = "REMINE_RETAINED_SEC_CAUSAL_CIK"
            target_ciks = causal_retained
        elif hint_retained:
            route = "REMINE_RETAINED_SEC_DISCOVERY_HINT"
            target_ciks = hint_retained
        elif causal:
            route = "TARGETED_SEC_FETCH_KNOWN_CIK"
            target_ciks = causal
        elif hints:
            route = "TARGETED_SEC_FETCH_DISCOVERY_HINT"
            target_ciks = hints
        else:
            route = "HISTORICAL_IDENTITY_DISCOVERY_REQUIRED"
            target_ciks = set()
        if causal:
            causal_episode_count += 1
        raw_target_ciks.update(target_ciks & retained_ciks)
        route_counts[route] += 1
        bucket_route_counts[(str(row.get("bucket") or ""), route)] += 1
        rows.append(dict(row) | {
            "observed_ciks": ";".join(sorted(old_observed[sid])),
            "timeline_identity_ciks": ";".join(sorted(causal)),
            "web_plan_ciks": ";".join(sorted(hints)),
            "causal_cik_count": len(causal),
            "discovery_hint_cik_count": len(hints),
            "retained_sec_cik_count": len((causal | hints) & retained_ciks),
            "retained_sec_source_objects": sum(retained_sources_by_cik[c] for c in ((causal | hints) & retained_ciks)),
            "existing_v3_identity_candidates": v3_existing_counts[sid]["IDENTITY_EXACT_TICKER"],
            "existing_v3_type_candidates": v3_existing_counts[sid]["SECURITY_TYPE_EXACT_TICKER_CLASS"],
            "existing_v3_sic_candidates": v3_existing_counts[sid]["SIC_HEADER"],
            "resolution_route": route,
            "target_ciks": ";".join(sorted(target_ciks)),
            "admission_effect": "NONE_PLAN_ONLY",
        })

    fields = list(rows[0]) if rows else []
    write_gzip_csv(output / "residual_recovery_inventory.csv.gz", fields, rows)
    remine = [row for row in rows if str(row["resolution_route"]).startswith("REMINE_RETAINED_SEC_")]
    write_gzip_csv(output / "retained_sec_remine_inventory.csv.gz", fields, remine)
    external = [row for row in rows if not str(row["resolution_route"]).startswith("REMINE_RETAINED_SEC_")]
    write_gzip_csv(output / "external_recovery_inventory.csv.gz", fields, external)

    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "candidate_only": True,
        "admission_effect": "NONE",
        "verified_checksum_members": verified,
        "definitive_unresolved_episodes": len(rows),
        "episodes_with_causal_cik": causal_episode_count,
        "episodes_without_causal_cik": len(rows) - causal_episode_count,
        "retained_sec_ciks": len(retained_ciks),
        "retained_sec_source_objects": int(sum(retained_sources_by_cik.values())),
        "retained_sec_target_ciks": len(raw_target_ciks),
        "retained_sec_remine_episodes": len(remine),
        "external_recovery_episodes": len(external),
        "resolution_routes": dict(sorted(route_counts.items())),
        "bucket_routes": {f"{bucket}:{route}": count for (bucket, route), count in sorted(bucket_route_counts.items())},
        "next_gate": "re-mine retained SEC raw shards against corrected residual inventory before issuing any new external requests",
        "policy": {
            "no_new_web_requests": True,
            "no_metadata_admission": True,
            "unknown_never_means_ineligible": True,
            "discovery_hints_are_not_promoted_to_causal_without_exact_ticker_proof": True,
        },
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Historical metadata V4 residual recovery plan",
        "",
        f"Definitive unresolved episodes: **{len(rows):,}**",
        f"Episodes with causal CIK authority: **{causal_episode_count:,}**",
        f"Episodes without causal CIK authority: **{len(rows)-causal_episode_count:,}**",
        f"Episodes eligible for retained-SEC re-mining: **{len(remine):,}**",
        f"Episodes requiring new external recovery after retained-corpus pass: **{len(external):,}**",
        "",
        "## Resolution routes",
    ]
    for route, count in sorted(route_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {route}: {count:,}")
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--v2-root", type=Path, required=True)
    parser.add_argument("--v3-root", type=Path, required=True)
    parser.add_argument("--corrected-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(audit_root=args.audit_root, v2_root=args.v2_root, v3_root=args.v3_root, corrected_root=args.corrected_root, output=args.output)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
